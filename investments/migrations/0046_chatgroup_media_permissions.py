from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0045_chat_message_voice_video"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatgroup",
            name="allow_voice_messages",
            field=models.BooleanField(default=True, verbose_name="السماح بالرسائل الصوتية"),
        ),
        migrations.AddField(
            model_name="chatgroup",
            name="allow_videos",
            field=models.BooleanField(default=True, verbose_name="السماح بإرسال الفيديو"),
        ),
    ]
