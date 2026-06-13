from django.contrib import admin

from .models import Deployment, Domain, EnvVar, Environment


@admin.register(Environment)
class EnvironmentAdmin(admin.ModelAdmin):
    list_display = ("__str__", "project", "kind", "runtime", "branch", "port", "auto_deploy", "org")
    list_filter = ("kind", "runtime", "auto_deploy")
    search_fields = ("name", "project__name", "project__slug")
    raw_id_fields = ("project", "worktree", "org")


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
        "org",
    )
    list_filter = ("status", "health")
    search_fields = ("commit_sha", "environment__name", "environment__project__name")
    raw_id_fields = ("environment", "org")
    readonly_fields = ("created_at", "live_at", "stopped_at")


@admin.register(EnvVar)
class EnvVarAdmin(admin.ModelAdmin):
    list_display = ("key", "environment", "is_secret", "org")
    list_filter = ("is_secret",)
    search_fields = ("key", "environment__name")
    raw_id_fields = ("environment", "org")


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("hostname", "environment", "status", "verified_at", "org")
    list_filter = ("status",)
    search_fields = ("hostname", "environment__name")
    raw_id_fields = ("environment", "org")
