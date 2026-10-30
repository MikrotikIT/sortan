import os
import re
from datetime import timedelta
from random import randint

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.html import strip_tags
from django.urls import reverse
from django.utils.text import get_valid_filename

from .models import ChatGroup, ChatGroupBan, ChatMembership, ChatMessage, ChatReaction, JoinApplication, User


REACTION_GLYPHS = {
    ChatReaction.Kind.LIKE: "👍",
    ChatReaction.Kind.HEART: "❤️",
    ChatReaction.Kind.FIRE: "🔥",
    ChatReaction.Kind.CLAP: "👏",
    ChatReaction.Kind.DISLIKE: "👎",
}
REACTION_ORDER = tuple(REACTION_GLYPHS)
DEMO_SETTINGS_DEFAULTS = {
    "demo_growth_duration_hours": 24,
    "demo_growth_interval_min_seconds": 5,
    "demo_growth_interval_max_seconds": 15,
    "demo_growth_step_min": 1,
    "demo_growth_step_max": 5,
    "demo_like_percent": 30,
    "demo_heart_percent": 40,
    "demo_fire_percent": 15,
    "demo_clap_percent": 10,
    "demo_dislike_percent": 5,
}


class ChatRuleError(Exception):
    pass


def group_member_access(user, group, *, allow_public_preview=False):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if not group.is_active and not user.is_staff:
        return False
    if user.is_staff:
        return True
    if user.approval_status != "approved":
        return False
    if ChatGroupBan.objects.filter(group=group, user=user).exists():
        return False
    if ChatMembership.objects.filter(group=group, user=user).exists():
        return True
    return bool(allow_public_preview and group.is_public)


def group_membership(group, user):
    if user.is_staff:
        return None
    return ChatMembership.objects.filter(group=group, user=user).first()


def user_can_post(user, group):
    if not group.is_active or not user.is_authenticated or not user.is_active:
        return False
    if not user.is_staff and user.approval_status != "approved":
        return False
    if not user.is_staff and ChatGroupBan.objects.filter(group=group, user=user).exists():
        return False
    membership = group_membership(group, user)
    if not user.is_staff and membership is None:
        return False
    if user.is_staff:
        return True
    if group.message_mode == ChatGroup.MessageMode.LOCKED:
        return False
    if group.message_mode == ChatGroup.MessageMode.MODERATORS:
        return membership.role == ChatMembership.Role.MODERATOR
    if group.message_mode == ChatGroup.MessageMode.SELECTED:
        return bool(membership.can_post or membership.role == ChatMembership.Role.MODERATOR)
    return True


def user_can_moderate(user, group):
    if user.is_staff:
        return True
    membership = group_membership(group, user)
    return bool(membership and membership.role == ChatMembership.Role.MODERATOR)


def _check_text_rules(group, user, text):
    text = strip_tags(text or "").strip()
    if text:
        if len(text) > 2000:
            raise ChatRuleError("الحد الأقصى لطول الرسالة 2000 حرف.")
        normalized = text.casefold()
        for term in group.blocked_terms.splitlines():
            term = term.strip().casefold()
            if term and term in normalized:
                raise ChatRuleError("تعذّر إرسال الرسالة لأنها تحتوي على عبارة محظورة في إعدادات المجموعة.")
        if not group.allow_links and re.search(r"(?:https?://|www\.)", normalized):
            raise ChatRuleError("إرسال الروابط متوقف في هذه المجموعة.")
    if group.slow_mode_seconds:
        last_message = ChatMessage.objects.filter(group=group, sender=user).order_by("-created_at").first()
        if last_message:
            elapsed = (timezone.now() - last_message.created_at).total_seconds()
            if elapsed < group.slow_mode_seconds:
                remaining = max(1, int(group.slow_mode_seconds - elapsed))
                raise ChatRuleError(f"انتظر {remaining} ثانية قبل إرسال رسالة أخرى.")
    return text


def _display_sender_name(value):
    name = str(value or "").split(" · ", 1)[0].strip()
    if not name or any(character.isdigit() for character in name):
        return "عضو"
    return name[:80]


def _get_sender_name(user):
    name = JoinApplication.objects.filter(user_id=user.pk).values_list("full_name", flat=True).first()
    return _display_sender_name(name or user.get_full_name())


def _reply_preview(message):
    if message.text:
        return message.text.strip()[:300]
    if message.image:
        return "صورة مرفقة"
    if message.attachment:
        return f"ملف مرفق: {message.attachment_name or 'تنزيل الملف'}"[:300]
    return "رسالة"


def serialize_chat_message(message, viewer_id=None):
    reaction_rows = list(message.reactions.all())
    real_counts = {kind: 0 for kind in REACTION_ORDER}
    demo_counts = {kind: 0 for kind in REACTION_ORDER}
    viewer_reaction = None
    for reaction in reaction_rows:
        real_counts[reaction.kind] = real_counts.get(reaction.kind, 0) + 1
        if reaction.user_id == viewer_id:
            viewer_reaction = reaction.kind
    for reaction_count in message.demo_reaction_counts.all():
        demo_counts[reaction_count.kind] = reaction_count.count
    media_url = reverse("chat_message_attachment", args=(message.pk,)) if message.image or message.attachment else ""
    growth_active = bool(
        message.demo_growth_enabled
        and message.demo_growth_ends_at
        and message.demo_growth_ends_at > timezone.now()
    )
    reply = getattr(message, "reply_to", None)
    reply_data = None
    if reply:
        reply_data = {
            "id": message.reply_to_original_id or reply.pk,
            "sender": _get_sender_name(reply.sender),
            "preview": message.reply_to_preview or _reply_preview(reply),
            "deleted": False,
        }
    elif message.reply_to_original_id:
        reply_data = {
            "id": message.reply_to_original_id,
            "sender": _display_sender_name(message.reply_to_sender_name),
            "preview": message.reply_to_preview or "رسالة",
            "deleted": True,
        }
    return {
        "id": message.pk,
        "sender_id": message.sender_id,
        "sender": _get_sender_name(message.sender),
        "text": message.text,
        "reply_to": reply_data,
        "created_at": timezone.localtime(message.created_at).strftime("%Y-%m-%d %H:%M"),
        "edited": bool(message.edited_at),
        "demo_growth_settings": {
            "enabled": growth_active,
            "duration_hours": message.demo_growth_duration_hours,
            "interval_min_seconds": message.demo_growth_interval_min_seconds,
            "interval_max_seconds": message.demo_growth_interval_max_seconds,
            "step_min": message.demo_growth_step_min,
            "step_max": message.demo_growth_step_max,
            "like_percent": message.demo_like_percent,
            "heart_percent": message.demo_heart_percent,
            "fire_percent": message.demo_fire_percent,
            "clap_percent": message.demo_clap_percent,
            "dislike_percent": message.demo_dislike_percent,
        },
        "image": bool(message.image),
        "attachment": bool(message.attachment),
        "attachment_name": message.attachment_name,
        "media_url": media_url,
        "reactions_enabled": message.group.reactions_enabled,
        "demo_growth_active": growth_active,
        "demo_growth_ends_at": message.demo_growth_ends_at.isoformat() if message.demo_growth_ends_at else None,
        "demo_reactions_present": any(demo_counts.values()),
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
        "user_reaction": viewer_reaction,
    }


def _get_message_for_user(message_id, user_id):
    message = ChatMessage.objects.select_related("group", "sender").get(pk=message_id)
    user = User.objects.get(pk=user_id)
    if not message.group.is_active or not group_member_access(user, message.group):
        raise ChatRuleError("لا تملك صلاحية الوصول إلى هذه المجموعة.")
    return message, user


def _postable_group(group_id, user_id):
    group = ChatGroup.objects.get(pk=group_id, is_active=True)
    user = User.objects.select_for_update().get(pk=user_id)
    if not group_member_access(user, group) or not user_can_post(user, group):
        raise ChatRuleError("المحادثة مقفلة لك أو لا تملك صلاحية الإرسال.")
    return group, user


def _get_reply_target(group, reply_to_id):
    if reply_to_id in (None, ""):
        return None
    if isinstance(reply_to_id, bool) or (
        isinstance(reply_to_id, float) and not reply_to_id.is_integer()
    ):
        raise ChatRuleError("رسالة الرد غير صالحة.")
    try:
        reply_to_id = int(reply_to_id)
    except (TypeError, ValueError) as exc:
        raise ChatRuleError("رسالة الرد غير صالحة.") from exc
    if reply_to_id < 1:
        raise ChatRuleError("رسالة الرد غير صالحة.")
    reply = ChatMessage.objects.select_related("sender").filter(pk=reply_to_id, group=group).first()
    if reply is None:
        raise ChatRuleError("رسالة الرد غير موجودة في هذه المجموعة.")
    return reply


def _reply_snapshot(reply):
    if reply is None:
        return {
            "reply_to": None,
            "reply_to_original_id": None,
            "reply_to_sender_name": "",
            "reply_to_preview": "",
        }
    return {
        "reply_to": reply,
        "reply_to_original_id": reply.pk,
        "reply_to_sender_name": _get_sender_name(reply.sender)[:120],
        "reply_to_preview": _reply_preview(reply),
    }


def _demo_settings(group, source):
    if not isinstance(source, dict):
        raise ChatRuleError("إعدادات المحاكاة التجريبية غير صالحة.")
    enabled_value = source.get("demo_growth_enabled", False)
    enabled = enabled_value is True or str(enabled_value).lower() in {"1", "true", "on", "yes"}
    values = {}
    limits = {
        "demo_growth_duration_hours": {1, 6, 12, 24, 48, 72},
        "demo_growth_interval_min_seconds": set(range(1, 16)),
        "demo_growth_interval_max_seconds": set(range(1, 16)),
        "demo_growth_step_min": set(range(1, 6)),
        "demo_growth_step_max": set(range(1, 6)),
        "demo_like_percent": set(range(101)),
        "demo_heart_percent": set(range(101)),
        "demo_fire_percent": set(range(101)),
        "demo_clap_percent": set(range(101)),
        "demo_dislike_percent": set(range(101)),
    }
    for name, default in DEMO_SETTINGS_DEFAULTS.items():
        raw_value = source.get(name, default)
        try:
            value = int(raw_value) if raw_value not in (None, "") else default
        except (TypeError, ValueError) as exc:
            raise ChatRuleError("إعدادات المحاكاة التجريبية غير صالحة.") from exc
        if value not in limits[name]:
            raise ChatRuleError("إعدادات المحاكاة التجريبية خارج الحدود المسموحة.")
        values[name] = value

    if values["demo_growth_interval_min_seconds"] > values["demo_growth_interval_max_seconds"]:
        raise ChatRuleError("يجب أن يكون الحد الأعلى للفاصل مساوياً أو أكبر من الحد الأدنى.")
    if values["demo_growth_step_min"] > values["demo_growth_step_max"]:
        raise ChatRuleError("يجب أن تكون الزيادة القصوى مساوياً أو أكبر من الدنيا.")
    if enabled:
        if not group.reactions_enabled:
            raise ChatRuleError("فعّل التفاعلات في إعدادات المجموعة قبل استخدام المحاكاة التجريبية.")
        percentage_fields = ("demo_like_percent", "demo_heart_percent", "demo_fire_percent", "demo_clap_percent", "demo_dislike_percent")
        if sum(values[field] for field in percentage_fields) != 100:
            raise ChatRuleError("يجب أن يساوي مجموع نسب التفاعلات 100%.")

    now = timezone.now()
    values["demo_growth_enabled"] = enabled
    values["demo_growth_ends_at"] = now + timedelta(hours=values["demo_growth_duration_hours"]) if enabled else None
    values["demo_growth_next_at"] = (
        now + timedelta(seconds=randint(values["demo_growth_interval_min_seconds"], values["demo_growth_interval_max_seconds"]))
        if enabled
        else None
    )
    return values


@transaction.atomic
def configure_message_demo_growth(message_id, user_id, source):
    user = User.objects.get(pk=user_id)
    if not user.is_active or not user.is_staff:
        raise ChatRuleError("إعداد الزيادة التجريبية متاح للإدارة فقط.")
    message = ChatMessage.objects.select_for_update().select_related("group", "sender").get(pk=message_id)
    settings = _demo_settings(message.group, source)
    for field_name, value in settings.items():
        setattr(message, field_name, value)
    message.save(update_fields=tuple(settings))
    return serialize_chat_message(message, viewer_id=user.pk)


@transaction.atomic
def create_text_message(group_id, user_id, text, reply_to_id=None):
    group, user = _postable_group(group_id, user_id)
    text = _check_text_rules(group, user, text)
    if not text:
        raise ChatRuleError("اكتب نص الرسالة أو أرفق صورة أو ملفاً.")
    reply_snapshot = _reply_snapshot(_get_reply_target(group, reply_to_id))
    message = ChatMessage.objects.create(group=group, sender=user, text=text, **reply_snapshot)
    return serialize_chat_message(message, viewer_id=user.pk)


@transaction.atomic
def create_uploaded_message(group_id, user_id, form):
    group, user = _postable_group(group_id, user_id)
    data = form.cleaned_data
    text = _check_text_rules(group, user, data.get("text", ""))
    image = data.get("image")
    attachment = data.get("attachment")
    if image and not group.allow_images:
        raise ChatRuleError("إرسال الصور متوقف في هذه المجموعة.")
    if attachment and not group.allow_files:
        raise ChatRuleError("إرفاق الملفات متوقف في هذه المجموعة.")
    if not text and not image and not attachment:
        raise ChatRuleError("اكتب رسالة أو أرفق صورة أو ملفاً.")
    reply_snapshot = _reply_snapshot(_get_reply_target(group, data.get("reply_to")))
    original_name = ""
    if attachment:
        original_name = get_valid_filename(os.path.basename(attachment.name.replace("\\", "/")))[:255]
    message = ChatMessage.objects.create(
        group=group,
        sender=user,
        text=text,
        image=image,
        attachment=attachment,
        attachment_name=original_name,
        **reply_snapshot,
    )
    message.sender = user
    return serialize_chat_message(message, viewer_id=user.pk)


@transaction.atomic
def edit_chat_message(message_id, user_id, text):
    message, user = _get_message_for_user(message_id, user_id)
    if message.sender_id != user.pk:
        raise ChatRuleError("يمكنك تعديل رسائلك فقط.")
    if not user_can_post(user, message.group):
        raise ChatRuleError("لا تملك صلاحية تعديل الرسالة.")
    text = _check_text_rules(message.group, user, text)
    if not text:
        raise ChatRuleError("لا يمكن جعل الرسالة فارغة؛ احذفها بدلاً من ذلك.")
    message.text = text
    message.edited_at = timezone.now()
    message.save(update_fields=("text", "edited_at"))
    return serialize_chat_message(message, viewer_id=user.pk)


@transaction.atomic
def delete_chat_message(message_id, user_id):
    message, user = _get_message_for_user(message_id, user_id)
    if message.sender_id != user.pk and not user_can_moderate(user, message.group):
        raise ChatRuleError("يمكنك حذف رسائلك فقط.")
    group_id = message.group_id
    message_id = message.pk
    message.delete()
    return {"message_id": message_id, "group_id": group_id}


@transaction.atomic
def set_message_reaction(message_id, user_id, kind):
    message, user = _get_message_for_user(message_id, user_id)
    if kind not in REACTION_ORDER:
        raise ChatRuleError("نوع التفاعل غير صالح.")
    if not message.group.reactions_enabled:
        raise ChatRuleError("التفاعلات متوقفة في هذه المجموعة.")
    existing = ChatReaction.objects.filter(message=message, user=user).first()
    if existing and existing.kind == kind:
        existing.delete()
        actor_reaction = None
    elif existing:
        existing.kind = kind
        existing.save(update_fields=("kind",))
        actor_reaction = kind
    else:
        ChatReaction.objects.create(message=message, user=user, kind=kind)
        actor_reaction = kind
    rows = message.reactions.values("kind").annotate(total=Count("pk"))
    real_counts = {kind_name: 0 for kind_name in REACTION_ORDER}
    for row in rows:
        real_counts[row["kind"]] = row["total"]
    demo_counts = {kind_name: 0 for kind_name in REACTION_ORDER}
    for row in message.demo_reaction_counts.values("kind", "count"):
        demo_counts[row["kind"]] = row["count"]
    return {
        "message_id": message.pk,
        "actor_id": user.pk,
        "actor_reaction": actor_reaction,
        "reactions": [
            {
                "kind": item,
                "glyph": REACTION_GLYPHS[item],
                "count": real_counts[item] + demo_counts[item],
                "real_count": real_counts[item],
                "demo_count": demo_counts[item],
            }
            for item in REACTION_ORDER
        ],
    }


def group_socket_access(group_id, user):
    group = ChatGroup.objects.filter(pk=group_id, is_active=True).first()
    return group if group and group_member_access(user, group) else None
