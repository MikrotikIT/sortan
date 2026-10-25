import django.contrib.auth.models
import django.contrib.auth.validators
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
import investments.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformSettings",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("default_voucher_count", models.PositiveIntegerField(default=3, verbose_name="القسائم المجانية عند التسجيل")),
                ("default_voucher_amount", models.DecimalField(decimal_places=2, default=100, max_digits=12, validators=[django.core.validators.MinValueValidator(0.01)], verbose_name="قيمة القسيمة الافتراضية")),
                ("withdrawal_cooldown_enabled", models.BooleanField(default=True, verbose_name="تفعيل فترة الانتظار للسحب")),
                ("withdrawal_interval_days", models.PositiveIntegerField(default=10, verbose_name="أيام الانتظار بين عمليات السحب")),
                ("withdrawal_tax_enabled", models.BooleanField(default=True, verbose_name="تفعيل ضريبة السحب")),
                ("withdrawal_tax_percent", models.DecimalField(decimal_places=2, default=10, max_digits=5, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)], verbose_name="ضريبة السحب (%)")),
                ("referral_deposit_percent", models.DecimalField(decimal_places=2, default=1, max_digits=5, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)], verbose_name="عمولة الدعوة من الإيداع (%)")),
                ("referral_profit_percent", models.DecimalField(decimal_places=2, default=10, max_digits=5, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)], verbose_name="عمولة الدعوة من الأرباح (%)")),
            ],
            options={"verbose_name": "إعدادات المنصة", "verbose_name_plural": "إعدادات المنصة"},
        ),
        migrations.CreateModel(
            name="Film",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180, verbose_name="اسم الفيلم")),
                ("description", models.TextField(blank=True, verbose_name="نبذة")),
                ("image_url", models.URLField(blank=True, max_length=500, verbose_name="رابط صورة الفيلم")),
                ("external_url", models.URLField(max_length=500, verbose_name="رابط الفيلم المطلوب للاستثمار")),
                ("investment_code", models.CharField(max_length=48, unique=True, verbose_name="كود الاستثمار")),
                ("waiting_days", models.PositiveIntegerField(default=10, verbose_name="مدة الاستثمار بالأيام")),
                ("profit_percent", models.DecimalField(decimal_places=2, default=3, max_digits=6, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)], verbose_name="نسبة الربح (%)")),
                ("active", models.BooleanField(default=True, verbose_name="متاح للاستثمار")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإضافة")),
            ],
            options={"verbose_name": "فيلم", "verbose_name_plural": "الأفلام", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(default=False, help_text="Designates that this user has all permissions without explicitly assigning them.", verbose_name="superuser status")),
                ("first_name", models.CharField(blank=True, max_length=150, verbose_name="first name")),
                ("last_name", models.CharField(blank=True, max_length=150, verbose_name="last name")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="email address")),
                ("is_staff", models.BooleanField(default=False, help_text="Designates whether the user can log into this admin site.", verbose_name="staff status")),
                ("is_active", models.BooleanField(default=True, help_text="Designates whether this user should be treated as active. Unselect this instead of deleting accounts.", verbose_name="active")),
                ("date_joined", models.DateTimeField(default=django.utils.timezone.now, verbose_name="date joined")),
                ("phone", models.CharField(max_length=20, unique=True, verbose_name="رقم الهاتف")),
                ("balance", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="الرصيد")),
                ("earnings_balance", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="الأرباح المتاحة للسحب")),
                ("total_earned", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="إجمالي الأرباح")),
                ("referral_code", models.CharField(blank=True, max_length=12, unique=True, verbose_name="كود الدعوة")),
                ("groups", models.ManyToManyField(blank=True, help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.", related_name="user_set", related_query_name="user", to="auth.group", verbose_name="groups")),
                ("user_permissions", models.ManyToManyField(blank=True, help_text="Specific permissions for this user.", related_name="user_set", related_query_name="user", to="auth.permission", verbose_name="user permissions")),
                ("referred_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="referrals", to=settings.AUTH_USER_MODEL, verbose_name="تمت دعوته بواسطة")),
            ],
            options={"verbose_name": "مستخدم", "verbose_name_plural": "المستخدمون"},
            managers=[("objects", investments.models.UserManager())],
        ),
        migrations.CreateModel(
            name="InvestmentVoucher",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(0.01)], verbose_name="قيمة القسيمة")),
                ("status", models.CharField(choices=[("available", "متاحة"), ("used", "مستخدمة"), ("revoked", "ملغاة")], default="available", max_length=12, verbose_name="الحالة")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإصدار")),
                ("used_at", models.DateTimeField(blank=True, null=True, verbose_name="تاريخ الاستخدام")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="vouchers", to=settings.AUTH_USER_MODEL, verbose_name="المستخدم")),
            ],
            options={"verbose_name": "قسيمة استثمار", "verbose_name_plural": "قسائم الاستثمار", "ordering": ("created_at",)},
        ),
        migrations.CreateModel(
            name="Investment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("film_title", models.CharField(max_length=180, verbose_name="اسم الفيلم")),
                ("film_image_url", models.URLField(blank=True, max_length=500, verbose_name="صورة الفيلم")),
                ("film_url", models.URLField(max_length=500, verbose_name="رابط الفيلم")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12, verbose_name="مبلغ الاستثمار")),
                ("profit_percent", models.DecimalField(decimal_places=2, max_digits=6, verbose_name="نسبة الربح وقت الاستثمار (%)")),
                ("expected_profit", models.DecimalField(decimal_places=2, max_digits=12, verbose_name="الربح المتوقع")),
                ("realized_profit", models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name="الربح المحقق")),
                ("status", models.CharField(choices=[("active", "قيد الاستثمار"), ("completed", "مكتمل")], default="active", max_length=12, verbose_name="الحالة")),
                ("invested_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="تاريخ الاستثمار")),
                ("matures_at", models.DateTimeField(verbose_name="موعد اكتمال الاستثمار")),
                ("settled_at", models.DateTimeField(blank=True, null=True, verbose_name="تاريخ احتساب الربح")),
                ("film", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="investments", to="investments.film", verbose_name="الفيلم")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="investments", to=settings.AUTH_USER_MODEL, verbose_name="المستخدم")),
                ("voucher", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="investment", to="investments.investmentvoucher", verbose_name="القسيمة")),
            ],
            options={"verbose_name": "استثمار", "verbose_name_plural": "الاستثمارات", "ordering": ("-invested_at",)},
        ),
        migrations.CreateModel(
            name="Deposit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(0.01)], verbose_name="المبلغ")),
                ("reference", models.CharField(blank=True, max_length=180, verbose_name="مرجع التحويل")),
                ("status", models.CharField(choices=[("pending", "قيد المراجعة"), ("approved", "مقبول"), ("rejected", "مرفوض")], default="pending", max_length=12, verbose_name="الحالة")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإضافة")),
                ("processed_at", models.DateTimeField(blank=True, null=True, verbose_name="تاريخ المعالجة")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deposits", to=settings.AUTH_USER_MODEL, verbose_name="المستخدم")),
            ],
            options={"verbose_name": "إيداع", "verbose_name_plural": "الإيداعات", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="ReferralCommission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(choices=[("deposit", "إيداع"), ("profit", "أرباح استثمار")], max_length=12, verbose_name="مصدر العمولة")),
                ("source_id", models.PositiveBigIntegerField(verbose_name="رقم العملية")),
                ("wallet", models.CharField(choices=[("balance", "الرصيد"), ("earnings", "الأرباح")], max_length=12, verbose_name="المحفظة")),
                ("percent", models.DecimalField(decimal_places=2, max_digits=5, verbose_name="النسبة وقت الاحتساب (%)")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, verbose_name="قيمة العمولة")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الاحتساب")),
                ("referrer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="referral_commissions", to=settings.AUTH_USER_MODEL, verbose_name="صاحب كود الدعوة")),
                ("referred_user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="referral_commissions_received", to=settings.AUTH_USER_MODEL, verbose_name="المستخدم المدعو")),
            ],
            options={"verbose_name": "عمولة دعوة", "verbose_name_plural": "عمولات الدعوات", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="WithdrawalRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(0.01)], verbose_name="المبلغ قبل الضريبة")),
                ("tax_percent", models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name="نسبة الضريبة وقت الطلب (%)")),
                ("tax_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="قيمة الضريبة")),
                ("net_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="المبلغ الصافي")),
                ("wallet_address", models.CharField(max_length=64, validators=[django.core.validators.RegexValidator("^T[1-9A-HJ-NP-Za-km-z]{33}$", "أدخل عنوان TRON TRC20 صحيحاً.")], verbose_name="عنوان USDT TRC20")),
                ("status", models.CharField(choices=[("pending", "قيد المراجعة"), ("paid", "مدفوع"), ("rejected", "مرفوض")], default="pending", max_length=12, verbose_name="الحالة")),
                ("requested_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الطلب")),
                ("processed_at", models.DateTimeField(blank=True, null=True, verbose_name="تاريخ المعالجة")),
                ("admin_note", models.CharField(blank=True, max_length=240, verbose_name="ملاحظة الإدارة")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="withdrawals", to=settings.AUTH_USER_MODEL, verbose_name="المستخدم")),
            ],
            options={"verbose_name": "طلب سحب", "verbose_name_plural": "طلبات السحب", "ordering": ("-requested_at",)},
        ),
        migrations.AddConstraint(
            model_name="referralcommission",
            constraint=models.UniqueConstraint(fields=("source", "source_id"), name="unique_referral_commission_source"),
        ),
    ]
