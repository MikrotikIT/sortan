from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0036_chatgroup_allowed_reactions"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformsettings",
            name="withdrawal_minimum_enabled",
            field=models.BooleanField(default=True, verbose_name="تفعيل الحد الأدنى للسحب"),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="withdrawal_minimum_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=5,
                max_digits=12,
                validators=[MinValueValidator(0.01)],
                verbose_name="الحد الأدنى للسحب (USDT)",
            ),
        ),
    ]
