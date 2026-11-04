from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0051_ai_usage_period_total")]

    operations = [
        migrations.AddField(
            model_name="aibotpool",
            name="is_enabled",
            field=models.BooleanField(default=True, verbose_name="تفعيل التوزيعة"),
        ),
    ]
