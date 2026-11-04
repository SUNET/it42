from django.contrib import admin

from .models import ApplicationCopy, ApplicationDraft, QuestionCopy, StatusChange


class StatusChangeInline(admin.TabularInline):
    model = StatusChange
    extra = 0


class QuestionCopyInline(admin.TabularInline):
    model = QuestionCopy
    extra = 0


@admin.register(ApplicationCopy)
class ApplicationCopyAdmin(admin.ModelAdmin):
    list_display = ("public_id", "user", "org_slug", "grant", "status", "last_seq", "updated_at")
    list_filter = ("org_slug", "status")
    search_fields = ("public_id", "user__sso_subject")
    inlines = [StatusChangeInline, QuestionCopyInline]


@admin.register(ApplicationDraft)
class ApplicationDraftAdmin(admin.ModelAdmin):
    list_display = ("user", "grant", "created_at", "updated_at")
    search_fields = ("user__sso_subject",)
