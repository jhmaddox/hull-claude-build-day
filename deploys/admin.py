from django.contrib import admin

from .models import Deployment, Environment


@admin.register(Environment)
class EnvironmentAdmin(admin.ModelAdmin):
    list_display = ("__str__", "project", "kind", "branch", "port", "auto_deploy")
    list_filter = ("kind", "auto_deploy")
    search_fields = ("name", "project__name", "project__slug")
    raw_id_fields = ("project", "worktree")


@admin.register(Deployment)
class DeploymentAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "environment",
        "status",
        "health",
        "port",
        "pid",
        "commit_sha",
        "created_at",
    )
    list_filter = ("status", "health")
    search_fields = ("commit_sha", "environment__name", "environment__project__name")
    raw_id_fields = ("environment",)
    readonly_fields = ("created_at", "live_at", "stopped_at")
