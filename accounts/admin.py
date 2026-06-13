from django.contrib import admin

from .models import Invitation, Membership, Org


@admin.register(Org)
class OrgAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    search_fields = ("name", "slug")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "org", "role", "created_at")
    list_filter = ("role",)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "org", "role", "accepted_at", "created_at")
