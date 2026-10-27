import logging

from celery import shared_task
from django.utils import timezone

from .models import ServiceHeartbeat
from .wallet_services import sync_all_wallets


logger = logging.getLogger(__name__)


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
