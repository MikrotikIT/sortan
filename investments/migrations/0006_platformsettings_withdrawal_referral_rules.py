from django.db import migrations, models


def copy_single_rule(apps, schema_editor):
    PlatformSettings = apps.get_model("investments", "PlatformSettings")
    for settings in PlatformSettings.objects.all():
        settings.withdrawal_referral_rules = (
            f"{settings.withdrawal_referral_after_count}:"
            f"{settings.withdrawal_referral_required_count}"
        )
        settings.save(update_fields=("withdrawal_referral_rules",))


def restore_single_rule(apps, schema_editor):
    PlatformSettings = apps.get_model("investments", "PlatformSettings")
    for settings in PlatformSettings.objects.all():
        first_rule = (settings.withdrawal_referral_rules or "3:2").split(",", 1)[0].strip()
        try:
            after_count, required_count = first_rule.split(":", 1)
            settings.withdrawal_referral_after_count = int(after_count)
            settings.withdrawal_referral_required_count = int(required_count)
        except (ValueError, TypeError):
            settings.withdrawal_referral_after_count = 3
            settings.withdrawal_referral_required_count = 2
        settings.save(update_fields=("withdrawal_referral_after_count", "withdrawal_referral_required_count"))


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0005_platformsettings_withdrawal_referral_after_count_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformsettings",
            name="withdrawal_referral_rules",
            field=models.TextField(
                blank=True,
                default="3:2",
                help_text="اكتب كل مرحلة بصيغة عدد السحوبات:عدد المدعوين، مثال: 3:2, 5:4, 9:6.",
                verbose_name="مراحل السحب وعدد المدعوين المطلوب",
            ),
        ),
        migrations.RunPython(copy_single_rule, restore_single_rule),
        migrations.RemoveField(
            model_name="platformsettings",
            name="withdrawal_referral_after_count",
        ),
        migrations.RemoveField(
            model_name="platformsettings",
            name="withdrawal_referral_required_count",
        ),
    ]
