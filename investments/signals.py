from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .wallet_services import ensure_wallet


@receiver(post_save, sender=get_user_model())
def create_user_tron_wallet(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        ensure_wallet(instance)
