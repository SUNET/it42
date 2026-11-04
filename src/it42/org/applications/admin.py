from django.contrib import admin

from .models import Application, ApplicationDocument, Question, ReviewNote


class DocumentInline(admin.TabularInline):
    model = ApplicationDocument
    extra = 0


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0


class ReviewNoteInline(admin.TabularInline):
    model = ReviewNote
    extra = 0


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("public_id", "applicant_name", "grant", "status", "seq", "submitted_at")
    list_filter = ("status", "grant")
    search_fields = ("public_id", "applicant_subject", "applicant_name")
    inlines = [DocumentInline, QuestionInline, ReviewNoteInline]
