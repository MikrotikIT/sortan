from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from investments.models import Wallet
from investments.wallet_services import decrypt_private_key, encrypt_private_key


class Command(BaseCommand):
    help = "إعادة تشفير مفاتيح المحافظ باستخدام WALLET_ENCRYPTION_KEY الحالي"

    def handle(self, *args, **options):
        if not settings.WALLET_ENCRYPTION_KEY:
            raise CommandError("اضبط WALLET_ENCRYPTION_KEY أولاً، ثم أعد تشغيل هذا الأمر.")
        changed = 0
        for wallet in Wallet.objects.iterator():
            private_key = decrypt_private_key(wallet.encrypted_private_key)
            wallet.encrypted_private_key = encrypt_private_key(private_key)
            wallet.save(update_fields=("encrypted_private_key",))
            changed += 1
        self.stdout.write(self.style.SUCCESS(f"أعيد تشفير مفاتيح {changed} محفظة."))
