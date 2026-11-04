from django.contrib import admin

from .models import PublicGrant


@admin.register(PublicGrant)
class PublicGrantAdmin(admin.ModelAdmin):
    list_display = ("title", "org_name", "status", "deadline", "updated_at")
    list_filter = ("org_slug", "status")
    search_fields = ("title", "grant_public_id")
