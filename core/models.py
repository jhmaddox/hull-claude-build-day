from django.db import models
from django.utils import timezone


class Event(models.Model):
    """A platform-wide activity feed entry — the global timeline of everything
    Helm and its agents do. Powers the dashboard live feed."""

    class Level(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="events",
    )
    ts = models.DateTimeField(default=timezone.now, db_index=True)
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    icon = models.CharField(max_length=40, default="dot")
    actor = models.CharField(max_length=120, default="helm")
    verb = models.CharField(max_length=300)
    url = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-ts"]

    def __str__(self):
        return f"{self.actor} {self.verb}"

    @classmethod
    def log(cls, verb, *, project=None, actor="helm", level="info", icon="dot", url=""):
        return cls.objects.create(
            project=project, actor=actor, verb=verb, level=level, icon=icon, url=url
        )
