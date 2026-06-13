"""Additive multitenancy + Monitor model for Observability v2.

Adds a nullable ``org`` FK to LogLine / MetricPoint / Incident (loop-safe) and
introduces the threshold ``Monitor`` model. Hand-authored so a builder does not
have to run makemigrations; the integrator's ``makemigrations --check`` should
report no further pending changes.
"""

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("deploys", "0001_initial"),
        ("observability", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="logline",
            name="org",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="accounts.org",
            ),
        ),
        migrations.AddField(
            model_name="metricpoint",
            name="org",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="accounts.org",
            ),
        ),
        migrations.AddField(
            model_name="incident",
            name="org",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="accounts.org",
            ),
        ),
        migrations.CreateModel(
            name="Monitor",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(blank=True, max_length=200)),
                (
                    "metric",
                    models.CharField(
                        choices=[
                            ("error_rate", "Error rate (%)"),
                            ("p50", "Latency p50 (ms)"),
                            ("p95", "Latency p95 (ms)"),
                            ("p99", "Latency p99 (ms)"),
                            ("req_rate", "Request rate (req/min)"),
                            ("throughput", "Throughput (total requests)"),
                        ],
                        default="error_rate",
                        max_length=20,
                    ),
                ),
                (
                    "comparator",
                    models.CharField(
                        choices=[
                            ("gt", "> greater than"),
                            ("gte", ">= greater or equal"),
                            ("lt", "< less than"),
                            ("lte", "<= less or equal"),
                        ],
                        default="gt",
                        max_length=4,
                    ),
                ),
                ("threshold", models.FloatField(default=0.0)),
                ("window_minutes", models.IntegerField(default=5)),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("sev1", "SEV1 — Critical"),
                            ("sev2", "SEV2 — Major"),
                            ("sev3", "SEV3 — Minor"),
                        ],
                        default="sev2",
                        max_length=10,
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                (
                    "org",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="accounts.org",
                    ),
                ),
                (
                    "deployment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="monitors",
                        to="deploys.deployment",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
