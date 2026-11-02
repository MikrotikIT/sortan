from decimal import Decimal

from django.db import migrations, models
from django.db.models import F, Sum, Value
from django.db.models.functions import Greatest


def credit_existing_demo_profits(apps, schema_editor):
    DemoInvestment = apps.get_model("investments", "DemoInvestment")
    User = apps.get_model("investments", "User")
    database = schema_editor.connection.alias

    totals = (
        DemoInvestment.objects.using(database)
        .filter(user__is_fake_account=True)
        .values("user_id")
        .annotate(total=Sum("realized_profit"))
    )
    for entry in totals.iterator():
        User.objects.using(database).filter(pk=entry["user_id"]).update(
            earnings_balance=F("earnings_balance") + entry["total"],
            total_earned=F("total_earned") + entry["total"],
        )

    DemoInvestment.objects.using(database).filter(user__is_fake_account=True).update(profit_credited=True)


def reverse_demo_profit_credit(apps, schema_editor):
    DemoInvestment = apps.get_model("investments", "DemoInvestment")
    User = apps.get_model("investments", "User")
    database = schema_editor.connection.alias

    totals = (
        DemoInvestment.objects.using(database)
        .filter(profit_credited=True)
        .values("user_id")
        .annotate(total=Sum("realized_profit"))
    )
    for entry in totals.iterator():
        adjustment = entry["total"]
        User.objects.using(database).filter(pk=entry["user_id"]).update(
            earnings_balance=Greatest(F("earnings_balance") - adjustment, Value(Decimal("0.00"))),
            total_earned=Greatest(F("total_earned") - adjustment, Value(Decimal("0.00"))),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0034_demoinvestment"),
    ]

    operations = [
        migrations.AddField(
            model_name="demoinvestment",
            name="profit_credited",
            field=models.BooleanField(default=False, editable=False, verbose_name="أضيف إلى رصيد الأرباح"),
        ),
        migrations.RunPython(credit_existing_demo_profits, reverse_demo_profit_credit),
    ]
