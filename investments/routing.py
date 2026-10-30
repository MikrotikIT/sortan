from django.urls import path

from .consumers import GroupChatConsumer


websocket_urlpatterns = [
    path("ws/chat/groups/<int:group_id>/", GroupChatConsumer.as_asgi()),
]
