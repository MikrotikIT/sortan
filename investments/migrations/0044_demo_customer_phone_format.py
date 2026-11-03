import investments.models
from django.db import migrations, models


def replace_demo_customer_numbers(apps, schema_editor):
    ChatDemoAccount = apps.get_model("investments", "ChatDemoAccount")
    used_numbers = set()
    for account in ChatDemoAccount.objects.order_by("pk").iterator():
        customer_number = investments.models.make_demo_customer_number(account.demo_country_code)
        while customer_number in used_numbers:
            customer_number = investments.models.make_demo_customer_number(account.demo_country_code)
        used_numbers.add(customer_number)
        account.demo_customer_number = customer_number
        account.save(update_fields=("demo_customer_number",))


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0043_demo_withdrawal_receipts"),
    ]

    operations = [
        migrations.RunPython(replace_demo_customer_numbers, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="chatdemoaccount",
            name="demo_customer_number",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                max_length=20,
                unique=True,
                verbose_name="رقم العميل",
            ),
        ),
    ]
