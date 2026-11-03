import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0046_chatgroup_media_permissions"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIChatSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=False, verbose_name="تفعيل نظام البوتات")),
                ("run_mode", models.CharField(choices=[("presence", "عند وجود شخص في المجموعة"), ("always", "تشغيل يدوي مستمر")], default="presence", max_length=12, verbose_name="شرط التشغيل")),
                ("active_time_only", models.BooleanField(default=True, help_text="عند إيقاف النظام أو غياب الأشخاص، يتوقف عدّاد العمر. أزل التحديد ليُحتسب الوقت حتى أثناء التوقف.", verbose_name="احتساب عمر البوت أثناء التشغيل فقط")),
                ("encrypted_openrouter_api_key", models.TextField(blank=True, verbose_name="مفتاح OpenRouter المشفر")),
                ("selected_model", models.CharField(blank=True, max_length=200, verbose_name="الموديل الافتراضي")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "إعدادات بوتات المحادثة", "verbose_name_plural": "إعدادات بوتات المحادثة"},
        ),
        migrations.CreateModel(
            name="AIBotTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, verbose_name="اسم الشخصية")),
                ("role", models.CharField(choices=[("asker", "يسأل بوتاً آخر"), ("bot_responder", "يرد على بوت محدد"), ("human_responder", "يرد على الأشخاص")], max_length=20, verbose_name="وظيفة البوت")),
                ("model_id", models.CharField(max_length=200, verbose_name="موديل OpenRouter")),
                ("system_prompt", models.TextField(max_length=4000, verbose_name="تعليمات الشخصية")),
                ("wait_min_seconds", models.PositiveSmallIntegerField(default=1, verbose_name="أقل انتظار بين الرسائل (ثانية)")),
                ("wait_max_seconds", models.PositiveSmallIntegerField(default=5, verbose_name="أعلى انتظار بين الرسائل (ثانية)")),
                ("lifetime_minutes", models.PositiveSmallIntegerField(default=10, verbose_name="عمر البوت (دقيقة)")),
                ("is_active", models.BooleanField(default=True, verbose_name="متاح للاستخدام")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("name", "pk"), "verbose_name": "قالب شخصية بوت", "verbose_name_plural": "قوالب شخصيات البوتات"},
        ),
        migrations.CreateModel(
            name="AIBotPool",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("desired_count", models.PositiveSmallIntegerField(default=1, verbose_name="عدد البوتات المطلوبة")),
                ("replacement_min_seconds", models.PositiveSmallIntegerField(default=5, verbose_name="أقل انتظار قبل البديل (ثانية)")),
                ("replacement_max_seconds", models.PositiveSmallIntegerField(default=60, verbose_name="أعلى انتظار قبل البديل (ثانية)")),
                ("next_replacement_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_ai_bot_pools", to=settings.AUTH_USER_MODEL)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ai_bot_pools", to="investments.chatgroup")),
                ("template", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pools", to="investments.aibottemplate")),
            ],
            options={"ordering": ("group__title", "template__name", "pk"), "verbose_name": "مجموعة تشغيل بوتات", "verbose_name_plural": "مجموعات تشغيل البوتات"},
        ),
        migrations.CreateModel(
            name="ChatGroupPresence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("connection_id", models.UUIDField(default=uuid.uuid4)),
                ("last_seen_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="live_presences", to="investments.chatgroup")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chat_live_presences", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="is_ai",
            field=models.BooleanField(default=False, verbose_name="حساب ذكاء اصطناعي"),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="bot_pool",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="accounts", to="investments.aibotpool"),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_role",
            field=models.CharField(blank=True, choices=[("asker", "يسأل بوتاً آخر"), ("bot_responder", "يرد على بوت محدد"), ("human_responder", "يرد على الأشخاص")], max_length=20, verbose_name="وظيفة البوت"),
        ),
        migrations.AddField(model_name="chatdemoaccount", name="ai_model_id", field=models.CharField(blank=True, max_length=200, verbose_name="موديل البوت")),
        migrations.AddField(model_name="chatdemoaccount", name="ai_system_prompt", field=models.TextField(blank=True, max_length=4000, verbose_name="تعليمات البوت")),
        migrations.AddField(model_name="chatdemoaccount", name="ai_wait_min_seconds", field=models.PositiveSmallIntegerField(default=1)),
        migrations.AddField(model_name="chatdemoaccount", name="ai_wait_max_seconds", field=models.PositiveSmallIntegerField(default=5)),
        migrations.AddField(model_name="chatdemoaccount", name="ai_lifetime_seconds", field=models.PositiveIntegerField(default=600)),
        migrations.AddField(model_name="chatdemoaccount", name="ai_elapsed_active_seconds", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_state",
            field=models.CharField(choices=[("ACTIVE", "نشط"), ("PAUSED", "متوقف"), ("DEAD", "انتهى عمره")], default="ACTIVE", max_length=8, verbose_name="حالة البوت"),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_partner",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ai_partnered_accounts", to="investments.chatdemoaccount"),
        ),
        migrations.AddField(model_name="chatdemoaccount", name="ai_last_active_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="chatdemoaccount", name="ai_next_action_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="chatdemoaccount", name="ai_wait_remaining_seconds", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="chatdemoaccount", name="ai_dead_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(
            model_name="chatmessage",
            name="demo_sender_is_ai",
            field=models.BooleanField(default=False, verbose_name="رسالة مرسلة بواسطة بوت ذكاء اصطناعي"),
        ),
        migrations.AddConstraint(
            model_name="aibotpool",
            constraint=models.UniqueConstraint(fields=("group", "template"), name="ai_pool_group_template_uniq"),
        ),
        migrations.AddConstraint(
            model_name="chatgrouppresence",
            constraint=models.UniqueConstraint(fields=("group", "user", "connection_id"), name="chat_presence_conn_uniq"),
        ),
        migrations.AddIndex(
            model_name="chatgrouppresence",
            index=models.Index(fields=["group", "last_seen_at"], name="chat_presence_group_seen_idx"),
        ),
    ]
