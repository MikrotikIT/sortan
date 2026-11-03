from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0049_ai_persona_pacing")]

    operations = [
        migrations.AddField(
            model_name="aibotpool",
            name="text_generation_count",
            field=models.PositiveBigIntegerField(default=0, verbose_name="عدد توليدات النص"),
        ),
        migrations.AddField(
            model_name="aibotpool",
            name="prompt_token_count",
            field=models.PositiveBigIntegerField(default=0, verbose_name="رموز الإدخال"),
        ),
        migrations.AddField(
            model_name="aibotpool",
            name="completion_token_count",
            field=models.PositiveBigIntegerField(default=0, verbose_name="رموز الإخراج"),
        ),
        migrations.AddField(
            model_name="aibotpool",
            name="total_cost_usd",
            field=models.DecimalField(decimal_places=12, default=0, max_digits=24, verbose_name="التكلفة بالدولار"),
        ),
        migrations.AddField(
            model_name="aibotpool",
            name="unpriced_generation_count",
            field=models.PositiveBigIntegerField(default=0, verbose_name="توليدات بلا تكلفة موثقة"),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_text_generation_count",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_prompt_token_count",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_completion_token_count",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_total_cost_usd",
            field=models.DecimalField(decimal_places=12, default=0, max_digits=24),
        ),
        migrations.AddField(
            model_name="chatdemoaccount",
            name="ai_unpriced_generation_count",
            field=models.PositiveBigIntegerField(default=0),
        ),
    ]
