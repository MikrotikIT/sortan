import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0003_film_minimum_investment_amount"),
    ]

    operations = [
        migrations.RenameField(
            model_name="film",
            old_name="waiting_days",
            new_name="waiting_duration",
        ),
        migrations.AlterField(
            model_name="film",
            name="waiting_duration",
            field=models.PositiveIntegerField(
                default=10,
                validators=[django.core.validators.MinValueValidator(1)],
                verbose_name="مدة الاستثمار",
            ),
        ),
        migrations.AddField(
            model_name="film",
            name="waiting_unit",
            field=models.CharField(
                choices=[("minutes", "دقائق"), ("hours", "ساعات"), ("days", "أيام")],
                default="days",
                max_length=8,
                verbose_name="وحدة مدة الاستثمار",
            ),
        ),
    ]
