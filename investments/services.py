from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import (
    Deposit,
    Investment,
    PlatformSettings,
    ReferralCommission,
    User,
    WithdrawalRequest,
)

CENT = Decimal("0.01")


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
def approve_deposit(deposit_id):
    deposit = Deposit.objects.select_for_update(of=("self",)).select_related("user__referred_by").get(pk=deposit_id)
    if deposit.status != Deposit.Status.PENDING:
        return False
    user = User.objects.select_for_update().get(pk=deposit.user_id)
    user.balance += deposit.amount
    user.save(update_fields=("balance",))
    settings = get_platform_settings()
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
    if deposit.status != Deposit.Status.PENDING:
        return False
    deposit.status = Deposit.Status.REJECTED
    deposit.processed_at = timezone.now()
    deposit.save(update_fields=("status", "processed_at"))
    return True


@transaction.atomic
def pay_withdrawal(withdrawal_id):
    withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal_id)
    if withdrawal.status != WithdrawalRequest.Status.PENDING:
        return False
    withdrawal.status = WithdrawalRequest.Status.PAID
    withdrawal.processed_at = timezone.now()
    withdrawal.save(update_fields=("status", "processed_at"))
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
