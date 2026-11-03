import json
import logging
import secrets
from datetime import timedelta
from random import randint
from urllib.request import Request, urlopen

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from .chat_services import create_ai_chat_message
from .models import AIBotPool, AIChatSettings, ChatDemoAccount, ChatGroup, ChatGroupPresence, ChatMessage


logger = logging.getLogger(__name__)
ARABIC_LETTERS = "ابتثجحخدذرزسشصضطظعغفقكلمنهوي"


def _should_run(settings_row, group, now):
    if not settings_row or not settings_row.enabled or not group.is_active:
        return False
    if group.message_mode == ChatGroup.MessageMode.LOCKED:
        return False
    if settings_row.run_mode == AIChatSettings.RunMode.ALWAYS:
        return True
    return ChatGroupPresence.objects.filter(
        group=group,
        last_seen_at__gte=now - timedelta(seconds=90),
        user__is_active=True,
    ).exists()


def _random_wait(bot):
    minimum = max(1, bot.ai_wait_min_seconds)
    maximum = max(minimum, bot.ai_wait_max_seconds)
    return randint(minimum, maximum)


def _mark_dead(bot, now):
    partner_id = bot.ai_partner_id
    bot.ai_state = "DEAD"
    bot.ai_dead_at = now
    bot.ai_last_active_at = None
    bot.ai_next_action_at = None
    bot.ai_wait_remaining_seconds = None
    bot.ai_partner = None
    bot.save(update_fields=(
        "ai_state", "ai_dead_at", "ai_elapsed_active_seconds", "ai_last_active_at", "ai_next_action_at",
        "ai_wait_remaining_seconds", "ai_partner",
    ))
    if partner_id:
        partner = ChatDemoAccount.objects.select_for_update().filter(pk=partner_id, is_ai=True).first()
        if partner:
            partner.ai_partner = None
            if partner.ai_state == "ACTIVE":
                partner.ai_next_action_at = now + timedelta(seconds=_random_wait(partner))
            partner.save(update_fields=("ai_partner", "ai_next_action_at"))
    pool = bot.bot_pool
    if pool and pool.desired_count > pool.accounts.filter(is_ai=True, ai_state__in=("ACTIVE", "PAUSED")).count():
        if not pool.next_replacement_at:
            pool.next_replacement_at = now + timedelta(
                seconds=randint(pool.replacement_min_seconds, pool.replacement_max_seconds)
            )
            pool.save(update_fields=("next_replacement_at", "updated_at"))


def _advance_active_time(bot, now):
    if bot.ai_last_active_at:
        bot.ai_elapsed_active_seconds += max(0, int((now - bot.ai_last_active_at).total_seconds()))
    bot.ai_last_active_at = None


def _active_lifetime_elapsed(bot, now):
    current_run = max(0, int((now - bot.ai_last_active_at).total_seconds())) if bot.ai_last_active_at else 0
    return bot.ai_elapsed_active_seconds + current_run


def _new_account_name(template):
    suffix = "".join(secrets.choice(ARABIC_LETTERS) for _ in range(6))
    return f"{template.name} {suffix}"[:120]


def _spawn_pool_account(pool, now):
    template = pool.template
    account = None
    for _ in range(20):
        name = _new_account_name(template)
        if not ChatDemoAccount.objects.filter(group_id=pool.group_id, display_name=name).exists():
            account = ChatDemoAccount.objects.create(
                group_id=pool.group_id,
                display_name=name,
                is_ai=True,
                bot_pool=pool,
            )
            break
    if account is None:
        logger.error("Unable to allocate a unique display name for AI bot pool %s", pool.pk)
        return None
    account.ai_role = template.role
    account.ai_model_id = template.model_id
    account.ai_system_prompt = template.system_prompt
    account.ai_wait_min_seconds = template.wait_min_seconds
    account.ai_wait_max_seconds = template.wait_max_seconds
    account.ai_lifetime_seconds = template.lifetime_minutes * 60
    account.ai_state = "ACTIVE"
    account.ai_next_action_at = now + timedelta(seconds=_random_wait(account))
    account.save(update_fields=(
        "ai_role", "ai_model_id", "ai_system_prompt", "ai_wait_min_seconds",
        "ai_wait_max_seconds", "ai_lifetime_seconds", "ai_state", "ai_next_action_at", "updated_at",
    ))
    return account


def _pair_unassigned_bots(group_id):
    broken_pairs = ChatDemoAccount.objects.select_for_update(of=("self",)).filter(
        group_id=group_id,
        is_ai=True,
        ai_partner__isnull=False,
    ).exclude(ai_partner__ai_state__in=("ACTIVE", "PAUSED"))
    for bot in broken_pairs:
        partner_id = bot.ai_partner_id
        bot.ai_partner_id = None
        bot.save(update_fields=("ai_partner",))
        ChatDemoAccount.objects.filter(pk=partner_id, ai_partner_id=bot.pk).update(ai_partner=None)
    askers = list(ChatDemoAccount.objects.select_for_update().filter(
        group_id=group_id, is_ai=True, ai_role="asker", ai_partner__isnull=True,
        ai_state__in=("ACTIVE", "PAUSED"),
    ).order_by("pk"))
    responders = list(ChatDemoAccount.objects.select_for_update().filter(
        group_id=group_id, is_ai=True, ai_role="bot_responder", ai_partner__isnull=True,
        ai_state__in=("ACTIVE", "PAUSED"),
    ).order_by("pk"))
    for asker, responder in zip(askers, responders):
        asker.ai_partner_id = responder.pk
        responder.ai_partner_id = asker.pk
        asker.save(update_fields=("ai_partner",))
        responder.save(update_fields=("ai_partner",))


def _maintain_group(group_id, settings_row, now):
    with transaction.atomic():
        group = ChatGroup.objects.select_for_update().filter(pk=group_id).first()
        if group is None:
            return False
        running = _should_run(settings_row, group, now)
        bots = list(
            ChatDemoAccount.objects.select_for_update(of=("self",))
            .select_related("bot_pool")
            .filter(group=group, is_ai=True, ai_state__in=("ACTIVE", "PAUSED"))
            .order_by("pk")
        )
        for bot in bots:
            if not settings_row.active_time_only and now >= bot.created_at + timedelta(seconds=bot.ai_lifetime_seconds):
                _mark_dead(bot, now)
                continue
            if running:
                if bot.ai_state == "PAUSED":
                    bot.ai_state = "ACTIVE"
                    bot.ai_last_active_at = now
                    wait = bot.ai_wait_remaining_seconds
                    bot.ai_next_action_at = now + timedelta(seconds=wait if wait is not None else _random_wait(bot))
                    bot.ai_wait_remaining_seconds = None
                    bot.save(update_fields=(
                        "ai_state", "ai_last_active_at", "ai_next_action_at", "ai_wait_remaining_seconds"
                    ))
                elif bot.ai_last_active_at is None:
                    bot.ai_last_active_at = now
                    bot.save(update_fields=("ai_last_active_at",))
                if settings_row.active_time_only and _active_lifetime_elapsed(bot, now) >= bot.ai_lifetime_seconds:
                    _advance_active_time(bot, now)
                    _mark_dead(bot, now)
            elif bot.ai_state == "ACTIVE":
                _advance_active_time(bot, now)
                if settings_row.active_time_only and bot.ai_elapsed_active_seconds >= bot.ai_lifetime_seconds:
                    _mark_dead(bot, now)
                    continue
                wait = max(0, int((bot.ai_next_action_at - now).total_seconds())) if bot.ai_next_action_at else _random_wait(bot)
                bot.ai_state = "PAUSED"
                bot.ai_last_active_at = None
                bot.ai_next_action_at = None
                bot.ai_wait_remaining_seconds = wait
                bot.save(update_fields=(
                    "ai_elapsed_active_seconds", "ai_state", "ai_last_active_at",
                    "ai_next_action_at", "ai_wait_remaining_seconds",
                ))

        if running:
            pools = AIBotPool.objects.select_for_update().select_related("template").filter(
                group=group, template__is_active=True
            ).order_by("pk")
            for pool in pools:
                occupied = pool.accounts.filter(is_ai=True, ai_state__in=("ACTIVE", "PAUSED")).count()
                if occupied >= pool.desired_count:
                    if pool.next_replacement_at:
                        pool.next_replacement_at = None
                        pool.save(update_fields=("next_replacement_at", "updated_at"))
                    continue
                if pool.next_replacement_at is None:
                    pool.next_replacement_at = now + timedelta(
                        seconds=randint(pool.replacement_min_seconds, pool.replacement_max_seconds)
                    )
                    pool.save(update_fields=("next_replacement_at", "updated_at"))
                if pool.next_replacement_at <= now:
                    _spawn_pool_account(pool, now)
                    occupied = pool.accounts.filter(is_ai=True, ai_state__in=("ACTIVE", "PAUSED")).count()
                    pool.next_replacement_at = (
                        now + timedelta(seconds=randint(pool.replacement_min_seconds, pool.replacement_max_seconds))
                        if occupied < pool.desired_count
                        else None
                    )
                    pool.save(update_fields=("next_replacement_at", "updated_at"))
            _pair_unassigned_bots(group.pk)
    return running


def _reply_target_for(bot):
    if bot.ai_role == "asker":
        partner = bot.ai_partner
        if not partner or partner.ai_state != "ACTIVE":
            return None, None
        last_mine = ChatMessage.objects.filter(demo_account=bot).order_by("-pk").first()
        if last_mine is None:
            return None, None
        answer = ChatMessage.objects.filter(
            group_id=bot.group_id, demo_account=partner, reply_to=last_mine
        ).order_by("-pk").first()
        return (answer, answer.pk) if answer else (None, None)
    if bot.ai_role == "bot_responder":
        partner = bot.ai_partner
        if not partner or partner.ai_state != "ACTIVE":
            return None, None
        target = ChatMessage.objects.filter(group_id=bot.group_id, demo_account=partner).order_by("-pk").first()
        if not target or ChatMessage.objects.filter(group_id=bot.group_id, demo_account=bot, reply_to=target).exists():
            return None, None
        return target, target.pk
    target = ChatMessage.objects.filter(
        group_id=bot.group_id,
        demo_account__isnull=True,
        text__gt="",
    ).exclude(replies__demo_account=bot).order_by("-pk").first()
    return (target, target.pk) if target else (None, None)


def _human_direct_reply_target(bot):
    return ChatMessage.objects.filter(
        group_id=bot.group_id,
        demo_account__isnull=True,
        text__gt="",
        reply_to__demo_account=bot,
    ).exclude(replies__demo_account=bot).order_by("-pk").first()


def _prompt_messages(bot, target):
    if bot.ai_role in {"asker", "bot_responder"} and bot.ai_partner_id:
        if target is None:
            return [{"role": "user", "content": "ابدأ حواراً بسؤال قصير مناسب لشخصيتك."}]
        if target and target.demo_account_id is None:
            parent = target.reply_to
            messages = []
            if parent and parent.text:
                messages.append({"role": "assistant", "content": parent.text[:1500]})
            messages.append({"role": "user", "content": target.text[:1500]})
            return messages
        pair_ids = (bot.pk, bot.ai_partner_id)
        messages = list(
            ChatMessage.objects.filter(group_id=bot.group_id, demo_account_id__in=pair_ids)
            .select_related("demo_account")
            .order_by("-pk")[:10]
        )
        messages.reverse()
        return [
            {"role": "assistant" if message.demo_account_id == bot.pk else "user", "content": message.text[:1500]}
            for message in messages if message.text.strip()
        ]
    context = []
    if target.reply_to_id and target.reply_to and target.reply_to.text:
        context.append({"role": "user", "content": f"الرسالة السابقة في سياق الرد: {target.reply_to.text[:1000]}"})
    context.append({"role": "user", "content": target.text[:1500]})
    return context


def _generate_response(bot, target, settings_row):
    api_key = settings_row.openrouter_api_key or getattr(settings, "OPENROUTER_API_KEY", "")
    model = bot.ai_model_id or settings_row.selected_model
    if not api_key or not model:
        raise RuntimeError("OpenRouter key or model is not configured")
    system_prompt = (bot.ai_system_prompt or "تحدث بالعربية وبأسلوب طبيعي.").strip()
    system_prompt += "\nاكتب رداً قصيراً ومناسباً لسياق المحادثة. لا تستخدم وسوماً HTML ولا تذكر أنك إنسان؛ الحساب موسوم بوضوح بأنه ذكاء اصطناعي."
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, *_prompt_messages(bot, target)],
        "temperature": 0.8,
        "max_tokens": 240,
    }
    request = Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Kodi-TV/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=18) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return strip_tags(str(content or "")).strip()[:2000]


def _reserve_due_bot(now):
    ids = ChatDemoAccount.objects.filter(
        is_ai=True, ai_state="ACTIVE", ai_next_action_at__lte=now,
        group__is_active=True, bot_pool__isnull=False,
    ).order_by("ai_next_action_at", "pk").values_list("pk", flat=True)[:40]
    for account_id in ids:
        with transaction.atomic():
            bot = ChatDemoAccount.objects.select_for_update(of=("self",)).select_related("group", "ai_partner", "bot_pool").filter(
                pk=account_id, is_ai=True, ai_state="ACTIVE", ai_next_action_at__lte=now
            ).first()
            if not bot:
                continue
            target = None
            reply_to_id = None
            if bot.ai_role in {"asker", "bot_responder"}:
                target = _human_direct_reply_target(bot)
                if target:
                    reply_to_id = target.pk
                elif not bot.ai_partner or bot.ai_partner.ai_state != "ACTIVE":
                    bot.ai_next_action_at = now + timedelta(seconds=_random_wait(bot))
                    bot.save(update_fields=("ai_next_action_at",))
                    continue
            if target is None and bot.ai_role == "asker":
                last_mine = ChatMessage.objects.filter(demo_account=bot).order_by("-pk").first()
                if last_mine and not ChatMessage.objects.filter(
                    group_id=bot.group_id, demo_account=bot.ai_partner, reply_to=last_mine
                ).exists():
                    bot.ai_next_action_at = now + timedelta(seconds=_random_wait(bot))
                    bot.save(update_fields=("ai_next_action_at",))
                    continue
            if target is None:
                target, reply_to_id = _reply_target_for(bot)
                if bot.ai_role != "asker" and target is None:
                    bot.ai_next_action_at = now + timedelta(seconds=max(2, _random_wait(bot)))
                    bot.save(update_fields=("ai_next_action_at",))
                    continue
            bot.ai_next_action_at = now + timedelta(seconds=45)
            bot.save(update_fields=("ai_next_action_at",))
            return bot.pk, target, reply_to_id
    return None


def _broadcast(group_id, message):
    layer = get_channel_layer()
    if layer:
        async_to_sync(layer.group_send)(
            f"chat_group_{group_id}",
            {"type": "chat.broadcast", "payload": {"type": "message_created", "message": message}},
        )


def advance_ai_chat_bots():
    now = timezone.now()
    settings_row, _ = AIChatSettings.objects.get_or_create(pk=1)
    ChatGroupPresence.objects.filter(last_seen_at__lt=now - timedelta(minutes=2)).delete()
    group_ids = ChatGroup.objects.filter(ai_bot_pools__isnull=False).order_by("pk").values_list("pk", flat=True).distinct()
    any_running = False
    for group_id in group_ids.iterator():
        any_running = _maintain_group(group_id, settings_row, now) or any_running
    if not any_running:
        return {"sent": 0, "running": False}
    reserved = _reserve_due_bot(now)
    if not reserved:
        return {"sent": 0, "running": True}
    bot_id, target, reply_to_id = reserved
    bot = ChatDemoAccount.objects.select_related("bot_pool__created_by").get(pk=bot_id)
    try:
        text = _generate_response(bot, target, settings_row)
        latest_settings = AIChatSettings.objects.filter(pk=1).first()
        latest_bot = ChatDemoAccount.objects.select_related("group").filter(pk=bot.pk).first()
        if not latest_bot or not _should_run(latest_settings, latest_bot.group, timezone.now()):
            if latest_bot and latest_bot.ai_state == "ACTIVE":
                ChatDemoAccount.objects.filter(pk=latest_bot.pk, ai_state="ACTIVE").update(
                    ai_next_action_at=timezone.now() + timedelta(seconds=_random_wait(latest_bot))
                )
            return {"sent": 0, "running": False}
        message = create_ai_chat_message(bot.pk, text, reply_to_id)
    except Exception as exc:
        logger.warning("AI chat bot %s could not generate a reply: %s", bot.pk, exc)
        ChatDemoAccount.objects.filter(pk=bot.pk, ai_state="ACTIVE").update(
            ai_next_action_at=now + timedelta(seconds=30)
        )
        return {"sent": 0, "running": True}
    ChatDemoAccount.objects.filter(pk=bot.pk, ai_state="ACTIVE").update(
        ai_next_action_at=timezone.now() + timedelta(seconds=_random_wait(bot))
    )
    try:
        _broadcast(bot.group_id, message)
    except Exception:
        logger.exception("Could not broadcast AI chat bot message %s", message.get("id"))
    return {"sent": 1, "running": True}
