from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Facility, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    filter_horizontal = ("facilities", "groups", "user_permissions")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Ekos", {"fields": ("role", "facilities")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Ekos", {"fields": ("role", "facilities")}),
    )


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "ttb_registry_number", "timezone")
    search_fields = ("name", "code")
    readonly_fields = ("created_at", "updated_at")
