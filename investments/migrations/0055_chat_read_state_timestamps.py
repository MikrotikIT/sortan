from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0054_investment_auto_posting"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmembership",
            name="last_read_at",
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name="وقت آخر قراءة"),
        ),
        migrations.AddField(
            model_name="chatgroupreadstate",
            name="last_read_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
