import logging
import json
import shutil
import subprocess
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path
from random import choices, randint

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q
from django.urls import reverse
from django.utils import timezone

from .chat_services import REACTION_GLYPHS, allowed_group_reactions, serialize_chat_message
from .models import (
    ChatGroup,
    ChatGroupBan,
    ChatGroupReadState,
    ChatMembership,
    ChatMessage,
    ChatReaction,
    ChatDemoReaction,
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
        preview = (
            "أرسل صورة" if message.image
            else "رسالة صوتية" if message.voice_message
            else "أرسل فيديو" if message.video
            else "أرسل ملفاً" if message.attachment
            else "رسالة جديدة"
        )
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
def process_chat_video(message_id):
    message = ChatMessage.objects.select_related("group", "sender").filter(pk=message_id).first()
    if not message or not message.video:
        return {"status": "missing"}

    private_root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
    if not message.video_hls_dir:
        message.video_hls_dir = f"group-chat/streams/{uuid.uuid4().hex}"
    output_root = (private_root / message.video_hls_dir).resolve()
    try:
        output_root.relative_to(private_root)
    except ValueError:
        logger.error("Unsafe HLS output path for chat message %s", message_id)
        message.video_hls_dir = f"group-chat/streams/{uuid.uuid4().hex}"
        output_root = (private_root / message.video_hls_dir).resolve()

    message.video_status = "processing"
    message.save(update_fields=("video_status", "video_hls_dir"))
    _broadcast_chat(message.group_id, {"type": "message_updated", "message": serialize_chat_message(message)})

    try:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise RuntimeError("FFmpeg and ffprobe must be installed to prepare chat videos.")

        probe = subprocess.run(
            [
                ffprobe, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "json", message.video.path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        streams = json.loads(probe.stdout).get("streams", [])
        if not streams:
            raise ValueError("The uploaded file does not contain a video stream.")
        source_width = int(streams[0]["width"])
        source_height = int(streams[0]["height"])
        if source_width < 2 or source_height < 2:
            raise ValueError("The uploaded video has invalid dimensions.")

        output_root.mkdir(parents=True, exist_ok=True)
        target_heights = [height for height in (144, 240, 360, 480, 720) if height < source_height]
        target_heights.append(min(source_height, 720))
        target_heights = sorted(set(target_heights))
        variants = []

        for height in target_heights:
            width_cap = max(2, int(1280 * height / 720) // 2 * 2)
            scale_ratio = min(1, height / source_height, width_cap / source_width)
            width = max(2, int(source_width * scale_ratio) // 2 * 2)
            output_height = max(2, int(source_height * scale_ratio) // 2 * 2)
            bitrate = 300_000 if height <= 240 else 550_000 if height <= 360 else 950_000 if height <= 480 else 1_600_000
            rendition_dir = output_root / f"{height}p"
            rendition_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", message.video.path,
                    "-map", "0:v:0", "-map", "0:a:0?", "-vf", f"scale={width}:{output_height}",
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-b:v", str(bitrate), "-maxrate", str(int(bitrate * 1.15)),
                    "-bufsize", str(bitrate * 2), "-g", "120", "-sc_threshold", "0",
                    "-c:a", "aac", "-b:a", "64k", "-ac", "2", "-ar", "44100",
                    "-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod",
                    "-hls_flags", "independent_segments",
                    "-hls_segment_filename", str(rendition_dir / "segment_%05d.ts"),
                    str(rendition_dir / "index.m3u8"),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=3600,
            )
            if not (rendition_dir / "index.m3u8").is_file():
                raise RuntimeError("FFmpeg did not produce a video playlist.")
            variants.append((height, width, output_height, bitrate + 64_000))

        master_lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS"]
        for height, width, output_height, bandwidth in variants:
            master_lines.extend((
                f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},AVERAGE-BANDWIDTH={bandwidth},RESOLUTION={width}x{output_height}",
                f"{height}p/index.m3u8",
            ))
        (output_root / "master.m3u8").write_text("\n".join(master_lines) + "\n", encoding="utf-8")
        message.video_status = "ready"
        message.save(update_fields=("video_status",))
        result = {"status": "ready", "variants": len(variants)}
    except Exception:
        logger.exception("Could not process chat video %s", message_id)
        shutil.rmtree(output_root, ignore_errors=True)
        message.video_status = "failed"
        message.save(update_fields=("video_status",))
        result = {"status": "failed"}

    _broadcast_chat(message.group_id, {"type": "message_updated", "message": serialize_chat_message(message)})
    return result


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
            allowed_reactions = allowed_group_reactions(message.group)
            if not allowed_reactions:
                continue
            amount = randint(message.demo_growth_step_min, message.demo_growth_step_max)
            configured_weights = {
                ChatReaction.Kind.LIKE.value: message.demo_like_percent,
                ChatReaction.Kind.HEART.value: message.demo_heart_percent,
                ChatReaction.Kind.FIRE.value: message.demo_fire_percent,
                ChatReaction.Kind.CLAP.value: message.demo_clap_percent,
                ChatReaction.Kind.DISLIKE.value: message.demo_dislike_percent,
            }
            weights = [configured_weights[kind] for kind in allowed_reactions]
            if not any(weights):
                weights = [1] * len(allowed_reactions)
            increments = Counter(choices(allowed_reactions, weights=weights, k=amount))
            for kind, increment in increments.items():
                counter, _ = DemoChatReactionCount.objects.get_or_create(message=message, kind=kind, defaults={"count": 0})
                DemoChatReactionCount.objects.filter(pk=counter.pk).update(count=F("count") + increment)
            delay = randint(message.demo_growth_interval_min_seconds, message.demo_growth_interval_max_seconds)
            message.demo_growth_next_at = now + timedelta(seconds=delay)
            message.save(update_fields=("demo_growth_next_at",))
            advanced_messages += 1
        if increments:
            allowed_reactions = allowed_group_reactions(message.group)
            real_counts = {kind: 0 for kind in allowed_reactions}
            for row in ChatReaction.objects.filter(message_id=message_id).values("kind").annotate(total=Count("pk")):
                if row["kind"] in real_counts:
                    real_counts[row["kind"]] = row["total"]
            demo_counts = {kind: 0 for kind in allowed_reactions}
            for row in DemoChatReactionCount.objects.filter(message_id=message_id).values("kind", "count"):
                if row["kind"] in demo_counts:
                    demo_counts[row["kind"]] = row["count"]
            for row in ChatDemoReaction.objects.filter(message_id=message_id).values("kind").annotate(total=Count("pk")):
                if row["kind"] in demo_counts:
                    demo_counts[row["kind"]] += row["total"]
            _broadcast_chat(
                message.group_id,
                {
                    "type": "reaction_updated",
                    "message_id": message_id,
                    "actor_id": None,
                    "actor_reaction": None,
                    "allowed_reactions": list(allowed_reactions),
                    "reactions_enabled": message.group.reactions_enabled,
                    "reactions": [
                        {
                            "kind": kind,
                            "glyph": REACTION_GLYPHS[kind],
                            "count": real_counts[kind] + demo_counts[kind],
                            "real_count": real_counts[kind],
                            "demo_count": demo_counts[kind],
                        }
                        for kind in allowed_reactions
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


@shared_task
def advance_ai_chat_bots():
    from .ai_chat_services import advance_ai_chat_bots as run_ai_chat_bots

    return run_ai_chat_bots()
