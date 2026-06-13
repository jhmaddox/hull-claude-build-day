"""Add ``muted_until`` to Monitor (mute/snooze) for Observability v2.

Hand-authored (matching 0002's style) so a builder need not run
``makemigrations``; the integrator's ``makemigrations observability --check
--dry-run`` should report no further pending changes. Nullable -> loop-safe and
no default needed on existing rows.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("observability", "0002_org_scoping_and_monitor"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitor",
            name="muted_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
