import django.utils.timezone
from django.db import migrations, models


def backfill_global_usage_totals(apps, schema_editor):
    from django.db.models import Sum

    database = schema_editor.connection.alias
    pool_model = apps.get_model("investments", "AIBotPool")
    settings_model = apps.get_model("investments", "AIChatSettings")
    totals = pool_model.objects.using(database).aggregate(
        generations=Sum("text_generation_count"),
        prompt_tokens=Sum("prompt_token_count"),
        completion_tokens=Sum("completion_token_count"),
        cost=Sum("total_cost_usd"),
        unpriced=Sum("unpriced_generation_count"),
    )
    with schema_editor.connection.cursor() as cursor:
        migration_table = schema_editor.quote_name("django_migrations")
        cursor.execute(
            f"SELECT applied FROM {migration_table} WHERE app = %s AND name = %s",
            ["investments", "0050_ai_usage_stats"],
        )
        tracking_start = cursor.fetchone()
    tracking_start = tracking_start[0] if tracking_start else django.utils.timezone.now()
    settings_model.objects.using(database).get_or_create(pk=1)
    settings_model.objects.using(database).filter(pk=1).update(
        ai_text_generation_count=totals["generations"] or 0,
        ai_prompt_token_count=totals["prompt_tokens"] or 0,
        ai_completion_token_count=totals["completion_tokens"] or 0,
        ai_total_cost_usd=totals["cost"] or 0,
        ai_unpriced_generation_count=totals["unpriced"] or 0,
        usage_period_started_at=tracking_start,
    )


class Migration(migrations.Migration):
    dependencies = [("investments", "0050_ai_usage_stats")]

    operations = [
        migrations.AddField(
            model_name="aichatsettings",
            name="ai_text_generation_count",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="aichatsettings",
            name="ai_prompt_token_count",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="aichatsettings",
            name="ai_completion_token_count",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="aichatsettings",
            name="ai_total_cost_usd",
            field=models.DecimalField(decimal_places=12, default=0, max_digits=24),
        ),
        migrations.AddField(
            model_name="aichatsettings",
            name="ai_unpriced_generation_count",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="aichatsettings",
            name="usage_period_started_at",
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name="بداية فترة الإحصاء"),
        ),
        migrations.RunPython(backfill_global_usage_totals, migrations.RunPython.noop),
    ]
