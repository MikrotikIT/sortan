import logging

from celery import shared_task

from .wallet_services import sync_all_wallets


logger = logging.getLogger(__name__)


@shared_task
def sync_tron_deposits():
    """Fetch confirmed TRC20 USDT transfers and refresh deposit wallet balances."""
    result = sync_all_wallets()
    logger.info(
        "TRON deposit sync completed: updated=%s imported=%s",
        result["updated"],
        result["imported"],
    )
    for error in result["errors"]:
        logger.warning("TRON wallet sync failed: %s", error)
    return result
