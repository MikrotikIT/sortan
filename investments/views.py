from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from random import choice, randint

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.db.models import Max, Q, Sum
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .forms import InvestmentForm, LoginForm, RegistrationForm, WithdrawalForm
from .models import Deposit, Film, Investment, InvestmentVoucher, PlatformSettings, SupportOption, UserNotification, WithdrawalRequest
from .notification_services import sanitize_notification_html
from .services import get_platform_settings, parse_deposit_activity_examples, parse_withdrawal_referral_rules, settle_due_investments, withdraw_available_at
from .wallet_services import ensure_wallet

MIN_REFERRAL_DEPOSIT_FOR_WITHDRAWAL = Decimal("100.00")


def home(request):
    if not request.user.is_authenticated:
        return redirect("login")
    settle_due_investments(request.user)
    request.user.refresh_from_db(fields=("balance", "earnings_balance"))
    return render(
        request,
        "investments/home.html",
        {
            "platform_settings": get_platform_settings(),
            "support_options": SupportOption.objects.filter(is_active=True),
        },
    )


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    referral_code = (request.GET.get("ref") or "").strip().upper()[:12]
    form = RegistrationForm(request.POST or None, initial={"invitation_code": referral_code})
    if request.method == "POST" and form.is_valid():
        user = form.create_user()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "تم إنشاء حسابك وإضافة قسائم الاستثمار المجانية.")
        return redirect("home")
    return render(request, "investments/register.html", {"form": form})


def sign_in(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"].strip()
        user = authenticate(request, phone=phone, password=form.cleaned_data["password"])
        if user is not None:
            login(request, user)
            return redirect("management_dashboard" if user.is_staff else "home")
        form.add_error(None, "رقم الهاتف أو كلمة المرور غير صحيحة.")
    return render(request, "investments/login.html", {"form": form})


@login_required
def sign_out(request):
    if request.method == "POST":
        logout(request)
    return redirect("login")


@login_required
def notification_list(request):
    page = Paginator(
        UserNotification.objects.filter(recipient=request.user)
        .select_related("related_withdrawal")
        .order_by("-created_at", "-pk"),
        30,
    ).get_page(request.GET.get("page"))
    for notification in page.object_list:
        body_html = notification.body_html
        if notification.related_withdrawal_id:
            withdrawal = notification.related_withdrawal
            body_html = body_html.replace(
                f"#{withdrawal.pk}",
                f"#{withdrawal.display_number}",
            )
        notification.rendered_html = mark_safe(sanitize_notification_html(body_html))
    return render(request, "investments/notifications.html", {"notification_page": page})


@login_required
def notification_open(request, pk):
    notification = get_object_or_404(UserNotification, pk=pk, recipient=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=("is_read", "read_at"))
    if notification.related_withdrawal_id:
        return redirect("withdrawal_receipt", pk=notification.related_withdrawal_id)
    return redirect("notifications")


@login_required
def withdrawal_receipt(request, pk):
    withdrawal = get_object_or_404(
        WithdrawalRequest.objects.filter(
            user=request.user,
            status=WithdrawalRequest.Status.PAID,
        ),
        pk=pk,
    )
    return render(request, "investments/withdrawal_receipt.html", {"withdrawal": withdrawal})


@login_required
@require_POST
def notification_mark_read(request, pk):
    notification = get_object_or_404(UserNotification, pk=pk, recipient=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=("is_read", "read_at"))
    return redirect("notifications")


@login_required
@require_POST
def notifications_mark_all_read(request):
    UserNotification.objects.filter(recipient=request.user, is_read=False).update(
        is_read=True,
        read_at=timezone.now(),
    )
    return redirect("notifications")


@login_required
@require_GET
@never_cache
def notification_unread_count(request):
    count = UserNotification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({"count": count})


@login_required
def dashboard(request):
    settle_due_investments(request.user)
    available_vouchers = request.user.vouchers.filter(status=InvestmentVoucher.Status.AVAILABLE)
    voucher_count = available_vouchers.count()
    voucher_total = available_vouchers.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    has_vouchers = voucher_count > 0
    investments = request.user.investments.select_related("film", "voucher")
    return render(
        request,
        "investments/dashboard.html",
        {
            "investments": investments,
            "has_vouchers": has_vouchers,
            "voucher_count": voucher_count,
            "voucher_total": voucher_total,
            "investment_form": InvestmentForm(
                user=request.user,
                has_vouchers=has_vouchers,
                initial={"amount": request.user.balance},
            ),
        },
    )


@login_required
def create_investment(request):
    if request.method != "POST":
        return redirect("dashboard")
    has_vouchers = request.user.vouchers.filter(status=InvestmentVoucher.Status.AVAILABLE).exists()
    form = InvestmentForm(request.POST, user=request.user, has_vouchers=has_vouchers)
    if not form.is_valid():
        for error in form.non_field_errors():
            messages.error(request, error)
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
        return redirect("dashboard")
    with transaction.atomic():
        owner = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        film = Film.objects.select_for_update().filter(pk=form.cleaned_data["film"].pk, active=True).first()
        if film is None:
            messages.error(request, "هذا الفيلم لم يعد متاحاً للاستثمار.")
            return redirect("dashboard")
        if film.is_expired:
            messages.error(request, "انتهت صلاحية رابط هذا الفيلم، ولا يمكن الاستثمار فيه.")
            return redirect("dashboard")
        if Investment.objects.filter(user_id=owner.pk, film_url=film.external_url).exists():
            messages.error(request, "سبق لك الاستثمار في هذا الرابط، ويمكن الاستثمار فيه مرة واحدة فقط.")
            return redirect("dashboard")
        funding_method = form.cleaned_data["funding_method"]
        voucher = None
        if funding_method == Investment.FundingSource.VOUCHER:
            voucher = (
                InvestmentVoucher.objects.select_for_update()
                .filter(user=request.user, status=InvestmentVoucher.Status.AVAILABLE)
                .order_by("created_at")
                .first()
            )
            if voucher is None:
                messages.error(request, "لا توجد لديك قسائم متاحة. اختر الاستثمار من الرصيد.")
                return redirect("dashboard")
            amount = voucher.amount
        else:
            amount = form.cleaned_data["amount"]
            if amount > owner.balance:
                messages.error(request, "رصيدك غير كافٍ لمبلغ الاستثمار المطلوب.")
                return redirect("dashboard")
            owner.balance -= amount
            owner.save(update_fields=("balance",))
        now = timezone.now()
        expected_profit = (amount * film.profit_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        Investment.objects.create(
            user=request.user,
            film=film,
            voucher=voucher,
            funding_source=funding_method,
            film_title=film.title,
            film_image_url=film.image_url,
            film_url=film.external_url,
            amount=amount,
            profit_percent=film.profit_percent,
            expected_profit=expected_profit,
            invested_at=now,
            matures_at=now + timedelta(**{film.waiting_unit: film.waiting_duration}),
        )
        if voucher is not None:
            voucher.status = InvestmentVoucher.Status.USED
            voucher.used_at = now
            voucher.save(update_fields=("status", "used_at"))
    messages.success(request, f"تم تسجيل استثمارك في «{film.title}».")
    return redirect("dashboard")


@login_required
def withdrawals(request):
    settle_due_investments(request.user)
    settings = get_platform_settings()
    available_at = withdraw_available_at(request.user, settings)
    pending_request = request.user.withdrawals.filter(status=WithdrawalRequest.Status.PENDING).exists()
    cooldown_passed = available_at is None or timezone.now() >= available_at
    paid_withdrawal_count = request.user.withdrawals.filter(status=WithdrawalRequest.Status.PAID).count()
    referral_count = (
        request.user.referrals.filter(is_active=True)
        .annotate(
            approved_deposit_total=Sum(
                "deposits__amount",
                filter=Q(deposits__status=Deposit.Status.APPROVED),
            )
        )
        .filter(approved_deposit_total__gte=MIN_REFERRAL_DEPOSIT_FOR_WITHDRAWAL)
        .count()
    )
    active_referral_rule = None
    if settings.withdrawal_referral_gate_enabled:
        try:
            referral_rules = parse_withdrawal_referral_rules(settings.withdrawal_referral_rules)
        except (ValueError, TypeError):
            referral_rules = []
        for rule in referral_rules:
            if paid_withdrawal_count >= rule[0]:
                active_referral_rule = rule
            else:
                break
    referral_gate_reached = active_referral_rule is not None
    required_referral_count = active_referral_rule[1] if active_referral_rule else 0
    referral_gate_blocked = referral_gate_reached and referral_count < required_referral_count
    remaining_referrals = max(required_referral_count - referral_count, 0)
    referral_progress_percent = (
        min(100, int(referral_count * 100 / required_referral_count))
        if required_referral_count
        else 0
    )
    can_request = not pending_request and cooldown_passed and not referral_gate_blocked
    form = WithdrawalForm(request.POST or None)
    if request.method == "POST":
        if referral_gate_blocked:
            messages.error(
                request,
                f"أكمل دعوة {remaining_referrals} مستخدم(ين) قبل تقديم طلب السحب.",
            )
        elif not can_request:
            messages.error(request, "لا يمكنك تقديم طلب سحب جديد حالياً.")
        elif form.is_valid():
            amount = form.cleaned_data["amount"]
            with transaction.atomic():
                user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
                if amount > user.earnings_balance:
                    form.add_error("amount", "المبلغ يتجاوز الأرباح المتاحة للسحب.")
                else:
                    tax_percent = settings.withdrawal_tax_percent if settings.withdrawal_tax_enabled else Decimal("0")
                    tax_amount = (amount * tax_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    user.earnings_balance -= amount
                    user.save(update_fields=("earnings_balance",))
                    WithdrawalRequest.objects.create(
                        user=user,
                        amount=amount,
                        tax_percent=tax_percent,
                        tax_amount=tax_amount,
                        net_amount=amount - tax_amount,
                        wallet_address=form.cleaned_data["wallet_address"],
                    )
                    messages.success(request, "تم إرسال طلب السحب إلى الإدارة للمراجعة.")
                    return redirect("withdrawals")
    return render(
        request,
        "investments/withdrawals.html",
        {
            "form": form,
            "settings": settings,
            "withdrawals": request.user.withdrawals.all(),
            "available_at": available_at,
            "pending_request": pending_request,
            "can_request": can_request,
            "referral_gate_reached": referral_gate_reached,
            "referral_gate_blocked": referral_gate_blocked,
            "active_referral_rule": active_referral_rule,
            "paid_withdrawal_count": paid_withdrawal_count,
            "referral_count": referral_count,
            "remaining_referrals": remaining_referrals,
            "referral_progress_percent": referral_progress_percent,
        },
    )


@login_required
def referrals(request):
    referred_users = request.user.referrals.all().order_by("-date_joined")
    commissions = request.user.referral_commissions.all()
    return render(
        request,
        "investments/referrals.html",
        {
            "referred_users": referred_users,
            "commissions": commissions,
            "referral_count": referred_users.count(),
            "referral_commission_total": commissions.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        },
    )


@login_required
def deposit_wallet(request):
    wallet, _ = ensure_wallet(request.user)
    platform_settings = get_platform_settings()
    try:
        deposit_activity_examples = parse_deposit_activity_examples(platform_settings.deposit_activity_examples)
    except ValueError:
        deposit_activity_examples = []
    recent_direct_deposit = request.user.deposits.filter(
        source=Deposit.Source.TRON,
        status=Deposit.Status.APPROVED,
        created_at__gte=timezone.now() - timedelta(hours=24),
    ).order_by("-created_at").first()
    direct_deposits = request.user.deposits.filter(
        source=Deposit.Source.TRON,
    ).exclude(
        status=Deposit.Status.UNEXPECTED,
    ).order_by("-created_at")[:20]
    latest_direct_deposit_id = request.user.deposits.filter(
        source=Deposit.Source.TRON,
        status=Deposit.Status.APPROVED,
    ).aggregate(latest_id=Max("pk"))["latest_id"] or 0
    return render(
        request,
        "investments/deposit.html",
        {
            "wallet": wallet,
            "minimum_deposit_amount": platform_settings.minimum_deposit_amount,
            "direct_deposits": direct_deposits,
            "latest_direct_deposit_id": latest_direct_deposit_id,
            "recent_direct_deposit": recent_direct_deposit,
            "deposit_activity_enabled": platform_settings.deposit_activity_enabled and bool(deposit_activity_examples),
            "deposit_activity_examples": deposit_activity_examples,
            "deposit_activity_interval_seconds": platform_settings.deposit_activity_interval_seconds,
        },
    )


@login_required
@require_GET
def deposit_notifications(request):
    try:
        after_id = min(max(int(request.GET.get("after", "0")), 0), 2**63 - 1)
    except (TypeError, ValueError):
        return JsonResponse({"error": "رقم الإيداع غير صالح."}, status=400)

    deposits = request.user.deposits.filter(
        source=Deposit.Source.TRON,
        status=Deposit.Status.APPROVED,
        pk__gt=after_id,
    ).order_by("pk")[:20]
    response = JsonResponse({
        "deposits": [
            {
                "id": deposit.pk,
                "amount": format(deposit.amount, "f"),
                "transaction_id": deposit.transaction_id or "",
            }
            for deposit in deposits
        ],
    })
    response["Cache-Control"] = "no-store"
    return response


@login_required
def online_counter(request):
    settings = get_platform_settings()
    if not settings.online_counter_enabled:
        response = JsonResponse({"enabled": False})
        response["Cache-Control"] = "no-store"
        return response

    now = timezone.now()
    minimum = settings.online_counter_min
    maximum = settings.online_counter_max
    current = settings.online_counter_current
    changed_at = settings.online_counter_updated_at
    should_change = current < minimum or current > maximum or changed_at is None
    if not should_change:
        should_change = (now - changed_at).total_seconds() >= 5

    if should_change:
        if current < minimum or current > maximum or changed_at is None:
            next_value = randint(minimum, maximum)
        elif minimum == maximum:
            next_value = minimum
        else:
            possible_directions = []
            if current > minimum:
                possible_directions.append(-1)
            if current < maximum:
                possible_directions.append(1)
            direction = choice(possible_directions)
            step = randint(settings.online_counter_step_min, settings.online_counter_step_max)
            next_value = max(minimum, min(maximum, current + direction * step))

        update_query = PlatformSettings.objects.filter(
            pk=settings.pk,
            online_counter_min=minimum,
            online_counter_max=maximum,
            online_counter_step_min=settings.online_counter_step_min,
            online_counter_step_max=settings.online_counter_step_max,
            online_counter_current=current,
        )
        if changed_at is None:
            update_query = update_query.filter(online_counter_updated_at__isnull=True)
        else:
            update_query = update_query.filter(online_counter_updated_at=changed_at)
        updated = update_query.update(online_counter_current=next_value, online_counter_updated_at=now)
        if updated:
            current = next_value
        else:
            latest = PlatformSettings.objects.filter(pk=settings.pk).first()
            if latest is None or not latest.online_counter_enabled:
                response = JsonResponse({"enabled": False})
                response["Cache-Control"] = "no-store"
                return response
            current = max(latest.online_counter_min, min(latest.online_counter_max, latest.online_counter_current))

    response = JsonResponse({"enabled": True, "count": current})
    response["Cache-Control"] = "no-store"
    return response
