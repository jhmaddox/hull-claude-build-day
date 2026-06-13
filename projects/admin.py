from django.contrib import admin

from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "framework", "status", "default_branch", "created_at")
    list_filter = ("status", "framework")
    search_fields = ("name", "slug", "repo_url")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")
