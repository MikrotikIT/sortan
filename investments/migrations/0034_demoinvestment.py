from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0033_user_is_fake_account"),
    ]

    operations = [
        migrations.CreateModel(
            name="DemoInvestment",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("film_title", models.CharField(max_length=180, verbose_name="اسم الفيلم")),
                ("amount", models.DecimalField(decimal_places=6, max_digits=20, verbose_name="مبلغ الاستثمار")),
                ("profit_percent", models.DecimalField(decimal_places=2, max_digits=6, verbose_name="نسبة الربح (%)")),
                ("realized_profit", models.DecimalField(decimal_places=2, max_digits=20, verbose_name="الربح التجريبي")),
                (
                    "status",
                    models.CharField(
                        choices=[("completed", "مكتمل")],
                        default="completed",
                        editable=False,
                        max_length=12,
                        verbose_name="الحالة",
                    ),
                ),
                ("invested_at", models.DateTimeField(verbose_name="تاريخ الاستثمار")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_demo_investments",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="أنشأه",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="demo_investments",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="حساب الاختبار",
                    ),
                ),
            ],
            options={
                "verbose_name": "استثمار تجريبي",
                "verbose_name_plural": "الاستثمارات التجريبية",
                "ordering": ("-invested_at", "-pk"),
            },
        ),
        migrations.AddConstraint(
            model_name="demoinvestment",
            constraint=models.UniqueConstraint(fields=("user", "film_title"), name="demo_user_film_title_uniq"),
        ),
    ]
