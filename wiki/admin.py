from django.contrib import admin

from .models import Page, PageLink, PageRevision, Space


@admin.register(Space)
class SpaceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "org", "updated_at")
    list_filter = ("org",)
    search_fields = ("name", "slug", "description")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "space", "parent", "org", "updated_at")
    list_filter = ("org", "space")
    search_fields = ("title", "slug", "body")
    raw_id_fields = ("parent", "space", "project", "created_by", "updated_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PageRevision)
class PageRevisionAdmin(admin.ModelAdmin):
    list_display = ("page", "number", "edited_by", "created_at")
    list_filter = ("org",)
    search_fields = ("title", "body")
    raw_id_fields = ("page", "edited_by")
    readonly_fields = ("created_at",)


@admin.register(PageLink)
class PageLinkAdmin(admin.ModelAdmin):
    list_display = ("source", "target", "target_title", "is_resolved", "org")
    list_filter = ("org",)
    search_fields = ("target_title",)
    raw_id_fields = ("source", "target")
