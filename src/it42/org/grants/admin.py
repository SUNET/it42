from django.contrib import admin

from .models import Grant


@admin.register(Grant)
class GrantAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "deadline", "created_by", "updated_at")
    list_filter = ("status",)
    search_fields = ("title", "public_id")
    readonly_fields = ("public_id",)
