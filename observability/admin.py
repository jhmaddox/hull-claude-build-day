from django.contrib import admin

from .models import Incident, LogLine, MetricPoint


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "title",
        "project",
        "severity",
        "status",
        "occurrences",
        "created_at",
    )
    list_filter = ("status", "severity", "project")
    search_fields = ("title", "error_type", "error_message", "signature")
    readonly_fields = ("signature", "created_at")


@admin.register(LogLine)
class LogLineAdmin(admin.ModelAdmin):
    list_display = ("ts", "deployment", "level", "method", "path", "status_code")
    list_filter = ("level",)
    search_fields = ("message", "path")


@admin.register(MetricPoint)
class MetricPointAdmin(admin.ModelAdmin):
    list_display = ("ts", "deployment", "name", "value")
    list_filter = ("name",)
