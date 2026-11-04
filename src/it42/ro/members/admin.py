from django.contrib import admin

from .models import Membership


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("email", "research_org", "role", "user", "added_at")
    list_filter = ("research_org", "role")
    search_fields = ("email",)
