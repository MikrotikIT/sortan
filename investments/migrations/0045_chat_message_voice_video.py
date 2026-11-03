import django.core.validators
import investments.models
import investments.storage
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0044_demo_customer_phone_format"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="voice_message",
            field=models.FileField(
                blank=True,
                storage=investments.storage.PrivateApplicationStorage(),
                upload_to=investments.models.chat_message_upload_path,
                validators=[django.core.validators.FileExtensionValidator(("webm", "ogg", "m4a", "mp3", "wav", "aac"))],
                verbose_name="رسالة صوتية",
            ),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="video",
            field=models.FileField(
                blank=True,
                storage=investments.storage.PrivateApplicationStorage(),
                upload_to=investments.models.chat_message_upload_path,
                validators=[django.core.validators.FileExtensionValidator(("mp4", "m4v", "mov", "webm", "mkv", "3gp"))],
                verbose_name="فيديو المحادثة",
            ),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="video_status",
            field=models.CharField(
                blank=True,
                choices=[("queued", "بانتظار التجهيز"), ("processing", "جارٍ التجهيز"), ("ready", "جاهز"), ("failed", "تعذر التجهيز")],
                default="",
                max_length=12,
                verbose_name="حالة تجهيز الفيديو",
            ),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="video_hls_dir",
            field=models.CharField(blank=True, editable=False, max_length=255),
        ),
    ]
