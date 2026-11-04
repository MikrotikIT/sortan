from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("investments", "0052_ai_bot_pool_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmembership",
            name="last_push_message_id",
            field=models.PositiveBigIntegerField(blank=True, editable=False, null=True),
        ),
    ]
