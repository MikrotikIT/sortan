import investments.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0031_platformsettings_deposit_activity_ranges"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformsettings",
            name="deposit_activity_amount_bands",
            field=models.JSONField(
                default=investments.models.default_deposit_activity_amount_bands,
                verbose_name="شرائح مبالغ إشعار النشاط واحتمالاتها",
            ),
        ),
    ]
