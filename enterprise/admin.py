from django.contrib import admin

from .models import ApiKey, AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "org", "actor", "action", "target_repr")
    list_filter = ("action", "org")
    search_fields = ("actor", "action", "target_repr", "target_id")
    date_hierarchy = "created_at"
    readonly_fields = (
        "org",
        "actor",
        "actor_user",
        "action",
        "target_type",
        "target_id",
        "target_repr",
        "metadata",
        "ip",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "org", "prefix", "is_active", "last_used_at", "created_at")
    list_filter = ("org",)
    search_fields = ("name", "prefix")
    readonly_fields = ("prefix", "hashed_key", "last_used_at", "created_at")
