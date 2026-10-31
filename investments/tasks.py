import logging
from collections import Counter
from datetime import timedelta
from random import choices, randint

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from celery import shared_task
from django.db import transaction
from django.db.models import Count, F, Q
from django.urls import reverse
from django.utils import timezone

from .chat_services import REACTION_GLYPHS, REACTION_ORDER, serialize_chat_message
from .models import (
    ChatGroup,
    ChatGroupBan,
    ChatGroupReadState,
    ChatMembership,
    ChatMessage,
    ChatReaction,
    DemoChatReactionCount,
    ServiceHeartbeat,
    UserNotification,
)
from .notification_services import notification_push_body
from .push_services import send_push_to_user, send_push_to_users
from .wallet_services import sync_all_wallets


logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 4})
def send_user_notification_push(self, notification_id):
    notification = UserNotification.objects.select_related("recipient").filter(pk=notification_id).first()
    if not notification:
        return {"success_count": 0, "failure_count": 0}

    body = notification_push_body(notification.body_html) or "لديك إشعار جديد."
    data = {
        "type": "site_notification",
        "notification_id": str(notification.pk),
        "url": reverse("notification_open", args=(notification.pk,)),
    }
    return send_push_to_user(
        notification.recipient,
        title=notification.title,
        body=body,
        data=data,
    )


@shared_task
def send_bulk_notification_push(user_ids, title, body, data):
    result = {"success_count": 0, "failure_count": 0}
    for start in range(0, len(user_ids), 1000):
        batch_result = send_push_to_users(
            user_ids[start : start + 1000],
            title=title,
            body=body,
            data=data,
        )
        result["success_count"] += batch_result["success_count"]
        result["failure_count"] += batch_result["failure_count"]
    return result


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 4})
def send_group_message_push(self, message_id):
    message = (
        ChatMessage.objects.select_related("group", "sender")
        .filter(pk=message_id, group__is_active=True)
        .first()
    )
    if not message:
        return {"success_count": 0, "failure_count": 0}

    banned_user_ids = ChatGroupBan.objects.filter(group_id=message.group_id).values_list("user_id", flat=True)
    memberships = list(
        ChatMembership.objects.filter(
            group_id=message.group_id,
            user__is_active=True,
            notifications_muted=False,
        )
        .filter(Q(user__is_staff=True) | Q(user__approval_status="approved"))
        .exclude(user_id=message.sender_id)
        .exclude(user_id__in=banned_user_ids)
        .select_related("user")
    )
    staff_ids = [membership.user_id for membership in memberships if membership.user.is_staff]
    staff_read_states = dict(
        ChatGroupReadState.objects.filter(group_id=message.group_id, user_id__in=staff_ids)
        .values_list("user_id", "last_read_message_id")
    )

    recipient_ids = []
    for membership in memberships:
        last_read_message_id = (
            staff_read_states.get(membership.user_id)
            if membership.user.is_staff
            else membership.last_read_message_id
        )
        if last_read_message_id is None or last_read_message_id < message.pk:
            recipient_ids.append(membership.user_id)

    if not recipient_ids:
        return {"success_count": 0, "failure_count": 0}

    preview = message.text.strip()
    if not preview:
        preview = "أرسل صورة" if message.image else "أرسل ملفاً" if message.attachment else "رسالة جديدة"
    sender_name = message.sender.get_full_name().strip() or "عضو"
    return send_push_to_users(
        recipient_ids,
        title=message.group.title,
        body=f"{sender_name}: {preview[:180]}",
        data={
            "type": "group_message",
            "group_id": str(message.group_id),
            "message_id": str(message.pk),
            "url": reverse("chat_group_room", args=(message.group_id,)),
        },
    )


def _broadcast_chat(group_id, payload):
    layer = get_channel_layer()
    if layer:
        try:
            async_to_sync(layer.group_send)(
                f"chat_group_{group_id}",
                {"type": "chat.broadcast", "payload": payload},
            )
        except Exception:
            logger.exception("Could not broadcast demo chat metrics for group %s", group_id)


@shared_task
def sync_tron_deposits():
    """Fetch confirmed TRC20 USDT transfers and refresh deposit wallet balances."""
    result = sync_all_wallets(trigger="scheduled")
    logger.info(
        "TRON deposit sync completed: updated=%s imported=%s",
        result["updated"],
        result["imported"],
    )
    for error in result["errors"]:
        logger.warning("TRON wallet sync failed: %s", error)
    return result


@shared_task
def record_celery_heartbeat():
    """Record that a task scheduled by Beat reached and ran on a worker."""
    ServiceHeartbeat.objects.update_or_create(
        component="beat-worker-pipeline",
        defaults={
            "last_seen_at": timezone.now(),
            "details": "مهمة مجدولة وصلت إلى Celery Worker ونُفذت.",
        },
    )


@shared_task
def advance_demo_chat_metrics():
    """Advance explicitly marked demo counters; real memberships/reactions are untouched."""
    now = timezone.now()
    member_group_ids = list(
        ChatGroup.objects.filter(
            is_active=True,
            demo_member_growth_enabled=True,
            demo_member_next_growth_at__lte=now,
        ).values_list("pk", flat=True)[:500]
    )
    grown_groups = 0
    for group_id in member_group_ids:
        with transaction.atomic():
            group = ChatGroup.objects.select_for_update().filter(pk=group_id).first()
            if not group or not group.demo_member_growth_enabled or not group.demo_member_next_growth_at or group.demo_member_next_growth_at > now:
                continue
            amount = randint(group.demo_member_increment_min, group.demo_member_increment_max)
            group.demo_member_offset = min(1_000_000, group.demo_member_offset + amount)
            if group.demo_member_offset >= 1_000_000:
                group.demo_member_growth_enabled = False
                group.demo_member_next_growth_at = None
            else:
                delay = randint(group.demo_member_interval_min_seconds, group.demo_member_interval_max_seconds)
                group.demo_member_next_growth_at = now + timedelta(seconds=delay)
            group.save(update_fields=("demo_member_offset", "demo_member_growth_enabled", "demo_member_next_growth_at", "updated_at"))
            grown_groups += 1
            actual_count = group.member_count
            stats = {
                "type": "group_stats",
                "actual_member_count": actual_count,
                "demo_member_offset": group.demo_member_offset,
            }
        _broadcast_chat(group_id, stats)

    message_ids = list(
        ChatMessage.objects.filter(
            group__is_active=True,
            group__reactions_enabled=True,
            demo_growth_enabled=True,
            demo_growth_ends_at__gt=now,
            demo_growth_next_at__lte=now,
        ).values_list("pk", flat=True)[:1000]
    )
    advanced_messages = 0
    for message_id in message_ids:
        with transaction.atomic():
            message = ChatMessage.objects.select_for_update().select_related("group").filter(pk=message_id).first()
            if not message or not message.demo_growth_enabled or not message.demo_growth_ends_at or message.demo_growth_ends_at <= now or not message.demo_growth_next_at or message.demo_growth_next_at > now:
                continue
            if not message.group.is_active or not message.group.reactions_enabled:
                continue
            amount = randint(message.demo_growth_step_min, message.demo_growth_step_max)
            weights = (
                message.demo_like_percent,
                message.demo_heart_percent,
                message.demo_fire_percent,
                message.demo_clap_percent,
                message.demo_dislike_percent,
            )
            kinds = (ChatReaction.Kind.LIKE, ChatReaction.Kind.HEART, ChatReaction.Kind.FIRE, ChatReaction.Kind.CLAP, ChatReaction.Kind.DISLIKE)
            increments = Counter(choices(kinds, weights=weights, k=amount))
            for kind, increment in increments.items():
                counter, _ = DemoChatReactionCount.objects.get_or_create(message=message, kind=kind, defaults={"count": 0})
                DemoChatReactionCount.objects.filter(pk=counter.pk).update(count=F("count") + increment)
            delay = randint(message.demo_growth_interval_min_seconds, message.demo_growth_interval_max_seconds)
            message.demo_growth_next_at = now + timedelta(seconds=delay)
            message.save(update_fields=("demo_growth_next_at",))
            advanced_messages += 1
        if increments:
            real_counts = {kind: 0 for kind in REACTION_ORDER}
            for row in ChatReaction.objects.filter(message_id=message_id).values("kind").annotate(total=Count("pk")):
                real_counts[row["kind"]] = row["total"]
            demo_counts = {kind: 0 for kind in REACTION_ORDER}
            for row in DemoChatReactionCount.objects.filter(message_id=message_id).values("kind", "count"):
                demo_counts[row["kind"]] = row["count"]
            _broadcast_chat(
                message.group_id,
                {
                    "type": "reaction_updated",
                    "message_id": message_id,
                    "actor_id": None,
                    "actor_reaction": None,
                    "reactions": [
                        {
                            "kind": kind,
                            "glyph": REACTION_GLYPHS[kind],
                            "count": real_counts[kind] + demo_counts[kind],
                            "real_count": real_counts[kind],
                            "demo_count": demo_counts[kind],
                        }
                        for kind in REACTION_ORDER
                    ],
                },
            )
    expired_message_ids = list(
        ChatMessage.objects.filter(
            demo_growth_enabled=True,
            demo_growth_ends_at__lte=now,
        ).values_list("pk", flat=True)[:1000]
    )
    for message_id in expired_message_ids:
        with transaction.atomic():
            message = ChatMessage.objects.select_for_update().select_related("group", "sender").filter(pk=message_id).first()
            if not message or not message.demo_growth_enabled or not message.demo_growth_ends_at or message.demo_growth_ends_at > now:
                continue
            message.demo_growth_enabled = False
            message.demo_growth_next_at = None
            message.save(update_fields=("demo_growth_enabled", "demo_growth_next_at"))
        if message.group.is_active:
            message_data = serialize_chat_message(message)
            _broadcast_chat(message.group_id, {"type": "message_updated", "message": message_data})
    return {"groups": grown_groups, "messages": advanced_messages}
