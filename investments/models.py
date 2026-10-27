import secrets
import string
from datetime import timedelta

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


def make_referral_code():
    alphabet = string.ascii_uppercase + string.digits
    return "CINE" + "".join(secrets.choice(alphabet) for _ in range(6))


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, phone, password, **extra_fields):
        if not phone:
            raise ValueError("يجب إدخال رقم الهاتف")
        user = self.model(phone=phone.strip(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, phone, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone, password, **extra_fields)

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("يجب أن يكون is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("يجب أن يكون is_superuser=True")
        return self._create_user(phone, password, **extra_fields)


class User(AbstractUser):
    username = None
    phone = models.CharField("رقم الهاتف", max_length=20, unique=True)
    balance = models.DecimalField("الرصيد", max_digits=20, decimal_places=6, default=0)
    earnings_balance = models.DecimalField("الأرباح المتاحة للسحب", max_digits=14, decimal_places=2, default=0)
    total_earned = models.DecimalField("إجمالي الأرباح", max_digits=14, decimal_places=2, default=0)
    referral_code = models.CharField("كود الدعوة", max_length=12, unique=True, blank=True)
    referred_by = models.ForeignKey("self", verbose_name="تمت دعوته بواسطة", null=True, blank=True, on_delete=models.SET_NULL, related_name="referrals")

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta:
        verbose_name = "مستخدم"
        verbose_name_plural = "المستخدمون"

    def save(self, *args, **kwargs):
        if not self.referral_code:
            code = make_referral_code()
            while User.objects.filter(referral_code=code).exists():
                code = make_referral_code()
            self.referral_code = code
        super().save(*args, **kwargs)

    def __str__(self):
        return self.phone


class PlatformSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    support_url = models.URLField("رابط الدعم الفني", max_length=500, blank=True, default="")
    default_voucher_count = models.PositiveIntegerField("القسائم المجانية عند التسجيل", default=3)
    default_voucher_amount = models.DecimalField("قيمة القسيمة الافتراضية", max_digits=12, decimal_places=2, default=100, validators=[MinValueValidator(0.01)])
    withdrawal_cooldown_enabled = models.BooleanField("تفعيل فترة الانتظار للسحب", default=True)
    withdrawal_interval_days = models.PositiveIntegerField("أيام الانتظار بين عمليات السحب", default=10)
    withdrawal_referral_gate_enabled = models.BooleanField(
        "اشتراط دعوات بعد عدد من عمليات السحب",
        default=True,
        help_text="عند التفعيل، يجب استيفاء عدد الدعوات المحدد بعد بلوغ حد السحوبات المدفوعة.",
    )
    withdrawal_referral_rules = models.TextField(
        "مراحل السحب وعدد المدعوين المطلوب",
        default="3:2",
        blank=True,
        help_text="اكتب كل مرحلة بصيغة عدد السحوبات:عدد المدعوين، مثال: 3:2, 5:4, 9:6.",
    )
    withdrawal_tax_enabled = models.BooleanField("تفعيل ضريبة السحب", default=True)
    withdrawal_tax_percent = models.DecimalField("ضريبة السحب (%)", max_digits=5, decimal_places=2, default=10, validators=[MinValueValidator(0), MaxValueValidator(100)])
    referral_deposit_percent = models.DecimalField("عمولة الدعوة من الإيداع (%)", max_digits=5, decimal_places=2, default=1, validators=[MinValueValidator(0), MaxValueValidator(100)])
    referral_profit_percent = models.DecimalField("عمولة الدعوة من الأرباح (%)", max_digits=5, decimal_places=2, default=10, validators=[MinValueValidator(0), MaxValueValidator(100)])
    online_counter_enabled = models.BooleanField("تفعيل عداد المتصلين التجريبي", default=True)
    online_counter_min = models.PositiveIntegerField("الحد الأدنى لعداد المتصلين", default=12000)
    online_counter_max = models.PositiveIntegerField("الحد الأعلى لعداد المتصلين", default=15000)
    online_counter_step_min = models.PositiveIntegerField("أقل مقدار للتغير", default=1, validators=[MinValueValidator(1)])
    online_counter_step_max = models.PositiveIntegerField("أكبر مقدار للتغير", default=30, validators=[MinValueValidator(1)])
    online_counter_current = models.PositiveIntegerField("قيمة عداد المتصلين الحالية", default=0, editable=False)
    online_counter_updated_at = models.DateTimeField("آخر تحديث لعداد المتصلين", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "إعدادات المنصة"
        verbose_name_plural = "إعدادات المنصة"

    def __str__(self):
        return "إعدادات المنصة"


class Film(models.Model):
    class DurationUnit(models.TextChoices):
        MINUTES = "minutes", "دقائق"
        HOURS = "hours", "ساعات"
        DAYS = "days", "أيام"

    class ExpiryUnit(models.TextChoices):
        MINUTES = "minutes", "دقائق"
        HOURS = "hours", "ساعات"
        DAYS = "days", "أيام"

    title = models.CharField("اسم الفيلم", max_length=180)
    description = models.TextField("نبذة", blank=True)
    image_url = models.URLField("رابط صورة الفيلم", max_length=500, blank=True)
    external_url = models.URLField("رابط الفيلم المطلوب للاستثمار", max_length=500)
    investment_code = models.CharField("كود الاستثمار", max_length=48, unique=True)
    waiting_duration = models.PositiveIntegerField("مدة الاستثمار", default=10, validators=[MinValueValidator(1)])
    waiting_unit = models.CharField("وحدة مدة الاستثمار", max_length=8, choices=DurationUnit.choices, default=DurationUnit.DAYS)
    profit_percent = models.DecimalField("نسبة الربح (%)", max_digits=6, decimal_places=2, default=3, validators=[MinValueValidator(0), MaxValueValidator(100)])
    minimum_investment_amount = models.DecimalField(
        "الحد الأدنى للاستثمار من الرصيد (USDT)",
        max_digits=12,
        decimal_places=2,
        default=100,
        validators=[MinValueValidator(0.01)],
        help_text="يُطبّق عند اختيار الاستثمار من الرصيد. القيمة الافتراضية 100 USDT.",
    )
    link_expiry_duration = models.PositiveIntegerField(
        "مدة صلاحية الرابط",
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="اتركها فارغة ليبقى الرابط صالحاً دون انتهاء محدد.",
    )
    link_expiry_unit = models.CharField("وحدة صلاحية الرابط", max_length=8, choices=ExpiryUnit.choices, default=ExpiryUnit.DAYS)
    link_expires_at = models.DateTimeField("انتهاء صلاحية الرابط", null=True, blank=True, editable=False)
    active = models.BooleanField("متاح للاستثمار", default=True)
    created_at = models.DateTimeField("تاريخ الإضافة", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "فيلم"
        verbose_name_plural = "الأفلام"

    def __str__(self):
        return self.title

    @property
    def is_expired(self):
        return self.link_expires_at is not None and timezone.now() >= self.link_expires_at

    def save(self, *args, **kwargs):
        expiry_changed = self._state.adding
        if not expiry_changed and self.pk:
            previous = type(self).objects.filter(pk=self.pk).values(
                "link_expiry_duration", "link_expiry_unit"
            ).first()
            expiry_changed = previous is not None and (
                previous["link_expiry_duration"] != self.link_expiry_duration
                or previous["link_expiry_unit"] != self.link_expiry_unit
            )
        if expiry_changed:
            if self.link_expiry_duration:
                self.link_expires_at = timezone.now() + timedelta(
                    **{self.link_expiry_unit: self.link_expiry_duration}
                )
            else:
                self.link_expires_at = None
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"link_expires_at"}
        super().save(*args, **kwargs)


class InvestmentVoucher(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "متاحة"
        USED = "used", "مستخدمة"
        REVOKED = "revoked", "ملغاة"

    user = models.ForeignKey(User, verbose_name="المستخدم", on_delete=models.CASCADE, related_name="vouchers")
    amount = models.DecimalField("قيمة القسيمة", max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)])
    status = models.CharField("الحالة", max_length=12, choices=Status.choices, default=Status.AVAILABLE)
    created_at = models.DateTimeField("تاريخ الإصدار", auto_now_add=True)
    used_at = models.DateTimeField("تاريخ الاستخدام", null=True, blank=True)

    class Meta:
        ordering = ("created_at",)
        verbose_name = "قسيمة استثمار"
        verbose_name_plural = "قسائم الاستثمار"

    def __str__(self):
        return f"{self.user.phone} — {self.amount} USDT ({self.get_status_display()})"


class Investment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "قيد الاستثمار"
        COMPLETED = "completed", "مكتمل"

    class FundingSource(models.TextChoices):
        VOUCHER = "voucher", "قسيمة استثمار"
        BALANCE = "balance", "الرصيد"

    user = models.ForeignKey(User, verbose_name="المستخدم", on_delete=models.CASCADE, related_name="investments")
    film = models.ForeignKey(Film, verbose_name="الفيلم", on_delete=models.PROTECT, related_name="investments")
    voucher = models.OneToOneField(InvestmentVoucher, verbose_name="القسيمة", null=True, blank=True, on_delete=models.PROTECT, related_name="investment")
    funding_source = models.CharField("طريقة الاستثمار", max_length=10, choices=FundingSource.choices, default=FundingSource.VOUCHER)
    film_title = models.CharField("اسم الفيلم", max_length=180)
    film_image_url = models.URLField("صورة الفيلم", max_length=500, blank=True)
    film_url = models.URLField("رابط الفيلم", max_length=500)
    amount = models.DecimalField("مبلغ الاستثمار", max_digits=20, decimal_places=6)
    profit_percent = models.DecimalField("نسبة الربح وقت الاستثمار (%)", max_digits=6, decimal_places=2)
    expected_profit = models.DecimalField("الربح المتوقع", max_digits=12, decimal_places=2)
    realized_profit = models.DecimalField("الربح المحقق", max_digits=12, decimal_places=2, default=0)
    status = models.CharField("الحالة", max_length=12, choices=Status.choices, default=Status.ACTIVE)
    invested_at = models.DateTimeField("تاريخ الاستثمار", default=timezone.now)
    matures_at = models.DateTimeField("موعد اكتمال الاستثمار")
    settled_at = models.DateTimeField("تاريخ احتساب الربح", null=True, blank=True)

    class Meta:
        ordering = ("-invested_at",)
        verbose_name = "استثمار"
        verbose_name_plural = "الاستثمارات"

    def __str__(self):
        return f"{self.film_title} — {self.user.phone}"


class Wallet(models.Model):
    user = models.OneToOneField(User, verbose_name="المستخدم", on_delete=models.CASCADE, related_name="wallet")
    address = models.CharField("عنوان TRON TRC20", max_length=64, unique=True)
    encrypted_private_key = models.TextField("المفتاح الخاص المشفر")
    usdt_balance = models.DecimalField("رصيد USDT على الشبكة", max_digits=20, decimal_places=6, default=0)
    balance_checked_at = models.DateTimeField("آخر تحديث للرصيد", null=True, blank=True)
    created_at = models.DateTimeField("تاريخ إنشاء المحفظة", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "محفظة TRON"
        verbose_name_plural = "محافظ TRON"

    def __str__(self):
        return f"{self.user.phone} — {self.address}"


class Deposit(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "يدوي"
        TRON = "tron", "TRON TRC20"

    class Status(models.TextChoices):
        PENDING = "pending", "قيد المراجعة"
        APPROVED = "approved", "مقبول"
        REJECTED = "rejected", "مرفوض"

    user = models.ForeignKey(User, verbose_name="المستخدم", on_delete=models.CASCADE, related_name="deposits")
    wallet = models.ForeignKey(Wallet, verbose_name="المحفظة", null=True, blank=True, on_delete=models.SET_NULL, related_name="deposits")
    amount = models.DecimalField("المبلغ", max_digits=20, decimal_places=6, validators=[MinValueValidator(0.000001)])
    reference = models.CharField("مرجع التحويل", max_length=180, blank=True)
    transaction_id = models.CharField("معرّف معاملة TRON", max_length=128, unique=True, null=True, blank=True)
    source = models.CharField("مصدر الإيداع", max_length=12, choices=Source.choices, default=Source.MANUAL)
    status = models.CharField("الحالة", max_length=12, choices=Status.choices, default=Status.PENDING)
    occurred_at = models.DateTimeField("وقت التحويل على الشبكة", null=True, blank=True)
    created_at = models.DateTimeField("تاريخ الإضافة", auto_now_add=True)
    processed_at = models.DateTimeField("تاريخ المعالجة", null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "إيداع"
        verbose_name_plural = "الإيداعات"

    def __str__(self):
        return f"{self.user.phone} — {self.amount} USDT"


class InternalBalanceCredit(models.Model):
    user = models.ForeignKey(
        User,
        verbose_name="المستخدم",
        on_delete=models.CASCADE,
        related_name="internal_balance_credits",
    )
    admin = models.ForeignKey(
        User,
        verbose_name="منفذ العملية",
        on_delete=models.PROTECT,
        related_name="issued_internal_balance_credits",
    )
    amount = models.DecimalField(
        "المبلغ",
        max_digits=20,
        decimal_places=6,
        validators=[MinValueValidator(0.000001)],
    )
    internal_note = models.CharField("ملاحظة داخلية", max_length=240, blank=True)
    created_at = models.DateTimeField("تاريخ الإضافة", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "إضافة رصيد داخلية"
        verbose_name_plural = "إضافات الرصيد الداخلية"

    def __str__(self):
        return f"{self.user.phone} — {self.amount} USDT"


class ReferralCommission(models.Model):
    class Source(models.TextChoices):
        DEPOSIT = "deposit", "إيداع"
        PROFIT = "profit", "أرباح استثمار"

    class Wallet(models.TextChoices):
        BALANCE = "balance", "الرصيد"
        EARNINGS = "earnings", "الأرباح"

    referrer = models.ForeignKey(User, verbose_name="صاحب كود الدعوة", on_delete=models.CASCADE, related_name="referral_commissions")
    referred_user = models.ForeignKey(User, verbose_name="المستخدم المدعو", on_delete=models.CASCADE, related_name="referral_commissions_received")
    source = models.CharField("مصدر العمولة", max_length=12, choices=Source.choices)
    source_id = models.PositiveBigIntegerField("رقم العملية")
    wallet = models.CharField("المحفظة", max_length=12, choices=Wallet.choices)
    percent = models.DecimalField("النسبة وقت الاحتساب (%)", max_digits=5, decimal_places=2)
    amount = models.DecimalField("قيمة العمولة", max_digits=14, decimal_places=2)
    created_at = models.DateTimeField("تاريخ الاحتساب", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [models.UniqueConstraint(fields=("source", "source_id"), name="unique_referral_commission_source")]
        verbose_name = "عمولة دعوة"
        verbose_name_plural = "عمولات الدعوات"

    def __str__(self):
        return f"{self.referrer.phone} — {self.amount} USDT"


class WithdrawalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "قيد المراجعة"
        PAID = "paid", "مدفوع"
        REJECTED = "rejected", "مرفوض"

    user = models.ForeignKey(User, verbose_name="المستخدم", on_delete=models.CASCADE, related_name="withdrawals")
    amount = models.DecimalField("المبلغ قبل الضريبة", max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    tax_percent = models.DecimalField("نسبة الضريبة وقت الطلب (%)", max_digits=5, decimal_places=2, default=0)
    tax_amount = models.DecimalField("قيمة الضريبة", max_digits=14, decimal_places=2, default=0)
    net_amount = models.DecimalField("المبلغ الصافي", max_digits=14, decimal_places=2, default=0)
    wallet_address = models.CharField(
        "عنوان USDT TRC20",
        max_length=64,
        validators=[RegexValidator(r"^T[1-9A-HJ-NP-Za-km-z]{33}$", "أدخل عنوان TRON TRC20 صحيحاً.")],
    )
    status = models.CharField("الحالة", max_length=12, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField("تاريخ الطلب", auto_now_add=True)
    processed_at = models.DateTimeField("تاريخ المعالجة", null=True, blank=True)
    admin_note = models.CharField("ملاحظة الإدارة", max_length=240, blank=True)

    class Meta:
        ordering = ("-requested_at",)
        verbose_name = "طلب سحب"
        verbose_name_plural = "طلبات السحب"

    def __str__(self):
        return f"{self.user.phone} — {self.amount} USDT ({self.get_status_display()})"
