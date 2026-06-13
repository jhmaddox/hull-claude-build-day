from django.contrib import admin

from .models import PullRequest


@admin.register(PullRequest)
class PullRequestAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "org",
        "project",
        "status",
        "ci_status",
        "additions",
        "deletions",
        "files_changed",
        "author",
        "created_at",
    )
    list_filter = ("status", "ci_status", "org", "project")
    search_fields = ("title", "description", "head_branch", "base_branch")
    readonly_fields = ("created_at", "merged_at", "diff")
    raw_id_fields = ("worktree",)
