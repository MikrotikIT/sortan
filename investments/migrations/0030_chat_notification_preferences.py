from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0029_pushdevice"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatgroup",
            name="notifications_muted_by_default",
            field=models.BooleanField(
                default=False,
                help_text="يطبق على العضويات الجديدة فقط، ويمكن لكل عضو تغيير الكتم لاحقاً.",
                verbose_name="كتم إشعارات المجموعة للأعضاء الجدد تلقائياً",
            ),
        ),
        migrations.AddField(
            model_name="chatmembership",
            name="notifications_muted",
            field=models.BooleanField(default=False, verbose_name="كتم إشعارات هذه المجموعة"),
        ),
    ]
