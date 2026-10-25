from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ImproperlyConfigured

from investments.wallet_services import sync_all_wallets


class Command(BaseCommand):
    help = "مزامنة إيداعات USDT TRC20 المؤكدة وأرصدة محافظ العملاء"

    def handle(self, *args, **options):
        try:
            result = sync_all_wallets()
        except ImproperlyConfigured as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"تم تحديث {result['updated']} محفظة وإضافة {result['imported']} إيداع مؤكد."
        ))
        if result["errors"]:
            for error in result["errors"]:
                self.stderr.write(self.style.WARNING(error))
