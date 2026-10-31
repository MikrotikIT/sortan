import logging
import mimetypes

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .chat_forms import ChatDemoGrowthForm, ChatUploadForm
from .chat_services import (
    ChatRuleError,
    configure_message_demo_growth,
    get_chat_unread_counts,
    group_member_access,
    mark_chat_group_read,
    serialize_chat_message,
    user_can_moderate,
    user_can_post,
)
from .models import ChatGroup, ChatGroupBan, ChatMembership, ChatMessage
from .chat_services import create_uploaded_message


logger = logging.getLogger(__name__)


def _eligible_user(user):
    return user.is_authenticated and user.is_active and (user.is_staff or user.approval_status == "approved")


def _message_json(message, user_id):
    message.sender_id = message.sender_id
    return serialize_chat_message(message, viewer_id=user_id)


def _broadcast_group_message(group_id, payload):
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    async_to_sync(channel_layer.group_send)(
        f"chat_group_{group_id}",
        {"type": "chat.broadcast", "payload": payload},
    )


@login_required
def chat_groups(request):
    if not _eligible_user(request.user):
        return redirect("account_review")
    groups_queryset = ChatGroup.objects.filter(is_active=True)
    if not request.user.is_staff:
        groups_queryset = groups_queryset.filter(Q(is_public=True) | Q(memberships__user=request.user))
    groups = list(
        groups_queryset
        .annotate(
            actual_member_count=Count(
                "memberships",
                filter=Q(memberships__user__is_active=True, memberships__user__approval_status="approved"),
                distinct=True,
            )
        )
        .distinct()
        .order_by("title", "pk")
    )
    memberships = dict(
        ChatMembership.objects.filter(user=request.user).values_list("group_id", "notifications_muted")
    )
    banned_ids = set(ChatGroupBan.objects.filter(user=request.user).values_list("group_id", flat=True))
    unread_counts, _ = get_chat_unread_counts(request.user, [group.pk for group in groups])
    for group in groups:
        group.has_membership = group.pk in memberships
        group.notifications_muted = memberships.get(group.pk, False)
        group.is_member = request.user.is_staff or group.has_membership
        group.is_banned = not request.user.is_staff and group.pk in banned_ids
        group.display_member_count = group.actual_member_count + group.demo_member_offset
        group.unread_count = unread_counts.get(group.pk, 0)
        group.image_url = reverse("chat_group_image", args=(group.pk,)) if group.image and not group.is_banned else ""
    return render(request, "investments/chat_groups.html", {"groups": groups})


@login_required
@require_GET
def chat_unread_count(request):
    if not _eligible_user(request.user):
        return JsonResponse({"ok": False}, status=403)
    unread_counts, unread_total = get_chat_unread_counts(request.user)
    response = JsonResponse({"ok": True, "total": unread_total, "groups": unread_counts})
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
def chat_group_mark_read(request, pk):
    if not _eligible_user(request.user):
        return JsonResponse({"ok": False}, status=403)
    group = get_object_or_404(ChatGroup, pk=pk, is_active=True)
    if not group_member_access(request.user, group):
        return JsonResponse({"ok": False}, status=403)
    try:
        message_id = int(request.POST.get("message_id", ""))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "معرّف الرسالة غير صالح."}, status=400)
    if not ChatMessage.objects.filter(pk=message_id, group=group).exists():
        return JsonResponse({"ok": False, "error": "الرسالة غير موجودة في هذه المجموعة."}, status=404)

    mark_chat_group_read(request.user, group, message_id)
    response = JsonResponse({"ok": True, "last_read_message_id": message_id})
    response["Cache-Control"] = "no-store"
    return response


def _requested_ids(value, limit=100):
    ids = []
    for item in (value or "").split(",")[:limit]:
        try:
            item_id = int(item)
        except (TypeError, ValueError):
            continue
        if item_id > 0 and item_id not in ids:
            ids.append(item_id)
    return ids


@login_required
@require_GET
def chat_live_stats(request):
    """Small polling fallback for live counters when a WebSocket is unavailable."""
    if not _eligible_user(request.user):
        return JsonResponse({"ok": False}, status=403)

    group_ids = _requested_ids(request.GET.get("groups"))
    message_ids = _requested_ids(request.GET.get("messages"))
    groups = ChatGroup.objects.filter(pk__in=group_ids, is_active=True)
    if not request.user.is_staff:
        groups = groups.filter(Q(is_public=True) | Q(memberships__user=request.user))
    groups = groups.annotate(
        actual_member_count=Count(
            "memberships",
            filter=Q(memberships__user__is_active=True, memberships__user__approval_status="approved"),
            distinct=True,
        )
    ).distinct()
    visible_groups = list(groups)

    member_group_ids = set(
        ChatMembership.objects.filter(user=request.user, group__is_active=True)
        .values_list("group_id", flat=True)
    )
    if not request.user.is_staff:
        member_group_ids.difference_update(
            ChatGroupBan.objects.filter(user=request.user).values_list("group_id", flat=True)
        )
    if request.user.is_staff:
        member_group_ids.update(group.pk for group in visible_groups)

    serialized_messages = []
    if message_ids and member_group_ids:
        page_messages = (
            ChatMessage.objects.filter(pk__in=message_ids, group_id__in=member_group_ids)
            .select_related("group", "sender", "reply_to", "reply_to__sender")
            .prefetch_related("reactions", "demo_reaction_counts")
        )
        serialized_messages = [
            serialize_chat_message(message, viewer_id=request.user.pk)
            for message in page_messages
        ]

    response = JsonResponse({
        "ok": True,
        "groups": [
            {
                "id": group.pk,
                "actual_member_count": group.actual_member_count,
                "demo_member_offset": group.demo_member_offset,
                "display_member_count": group.actual_member_count + group.demo_member_offset,
            }
            for group in visible_groups
        ],
        "messages": serialized_messages,
    })
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
def chat_group_join(request, pk):
    if not _eligible_user(request.user):
        return redirect("account_review")
    group = get_object_or_404(ChatGroup, pk=pk, is_active=True)
    if not request.user.is_staff and not group.is_public:
        raise Http404
    if not request.user.is_staff and ChatGroupBan.objects.filter(group=group, user=request.user).exists():
        messages.error(request, "أنت محظور من هذه المجموعة.")
        return redirect("chat_groups")
    if ChatMembership.objects.filter(group=group, user=request.user).exists():
        return redirect("chat_group_room", pk=group.pk)
    with transaction.atomic():
        group = ChatGroup.objects.select_for_update().get(pk=group.pk)
        if not request.user.is_staff and group.max_members and group.member_count >= group.max_members:
            messages.error(request, "وصلت المجموعة إلى الحد الأقصى للأعضاء.")
            return redirect("chat_groups")
        ChatMembership.objects.get_or_create(
            group=group,
            user=request.user,
            defaults={"notifications_muted": group.notifications_muted_by_default},
        )
    messages.success(request, f"انضممت إلى مجموعة {group.title}.")
    return redirect("chat_group_room", pk=group.pk)


@login_required
@require_POST
def chat_group_leave(request, pk):
    if not _eligible_user(request.user):
        return redirect("account_review")
    group = get_object_or_404(ChatGroup, pk=pk)
    ChatMembership.objects.filter(group=group, user=request.user).delete()
    _broadcast_group_message(group.pk, {"type": "member_removed", "target_user_id": request.user.pk})
    messages.success(request, f"غادرت مجموعة {group.title}.")
    return redirect("chat_groups")


@login_required
@require_POST
def chat_group_toggle_notifications(request, pk):
    if not _eligible_user(request.user):
        return redirect("account_review")
    group = get_object_or_404(ChatGroup, pk=pk, is_active=True)
    if not group_member_access(request.user, group):
        raise Http404
    with transaction.atomic():
        membership = get_object_or_404(
            ChatMembership.objects.select_for_update(),
            group=group,
            user=request.user,
        )
        membership.notifications_muted = not membership.notifications_muted
        membership.save(update_fields=("notifications_muted",))

    if membership.notifications_muted:
        messages.success(request, f"تم كتم إشعارات مجموعة {group.title}.")
    else:
        messages.success(request, f"تم إلغاء كتم إشعارات مجموعة {group.title}.")

    destination = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        destination,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        destination = reverse("chat_group_room", args=(group.pk,))
    return redirect(destination)


@login_required
def chat_group_room(request, pk):
    if not _eligible_user(request.user):
        return redirect("account_review")
    group = get_object_or_404(ChatGroup, pk=pk, is_active=True)
    membership = ChatMembership.objects.filter(group=group, user=request.user).first()
    is_banned = ChatGroupBan.objects.filter(group=group, user=request.user).exists()
    if not request.user.is_staff and not membership and (not group.is_public or is_banned):
        raise Http404

    messages_data = []
    has_older_messages = False
    can_post = False
    can_moderate = False
    if request.user.is_staff or membership:
        page_messages = list(
            ChatMessage.objects.filter(group=group)
            .select_related("group", "sender", "reply_to", "reply_to__sender")
            .prefetch_related("reactions", "demo_reaction_counts")
            .order_by("-created_at", "-pk")[:100]
        )
        page_messages.reverse()
        has_older_messages = len(page_messages) == 100
        messages_data = [_message_json(message, request.user.pk) for message in page_messages]
        if (membership or request.user.is_staff) and page_messages:
            latest_message_id = page_messages[-1].pk
            mark_chat_group_read(request.user, group, latest_message_id)
        can_post = user_can_post(request.user, group)
        can_moderate = user_can_moderate(request.user, group)

    context = {
        "group": group,
        "membership": membership,
        "is_banned": is_banned,
        "actual_member_count": group.member_count,
        "display_member_count": group.member_count + group.demo_member_offset,
        "messages_data": messages_data,
        "has_older_messages": has_older_messages,
        "can_post": can_post,
        "can_moderate": can_moderate,
        "ws_path": f"/ws/chat/groups/{group.pk}/",
        "history_url": reverse("chat_group_history", args=(group.pk,)),
        "read_url": reverse("chat_group_mark_read", args=(group.pk,)),
        "demo_growth_url_template": reverse("chat_message_demo_growth", args=(0,)),
    }
    return render(request, "investments/chat_room.html", context)


@login_required
@require_GET
def chat_group_history(request, pk):
    if not _eligible_user(request.user):
        return JsonResponse({"ok": False, "error": "يلزم اعتماد الحساب لاستخدام المحادثة."}, status=403)
    group = get_object_or_404(ChatGroup, pk=pk, is_active=True)
    if not group_member_access(request.user, group):
        return JsonResponse({"ok": False, "error": "لا تملك صلاحية مشاهدة رسائل هذه المجموعة."}, status=403)
    try:
        before_id = int(request.GET.get("before", ""))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "مؤشر الرسالة غير صالح."}, status=400)

    cursor = get_object_or_404(ChatMessage, pk=before_id, group=group)
    older_messages = list(
        ChatMessage.objects.filter(group=group)
        .filter(Q(created_at__lt=cursor.created_at) | Q(created_at=cursor.created_at, pk__lt=cursor.pk))
        .select_related("group", "sender", "reply_to", "reply_to__sender")
        .prefetch_related("reactions", "demo_reaction_counts")
        .order_by("-created_at", "-pk")[:51]
    )
    has_more = len(older_messages) > 50
    older_messages = list(reversed(older_messages[:50]))
    response = JsonResponse({
        "ok": True,
        "messages": [_message_json(message, request.user.pk) for message in older_messages],
        "has_more": has_more,
    })
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
def chat_group_send(request, pk):
    if not _eligible_user(request.user):
        return JsonResponse({"ok": False, "error": "يلزم اعتماد الحساب لاستخدام المحادثة."}, status=403)
    group = get_object_or_404(ChatGroup, pk=pk, is_active=True)
    if not group_member_access(request.user, group) or not user_can_post(request.user, group):
        return JsonResponse({"ok": False, "error": "لا تملك صلاحية الإرسال في هذه المجموعة."}, status=403)
    form = ChatUploadForm(request.POST, request.FILES, group=group)
    if not form.is_valid():
        errors = [str(error) for errors in form.errors.values() for error in errors]
        return JsonResponse({"ok": False, "error": errors[0] if errors else "راجع بيانات الرسالة."}, status=400)
    try:
        message_data = create_uploaded_message(group.pk, request.user.pk, form)
    except ChatRuleError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    try:
        _broadcast_group_message(group.pk, {"type": "message_created", "message": message_data})
    except Exception:
        logger.exception("Could not broadcast chat message %s", message_data["id"])
    return JsonResponse({"ok": True, "message": message_data})


@login_required
@require_POST
def chat_message_demo_growth(request, pk):
    if not request.user.is_staff:
        return JsonResponse({"ok": False, "error": "إعداد الزيادة التجريبية متاح للإدارة فقط."}, status=403)
    message = get_object_or_404(ChatMessage.objects.select_related("group"), pk=pk)
    form = ChatDemoGrowthForm(request.POST, group=message.group)
    if not form.is_valid():
        errors = [str(error) for field_errors in form.errors.values() for error in field_errors]
        return JsonResponse({"ok": False, "error": errors[0] if errors else "راجع إعدادات الزيادة."}, status=400)
    try:
        message_data = configure_message_demo_growth(message.pk, request.user.pk, form.cleaned_data)
    except ChatRuleError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    try:
        _broadcast_group_message(message.group_id, {"type": "message_updated", "message": message_data})
    except Exception:
        logger.exception("Could not broadcast demo reaction settings for message %s", message.pk)
    return JsonResponse({"ok": True, "message": message_data})


def _private_file_response(request, file_field, *, as_attachment, filename=""):
    try:
        file_field.open("rb")
        response = FileResponse(
            file_field,
            as_attachment=as_attachment,
            filename=filename or file_field.name.rsplit("/", 1)[-1],
            content_type=("application/octet-stream" if as_attachment else mimetypes.guess_type(file_field.name)[0] or "image/webp"),
        )
    except (FileNotFoundError, OSError, ValueError, ObjectDoesNotExist):
        raise Http404
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def chat_group_image(request, pk):
    group = get_object_or_404(ChatGroup, pk=pk)
    if not group.image or not group_member_access(request.user, group, allow_public_preview=group.is_public):
        raise Http404
    return _private_file_response(request, group.image, as_attachment=False)


@login_required
def chat_message_attachment(request, pk):
    message = get_object_or_404(ChatMessage.objects.select_related("group"), pk=pk)
    if not group_member_access(request.user, message.group) or not message.group.is_active:
        raise Http404
    if message.image:
        return _private_file_response(request, message.image, as_attachment=False)
    if message.attachment:
        return _private_file_response(
            request,
            message.attachment,
            as_attachment=True,
            filename=message.attachment_name,
        )
    raise Http404
