from django.contrib import admin

from .models import Activity, Board, Comment, Label, Sprint, Ticket


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "org", "project")
    list_filter = ("org",)


@admin.register(Sprint)
class SprintAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "board", "org")
    list_filter = ("org", "status")


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "org")
    list_filter = ("org",)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("key", "title", "type", "status", "priority", "org")
    list_filter = ("org", "type", "status", "priority")
    search_fields = ("key", "title", "description")
    raw_id_fields = ("incident", "pull_request", "agent_run", "assignee", "reporter")


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "display_author", "created_at")


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("ticket", "actor", "verb", "created_at")
