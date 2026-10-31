import csv
from functools import wraps
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, DateTimeField, F, Max, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .management_forms import CustomerBlockForm, CustomerInfoForm, CustomerPasswordForm, FilmForm, InternalBalanceCreditForm, JoinApplicationDecisionForm, ManualDepositForm, NotificationForm, PlatformSettingsForm, SupportOptionForm, VoucherAmountForm, VoucherIssueForm
from .models import Deposit, Film, InternalBalanceCredit, Investment, InvestmentVoucher, JoinApplication, ServiceHeartbeat, SupportOption, User, UserNotification, Wallet, WalletSyncRun, WithdrawalRequest
from .services import approve_deposit, deposit_status_for_amount, get_platform_settings, pay_withdrawal, reject_deposit, reject_withdrawal
from .wallet_services import decrypt_private_key, ensure_wallet, sync_all_wallets
from config.celery import app as celery_app


def staff_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


def _date_filters(request, start_key="date_from", end_key="date_to"):
    try:
        date_from = parse_date(request.GET.get(start_key, "")) if request.GET.get(start_key) else None
    except ValueError:
        date_from = None
    try:
        date_to = parse_date(request.GET.get(end_key, "")) if request.GET.get(end_key) else None
    except ValueError:
        date_to = None
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    return date_from, date_to


def _apply_date_range(queryset, field_name, date_from, date_to):
    if date_from:
        queryset = queryset.filter(**{f"{field_name}__date__gte": date_from})
    if date_to:
        queryset = queryset.filter(**{f"{field_name}__date__lte": date_to})
    return queryset


def _apply_deposit_date_range(queryset, date_from, date_to):
    if date_from:
        queryset = queryset.filter(
            Q(occurred_at__date__gte=date_from)
            | Q(occurred_at__isnull=True, created_at__date__gte=date_from)
        )
    if date_to:
        queryset = queryset.filter(
            Q(occurred_at__date__lte=date_to)
            | Q(occurred_at__isnull=True, created_at__date__lte=date_to)
        )
    return queryset


def _paginate(request, queryset, per_page=50):
    page_obj = Paginator(queryset, per_page).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page_obj, params.urlencode()


@staff_required
def dashboard(request):
    return render(
        request,
        "management/dashboard.html",
        {
            "user_count": User.objects.filter(is_staff=False).count(),
            "film_count": Film.objects.count(),
            "active_investment_count": Investment.objects.filter(status=Investment.Status.ACTIVE).count(),
            "pending_deposit_count": Deposit.objects.filter(
                status__in=(Deposit.Status.PENDING, Deposit.Status.UNEXPECTED)
            ).count(),
            "pending_withdrawal_count": WithdrawalRequest.objects.filter(status=WithdrawalRequest.Status.PENDING).count(),
            "wallet_count": Wallet.objects.count(),
            "wallet_total": Wallet.objects.aggregate(total=Sum("usdt_balance"))["total"] or 0,
            "recent_investments": Investment.objects.select_related("user", "film").order_by("-invested_at")[:6],
            "recent_withdrawals": WithdrawalRequest.objects.select_related("user").order_by("-requested_at")[:5],
        },
    )


@staff_required
def join_applications(request):
    status = request.GET.get("status", "pending")
    query = request.GET.get("q", "").strip()[:100]
    applications = JoinApplication.objects.select_related("user", "reviewed_by").order_by("-updated_at", "-pk")
    if status in {"pending", "approved", "rejected", "blocked"}:
        applications = applications.filter(user__approval_status=status)
    elif status != "all":
        status = "pending"
        applications = applications.filter(user__approval_status=status)
    if query:
        applications = applications.filter(Q(full_name__icontains=query) | Q(user__phone__icontains=query))
    page_obj, query_string = _paginate(request, applications)
    return render(
        request,
        "management/join_applications.html",
        {
            "applications": page_obj,
            "status_filter": status,
            "query": query,
            "query_string": query_string,
            "pending_count": JoinApplication.objects.filter(user__approval_status="pending", user__is_staff=False).count(),
        },
    )


@staff_required
def join_application_detail(request, pk):
    application = get_object_or_404(
        JoinApplication.objects.select_related("user", "reviewed_by"),
        pk=pk,
    )
    form = JoinApplicationDecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        decision = form.cleaned_data["decision"]
        reason = form.cleaned_data["rejection_reason"].strip()
        with transaction.atomic():
            application = get_object_or_404(
                JoinApplication.objects.select_for_update().select_related("user"),
                pk=pk,
            )
            user = User.objects.select_for_update().get(pk=application.user_id)
            if user.approval_status != "pending":
                messages.warning(request, "تمت مراجعة هذا الطلب مسبقاً.")
            else:
                previous_status = user.approval_status
                user.approval_status = decision
                if decision == "blocked":
                    user.is_active = False
                    user.blocked_from_status = previous_status
                    user.block_reason = reason
                    user.save(update_fields=("approval_status", "is_active", "blocked_from_status", "block_reason"))
                else:
                    user.save(update_fields=("approval_status",))
                application.reviewed_by = request.user
                application.reviewed_at = timezone.now()
                application.rejection_reason = reason if decision in {"rejected", "blocked"} else ""
                application.save(update_fields=("reviewed_by", "reviewed_at", "rejection_reason", "updated_at"))

                if decision == "approved":
                    title = "تم قبول طلب انضمامك"
                    body = (
                        "<p>نبارك لك، تمت الموافقة على طلب انضمامك إلى منصة KODI العالمية.</p>"
                        "<p>أصبح بإمكانك الآن تسجيل الدخول واستخدام المنصة.</p>"
                    )
                elif decision == "rejected":
                    title = "تم رفض طلب انضمامك"
                    body = (
                        "<p>نأسف لإبلاغك بأنه تم رفض طلب الانضمام.</p>"
                        f"<p><strong>سبب الرفض:</strong> {escape(reason)}</p>"
                        f'<p><a href="{reverse("join_application")}">افتح وثيقة طلب الانضمام وعدّل بياناتك ثم أعد الإرسال.</a></p>'
                    )
                if decision != "blocked":
                    UserNotification.objects.create(recipient=user, sender=request.user, title=title, body_html=body)
                messages.success(
                    request,
                    {
                        "approved": "تمت الموافقة على الطلب وإشعار العميل.",
                        "rejected": "تم رفض الطلب وإرسال السبب إلى العميل.",
                        "blocked": "تم حظر الحساب وتعطيل تسجيل الدخول، وحُفظ السبب في سجل الطلب.",
                    }[decision],
                )
        return redirect("management_join_applications")

    return render(
        request,
        "management/join_application_detail.html",
        {"application": application, "form": form},
    )


@staff_required
def send_notifications(request):
    form = NotificationForm(request.POST or None)
    recipients = User.objects.filter(is_active=True, is_staff=False)
    recipient_count = recipients.count()
    if request.method == "POST" and form.is_valid():
        notifications = [
            UserNotification(
                recipient=recipient,
                sender=request.user,
                title=form.cleaned_data["title"],
                body_html=form.cleaned_data["body_html"],
            )
            for recipient in recipients.iterator(chunk_size=500)
        ]
        with transaction.atomic():
            UserNotification.objects.bulk_create(notifications, batch_size=500)
        messages.success(request, f"تم إرسال الإشعار إلى {len(notifications)} عميل.")
        return redirect("management_send_notifications")
    return render(
        request,
        "management/send_notifications.html",
        {"form": form, "recipient_count": recipient_count},
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
        ("حد الإيداع", [form["minimum_deposit_amount"]]),
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
def support_options(request):
    form = SupportOptionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تمت إضافة خيار الدعم الفني.")
        return redirect("management_support_options")
    return render(
        request,
        "management/support_options.html",
        {"form": form, "options": SupportOption.objects.order_by("sort_order", "pk")},
    )


@staff_required
def support_option_edit(request, pk):
    option = get_object_or_404(SupportOption, pk=pk)
    form = SupportOptionForm(request.POST or None, request.FILES or None, instance=option)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم حفظ خيار الدعم الفني.")
        return redirect("management_support_options")
    return render(
        request,
        "management/support_option_form.html",
        {"form": form, "option": option, "heading": "تعديل خيار الدعم"},
    )


@staff_required
@require_POST
def support_option_delete(request, pk):
    option = get_object_or_404(SupportOption, pk=pk)
    option.delete()
    messages.success(request, "تم حذف خيار الدعم الفني.")
    return redirect("management_support_options")


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
    voucher_items = InvestmentVoucher.objects.select_related("user").order_by("-created_at", "-pk")
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if query:
        voucher_items = voucher_items.filter(user__phone__icontains=query)
    if status in InvestmentVoucher.Status.values:
        voucher_items = voucher_items.filter(status=status)
    date_from, date_to = _date_filters(request)
    voucher_items = _apply_date_range(voucher_items, "created_at", date_from, date_to)
    page_obj, pagination_query = _paginate(request, voucher_items)
    return render(
        request,
        "management/vouchers.html",
        {
            "form": form,
            "vouchers": page_obj,
            "page_obj": page_obj,
            "pagination_query": pagination_query,
            "filter_q": query,
            "filter_status": status,
            "date_from": date_from,
            "date_to": date_to,
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
                    status=deposit_status_for_amount(form.cleaned_data["amount"]),
                )
                if deposit.status == Deposit.Status.UNEXPECTED:
                    messages.warning(
                        request,
                        f"تم تسجيل الإيداع #{deposit.pk} كرصيد غير متوقع لأنه أقل من الحد الأدنى، ولم يضف إلى رصيد العميل.",
                    )
                else:
                    messages.success(request, f"تم تسجيل الإيداع #{deposit.pk} بانتظار المراجعة.")
                return redirect("management_deposits")
        elif action in {"approve", "approve_unexpected", "reject"}:
            deposit_id = request.POST.get("deposit_id")
            deposit = get_object_or_404(Deposit, pk=deposit_id)
            if action in {"approve", "approve_unexpected"}:
                changed = approve_deposit(deposit.pk, allow_unexpected=action == "approve_unexpected")
            else:
                changed = reject_deposit(deposit.pk)
            if changed:
                messages.success(request, "تم تحديث حالة الإيداع.")
            elif action == "approve" and (
                deposit.status == Deposit.Status.UNEXPECTED
                or deposit.amount < get_platform_settings().minimum_deposit_amount
            ):
                messages.warning(request, "المبلغ أقل من حد الإيداع الحالي. راجعه واستخدم الاعتماد الاستثنائي إذا رغبت بإضافته إلى رصيد العميل.")
            else:
                messages.info(request, "تمت معالجة هذا الإيداع سابقاً.")
            return redirect("management_deposits")
    deposit_items = Deposit.objects.select_related("user").order_by("-created_at", "-pk")
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    source = request.GET.get("source", "")
    if query:
        deposit_items = deposit_items.filter(
            Q(user__phone__icontains=query)
            | Q(reference__icontains=query)
            | Q(transaction_id__icontains=query)
        )
    if status in Deposit.Status.values:
        deposit_items = deposit_items.filter(status=status)
    if source in Deposit.Source.values:
        deposit_items = deposit_items.filter(source=source)
    date_from, date_to = _date_filters(request)
    deposit_items = _apply_deposit_date_range(deposit_items, date_from, date_to)
    page_obj, pagination_query = _paginate(request, deposit_items)
    return render(
        request,
        "management/deposits.html",
        {
            "form": form,
            "deposits": page_obj,
            "page_obj": page_obj,
            "pagination_query": pagination_query,
            "filter_q": query,
            "filter_status": status,
            "filter_source": source,
            "date_from": date_from,
            "date_to": date_to,
            "deposit_status_choices": Deposit.Status.choices,
            "minimum_deposit_amount": get_platform_settings().minimum_deposit_amount,
        },
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

    credits = InternalBalanceCredit.objects.select_related("user", "admin").order_by("-created_at", "-pk")
    query = request.GET.get("q", "").strip()
    if query:
        credits = credits.filter(
            Q(user__phone__icontains=query)
            | Q(admin__phone__icontains=query)
            | Q(internal_note__icontains=query)
        )
    date_from, date_to = _date_filters(request)
    credits = _apply_date_range(credits, "created_at", date_from, date_to)
    page_obj, pagination_query = _paginate(request, credits)
    return render(
        request,
        "management/internal_credits.html",
        {
            "form": form,
            "credits": page_obj,
            "page_obj": page_obj,
            "pagination_query": pagination_query,
            "filter_q": query,
            "date_from": date_from,
            "date_to": date_to,
        },
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
    withdrawal_items = WithdrawalRequest.objects.select_related("user").order_by("-requested_at", "-pk")
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if query:
        search_filter = Q(user__phone__icontains=query) | Q(wallet_address__icontains=query)
        if query.isdecimal():
            internal_id = int(query) - WithdrawalRequest.DISPLAY_NUMBER_OFFSET
            if internal_id > 0:
                search_filter |= Q(pk=internal_id)
        withdrawal_items = withdrawal_items.filter(search_filter)
    if status in WithdrawalRequest.Status.values:
        withdrawal_items = withdrawal_items.filter(status=status)
    date_from, date_to = _date_filters(request)
    withdrawal_items = _apply_date_range(withdrawal_items, "requested_at", date_from, date_to)
    page_obj, pagination_query = _paginate(request, withdrawal_items)
    return render(
        request,
        "management/withdrawals.html",
        {
            "withdrawals": page_obj,
            "page_obj": page_obj,
            "pagination_query": pagination_query,
            "filter_q": query,
            "filter_status": status,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@staff_required
def customers(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    account_type = request.GET.get("type", "all")
    if account_type not in {"all", "customers", "staff"}:
        account_type = "all"
    items = User.objects.all().select_related("referred_by").annotate(
        investment_count=Count("investments", distinct=True),
        deposit_count=Count("deposits", filter=Q(deposits__status=Deposit.Status.APPROVED), distinct=True),
        referral_count=Count("referrals", distinct=True),
        available_voucher_count=Count(
            "vouchers", filter=Q(vouchers__status=InvestmentVoucher.Status.AVAILABLE), distinct=True
        ),
    ).order_by("-date_joined")
    if account_type == "customers":
        items = items.filter(is_staff=False)
    elif account_type == "staff":
        items = items.filter(is_staff=True)
    if query:
        items = items.filter(Q(phone__icontains=query) | Q(referral_code__icontains=query))
    if status == "active":
        items = items.filter(is_active=True).filter(Q(is_staff=True) | Q(approval_status="approved"))
    elif status == "inactive":
        items = items.filter(is_active=False)
    elif status == "blocked":
        items = items.filter(is_staff=False, approval_status="blocked")
    date_from, date_to = _date_filters(request)
    items = _apply_date_range(items, "date_joined", date_from, date_to)
    page_obj, pagination_query = _paginate(request, items)
    return render(
        request,
        "management/customers.html",
        {
            "customers": page_obj,
            "page_obj": page_obj,
            "pagination_query": pagination_query,
            "query": query,
            "filter_type": account_type,
            "filter_status": status,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@staff_required
@require_POST
def block_customer(request, pk):
    form = CustomerBlockForm(request.POST)
    if not form.is_valid():
        messages.error(request, "اكتب سبب الحظر ثم أعد المحاولة.")
        return redirect("management_customers")

    with transaction.atomic():
        customer = get_object_or_404(User.objects.select_for_update(), pk=pk, is_staff=False)
        if not customer.is_active or customer.approval_status != "approved":
            messages.info(request, "يمكن حظر العملاء النشطين المقبولين فقط.")
        else:
            customer.blocked_from_status = customer.approval_status
            customer.approval_status = "blocked"
            customer.block_reason = form.cleaned_data["reason"]
            customer.is_active = False
            customer.save(update_fields=("approval_status", "blocked_from_status", "block_reason", "is_active"))
            messages.success(request, f"تم حظر حساب العميل {customer.phone} وتعطيل تسجيل دخوله.")
    return redirect("management_customers")


@staff_required
@require_POST
def unblock_customer(request, pk):
    with transaction.atomic():
        customer = get_object_or_404(User.objects.select_for_update(), pk=pk, is_staff=False)
        if customer.approval_status != "blocked":
            messages.info(request, "هذا الحساب غير محظور.")
        else:
            previous_status = customer.blocked_from_status
            if previous_status not in {"approved", "pending", "rejected"}:
                previous_status = "approved"
            customer.approval_status = previous_status
            customer.blocked_from_status = ""
            customer.is_active = True
            customer.save(update_fields=("approval_status", "blocked_from_status", "is_active"))

            if previous_status == "approved":
                title = "تم رفع الحظر عن حسابك"
                body = "<p>تم رفع الحظر عن حسابك، ويمكنك الآن تسجيل الدخول واستخدام المنصة.</p>"
            else:
                title = "تم رفع الحظر عن حسابك"
                body = f"<p>تم رفع الحظر عن حسابك. حالة طلب الانضمام الحالية: {customer.get_approval_status_display()}.</p>"
            UserNotification.objects.create(
                recipient=customer,
                sender=request.user,
                title=title,
                body_html=body,
            )
            messages.success(request, f"تم رفع الحظر عن العميل {customer.phone} وإعادة حالة حسابه السابقة.")
    return redirect("management_customers")


@staff_required
def customer_detail(request, pk):
    customer = get_object_or_404(User.objects.select_related("referred_by"), pk=pk, is_staff=False)
    customer_application = JoinApplication.objects.filter(user=customer).first()
    profile_initial = {
        "full_name": customer_application.full_name if customer_application else customer.get_full_name(),
        "father_name": customer_application.father_name if customer_application else "",
        "mother_name": customer_application.mother_name if customer_application else "",
        "gender": customer_application.gender if customer_application else "",
        "marital_status": customer_application.marital_status if customer_application else "",
        "financial_status": customer_application.financial_status if customer_application else "",
    }
    profile_form = CustomerInfoForm(initial=profile_initial)
    password_form = CustomerPasswordForm()
    notification_form = NotificationForm()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "profile":
            profile_form = CustomerInfoForm(request.POST)
            if profile_form.is_valid():
                with transaction.atomic():
                    customer = get_object_or_404(User.objects.select_for_update(), pk=pk, is_staff=False)
                    customer_application = JoinApplication.objects.select_for_update().filter(user=customer).first()
                    if customer_application is None:
                        customer_application = JoinApplication(user=customer, profile_image="")
                    for field in (
                        "full_name", "father_name", "mother_name", "gender", "marital_status", "financial_status"
                    ):
                        setattr(customer_application, field, profile_form.cleaned_data[field])
                    customer_application.save()
                    name_parts = profile_form.cleaned_data["full_name"].split(maxsplit=1)
                    customer.first_name = name_parts[0]
                    customer.last_name = name_parts[1] if len(name_parts) > 1 else ""
                    customer.save(update_fields=("first_name", "last_name"))
                messages.success(request, f"تم تحديث معلومات العميل {customer.phone}.")
                return redirect("management_customer_detail", pk=customer.pk)
        elif action == "password":
            password_form = CustomerPasswordForm(request.POST)
            if password_form.is_valid():
                customer.set_password(password_form.cleaned_data["password1"])
                customer.save(update_fields=("password",))
                messages.success(request, f"تم تغيير كلمة مرور العميل {customer.phone}.")
                return redirect("management_customer_detail", pk=customer.pk)
        elif action == "notification":
            notification_form = NotificationForm(request.POST)
            if notification_form.is_valid():
                UserNotification.objects.create(
                    recipient=customer,
                    sender=request.user,
                    title=notification_form.cleaned_data["title"],
                    body_html=notification_form.cleaned_data["body_html"],
                )
                messages.success(request, f"تم إرسال إشعار إلى العميل {customer.phone}.")
                return redirect("management_customer_detail", pk=customer.pk)
    wallet, _ = ensure_wallet(customer)
    return render(
        request,
        "management/customer_detail.html",
        {
            "customer": customer,
            "customer_application": customer_application,
            "profile_form": profile_form,
            "password_form": password_form,
            "referral_link": request.build_absolute_uri(
                f"{reverse('register')}?{urlencode({'ref': customer.referral_code})}"
            ),
            "wallet": wallet,
            "investments": customer.investments.all()[:50],
            "deposits": customer.deposits.all()[:50],
            "withdrawals": customer.withdrawals.all()[:50],
            "vouchers": customer.vouchers.all()[:50],
            "referrals": customer.referrals.order_by("-date_joined")[:50],
            "commissions": customer.referral_commissions.all()[:50],
            "paid_withdrawal_count": customer.withdrawals.filter(status=WithdrawalRequest.Status.PAID).count(),
            "notification_form": notification_form,
            "notifications": customer.notifications.order_by("-created_at", "-pk")[:10],
        },
    )


@staff_required
def investments(request):
    queryset = Investment.objects.select_related("user", "film").order_by("-invested_at", "-pk")
    query = request.GET.get("q", "").strip()
    customer_query = request.GET.get("customer", "").strip()
    film_id = request.GET.get("film", "").strip()
    status = request.GET.get("status", "")
    funding_source = request.GET.get("funding", "")
    if query:
        queryset = queryset.filter(
            Q(user__phone__icontains=query)
            | Q(film_title__icontains=query)
            | Q(film_url__icontains=query)
        )
    if customer_query:
        queryset = queryset.filter(user__phone__icontains=customer_query)
    if film_id.isdigit():
        queryset = queryset.filter(film_id=int(film_id))
    if status in Investment.Status.values:
        queryset = queryset.filter(status=status)
    if funding_source in Investment.FundingSource.values:
        queryset = queryset.filter(funding_source=funding_source)
    invested_from, invested_to = _date_filters(request, "invested_from", "invested_to")
    queryset = _apply_date_range(queryset, "invested_at", invested_from, invested_to)
    matures_from, matures_to = _date_filters(request, "matures_from", "matures_to")
    queryset = _apply_date_range(queryset, "matures_at", matures_from, matures_to)
    page_obj, pagination_query = _paginate(request, queryset)
    return render(
        request,
        "management/investments.html",
        {
            "investments": page_obj,
            "page_obj": page_obj,
            "pagination_query": pagination_query,
            "filter_q": query,
            "filter_customer": customer_query,
            "filter_film": film_id,
            "films": Film.objects.order_by("title"),
            "filter_status": status,
            "filter_funding": funding_source,
            "invested_from": invested_from,
            "invested_to": invested_to,
            "matures_from": matures_from,
            "matures_to": matures_to,
        },
    )


@staff_required
def wallets(request):
    queryset = Wallet.objects.select_related("user").order_by("-created_at")
    query = request.GET.get("q", "").strip()
    sync_status = request.GET.get("sync", "")
    if query:
        queryset = queryset.filter(Q(user__phone__icontains=query) | Q(address__icontains=query))
    if sync_status == "never":
        queryset = queryset.filter(balance_checked_at__isnull=True)
    elif sync_status == "stale":
        stale_before = timezone.now() - timedelta(
            seconds=max(settings.TRON_DEPOSIT_SYNC_INTERVAL_SECONDS * 2, 600)
        )
        queryset = queryset.filter(balance_checked_at__lt=stale_before)
    elif sync_status == "positive":
        queryset = queryset.filter(usdt_balance__gt=0)
    date_from, date_to = _date_filters(request)
    queryset = _apply_date_range(queryset, "balance_checked_at", date_from, date_to)
    page_obj, pagination_query = _paginate(request, queryset)
    return render(
        request,
        "management/wallets.html",
        {
            "wallets": page_obj,
            "page_obj": page_obj,
            "pagination_query": pagination_query,
            "filter_q": query,
            "filter_sync": sync_status,
            "date_from": date_from,
            "date_to": date_to,
            "wallet_count": queryset.count(),
            "total_usdt": queryset.aggregate(total=Sum("usdt_balance"))["total"] or 0,
            "has_trongrid_key": bool(settings.TRONGRID_API_KEY),
            "sync_interval_seconds": settings.TRON_DEPOSIT_SYNC_INTERVAL_SECONDS,
        },
    )


@staff_required
def wallet_detail(request, pk):
    wallet = get_object_or_404(Wallet.objects.select_related("user"), pk=pk)
    deposit_queryset = wallet.deposits.order_by("-occurred_at", "-created_at", "-pk")
    page_obj = Paginator(deposit_queryset, 50).get_page(request.GET.get("page"))
    deposit_totals = wallet.deposits.aggregate(
        all_amount=Sum("amount"),
        approved_amount=Sum("amount", filter=Q(status=Deposit.Status.APPROVED)),
        pending_amount=Sum("amount", filter=Q(status=Deposit.Status.PENDING)),
        unexpected_amount=Sum("amount", filter=Q(status=Deposit.Status.UNEXPECTED)),
        deposit_count=Count("pk"),
    )
    return render(
        request,
        "management/wallet_detail.html",
        {
            "wallet": wallet,
            "deposits": page_obj,
            "deposit_totals": deposit_totals,
        },
    )


@staff_required
def system_health(request):
    now = timezone.now()
    latest_sync = WalletSyncRun.objects.order_by("-started_at", "-pk").first()
    last_successful_sync = WalletSyncRun.objects.filter(status=WalletSyncRun.Status.SUCCEEDED).order_by("-completed_at", "-pk").first()
    sync_runs = WalletSyncRun.objects.select_related("requested_by").order_by("-started_at", "-pk")[:30]
    heartbeat = ServiceHeartbeat.objects.filter(component="beat-worker-pipeline").first()
    heartbeat_is_recent = bool(
        heartbeat and heartbeat.last_seen_at >= now - timedelta(minutes=3)
    )
    try:
        worker_replies = celery_app.control.inspect(timeout=1).ping() or {}
        worker_names = sorted(worker_replies.keys())
        worker_probe_error = False
    except Exception:
        worker_names = []
        worker_probe_error = True
    return render(
        request,
        "management/system_health.html",
        {
            "latest_sync": latest_sync,
            "last_successful_sync": last_successful_sync,
            "sync_runs": sync_runs,
            "heartbeat": heartbeat,
            "heartbeat_is_recent": heartbeat_is_recent,
            "worker_names": worker_names,
            "worker_probe_error": worker_probe_error,
            "tron_configured": bool(settings.TRONGRID_API_KEY),
            "sync_interval_seconds": settings.TRON_DEPOSIT_SYNC_INTERVAL_SECONDS,
        },
    )


@staff_required
@require_POST
def sync_wallet_balances(request):
    try:
        result = sync_all_wallets(
            trigger=WalletSyncRun.Trigger.MANUAL,
            requested_by=request.user,
        )
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


def _reconciliation_data(request):
    today = timezone.localdate()
    date_from, date_to = _date_filters(request)
    if not date_from and not date_to:
        date_from = today - timedelta(days=29)
        date_to = today

    deposits = _apply_deposit_date_range(Deposit.objects.select_related("user", "wallet"), date_from, date_to)
    approved_tron = deposits.filter(status=Deposit.Status.APPROVED, source=Deposit.Source.TRON)
    approved_manual = deposits.filter(status=Deposit.Status.APPROVED, source=Deposit.Source.MANUAL)
    approved_deposits = deposits.filter(status=Deposit.Status.APPROVED)
    unexpected = deposits.filter(status=Deposit.Status.UNEXPECTED)
    pending = deposits.filter(status=Deposit.Status.PENDING)

    paid_withdrawals = _apply_date_range(
        WithdrawalRequest.objects.select_related("user").filter(status=WithdrawalRequest.Status.PAID),
        "processed_at",
        date_from,
        date_to,
    )
    inflow_total = approved_deposits.aggregate(total=Sum("amount"))["total"] or 0
    outflow_total = paid_withdrawals.aggregate(total=Sum("net_amount"))["total"] or 0
    wallet_queryset = Wallet.objects.select_related("user").order_by("pk")
    stale_before = timezone.now() - timedelta(seconds=max(settings.TRON_DEPOSIT_SYNC_INTERVAL_SECONDS * 2, 600))
    wallet_totals = wallet_queryset.aggregate(
        total=Sum("usdt_balance"),
        count=Count("pk"),
        latest_check=Max("balance_checked_at"),
    )
    metrics = [
        {
            "label": "إيداعات TRON المعتمدة",
            "description": "تحويلات USDT المكتشفة على شبكة TRON واعتمدت كإيداعات خلال الفترة.",
            "count": approved_tron.count(),
            "amount": approved_tron.aggregate(total=Sum("amount"))["total"] or 0,
        },
        {
            "label": "الإيداعات اليدوية المعتمدة",
            "description": "إيداعات سجلتها الإدارة واعتمدتها يدوياً.",
            "count": approved_manual.count(),
            "amount": approved_manual.aggregate(total=Sum("amount"))["total"] or 0,
        },
        {
            "label": "الأرصدة غير المتوقعة",
            "description": "تحويلات وصلت إلى المحفظة لكنها لم تُضف تلقائياً إلى الرصيد المتاح، مثل المبالغ الأقل من الحد الأدنى.",
            "count": unexpected.count(),
            "amount": unexpected.aggregate(total=Sum("amount"))["total"] or 0,
        },
        {
            "label": "إيداعات قيد المراجعة",
            "description": "إيداعات لم تُعتمد أو تُرفض بعد، لذلك تظهر منفصلة عن الإيداعات المعتمدة.",
            "count": pending.count(),
            "amount": pending.aggregate(total=Sum("amount"))["total"] or 0,
        },
        {
            "label": "السحوبات المدفوعة — الصافي",
            "description": "صافي ما دُفع للعملاء بعد احتساب الضريبة المسجلة في طلب السحب.",
            "count": paid_withdrawals.count(),
            "amount": paid_withdrawals.aggregate(total=Sum("net_amount"))["total"] or 0,
        },
    ]
    return {
        "date_from": date_from,
        "date_to": date_to,
        "inflow_total": inflow_total,
        "outflow_total": outflow_total,
        "net_flow_total": inflow_total - outflow_total,
        "metrics": metrics,
        "wallets": wallet_queryset,
        "wallet_total": wallet_totals["total"] or 0,
        "wallet_count": wallet_totals["count"],
        "latest_wallet_check": wallet_totals["latest_check"],
        "wallets_without_sync": wallet_queryset.filter(balance_checked_at__isnull=True).count(),
        "wallets_stale": wallet_queryset.filter(balance_checked_at__lt=stale_before).count(),
        "deposits": deposits.order_by("occurred_at", "created_at", "pk"),
        "paid_withdrawals": paid_withdrawals.order_by("processed_at", "pk"),
    }


def _reconciliation_chart_data(report):
    date_to = report["date_to"] or timezone.localdate()
    deposits = report["deposits"].filter(status=Deposit.Status.APPROVED)
    deposit_day = TruncDate(
        Coalesce("occurred_at", "created_at", output_field=DateTimeField()),
        tzinfo=timezone.get_current_timezone(),
    )
    daily_inflows = {
        row["day"]: row["amount"] or 0
        for row in deposits.order_by().annotate(day=deposit_day)
        .values("day")
        .annotate(amount=Sum("amount"))
    }
    daily_outflows = {
        row["day"]: row["amount"] or 0
        for row in report["paid_withdrawals"].order_by().annotate(
            day=TruncDate("processed_at", tzinfo=timezone.get_current_timezone())
        )
        .values("day")
        .annotate(amount=Sum("net_amount"))
    }
    activity_days = set(daily_inflows) | set(daily_outflows)
    date_from = report["date_from"] or min(
        activity_days,
        default=date_to - timedelta(days=29),
    )
    if date_from > date_to:
        date_to = date_from

    days_in_period = (date_to - date_from).days + 1
    weekly = days_in_period > 90
    if weekly:
        cursor = date_from - timedelta(days=date_from.weekday())
        last_bucket = date_to - timedelta(days=date_to.weekday())
        bucket_starts = []
        while cursor <= last_bucket:
            bucket_starts.append(cursor)
            cursor += timedelta(days=7)
    else:
        bucket_starts = [date_from + timedelta(days=offset) for offset in range(days_in_period)]

    bucketed_inflows = {}
    bucketed_outflows = {}
    for day in activity_days:
        bucket_start = day - timedelta(days=day.weekday()) if weekly else day
        bucketed_inflows[bucket_start] = bucketed_inflows.get(bucket_start, 0) + daily_inflows.get(day, 0)
        bucketed_outflows[bucket_start] = bucketed_outflows.get(bucket_start, 0) + daily_outflows.get(day, 0)

    bucket_values = []
    for bucket_start in bucket_starts:
        inflow = bucketed_inflows.get(bucket_start, 0)
        outflow = bucketed_outflows.get(bucket_start, 0)
        bucket_values.append(
            {
                "day": bucket_start,
                "inflow": inflow,
                "outflow": outflow,
                "net": inflow - outflow,
            }
        )

    width, height = 900, 320
    left, right, top, bottom = 68, 18, 20, 46
    plot_width = width - left - right
    plot_height = height - top - bottom
    all_values = [float(row[key]) for row in bucket_values for key in ("inflow", "outflow", "net")]
    scale_min = min([0.0, *all_values])
    scale_max = max([0.0, *all_values])
    if scale_min == scale_max:
        scale_min, scale_max = -1.0, 1.0

    def point_for(index, value):
        x = left + (plot_width / 2 if len(bucket_values) == 1 else index * plot_width / max(len(bucket_values) - 1, 1))
        y = top + (scale_max - float(value)) * plot_height / (scale_max - scale_min)
        return x, y

    for key in ("inflow", "outflow", "net"):
        points = [point_for(index, row[key]) for index, row in enumerate(bucket_values)]
        report[f"chart_{key}_points"] = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    tick_values = [scale_min + (scale_max - scale_min) * index / 4 for index in range(5)]
    report["chart_y_ticks"] = [
        {
            "y": top + (scale_max - value) * plot_height / (scale_max - scale_min),
            "text_y": top + (scale_max - value) * plot_height / (scale_max - scale_min) + 4,
            "label": f"{value:,.2f}",
        }
        for value in tick_values
    ]
    report["chart_zero_y"] = top + (scale_max * plot_height / (scale_max - scale_min))

    label_count = min(7, len(bucket_values))
    label_indices = {
        round(index * (len(bucket_values) - 1) / max(label_count - 1, 1))
        for index in range(label_count)
    }
    report["chart_x_labels"] = [
        {
            "x": point_for(index, 0)[0],
            "y": height - 10,
            "label": row["day"].strftime("%d/%m/%y" if weekly else "%d/%m"),
        }
        for index, row in enumerate(bucket_values)
        if index in label_indices
    ]
    report["chart_rows"] = [
        {
            **row,
            "label": (
                f"أسبوع {max(row['day'], date_from).strftime('%Y-%m-%d')}"
                if weekly
                else row["day"].strftime("%Y-%m-%d")
            ),
        }
        for row in bucket_values
    ]
    report["chart_interval_label"] = "أسبوعي" if weekly else "يومي"
    report["chart_has_activity"] = bool(activity_days)
    report["chart_view_box"] = f"0 0 {width} {height}"
    report["chart_left"] = left
    report["chart_right"] = width - right
    report["chart_top"] = top
    report["chart_bottom"] = top + plot_height
    return report


@staff_required
def reconciliation(request):
    report = _reconciliation_data(request)
    report = _reconciliation_chart_data(report)
    maximum_flow = max(float(report["inflow_total"]), float(report["outflow_total"]), 0)
    report["inflow_width"] = float(report["inflow_total"]) / maximum_flow * 100 if maximum_flow else 0
    report["outflow_width"] = float(report["outflow_total"]) / maximum_flow * 100 if maximum_flow else 0
    return render(request, "management/reconciliation.html", report)


@staff_required
def reconciliation_export(request):
    report = _reconciliation_data(request)
    report = _reconciliation_chart_data(report)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response.write("\ufeff")
    response["Content-Disposition"] = "attachment; filename=financial-reconciliation.csv"
    writer = csv.writer(response)
    writer.writerow(["نوع البيان", "العدد", "المبلغ USDT", "رقم العميل", "التاريخ", "الحالة", "المصدر", "مرجع / TxID", "عنوان المحفظة"])
    for metric in report["metrics"]:
        writer.writerow([metric["label"], metric["count"], metric["amount"]])
    writer.writerow(["إجمالي الإيداعات المعتمدة — داخل", "", report["inflow_total"]])
    writer.writerow(["صافي السحوبات المدفوعة — خارج", "", report["outflow_total"]])
    writer.writerow(["الفرق — الداخل ناقص الخارج", "", report["net_flow_total"]])
    writer.writerow([])
    writer.writerow([f"التدفقات حسب الفترة ({report['chart_interval_label']})", "الإيداعات المعتمدة", "السحوبات المدفوعة", "صافي الحركة"])
    for row in report["chart_rows"]:
        writer.writerow([row["label"], row["inflow"], row["outflow"], row["net"]])
    writer.writerow(["الرصيد الفعلي الحالي على الشبكة", report["wallet_count"], report["wallet_total"]])
    writer.writerow([])
    for deposit in report["deposits"]:
        writer.writerow([
            "إيداع",
            "",
            deposit.amount,
            deposit.user.phone,
            deposit.occurred_at or deposit.created_at,
            deposit.get_status_display(),
            deposit.get_source_display(),
            deposit.transaction_id or deposit.reference,
            deposit.wallet.address if deposit.wallet_id else "",
        ])
    for withdrawal in report["paid_withdrawals"]:
        writer.writerow([
            "سحب مدفوع — الصافي",
            "",
            withdrawal.net_amount,
            withdrawal.user.phone,
            withdrawal.processed_at,
            withdrawal.get_status_display(),
            "TRC20",
            "",
            withdrawal.wallet_address,
        ])
    for wallet in report["wallets"]:
        writer.writerow([
            "لقطة رصيد شبكة",
            "",
            wallet.usdt_balance,
            wallet.user.phone,
            wallet.balance_checked_at or "",
            "مزامنة قديمة" if wallet.balance_checked_at else "لم تتم المزامنة",
            "TRC20",
            "",
            wallet.address,
        ])
    return response
