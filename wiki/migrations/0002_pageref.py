import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("projects", "0002_project_org_alter_project_slug_project_uniq_org_slug"),
        ("vcs", "0002_pullrequest_org"),
        ("observability", "0001_initial"),
        ("wiki", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PageRef",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("note", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("incident", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="observability.incident")),
                ("org", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.org")),
                ("page", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="refs", to="wiki.page")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="projects.project")),
                ("pull_request", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="vcs.pullrequest")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="pageref",
            index=models.Index(fields=["org", "page"], name="wiki_pagere_org_id_2d8a9e_idx"),
        ),
    ]
