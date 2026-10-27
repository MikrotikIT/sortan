import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0012_platformsettings_support_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="film",
            name="link_expiry_duration",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="اتركها فارغة ليبقى الرابط صالحاً دون انتهاء محدد.",
                null=True,
                validators=[django.core.validators.MinValueValidator(1)],
                verbose_name="مدة صلاحية الرابط",
            ),
        ),
        migrations.AddField(
            model_name="film",
            name="link_expiry_unit",
            field=models.CharField(
                choices=[("minutes", "دقائق"), ("hours", "ساعات"), ("days", "أيام")],
                default="days",
                max_length=8,
                verbose_name="وحدة صلاحية الرابط",
            ),
        ),
        migrations.AddField(
            model_name="film",
            name="link_expires_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="انتهاء صلاحية الرابط",
            ),
        ),
    ]
