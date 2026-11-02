from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0037_platformsettings_withdrawal_minimum"),
    ]

    operations = [
        migrations.AddField(
            model_name="supportoption",
            name="show_on_auth_pages",
            field=models.BooleanField(
                default=False,
                help_text="يعرض هذا الخيار في صفحتي تسجيل الدخول وإنشاء الحساب عند تفعيله.",
                verbose_name="إظهاره في تسجيل الدخول والتسجيل",
            ),
        ),
    ]
