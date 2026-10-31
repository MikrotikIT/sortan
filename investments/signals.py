from django.contrib.auth import get_user_model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .wallet_services import ensure_wallet
from .models import ChatGroup, ChatMessage, JoinApplication, UserNotification
from .push_services import queue_user_notification_push


@receiver(post_save, sender=get_user_model())
def create_user_tron_wallet(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        ensure_wallet(instance)


@receiver(post_save, sender=UserNotification)
def send_user_notification_to_app(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        queue_user_notification_push(instance.pk)


@receiver(post_delete, sender=JoinApplication)
def delete_join_application_photo(sender, instance, **kwargs):
    if instance.profile_image:
        instance.profile_image.delete(save=False)


@receiver(post_delete, sender=ChatGroup)
def delete_chat_group_image(sender, instance, **kwargs):
    if instance.image:
        instance.image.delete(save=False)


@receiver(post_delete, sender=ChatMessage)
def delete_chat_message_files(sender, instance, **kwargs):
    for field_name in ("image", "attachment"):
        uploaded_file = getattr(instance, field_name)
        if uploaded_file:
            uploaded_file.delete(save=False)
