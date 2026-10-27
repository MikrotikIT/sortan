from functools import wraps
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db import transaction
from django.db.models import Count, DateTimeField, F, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .management_forms import FilmForm, InternalBalanceCreditForm, ManualDepositForm, PlatformSettingsForm, VoucherAmountForm, VoucherIssueForm
from .models import Deposit, Film, InternalBalanceCredit, Investment, InvestmentVoucher, User, Wallet, WithdrawalRequest
from .services import approve_deposit, get_platform_settings, pay_withdrawal, reject_deposit, reject_withdrawal
from .wallet_services import decrypt_private_key, ensure_wallet, sync_all_wallets


def staff_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


@staff_required
def dashboard(request):
    return render(
        request,
        "management/dashboard.html",
        {
            "user_count": User.objects.filter(is_staff=False).count(),
            "film_count": Film.objects.count(),
            "active_investment_count": Investment.objects.filter(status=Investment.Status.ACTIVE).count(),
            "pending_deposit_count": Deposit.objects.filter(status=Deposit.Status.PENDING).count(),
            "pending_withdrawal_count": WithdrawalRequest.objects.filter(status=WithdrawalRequest.Status.PENDING).count(),
            "wallet_count": Wallet.objects.count(),
            "wallet_total": Wallet.objects.aggregate(total=Sum("usdt_balance"))["total"] or 0,
            "recent_investments": Investment.objects.select_related("user", "film").order_by("-invested_at")[:6],
            "recent_withdrawals": WithdrawalRequest.objects.select_related("user").order_by("-requested_at")[:5],
        },
    )


@staff_required
def films(request):
    items = Film.objects.annotate(investment_count=Count("investments")).order_by("-created_at")
    return render(request, "management/films.html", {"films": items})


@staff_required
def film_create(request):
    form = FilmForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        film = form.save()
        messages.success(request, f"تمت إضافة فيلم «{film.title}».")
        return redirect("management_films")
    return render(request, "management/film_form.html", {"form": form, "heading": "إضافة فيلم جديد"})


@staff_required
def film_edit(request, pk):
    film = get_object_or_404(Film, pk=pk)
    form = FilmForm(request.POST or None, instance=film)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم حفظ تعديلات الفيلم.")
        return redirect("management_films")
    return render(request, "management/film_form.html", {"form": form, "heading": "تعديل الفيلم", "film": film})


@staff_required
def film_toggle(request, pk):
    if request.method != "POST":
        return redirect("management_films")
    film = get_object_or_404(Film, pk=pk)
    film.active = not film.active
    film.save(update_fields=("active",))
    messages.success(request, "تم تحديث إتاحة الفيلم للاستثمار.")
    return redirect("management_films")


@staff_required
def platform_settings(request):
    settings = get_platform_settings()
    form = PlatformSettingsForm(request.POST or None, instance=settings)
    setting_sections = [
        ("الدعم الفني", [form["support_url"]]),
        ("قسائم التسجيل", [form["default_voucher_count"], form["default_voucher_amount"]]),
        ("فترة السحب والضريبة", [
            form["withdrawal_cooldown_enabled"], form["withdrawal_interval_days"],
            form["withdrawal_tax_enabled"], form["withdrawal_tax_percent"],
        ]),
        ("شرط الدعوات بعد السحب", [
            form["withdrawal_referral_gate_enabled"],
        ]),
        ("عمولات الدعوة", [form["referral_deposit_percent"], form["referral_profit_percent"]]),
        ("عداد المتصلين التجريبي", [
            form["online_counter_enabled"], form["online_counter_min"], form["online_counter_max"],
            form["online_counter_step_min"], form["online_counter_step_max"],
        ]),
        ("إشعار النشاط التجريبي للإيداع", [
            form["deposit_activity_enabled"],
            form["deposit_activity_examples"],
            form["deposit_activity_interval_seconds"],
        ]),
    ]
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم حفظ إعدادات المنصة.")
        return redirect("management_settings")
    return render(request, "management/settings.html", {"form": form, "setting_sections": setting_sections})


@staff_required
def vouchers(request):
    settings = get_platform_settings()
    form = VoucherIssueForm(
        request.POST or None,
        initial={"count": settings.default_voucher_count, "amount": settings.default_voucher_amount},
    )
    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data["target_user"]
        count = form.cleaned_data["count"]
        amount = form.cleaned_data["amount"]
        with transaction.atomic():
            InvestmentVoucher.objects.bulk_create(
                [InvestmentVoucher(user=user, amount=amount) for _ in range(count)]
            )
        messages.success(request, f"تم إصدار {count} قسيمة للمستخدم {user.phone}.")
        return redirect("management_vouchers")
    return render(
        request,
        "management/vouchers.html",
        {
            "form": form,
            "vouchers": InvestmentVoucher.objects.select_related("user").order_by("-created_at")[:100],
            "available_count": InvestmentVoucher.objects.filter(status=InvestmentVoucher.Status.AVAILABLE).count(),
            "used_count": InvestmentVoucher.objects.filter(status=InvestmentVoucher.Status.USED).count(),
        },
    )


@staff_required
def voucher_edit(request, pk):
    voucher = get_object_or_404(InvestmentVoucher, pk=pk)
    if voucher.status != InvestmentVoucher.Status.AVAILABLE:
        messages.error(request, "يمكن تعديل قيمة القسائم المتاحة فقط.")
        return redirect("management_vouchers")
    form = VoucherAmountForm(request.POST or None, instance=voucher)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم تعديل قيمة القسيمة.")
        return redirect("management_vouchers")
    return render(request, "management/voucher_form.html", {"form": form, "voucher": voucher})


@staff_required
def voucher_revoke(request, pk):
    if request.method != "POST":
        return redirect("management_vouchers")
    voucher = get_object_or_404(InvestmentVoucher, pk=pk)
    if voucher.status == InvestmentVoucher.Status.AVAILABLE:
        voucher.status = InvestmentVoucher.Status.REVOKED
        voucher.save(update_fields=("status",))
        messages.success(request, "تم إلغاء القسيمة.")
    else:
        messages.error(request, "يمكن إلغاء القسائم المتاحة فقط.")
    return redirect("management_vouchers")


@staff_required
def deposits(request):
    form = ManualDepositForm(request.POST or None)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            if form.is_valid():
                deposit = Deposit.objects.create(
                    user=form.cleaned_data["target_user"],
                    amount=form.cleaned_data["amount"],
                    reference=form.cleaned_data["reference"],
                )
                messages.success(request, f"تم تسجيل الإيداع #{deposit.pk} بانتظار المراجعة.")
                return redirect("management_deposits")
        elif action in {"approve", "reject"}:
            deposit_id = request.POST.get("deposit_id")
            deposit = get_object_or_404(Deposit, pk=deposit_id)
            changed = approve_deposit(deposit.pk) if action == "approve" else reject_deposit(deposit.pk)
            if changed:
                messages.success(request, "تم تحديث حالة الإيداع.")
            else:
                messages.info(request, "تمت معالجة هذا الإيداع سابقاً.")
            return redirect("management_deposits")
    return render(
        request,
        "management/deposits.html",
        {"form": form, "deposits": Deposit.objects.select_related("user").order_by("-created_at")[:100]},
    )


@staff_required
def internal_credits(request):
    form = InternalBalanceCreditForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data["target_user"]
        amount = form.cleaned_data["amount"]
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            user.balance = F("balance") + amount
            user.save(update_fields=("balance",))
            InternalBalanceCredit.objects.create(
                user=user,
                admin=request.user,
                amount=amount,
                internal_note=form.cleaned_data["internal_note"],
            )
        messages.success(request, f"تمت إضافة {amount} USDT إلى رصيد العميل {user.phone}.")
        return redirect("management_internal_credits")

    credits = InternalBalanceCredit.objects.select_related("user", "admin")[:150]
    return render(
        request,
        "management/internal_credits.html",
        {"form": form, "credits": credits},
    )


@staff_required
def withdrawals(request):
    if request.method == "POST":
        action = request.POST.get("action")
        withdrawal = get_object_or_404(WithdrawalRequest, pk=request.POST.get("withdrawal_id"))
        if action == "paid":
            changed = pay_withdrawal(withdrawal.pk)
        elif action == "reject":
            changed = reject_withdrawal(withdrawal.pk, "تم الرفض من صفحة الإدارة")
        else:
            changed = False
        if changed:
            messages.success(request, "تم تحديث حالة طلب السحب.")
        else:
            messages.info(request, "تمت معالجة طلب السحب سابقاً أو لم يعد قيد المراجعة.")
        return redirect("management_withdrawals")
    return render(
        request,
        "management/withdrawals.html",
        {"withdrawals": WithdrawalRequest.objects.select_related("user").order_by("-requested_at")[:150]},
    )


@staff_required
def customers(request):
    query = request.GET.get("q", "").strip()
    items = User.objects.filter(is_staff=False).select_related("referred_by").annotate(
        investment_count=Count("investments", distinct=True),
        deposit_count=Count("deposits", filter=Q(deposits__status=Deposit.Status.APPROVED), distinct=True),
        referral_count=Count("referrals", distinct=True),
        available_voucher_count=Count(
            "vouchers", filter=Q(vouchers__status=InvestmentVoucher.Status.AVAILABLE), distinct=True
        ),
    ).order_by("-date_joined")
    if query:
        items = items.filter(Q(phone__icontains=query) | Q(referral_code__icontains=query))
    return render(request, "management/customers.html", {"customers": items[:200], "query": query})


@staff_required
def customer_detail(request, pk):
    customer = get_object_or_404(User.objects.select_related("referred_by"), pk=pk, is_staff=False)
    wallet, _ = ensure_wallet(customer)
    return render(
        request,
        "management/customer_detail.html",
        {
            "customer": customer,
            "wallet": wallet,
            "investments": customer.investments.all()[:50],
            "deposits": customer.deposits.all()[:50],
            "withdrawals": customer.withdrawals.all()[:50],
            "vouchers": customer.vouchers.all()[:50],
            "referrals": customer.referrals.order_by("-date_joined")[:50],
            "commissions": customer.referral_commissions.all()[:50],
            "paid_withdrawal_count": customer.withdrawals.filter(status=WithdrawalRequest.Status.PAID).count(),
        },
    )


@staff_required
def wallets(request):
    queryset = Wallet.objects.select_related("user").order_by("-created_at")
    return render(
        request,
        "management/wallets.html",
        {
            "wallets": queryset[:250],
            "wallet_count": queryset.count(),
            "total_usdt": queryset.aggregate(total=Sum("usdt_balance"))["total"] or 0,
            "has_trongrid_key": bool(settings.TRONGRID_API_KEY),
            "sync_interval_seconds": settings.TRON_DEPOSIT_SYNC_INTERVAL_SECONDS,
        },
    )


@staff_required
@require_POST
def sync_wallet_balances(request):
    try:
        result = sync_all_wallets()
    except ImproperlyConfigured as exc:
        messages.error(request, str(exc))
        return redirect("management_wallets")
    if result["errors"]:
        messages.warning(
            request,
            f"تم تحديث {result['updated']} محفظة وإضافة {result['imported']} إيداع. تعذر تحديث {len(result['errors'])} محفظة؛ راجع إعداد TronGrid.",
        )
    else:
        messages.success(request, f"اكتملت المزامنة: تم تحديث {result['updated']} محفظة وإضافة {result['imported']} إيداع مؤكد.")
    return redirect("management_wallets")


@staff_required
@require_POST
def reveal_wallet_key(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    wallet = get_object_or_404(Wallet, pk=pk)
    response = JsonResponse({"private_key": decrypt_private_key(wallet.encrypted_private_key)})
    response["Cache-Control"] = "no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@staff_required
def finance(request):
    try:
        period_days = int(request.GET.get("days", "30"))
    except (TypeError, ValueError):
        period_days = 30
    if period_days not in (30, 60, 90):
        period_days = 30
    today = timezone.localdate()
    start_date = today - timedelta(days=period_days - 1)
    approved = Deposit.objects.filter(status=Deposit.Status.APPROVED).filter(
        Q(occurred_at__date__gte=start_date) | Q(occurred_at__isnull=True, created_at__date__gte=start_date)
    )
    date_expr = TruncDate(
        Coalesce("occurred_at", "created_at", output_field=DateTimeField()),
        tzinfo=timezone.get_current_timezone(),
    )
    totals_by_day = {
        row["day"]: row["total"]
        for row in approved.annotate(day=date_expr).values("day").annotate(total=Sum("amount"))
    }
    daily_deposits = []
    for offset in range(period_days):
        day = start_date + timedelta(days=offset)
        daily_deposits.append({"day": day, "total": totals_by_day.get(day, 0)})
    maximum = max((float(item["total"]) for item in daily_deposits), default=0)
    for item in daily_deposits:
        item["width"] = min(100, max(4, (float(item["total"]) / maximum * 100))) if maximum else 4
    today_deposits = Deposit.objects.filter(status=Deposit.Status.APPROVED).filter(
        Q(occurred_at__date=today) | Q(occurred_at__isnull=True, created_at__date=today)
    ).aggregate(total=Sum("amount"))["total"] or 0
    period_total = sum((item["total"] for item in daily_deposits), 0)
    return render(
        request,
        "management/finance.html",
        {
            "period_days": period_days,
            "daily_deposits": daily_deposits,
            "today_deposits": today_deposits,
            "period_total": period_total,
            "period_count": approved.count(),
            "recent_deposits": Deposit.objects.filter(status=Deposit.Status.APPROVED)
            .select_related("user", "wallet").order_by("-occurred_at", "-created_at")[:30],
        },
    )
