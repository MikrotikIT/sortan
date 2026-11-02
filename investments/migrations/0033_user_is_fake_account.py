from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0032_platformsettings_deposit_activity_amount_bands"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_fake_account",
            field=models.BooleanField(default=False, verbose_name="حساب وهمي"),
        ),
    ]
