from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0038_supportoption_show_on_auth_pages"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatDemoAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(max_length=120, verbose_name="الاسم والكنية")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخر تعديل")),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="demo_accounts", to="investments.chatgroup")),
            ],
            options={
                "verbose_name": "حساب محادثة تجريبي",
                "verbose_name_plural": "حسابات المحادثة التجريبية",
                "ordering": ("display_name", "pk"),
                "constraints": [
                    models.UniqueConstraint(fields=("group", "display_name"), name="unique_chat_demo_account_name_per_group"),
                ],
            },
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="demo_account",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="messages", to="investments.chatdemoaccount", verbose_name="هوية الحساب التجريبي"),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="demo_sender_name",
            field=models.CharField(blank=True, max_length=120, verbose_name="اسم المرسل التجريبي وقت الإرسال"),
        ),
    ]
