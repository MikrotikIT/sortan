from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0039_chatdemoaccount_and_message_identity"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatDemoReaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("like", "إعجاب"), ("heart", "قلب"), ("fire", "نار"), ("clap", "تصفيق"), ("dislike", "عدم إعجاب")], max_length=8, verbose_name="نوع التفاعل")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="وقت التفاعل")),
                ("demo_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reactions", to="investments.chatdemoaccount")),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="demo_account_reactions", to="investments.chatmessage")),
            ],
            options={
                "verbose_name": "تفاعل حساب محادثة تجريبي",
                "verbose_name_plural": "تفاعلات حسابات المحادثة التجريبية",
            },
        ),
        migrations.AddConstraint(
            model_name="chatdemoreaction",
            constraint=models.UniqueConstraint(fields=("message", "demo_account"), name="unique_chat_demo_reaction"),
        ),
        migrations.AddIndex(
            model_name="chatdemoreaction",
            index=models.Index(fields=["message", "kind"], name="chat_demo_rxn_msg_kind_idx"),
        ),
    ]
