from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from investments.wallet_services import ensure_wallet


class Command(BaseCommand):
    help = "إنشاء محافظ TRON للحسابات القديمة التي لا تملك محفظة"

    def handle(self, *args, **options):
        created = 0
        User = get_user_model()
        for user in User.objects.iterator():
            _, was_created = ensure_wallet(user)
            created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"اكتمل الفحص؛ تم إنشاء {created} محفظة جديدة."))
