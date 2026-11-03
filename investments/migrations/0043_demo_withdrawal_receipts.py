import uuid

import django.core.validators
import django.db.models.deletion
import investments.models
from django.db import migrations, models


def populate_demo_account_identity(apps, schema_editor):
    ChatDemoAccount = apps.get_model("investments", "ChatDemoAccount")
    country_codes = ("SY", "LB", "IQ", "JO", "EG", "SA", "AE", "TR")
    for account in ChatDemoAccount.objects.filter(demo_customer_number__isnull=True).iterator():
        account.demo_customer_number = f"DEMO-{uuid.uuid4().hex[:12].upper()}"
        account.demo_country_code = country_codes[(account.pk - 1) % len(country_codes)]
        account.save(update_fields=("demo_customer_number", "demo_country_code"))


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0042_joinapplication_age"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatdemoaccount",
            name="demo_customer_number",
            field=models.CharField(blank=True, max_length=17, null=True, verbose_name="رقم العميل التجريبي"),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="demo_country_code",
            field=models.CharField(blank=True, max_length=2, null=True, verbose_name="الدولة التجريبية"),
        ),
        migrations.RunPython(populate_demo_account_identity, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="chatdemoaccount",
            name="demo_customer_number",
            field=models.CharField(
                default=investments.models.make_demo_customer_number,
                editable=False,
                max_length=17,
                unique=True,
                verbose_name="رقم العميل التجريبي",
            ),
        ),
        migrations.AlterField(
            model_name="chatdemoaccount",
            name="demo_country_code",
            field=models.CharField(
                default=investments.models.make_demo_country_code,
                editable=False,
                max_length=2,
                verbose_name="الدولة التجريبية",
            ),
        ),
        migrations.CreateModel(
            name="DemoWithdrawalReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(0.01)], verbose_name="المبلغ قبل الضريبة")),
                ("tax_percent", models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name="نسبة الضريبة وقت الإنشاء (%)")),
                ("tax_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="قيمة الضريبة")),
                ("net_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="الصافي المحسوب")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ إنشاء الإيصال التجريبي")),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="withdrawal_receipts", to="investments.chatdemoaccount", verbose_name="حساب المحادثة التجريبي")),
            ],
            options={
                "verbose_name": "إيصال سحب تجريبي",
                "verbose_name_plural": "إيصالات السحب التجريبية",
                "ordering": ("-created_at", "-pk"),
            },
        ),
    ]
