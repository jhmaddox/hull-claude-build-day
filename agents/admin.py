from django.contrib import admin

from .models import AgentRun, Worktree


@admin.register(Worktree)
class WorktreeAdmin(admin.ModelAdmin):
    list_display = ("__str__", "project", "branch", "base_branch", "status", "created_at")
    list_filter = ("status", "project")
    search_fields = ("name", "branch", "base_branch", "path")
    readonly_fields = ("created_at",)


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "project",
        "kind",
        "status",
        "num_turns",
        "cost_usd",
        "created_at",
    )
    list_filter = ("kind", "status", "project")
    search_fields = ("title", "prompt")
    readonly_fields = ("created_at", "started_at", "ended_at", "output")
    raw_id_fields = ("worktree", "pull_request", "incident")
