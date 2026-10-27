import django.conf
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(django.conf.settings.AUTH_USER_MODEL),
        ("investments", "0014_platformsettings_deposit_activity"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180, verbose_name="العنوان")),
                ("body_html", models.TextField(verbose_name="محتوى HTML")),
                ("is_read", models.BooleanField(default=False, verbose_name="مقروء")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإرسال")),
                ("read_at", models.DateTimeField(blank=True, null=True, verbose_name="تاريخ القراءة")),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to=django.conf.settings.AUTH_USER_MODEL,
                        verbose_name="المستلم",
                    ),
                ),
                (
                    "sender",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sent_notifications",
                        to=django.conf.settings.AUTH_USER_MODEL,
                        verbose_name="المرسل من الإدارة",
                    ),
                ),
            ],
            options={
                "verbose_name": "إشعار مستخدم",
                "verbose_name_plural": "إشعارات المستخدمين",
                "ordering": ("-created_at", "-pk"),
            },
        ),
        migrations.AddIndex(
            model_name="usernotification",
            index=models.Index(fields=["recipient", "is_read", "created_at"], name="notif_user_read_time_idx"),
        ),
    ]
