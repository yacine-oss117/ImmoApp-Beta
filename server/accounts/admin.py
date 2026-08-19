from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Agency, RegistrationRequest, UserInvite

User = get_user_model()


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "display_name",
        "agency_code",
        "is_active",
        "max_users",
        "max_managers",
        "max_agents_per_manager",
    )
    list_filter = ("is_active",)
    search_fields = ("display_name", "legal_name", "agency_code")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Agency & Role",
            {
                "fields": (
                    "role",
                    "agency",
                    "manager",
                    "access_scope",
                    "is_owner",
                    "can_hard_delete",
                )
            },
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "Agency & Role",
            {
                "fields": (
                    "role",
                    "agency",
                    "manager",
                    "access_scope",
                    "is_owner",
                    "can_hard_delete",
                )
            },
        ),
    )
    list_display = ("username", "email", "role", "agency", "manager", "is_active", "is_superuser")
    list_filter = ("role", "is_active", "is_superuser", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")


@admin.register(RegistrationRequest)
class RegistrationRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "owner_email", "status", "created_at", "reviewed_at")
    list_filter = ("status",)
    search_fields = ("owner_email", "agency_name", "legal_name")


@admin.register(UserInvite)
class UserInviteAdmin(admin.ModelAdmin):
    list_display = ("id", "agency", "invite_email", "role", "status", "created_at", "expires_at")
    list_filter = ("status", "role")
    search_fields = ("invite_email", "invite_name")
