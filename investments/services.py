from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.utils.html import format_html
from django.utils import timezone

from .models import (
    Deposit,
    Investment,
    PlatformSettings,
    ReferralCommission,
    User,
    UserNotification,
    WithdrawalRequest,
)

CENT = Decimal("0.01")


def parse_deposit_activity_examples(value):
    examples = []
    for line_number, line in enumerate((value or "").splitlines(), start=1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 3 or not all(parts):
            raise ValueError(f"السطر {line_number}: استخدم الصيغة الدولة|رقم الهاتف|المبلغ.")
        country, phone, amount_text = parts
        try:
            amount = Decimal(amount_text.replace(",", ""))
        except InvalidOperation as exc:
            raise ValueError(f"السطر {line_number}: أدخل مبلغاً صحيحاً.") from exc
        if not amount.is_finite() or amount <= 0:
            raise ValueError(f"السطر {line_number}: يجب أن يكون المبلغ أكبر من صفر.")
        if not any(mask in phone for mask in ("*", "•", "×")):
            phone = f"{phone[:-3]}***" if len(phone) > 3 else "***"
        examples.append({"country": country, "phone": phone, "amount": format(amount, "f")})
    return examples


def parse_withdrawal_referral_rules(value):
    rules = []
    for item in (value or "").replace("،", ",").split(","):
        item = item.strip()
        if not item:
            continue
        withdrawal_count, referral_count = item.split(":", 1)
        withdrawal_count = int(withdrawal_count.strip())
        referral_count = int(referral_count.strip())
        if withdrawal_count < 1 or referral_count < 1:
            raise ValueError("يجب أن تكون أعداد السحوبات والمدعوين أعداداً موجبة.")
        rules.append((withdrawal_count, referral_count))
    return sorted(rules)


def get_platform_settings():
    settings, _ = PlatformSettings.objects.get_or_create(pk=1)
    return settings


def deposit_status_for_amount(amount, settings=None):
    settings = settings or get_platform_settings()
    if amount < settings.minimum_deposit_amount:
        return Deposit.Status.UNEXPECTED
    return Deposit.Status.PENDING


def withdraw_available_at(user, settings=None):
    settings = settings or get_platform_settings()
    if not settings.withdrawal_cooldown_enabled:
        return None
    last_paid = user.withdrawals.filter(status=WithdrawalRequest.Status.PAID).order_by("-processed_at").first()
    anchor = last_paid.processed_at if last_paid and last_paid.processed_at else user.date_joined
    from datetime import timedelta

    return anchor + timedelta(days=settings.withdrawal_interval_days)


def settle_due_investments(user=None):
    now = timezone.now()
    due = Investment.objects.filter(status=Investment.Status.ACTIVE, matures_at__lte=now)
    if user is not None:
        due = due.filter(user=user)
    settings = get_platform_settings()
    settled = 0
    with transaction.atomic():
        for investment in due.select_for_update(of=("self",)).select_related("user__referred_by").order_by("id"):
            if investment.status != Investment.Status.ACTIVE:
                continue
            owner = User.objects.select_for_update().get(pk=investment.user_id)
            profit = (investment.amount * investment.profit_percent / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
            if investment.funding_source == Investment.FundingSource.BALANCE:
                owner.balance += investment.amount
            owner.earnings_balance += profit
            owner.total_earned += profit
            owner.save(update_fields=("balance", "earnings_balance", "total_earned"))
            investment.realized_profit = profit
            investment.status = Investment.Status.COMPLETED
            investment.settled_at = now
            investment.save(update_fields=("realized_profit", "status", "settled_at"))
            if owner.referred_by_id and settings.referral_profit_percent > 0:
                commission_amount = (profit * settings.referral_profit_percent / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
                if commission_amount > 0:
                    commission, created = ReferralCommission.objects.get_or_create(
                        source=ReferralCommission.Source.PROFIT,
                        source_id=investment.pk,
                        defaults={
                            "referrer_id": owner.referred_by_id,
                            "referred_user": owner,
                            "wallet": ReferralCommission.Wallet.EARNINGS,
                            "percent": settings.referral_profit_percent,
                            "amount": commission_amount,
                        },
                    )
                    if created:
                        referrer = User.objects.select_for_update().get(pk=commission.referrer_id)
                        referrer.earnings_balance += commission_amount
                        referrer.total_earned += commission_amount
                        referrer.save(update_fields=("earnings_balance", "total_earned"))
            settled += 1
    return settled


@transaction.atomic
def approve_deposit(deposit_id, *, allow_unexpected=False):
    deposit = Deposit.objects.select_for_update(of=("self",)).select_related("user__referred_by").get(pk=deposit_id)
    if deposit.status not in {Deposit.Status.PENDING, Deposit.Status.UNEXPECTED}:
        return False
    settings = get_platform_settings()
    is_below_minimum = deposit.amount < settings.minimum_deposit_amount
    if (deposit.status == Deposit.Status.UNEXPECTED or is_below_minimum) and not allow_unexpected:
        if is_below_minimum and deposit.status != Deposit.Status.UNEXPECTED:
            deposit.status = Deposit.Status.UNEXPECTED
            deposit.save(update_fields=("status",))
        return False
    user = User.objects.select_for_update().get(pk=deposit.user_id)
    user.balance += deposit.amount
    user.save(update_fields=("balance",))
    if user.referred_by_id and settings.referral_deposit_percent > 0:
        amount = (deposit.amount * settings.referral_deposit_percent / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
        if amount > 0:
            commission, created = ReferralCommission.objects.get_or_create(
                source=ReferralCommission.Source.DEPOSIT,
                source_id=deposit.pk,
                defaults={
                    "referrer_id": user.referred_by_id,
                    "referred_user": user,
                    "wallet": ReferralCommission.Wallet.EARNINGS,
                    "percent": settings.referral_deposit_percent,
                    "amount": amount,
                },
            )
            if created:
                referrer = User.objects.select_for_update().get(pk=commission.referrer_id)
                referrer.earnings_balance += amount
                referrer.total_earned += amount
                referrer.save(update_fields=("earnings_balance", "total_earned"))
    deposit.status = Deposit.Status.APPROVED
    deposit.processed_at = timezone.now()
    deposit.save(update_fields=("status", "processed_at"))
    return True


@transaction.atomic
def reject_deposit(deposit_id):
    deposit = Deposit.objects.select_for_update().get(pk=deposit_id)
    if deposit.status not in {Deposit.Status.PENDING, Deposit.Status.UNEXPECTED}:
        return False
    deposit.status = Deposit.Status.REJECTED
    deposit.processed_at = timezone.now()
    deposit.save(update_fields=("status", "processed_at"))
    return True


@transaction.atomic
def pay_withdrawal(withdrawal_id):
    withdrawal = WithdrawalRequest.objects.select_for_update().select_related("user").get(pk=withdrawal_id)
    if withdrawal.status != WithdrawalRequest.Status.PENDING:
        return False
    withdrawal.status = WithdrawalRequest.Status.PAID
    withdrawal.processed_at = timezone.now()
    withdrawal.save(update_fields=("status", "processed_at"))
    UserNotification.objects.get_or_create(
        related_withdrawal=withdrawal,
        defaults={
            "recipient": withdrawal.user,
            "title": "تم إتمام السحب بنجاح",
            "body_html": format_html(
                "<p>اكتمل طلب السحب رقم <strong>#{}</strong>.</p>"
                "<p>المبلغ قبل الضريبة: {} USDT<br>"
                "الضريبة: {} USDT<br>"
                "صافي المبلغ المدفوع: <strong>{} USDT</strong></p>"
                "<p>عنوان محفظة الاستلام: <code dir=\"ltr\">{}</code></p>"
                "<p>اضغط على عرض تفاصيل السحب للاطلاع على الإيصال الكامل.</p>",
                withdrawal.display_number,
                withdrawal.amount,
                withdrawal.tax_amount,
                withdrawal.net_amount,
                withdrawal.wallet_address,
            ),
        },
    )
    return True


@transaction.atomic
def reject_withdrawal(withdrawal_id, note=""):
    withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal_id)
    if withdrawal.status != WithdrawalRequest.Status.PENDING:
        return False
    user = User.objects.select_for_update().get(pk=withdrawal.user_id)
    user.earnings_balance += withdrawal.amount
    user.save(update_fields=("earnings_balance",))
    withdrawal.status = WithdrawalRequest.Status.REJECTED
    withdrawal.processed_at = timezone.now()
    withdrawal.admin_note = note
    withdrawal.save(update_fields=("status", "processed_at", "admin_note"))
    return True
