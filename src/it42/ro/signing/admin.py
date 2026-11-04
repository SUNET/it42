from django.contrib import admin

from .models import RequestDocument, SignatureRequest


class RequestDocumentInline(admin.TabularInline):
    model = RequestDocument
    extra = 0


@admin.register(SignatureRequest)
class SignatureRequestAdmin(admin.ModelAdmin):
    list_display = (
        "applicant_name",
        "grant_title",
        "org_slug",
        "research_org",
        "status",
        "deadline",
    )
    list_filter = ("research_org", "org_slug", "status")
    inlines = [RequestDocumentInline]
