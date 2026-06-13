from django.contrib import admin

from .models import WorkflowRun


@admin.register(WorkflowRun)
class WorkflowRunAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "status",
        "backend",
        "project",
        "ref_type",
        "ref_id",
        "created_at",
        "ended_at",
    )
    list_filter = ("status", "backend", "ref_type")
    search_fields = ("name", "detail")
    readonly_fields = ("created_at", "ended_at")
