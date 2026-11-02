import investments.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0035_credit_demo_investment_profits"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatgroup",
            name="allowed_reactions",
            field=models.JSONField(
                default=investments.models.default_chat_reactions,
                verbose_name="التفاعلات المتاحة",
            ),
        ),
    ]
