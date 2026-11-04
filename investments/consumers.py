import logging
import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .chat_services import (
    ChatRuleError,
    create_text_message,
    delete_chat_message,
    edit_chat_message,
    group_member_access,
    set_message_reaction,
    user_can_moderate,
    user_can_post,
)
from .models import ChatGroup, ChatGroupPresence


logger = logging.getLogger(__name__)


@database_sync_to_async
def _socket_context(group_id, user):
    group = ChatGroup.objects.filter(pk=group_id, is_active=True).first()
    if not group or not group_member_access(user, group):
        return None
    return {
        "group_id": group.pk,
        "user_id": user.pk,
        "can_post": user_can_post(user, group),
        "can_moderate": user_can_moderate(user, group),
        "can_react": group.reactions_enabled,
    }


@database_sync_to_async
def _register_presence(group_id, user_id, connection_id):
    ChatGroupPresence.objects.update_or_create(
        group_id=group_id,
        user_id=user_id,
        connection_id=connection_id,
        defaults={},
    )


@database_sync_to_async
def _touch_presence(group_id, user_id, connection_id):
    return ChatGroupPresence.objects.filter(
        group_id=group_id, user_id=user_id, connection_id=connection_id
    ).update(last_seen_at=timezone.now())


@database_sync_to_async
def _remove_presence(group_id, user_id, connection_id):
    ChatGroupPresence.objects.filter(
        group_id=group_id, user_id=user_id, connection_id=connection_id
    ).delete()


class GroupChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated or not user.is_active:
            await self.close(code=4401)
            return
        try:
            group_id = int(self.scope["url_route"]["kwargs"]["group_id"])
        except (KeyError, TypeError, ValueError):
            await self.close(code=4404)
            return

        self.chat_context = await _socket_context(group_id, user)
        if self.chat_context is None:
            await self.close(code=4403)
            return
        self.presence_connection_id = uuid.uuid4()
        await _register_presence(
            self.chat_context["group_id"], self.chat_context["user_id"], self.presence_connection_id
        )
        self.room_group_name = f"chat_group_{self.chat_context['group_id']}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        await self.send_json({"type": "ready", **self.chat_context})

    async def disconnect(self, close_code):
        room_group_name = getattr(self, "room_group_name", None)
        if room_group_name:
            await self.channel_layer.group_discard(room_group_name, self.channel_name)
        if getattr(self, "presence_connection_id", None) and getattr(self, "chat_context", None):
            await _remove_presence(
                self.chat_context["group_id"], self.chat_context["user_id"], self.presence_connection_id
            )

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            await self.send_json({"type": "error", "message": "صيغة الطلب غير صالحة."})
            return
        # Older chat clients may use `type` for the command field, while the
        # current client uses `action` (responses continue to use `type`).
        action = content.get("action") or content.get("type")
        user_id = self.chat_context["user_id"]
        try:
            if action == "heartbeat":
                await _touch_presence(
                    self.chat_context["group_id"], user_id, self.presence_connection_id
                )
            elif action == "send":
                message = await database_sync_to_async(create_text_message)(
                    self.chat_context["group_id"], user_id, str(content.get("text", ""))[:2000],
                    content.get("reply_to"),
                )
                await self.send_json({"type": "message_accepted", "message_id": message["id"]})
                await self._broadcast({"type": "message_created", "message": message})
            elif action == "edit":
                message = await database_sync_to_async(edit_chat_message)(
                    int(content.get("message_id")), user_id, str(content.get("text", ""))[:2000]
                )
                await self._broadcast({"type": "message_updated", "message": message})
            elif action == "delete":
                result = await database_sync_to_async(delete_chat_message)(int(content.get("message_id")), user_id)
                await self._broadcast({"type": "message_deleted", "message_id": result["message_id"]})
            elif action == "react":
                result = await database_sync_to_async(set_message_reaction)(
                    int(content.get("message_id")), user_id, str(content.get("kind", ""))
                )
                await self._broadcast({"type": "reaction_updated", **result})
            else:
                logger.warning(
                    "Unknown group chat websocket action %r for user %s in group %s",
                    str(action)[:64], user_id, self.chat_context["group_id"],
                )
                await self.send_json({"type": "error", "message": "الإجراء غير معروف."})
        except (ChatRuleError, ValueError, TypeError, ObjectDoesNotExist) as exc:
            message = str(exc) if isinstance(exc, ChatRuleError) else "تعذّر تنفيذ الإجراء. حدّث الصفحة وحاول مجدداً."
            await self.send_json({"type": "error", "message": message})

    async def _broadcast(self, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "chat.broadcast", "payload": payload},
        )

    async def chat_broadcast(self, event):
        payload = event.get("payload", {})
        if payload.get("type") in {"member_banned", "member_removed"}:
            if payload.get("target_user_id") == self.chat_context["user_id"]:
                await self.send_json({"type": "access_revoked", "message": "لم تعد عضواً في هذه المجموعة."})
                await self.close(code=4403)
            return
        if payload.get("type") == "group_closed":
            await self.send_json({"type": "group_closed", "message": "تم إيقاف هذه المجموعة."})
            await self.close(code=4403)
            return
        await self.send_json(payload)
