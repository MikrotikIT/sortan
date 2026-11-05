import logging
import secrets
from datetime import datetime, time as datetime_time, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .chat_services import ChatRuleError, create_text_message, user_can_post
from .models import (
    ChatGroup,
    ChatMembership,
    Film,
    InvestmentAutoPostLink,
    InvestmentAutoPostRun,
    InvestmentAutoPostSchedule,
    User,
)


logger = logging.getLogger(__name__)
AUTO_POST_GRACE = timedelta(minutes=3)


def get_auto_post_publishers(group):
    if group.message_mode == ChatGroup.MessageMode.LOCKED:
        publishers = User.objects.filter(is_active=True, is_staff=True)
    else:
        member_filter = Q(chat_memberships__group=group, approval_status="approved")
        if group.message_mode == ChatGroup.MessageMode.MODERATORS:
            member_filter &= Q(chat_memberships__role=ChatMembership.Role.MODERATOR)
        elif group.message_mode == ChatGroup.MessageMode.SELECTED:
            member_filter &= (
                Q(chat_memberships__can_post=True)
                | Q(chat_memberships__role=ChatMembership.Role.MODERATOR)
            )
        publishers = User.objects.filter(is_active=True).filter(Q(is_staff=True) | member_filter)
        publishers = publishers.exclude(Q(is_staff=False, chat_group_bans__group=group))
    return publishers.distinct().order_by("phone")


def _investment_code(external_url):
    # Codes are matched together with the investment URL. Avoid an active film
    # with the same URL/code pair so the generated activation is unambiguous.
    existing_codes = set(
        Film.objects.filter(active=True, external_url=external_url).values_list("investment_code", flat=True)
    )
    for _ in range(10_000):
        code = f"{secrets.randbelow(10_000):04d}"
        if code not in existing_codes:
            return code
    raise ValueError("تعذر إنشاء كود تفعيل فريد لهذا الرابط.")


def _format_message(schedule, film):
    duration = f"{film.waiting_duration} {film.get_waiting_unit_display()}"
    expiry = (
        f"{film.link_expiry_duration} {film.get_link_expiry_unit_display()}"
        if film.link_expiry_duration
        else "غير محددة"
    )
    return schedule.message_template.format(
        link=film.external_url,
        code=film.investment_code,
        title=film.title,
        minimum=f"{film.minimum_investment_amount:.2f}",
        duration=duration,
        profit=f"{film.profit_percent:.2f}%",
        expiry=expiry,
    )


def _broadcast_message(group_id, message_data):
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            f"chat_group_{group_id}",
            {"type": "chat.broadcast", "payload": {"type": "message_created", "message": message_data}},
        )
    except Exception:
        logger.exception("Could not broadcast scheduled investment message for group %s", group_id)


def publish_investment_auto_post_slot(schedule_id, scheduled_at):
    with transaction.atomic():
        schedule = (
            InvestmentAutoPostSchedule.objects.select_for_update()
            .select_related("group", "sender")
            .filter(pk=schedule_id, enabled=True, group__is_active=True)
            .first()
        )
        if schedule is None:
            return "skipped"

        run, created = InvestmentAutoPostRun.objects.get_or_create(
            schedule=schedule,
            scheduled_at=scheduled_at,
            defaults={
                "status": InvestmentAutoPostRun.Status.FAILED,
                "error": "جارٍ تجهيز النشر.",
            },
        )
        if not created:
            return run.status

        try:
            with transaction.atomic():
                link_item = (
                    InvestmentAutoPostLink.objects.select_for_update()
                    .filter(status=InvestmentAutoPostLink.Status.AVAILABLE)
                    .order_by("created_at", "pk")
                    .first()
                )
                if link_item is None:
                    raise ValueError("سلة روابط الاستثمار فارغة.")
                if not user_can_post(schedule.sender, schedule.group):
                    raise ChatRuleError("الناشر المحدد لم يعد يملك صلاحية النشر في المجموعة.")

                image_url = link_item.image.url if link_item.image else link_item.image_url
                film = Film.objects.create(
                    title=link_item.title,
                    description=link_item.description,
                    image_url=image_url,
                    external_url=link_item.external_url,
                    investment_code=_investment_code(link_item.external_url),
                    waiting_duration=schedule.waiting_duration,
                    waiting_unit=schedule.waiting_unit,
                    profit_percent=schedule.profit_percent,
                    minimum_investment_amount=schedule.minimum_investment_amount,
                    link_expiry_duration=schedule.link_expiry_duration,
                    link_expiry_unit=schedule.link_expiry_unit,
                    active=True,
                )
                message_data = create_text_message(
                    schedule.group_id,
                    schedule.sender_id,
                    _format_message(schedule, film),
                )
                link_item.status = InvestmentAutoPostLink.Status.USED
                link_item.used_film = film
                link_item.used_at = timezone.now()
                link_item.save(update_fields=("status", "used_film", "used_at"))
                run.status = InvestmentAutoPostRun.Status.SENT
                run.link_item = link_item
                run.film = film
                run.message_id = message_data["id"]
                run.error = ""
                run.save(update_fields=("status", "link_item", "film", "message", "error"))
                transaction.on_commit(
                    lambda group_id=schedule.group_id, payload=message_data: _broadcast_message(group_id, payload)
                )
        except Exception as exc:
            run.status = InvestmentAutoPostRun.Status.FAILED
            run.error = str(exc)[:4000] or exc.__class__.__name__
            run.save(update_fields=("status", "error"))
            logger.exception("Scheduled investment post %s failed", schedule.pk)
            return "failed"

        return "sent"


def process_due_investment_auto_posts(now=None):
    now = now or timezone.now()
    sent = failed = 0
    schedules = InvestmentAutoPostSchedule.objects.filter(
        enabled=True,
        group__is_active=True,
    ).select_related("group", "sender")
    for schedule in schedules.iterator(chunk_size=200):
        try:
            zone = ZoneInfo(schedule.timezone_name)
        except (KeyError, TypeError, ValueError):
            logger.error("Invalid timezone %r for investment auto-post schedule %s", schedule.timezone_name, schedule.pk)
            continue
        local_now = now.astimezone(zone)
        for raw_time in schedule.publish_times or []:
            try:
                scheduled_time = datetime_time.fromisoformat(str(raw_time))
            except (TypeError, ValueError):
                logger.error("Invalid publish time %r for investment auto-post schedule %s", raw_time, schedule.pk)
                continue
            naive_scheduled_at = datetime.combine(local_now.date(), scheduled_time)
            localized_scheduled_at = naive_scheduled_at.replace(tzinfo=zone)
            # Skip nonexistent local times during a daylight-saving transition.
            if localized_scheduled_at.astimezone(datetime_timezone.utc).astimezone(zone).replace(tzinfo=None) != naive_scheduled_at:
                continue
            scheduled_at = localized_scheduled_at.astimezone(datetime_timezone.utc)
            delay = now - scheduled_at
            if timedelta(0) <= delay <= AUTO_POST_GRACE:
                result = publish_investment_auto_post_slot(schedule.pk, scheduled_at)
                sent += result == "sent"
                failed += result == "failed"
    return {"sent": sent, "failed": failed}
