from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0040_chatdemoreaction"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatgroup",
            name="display_order",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="ترتيب الظهور"),
        ),
        migrations.AlterModelOptions(
            name="chatgroup",
            options={
                "ordering": ("display_order", "title", "pk"),
                "verbose_name": "مجموعة محادثة",
                "verbose_name_plural": "مجموعات المحادثة",
            },
        ),
    ]
