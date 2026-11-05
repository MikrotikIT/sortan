import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0053_chatmembership_last_push_message"),
    ]

    operations = [
        migrations.CreateModel(
            name="InvestmentAutoPostLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180, verbose_name="اسم الفيلم")),
                ("description", models.TextField(blank=True, verbose_name="نبذة الفيلم")),
                ("external_url", models.URLField(max_length=500, verbose_name="رابط الاستثمار")),
                ("image_url", models.URLField(blank=True, max_length=500, verbose_name="رابط صورة خارجي")),
                ("image", models.ImageField(blank=True, upload_to="investment_link_basket/", validators=[django.core.validators.FileExtensionValidator(("jpg", "jpeg", "png", "webp"))], verbose_name="صورة الفيلم")),
                ("status", models.CharField(choices=[("available", "في السلة"), ("used", "تم النشر")], default="available", max_length=12, verbose_name="الحالة")),
                ("used_at", models.DateTimeField(blank=True, null=True, verbose_name="وقت الاستخدام")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإضافة")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_investment_auto_post_links", to="investments.user")),
                ("used_film", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="auto_post_source_links", to="investments.film")),
            ],
            options={
                "verbose_name": "رابط جاهز للنشر",
                "verbose_name_plural": "سلة روابط الاستثمار",
                "ordering": ("status", "created_at", "pk"),
            },
        ),
        migrations.CreateModel(
            name="InvestmentAutoPostSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, verbose_name="اسم الجدولة")),
                ("enabled", models.BooleanField(default=False, verbose_name="مفعّلة")),
                ("timezone_name", models.CharField(default="Asia/Damascus", max_length=64, verbose_name="المنطقة الزمنية")),
                ("publish_times", models.JSONField(default=list, verbose_name="أوقات النشر اليومية")),
                ("waiting_duration", models.PositiveIntegerField(default=10, validators=[django.core.validators.MinValueValidator(1)], verbose_name="مدة الاستثمار")),
                ("waiting_unit", models.CharField(choices=[("seconds", "ثوانٍ"), ("minutes", "دقائق"), ("hours", "ساعات"), ("days", "أيام")], default="days", max_length=8, verbose_name="وحدة مدة الاستثمار")),
                ("minimum_investment_amount", models.DecimalField(decimal_places=2, default=100, max_digits=12, validators=[django.core.validators.MinValueValidator(0.01)], verbose_name="الحد الأدنى للاستثمار (USDT)")),
                ("profit_percent", models.DecimalField(decimal_places=2, default=3, max_digits=6, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)], verbose_name="نسبة الربح (%)")),
                ("link_expiry_duration", models.PositiveIntegerField(blank=True, default=1, null=True, validators=[django.core.validators.MinValueValidator(1)], verbose_name="مدة صلاحية الرابط")),
                ("link_expiry_unit", models.CharField(choices=[("minutes", "دقائق"), ("hours", "ساعات"), ("days", "أيام")], default="days", max_length=8, verbose_name="وحدة صلاحية الرابط")),
                ("message_template", models.TextField(default="أهلاً بكم\nهذا هو رابط الاستثمار: {link}\nكود الاستثمار: {code}\nمدة الاستثمار: {duration}\nالحد الأدنى: {minimum} USDT", verbose_name="قالب رسالة المجموعة")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخر تعديل")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_investment_auto_post_schedules", to="investments.user")),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="investment_auto_post_schedules", to="investments.chatgroup", verbose_name="مجموعة النشر")),
                ("sender", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="investment_auto_post_schedules", to="investments.user", verbose_name="الناشر")),
            ],
            options={
                "verbose_name": "جدولة نشر استثمار",
                "verbose_name_plural": "جداول نشر الاستثمارات",
                "ordering": ("name", "pk"),
            },
        ),
        migrations.CreateModel(
            name="InvestmentAutoPostRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scheduled_at", models.DateTimeField(verbose_name="موعد النشر المحدد")),
                ("status", models.CharField(choices=[("sent", "تم النشر"), ("failed", "فشل النشر")], max_length=8, verbose_name="الحالة")),
                ("error", models.TextField(blank=True, verbose_name="تفاصيل الخطأ")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="وقت التنفيذ")),
                ("film", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="auto_post_runs", to="investments.film")),
                ("link_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="runs", to="investments.investmentautopostlink")),
                ("message", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="investment_auto_post_runs", to="investments.chatmessage")),
                ("schedule", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="runs", to="investments.investmentautopostschedule")),
            ],
            options={
                "verbose_name": "تنفيذ نشر استثمار مجدول",
                "verbose_name_plural": "سجل نشر الاستثمارات المجدول",
                "ordering": ("-scheduled_at", "-pk"),
            },
        ),
        migrations.AddConstraint(
            model_name="investmentautopostrun",
            constraint=models.UniqueConstraint(fields=("schedule", "scheduled_at"), name="auto_post_sched_slot_uniq"),
        ),
    ]
