import logging
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import get_valid_filename
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
from .models import ChatDemoAccount, ChatGroup, ChatGroupBan, ChatMembership, ChatMessage, ChatReaction
from .chat_services import create_uploaded_message


logger = logging.getLogger(__name__)


def _eligible_user(user):
    return user.is_authenticated and user.is_active and (user.is_staff or user.approval_status == "approved")


CHAT_VIDEO_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
CHAT_VIDEO_UPLOAD_MAX_SIZE = 200 * 1024 * 1024


def _chat_video_upload_paths(upload_id):
    root = (Path(settings.PRIVATE_MEDIA_ROOT) / "group-chat" / "uploads").resolve()
    upload_dir = (root / str(upload_id)).resolve()
    upload_dir.relative_to(root)
    return root, upload_dir


def _load_chat_video_upload(upload_id, group, user):
    _root, upload_dir = _chat_video_upload_paths(upload_id)
    metadata_path = upload_dir / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if metadata.get("group_id") != group.pk or metadata.get("user_id") != user.pk:
        return None, None
    return metadata, upload_dir


def _video_upload_permission_error(request, group_id):
    if not _eligible_user(request.user):
        return JsonResponse({"ok": False, "error": "يلزم اعتماد الحساب لاستخدام المحادثة."}, status=403)
    group = ChatGroup.objects.filter(pk=group_id, is_active=True).first()
    if group is None or not group_member_access(request.user, group) or not user_can_post(request.user, group):
        return JsonResponse({"ok": False, "error": "لا تملك صلاحية الإرسال في هذه المجموعة."}, status=403)
    if not group.allow_videos:
        return JsonResponse({"ok": False, "error": "إرسال الفيديو متوقف في هذه المجموعة."}, status=403)
    return group


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
        .order_by("display_order", "title", "pk")
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
    demo_account = None
    demo_account_value = request.GET.get("demo_account_id")
    if demo_account_value:
        if not request.user.is_staff:
            return JsonResponse({"ok": False}, status=403)
        try:
            demo_account_id = int(demo_account_value)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False}, status=400)
        demo_account = ChatDemoAccount.objects.filter(pk=demo_account_id, group__is_active=True).first()
        if demo_account is None or (group_ids and demo_account.group_id not in group_ids):
            return JsonResponse({"ok": False}, status=404)
        group_ids = [demo_account.group_id]
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
            .prefetch_related("reactions", "demo_reaction_counts", "demo_account_reactions")
        )
        serialized_messages = [
            serialize_chat_message(message, viewer_id=request.user.pk, demo_account_id=demo_account.pk if demo_account else None)
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
def chat_video_upload_start(request, pk):
    group = _video_upload_permission_error(request, pk)
    if isinstance(group, JsonResponse):
        return group

    try:
        file_size = int(request.POST.get("size", ""))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "تعذر قراءة حجم الفيديو."}, status=400)
    original_name = get_valid_filename(Path(request.POST.get("name", "").replace("\\", "/")).name)[:255]
    extension = Path(original_name).suffix.lstrip(".").lower()
    if not original_name or extension not in ChatUploadForm.ALLOWED_VIDEO_EXTENSIONS:
        return JsonResponse({"ok": False, "error": "صيغة الفيديو غير مدعومة."}, status=400)
    if file_size <= 0 or file_size > CHAT_VIDEO_UPLOAD_MAX_SIZE:
        return JsonResponse({"ok": False, "error": "يجب ألا يتجاوز حجم الفيديو 200 ميغابايت."}, status=400)

    root, _upload_dir = _chat_video_upload_paths(uuid.uuid4())
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    cutoff = timezone.now().timestamp() - 24 * 60 * 60
    for stale_dir in root.iterdir():
        if not stale_dir.is_dir():
            continue
        try:
            uuid.UUID(stale_dir.name)
            if stale_dir.stat().st_mtime < cutoff:
                shutil.rmtree(stale_dir, ignore_errors=True)
        except (ValueError, OSError):
            continue

    requested_upload_id = request.POST.get("upload_id", "").strip()
    if requested_upload_id:
        try:
            requested_upload_id = uuid.UUID(requested_upload_id)
        except ValueError:
            return JsonResponse({"ok": False, "error": "جلسة رفع الفيديو غير صالحة."}, status=400)
        existing_metadata, _existing_dir = _load_chat_video_upload(requested_upload_id, group, request.user)
        if (
            existing_metadata
            and existing_metadata.get("name") == original_name
            and existing_metadata.get("size") == file_size
            and existing_metadata.get("last_modified") == request.POST.get("last_modified", "")
        ):
            received_chunks = []
            _root, existing_dir = _chat_video_upload_paths(requested_upload_id)
            for index in range(existing_metadata["chunk_count"]):
                chunk_path = existing_dir / f"chunk-{index:06d}.part"
                expected_size = min(
                    existing_metadata["chunk_size"],
                    existing_metadata["size"] - index * existing_metadata["chunk_size"],
                )
                if chunk_path.is_file() and chunk_path.stat().st_size == expected_size:
                    received_chunks.append(index)
            return JsonResponse({
                "ok": True,
                "upload_id": str(requested_upload_id),
                "chunk_size": existing_metadata["chunk_size"],
                "chunk_count": existing_metadata["chunk_count"],
                "received_chunks": received_chunks,
                "chunk_url": reverse("chat_video_upload_chunk", args=(group.pk, requested_upload_id, 0)),
                "complete_url": reverse("chat_video_upload_complete", args=(group.pk, requested_upload_id)),
                "cancel_url": reverse("chat_video_upload_cancel", args=(group.pk, requested_upload_id)),
            })

    upload_id = uuid.uuid4()
    root, upload_dir = _chat_video_upload_paths(upload_id)
    upload_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    chunk_count = (file_size + CHAT_VIDEO_UPLOAD_CHUNK_SIZE - 1) // CHAT_VIDEO_UPLOAD_CHUNK_SIZE
    metadata = {
        "group_id": group.pk,
        "user_id": request.user.pk,
        "name": original_name,
        "size": file_size,
        "chunk_size": CHAT_VIDEO_UPLOAD_CHUNK_SIZE,
        "chunk_count": chunk_count,
        "content_type": mimetypes.guess_type(original_name)[0] or "application/octet-stream",
        "last_modified": request.POST.get("last_modified", ""),
    }
    (upload_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return JsonResponse({
        "ok": True,
        "upload_id": str(upload_id),
        "chunk_size": CHAT_VIDEO_UPLOAD_CHUNK_SIZE,
        "chunk_count": chunk_count,
        "received_chunks": [],
        "chunk_url": reverse("chat_video_upload_chunk", args=(group.pk, upload_id, 0)),
        "complete_url": reverse("chat_video_upload_complete", args=(group.pk, upload_id)),
        "cancel_url": reverse("chat_video_upload_cancel", args=(group.pk, upload_id)),
    })


@login_required
@require_POST
def chat_video_upload_chunk(request, pk, upload_id, chunk_index):
    group = _video_upload_permission_error(request, pk)
    if isinstance(group, JsonResponse):
        return group
    metadata, upload_dir = _load_chat_video_upload(upload_id, group, request.user)
    if metadata is None:
        return JsonResponse({"ok": False, "error": "جلسة رفع الفيديو غير موجودة أو انتهت صلاحيتها."}, status=404)
    if chunk_index < 0 or chunk_index >= metadata["chunk_count"]:
        return JsonResponse({"ok": False, "error": "رقم جزء الفيديو غير صالح."}, status=400)
    uploaded_chunk = request.FILES.get("chunk")
    if uploaded_chunk is None:
        return JsonResponse({"ok": False, "error": "لم يصل جزء الفيديو."}, status=400)
    expected_size = min(
        metadata["chunk_size"],
        metadata["size"] - chunk_index * metadata["chunk_size"],
    )
    if uploaded_chunk.size != expected_size:
        return JsonResponse({"ok": False, "error": "حجم جزء الفيديو غير مكتمل؛ أعد المحاولة."}, status=400)

    chunk_path = upload_dir / f"chunk-{chunk_index:06d}.part"
    temporary_path = upload_dir / f".chunk-{chunk_index:06d}-{uuid.uuid4().hex}.tmp"
    written = 0
    try:
        with temporary_path.open("xb") as destination:
            for chunk in uploaded_chunk.chunks():
                destination.write(chunk)
                written += len(chunk)
        if written != expected_size:
            temporary_path.unlink(missing_ok=True)
            return JsonResponse({"ok": False, "error": "لم يكتمل حفظ جزء الفيديو؛ أعد المحاولة."}, status=400)
        os.replace(temporary_path, chunk_path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        logger.exception("Could not save video upload chunk %s for upload %s", chunk_index, upload_id)
        return JsonResponse({"ok": False, "error": "تعذر حفظ جزء الفيديو على الخادم."}, status=500)
    return JsonResponse({"ok": True, "chunk_index": chunk_index})


@login_required
@require_POST
def chat_video_upload_cancel(request, pk, upload_id):
    if not _eligible_user(request.user):
        return JsonResponse({"ok": False, "error": "يلزم اعتماد الحساب لاستخدام المحادثة."}, status=403)
    group = ChatGroup.objects.filter(pk=pk).first()
    if group is None:
        return JsonResponse({"ok": False, "error": "مجموعة المحادثة غير موجودة."}, status=404)
    _metadata, upload_dir = _load_chat_video_upload(upload_id, group, request.user)
    if upload_dir is None:
        return JsonResponse({"ok": True})
    shutil.rmtree(upload_dir, ignore_errors=True)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def chat_video_upload_complete(request, pk, upload_id):
    group = _video_upload_permission_error(request, pk)
    if isinstance(group, JsonResponse):
        return group
    metadata, upload_dir = _load_chat_video_upload(upload_id, group, request.user)
    if metadata is None:
        return JsonResponse({"ok": False, "error": "جلسة رفع الفيديو غير موجودة أو انتهت صلاحيتها."}, status=404)

    assembled_path = upload_dir / "assembled.upload"
    written = 0
    try:
        with assembled_path.open("wb") as destination:
            for index in range(metadata["chunk_count"]):
                chunk_path = upload_dir / f"chunk-{index:06d}.part"
                expected_size = min(
                    metadata["chunk_size"],
                    metadata["size"] - index * metadata["chunk_size"],
                )
                if not chunk_path.is_file() or chunk_path.stat().st_size != expected_size:
                    assembled_path.unlink(missing_ok=True)
                    return JsonResponse({"ok": False, "error": "بعض أجزاء الفيديو لم تصل بعد؛ أعد إرسالها."}, status=400)
                with chunk_path.open("rb") as source:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                    written += expected_size
        if written != metadata["size"]:
            assembled_path.unlink(missing_ok=True)
            return JsonResponse({"ok": False, "error": "حجم الفيديو المرفوع غير مكتمل."}, status=400)
    except OSError:
        assembled_path.unlink(missing_ok=True)
        logger.exception("Could not assemble chat video upload %s", upload_id)
        return JsonResponse({"ok": False, "error": "تعذر تجميع أجزاء الفيديو على الخادم."}, status=500)

    uploaded_video = UploadedFile(
        assembled_path.open("rb"),
        name=metadata["name"],
        content_type=metadata["content_type"],
        size=metadata["size"],
    )
    form = ChatUploadForm(request.POST, {"video": uploaded_video}, group=group)
    if not form.is_valid():
        errors = [str(error) for field_errors in form.errors.values() for error in field_errors]
        uploaded_video.close()
        assembled_path.unlink(missing_ok=True)
        return JsonResponse({"ok": False, "error": errors[0] if errors else "راجع بيانات الفيديو."}, status=400)
    try:
        message_data = create_uploaded_message(group.pk, request.user.pk, form)
    except ChatRuleError as exc:
        uploaded_video.close()
        assembled_path.unlink(missing_ok=True)
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    finally:
        uploaded_video.close()

    shutil.rmtree(upload_dir, ignore_errors=True)
    try:
        _broadcast_group_message(group.pk, {"type": "message_created", "message": message_data})
    except Exception:
        logger.exception("Could not broadcast chat message %s", message_data["id"])
    return JsonResponse({"ok": True, "message": message_data})


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
            .prefetch_related("reactions", "demo_reaction_counts", "demo_account_reactions")
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
def chat_group_detail(request, pk):
    if not _eligible_user(request.user):
        return redirect("account_review")
    group = get_object_or_404(ChatGroup, pk=pk, is_active=True)
    membership = ChatMembership.objects.filter(group=group, user=request.user).first()
    is_banned = ChatGroupBan.objects.filter(group=group, user=request.user).exists()
    if not request.user.is_staff and not membership and not group.is_public:
        raise Http404

    member_count = group.member_count
    is_full = bool(group.max_members and member_count >= group.max_members)
    can_join = bool(group.is_public and not request.user.is_staff and not membership and not is_banned and not is_full)
    can_open_room = bool(request.user.is_staff or (membership and not is_banned))
    reaction_emojis = {
        "like": "👍",
        "heart": "❤️",
        "fire": "🔥",
        "clap": "👏",
        "dislike": "👎",
    }
    allowed_reactions = set(group.allowed_reactions or ())
    reactions = [
        {"kind": kind, "label": label, "emoji": reaction_emojis[kind]}
        for kind, label in ChatReaction.Kind.choices
        if kind in allowed_reactions
    ]

    return render(
        request,
        "investments/chat_group_detail.html",
        {
            "group": group,
            "membership": membership,
            "is_banned": is_banned,
            "member_count": member_count,
            "display_member_count": member_count + group.demo_member_offset,
            "is_full": is_full,
            "can_join": can_join,
            "can_open_room": can_open_room,
            "reactions": reactions,
            "image_url": reverse("chat_group_image", args=(group.pk,)) if group.image and not is_banned else "",
        },
    )


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
        .prefetch_related("reactions", "demo_reaction_counts", "demo_account_reactions")
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
        demo_account_value = request.POST.get("demo_account_id")
        demo_account_id = int(demo_account_value) if demo_account_value else None
        message_data = configure_message_demo_growth(
            message.pk,
            request.user.pk,
            form.cleaned_data,
            demo_account_id=demo_account_id,
        )
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "هوية الحساب التجريبي غير صالحة."}, status=400)
    except ChatRuleError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    try:
        _broadcast_group_message(
            message.group_id,
            {"type": "message_updated", "message": message_data, "demo_account_id": demo_account_id},
        )
    except Exception:
        logger.exception("Could not broadcast demo reaction settings for message %s", message.pk)
    return JsonResponse({"ok": True, "message": message_data})


def _stream_file_range(file_obj, remaining):
    while remaining > 0:
        chunk = file_obj.read(min(64 * 1024, remaining))
        if not chunk:
            break
        remaining -= len(chunk)
        yield chunk


def _private_file_response(request, file_field, *, as_attachment, filename="", content_type=None, enable_ranges=False):
    try:
        file_field.open("rb")
        response_type = content_type or (
            "application/octet-stream" if as_attachment else mimetypes.guess_type(file_field.name)[0] or "image/webp"
        )
        if enable_ranges:
            size = file_field.size
            range_header = request.headers.get("Range", "")
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
                if not match or size == 0:
                    file_field.close()
                    response = HttpResponse(status=416)
                    response["Content-Range"] = f"bytes */{size}"
                    response["Cache-Control"] = "private, no-store"
                    return response
                start_text, end_text = match.groups()
                if not start_text:
                    suffix_length = int(end_text or 0)
                    start = max(0, size - suffix_length)
                    end = size - 1
                else:
                    start = int(start_text)
                    end = min(int(end_text) if end_text else size - 1, size - 1)
                if start >= size or end < start:
                    file_field.close()
                    response = HttpResponse(status=416)
                    response["Content-Range"] = f"bytes */{size}"
                    response["Cache-Control"] = "private, no-store"
                    return response
                length = end - start + 1
                file_field.seek(start)
                response = StreamingHttpResponse(
                    _stream_file_range(file_field, length),
                    status=206,
                    content_type=response_type,
                )
                response["Content-Range"] = f"bytes {start}-{end}/{size}"
                response["Content-Length"] = str(length)
                response._resource_closers.append(file_field.close)
            else:
                response = FileResponse(file_field, as_attachment=as_attachment, filename=filename or file_field.name.rsplit("/", 1)[-1], content_type=response_type)
            response["Accept-Ranges"] = "bytes"
        else:
            response = FileResponse(
                file_field,
                as_attachment=as_attachment,
                filename=filename or file_field.name.rsplit("/", 1)[-1],
                content_type=response_type,
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
    if message.voice_message:
        voice_types = {
            "webm": "audio/webm", "ogg": "audio/ogg", "m4a": "audio/mp4",
            "mp3": "audio/mpeg", "wav": "audio/wav", "aac": "audio/aac",
        }
        extension = Path(message.voice_message.name).suffix.lower().lstrip(".")
        return _private_file_response(
            request,
            message.voice_message,
            as_attachment=False,
            content_type=voice_types.get(extension, "application/octet-stream"),
            enable_ranges=True,
        )
    if message.video:
        extension = Path(message.video.name).suffix.lower().lstrip(".")
        video_types = {"mov": "video/quicktime", "mkv": "video/x-matroska", "3gp": "video/3gpp"}
        content_type = video_types.get(extension, mimetypes.guess_type(message.video.name)[0] or "video/mp4")
        return _private_file_response(
            request,
            message.video,
            as_attachment=False,
            content_type=content_type,
            enable_ranges=True,
        )
    if message.attachment:
        return _private_file_response(
            request,
            message.attachment,
            as_attachment=True,
            filename=message.attachment_name,
        )
    raise Http404


@login_required
@require_GET
def chat_message_video_stream(request, pk, resource):
    message = get_object_or_404(ChatMessage.objects.select_related("group"), pk=pk)
    if (
        not message.group.is_active
        or not group_member_access(request.user, message.group)
        or not message.video
        or message.video_status != "ready"
        or not message.video_hls_dir
    ):
        raise Http404

    private_root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
    stream_root = (private_root / message.video_hls_dir).resolve()
    stream_path = (stream_root / resource).resolve()
    try:
        stream_root.relative_to(private_root)
        stream_path.relative_to(stream_root)
    except ValueError:
        raise Http404
    if not stream_path.is_file():
        raise Http404

    content_type = {
        ".m3u8": "application/vnd.apple.mpegurl",
        ".ts": "video/mp2t",
    }.get(stream_path.suffix.lower(), "application/octet-stream")
    try:
        response = FileResponse(stream_path.open("rb"), content_type=content_type)
    except OSError:
        raise Http404
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
