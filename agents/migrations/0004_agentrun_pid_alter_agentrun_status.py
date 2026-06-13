from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0003_agentrun_org_worktree_org"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="pid",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="agentrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("done", "Done"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                ],
                default="queued",
                max_length=20,
            ),
        ),
    ]
