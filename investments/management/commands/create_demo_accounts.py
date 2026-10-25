from django.core.management.base import BaseCommand

from investments.models import InvestmentVoucher, User
from investments.services import get_platform_settings
from investments.wallet_services import ensure_wallet


class Command(BaseCommand):
    help = "إنشاء حسابي العميل والإدارة للتجربة المحلية"

    def handle(self, *args, **options):
        settings = get_platform_settings()
        demo_user, _ = User.objects.get_or_create(phone="123")
        demo_user.is_active = True
        demo_user.is_staff = False
        demo_user.is_superuser = False
        demo_user.set_password("123")
        demo_user.save()
        ensure_wallet(demo_user)
        if not demo_user.vouchers.exists():
            InvestmentVoucher.objects.bulk_create(
                [
                    InvestmentVoucher(user=demo_user, amount=settings.default_voucher_amount)
                    for _ in range(settings.default_voucher_count)
                ]
            )

        demo_admin, _ = User.objects.get_or_create(phone="12")
        demo_admin.is_active = True
        demo_admin.is_staff = True
        demo_admin.is_superuser = True
        demo_admin.set_password("12")
        demo_admin.save()
        ensure_wallet(demo_admin)

        self.stdout.write(self.style.SUCCESS("تم تجهيز حسابات التجربة المحلية:"))
        self.stdout.write("العميل: الهاتف 123 — كلمة المرور 123")
        self.stdout.write("الإدارة: الهاتف 12 — كلمة المرور 12")
