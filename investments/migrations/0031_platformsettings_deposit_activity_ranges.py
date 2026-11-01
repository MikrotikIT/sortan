import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0030_chat_notification_preferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformsettings",
            name="deposit_activity_min_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=50,
                max_digits=12,
                validators=[
                    django.core.validators.MinValueValidator(50),
                    django.core.validators.MaxValueValidator(1000000),
                ],
                verbose_name="أقل مبلغ لإشعار النشاط (USDT)",
            ),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="deposit_activity_max_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=40000,
                max_digits=12,
                validators=[
                    django.core.validators.MinValueValidator(50),
                    django.core.validators.MaxValueValidator(1000000),
                ],
                verbose_name="أعلى مبلغ لإشعار النشاط (USDT)",
            ),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="deposit_activity_min_interval_seconds",
            field=models.PositiveIntegerField(
                default=3,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(300),
                ],
                verbose_name="أقل فترة بين إشعارات النشاط (ثوانٍ)",
            ),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="deposit_activity_max_interval_seconds",
            field=models.PositiveIntegerField(
                default=8,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(300),
                ],
                verbose_name="أعلى فترة بين إشعارات النشاط (ثوانٍ)",
            ),
        ),
    ]
