import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0041_chatgroup_display_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="joinapplication",
            name="age",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(120)],
                verbose_name="العمر",
            ),
        ),
    ]
