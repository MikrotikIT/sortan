import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0013_film_link_expiration"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformsettings",
            name="deposit_activity_enabled",
            field=models.BooleanField(default=True, verbose_name="إظهار إشعار النشاط التجريبي"),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="deposit_activity_examples",
            field=models.TextField(
                default="سوريا|0963980***|100\nالعراق|0770123***|150\nالأردن|0791234***|200\nالسودان|0912345***|300\nلبنان|031234***|250",
                help_text="سطر لكل إشعار بالصيغة الدولة|رقم الهاتف|المبلغ. هذه بيانات عرض تجريبية وليست إيداعات حقيقية.",
                verbose_name="بيانات إشعار النشاط التجريبي",
            ),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="deposit_activity_interval_seconds",
            field=models.PositiveIntegerField(
                default=10,
                validators=[django.core.validators.MinValueValidator(5), django.core.validators.MaxValueValidator(120)],
                verbose_name="الفاصل بين إشعارات النشاط (ثوانٍ)",
            ),
        ),
    ]
