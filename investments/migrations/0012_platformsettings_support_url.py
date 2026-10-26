from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0011_platformsettings_online_counter_current_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformsettings",
            name="support_url",
            field=models.URLField(blank=True, default="", max_length=500, verbose_name="رابط الدعم الفني"),
        ),
    ]
