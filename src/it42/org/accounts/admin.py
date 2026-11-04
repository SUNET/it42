from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class SubjectUserAdmin(UserAdmin):
    list_display = ("username", "sso_subject", "email", "first_name", "last_name", "is_staff")
    search_fields = ("username", "sso_subject", "email")
    fieldsets = (*(UserAdmin.fieldsets or ()), ("SSO", {"fields": ("sso_subject",)}))
