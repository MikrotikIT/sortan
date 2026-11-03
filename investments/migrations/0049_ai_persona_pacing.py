from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


PERSONA_SPEEDS = {
    "سائل كواليس السينما": ("5.0", "2.0"),
    "مكتشف الحكايات السينمائية": ("4.5", "1.8"),
    "عين المشاهد": ("4.0", "1.6"),
    "محاور كواليس الإنتاج": ("5.0", "2.5"),
    "ناقد سينمائي هادئ": ("4.5", "2.0"),
    "قارئ الصورة والصوت": ("5.5", "2.2"),
    "مرشد مجتمع Kodi TV": ("6.0", "2.5"),
    "مساعد العضو الجديد": ("5.5", "2.0"),
    "مجيب أسئلة صناعة الأفلام": ("5.0", "2.2"),
}


def set_starter_persona_speeds(apps, schema_editor):
    template_model = apps.get_model("investments", "AIBotTemplate")
    for name, (reading_speed, writing_speed) in PERSONA_SPEEDS.items():
        template_model.objects.filter(name=name).update(
            reading_words_per_second=Decimal(reading_speed),
            writing_words_per_second=Decimal(writing_speed),
        )


class Migration(migrations.Migration):
    dependencies = [("investments", "0048_seed_ai_personality_templates")]

    operations = [
        migrations.AddField(
            model_name="aibottemplate",
            name="reading_words_per_second",
            field=models.DecimalField(decimal_places=1, default=4.0, max_digits=4, verbose_name="سرعة القراءة (كلمة/ثانية)"),
        ),
        migrations.AddField(
            model_name="aibottemplate",
            name="writing_words_per_second",
            field=models.DecimalField(decimal_places=1, default=1.5, max_digits=4, verbose_name="سرعة الكتابة (كلمة/ثانية)"),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_reading_words_per_second",
            field=models.DecimalField(decimal_places=1, default=4.0, max_digits=4),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_writing_words_per_second",
            field=models.DecimalField(decimal_places=1, default=1.5, max_digits=4),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_pending_text",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_pending_reply_to",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="pending_ai_bot_replies",
                to="investments.chatmessage",
            ),
        ),
        migrations.RunPython(set_starter_persona_speeds, migrations.RunPython.noop),
    ]
