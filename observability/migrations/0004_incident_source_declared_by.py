"""Add ``source`` + ``declared_by`` to Incident (manual 'Declare incident').

Hand-authored (matching 0002/0003's style) so a builder need not run
``makemigrations``; the integrator's ``makemigrations observability --check
--dry-run`` should report no further pending changes. Both fields are additive
and nullable/defaulted -> loop-safe; the autonomous detector keeps writing
``source='auto'`` (the default) with ``declared_by`` left blank.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("observability", "0003_monitor_muted_until"),
    ]

    operations = [
        migrations.AddField(
            model_name="incident",
            name="source",
            field=models.CharField(
                choices=[("auto", "Auto-detected"), ("manual", "Manually declared")],
                default="auto",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="incident",
            name="declared_by",
            field=models.CharField(blank=True, max_length=150),
        ),
    ]
