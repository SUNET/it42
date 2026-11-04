from django.contrib import admin

from .models import (
    Assessment,
    Assignment,
    Declaration,
    FinalStatement,
    Meeting,
    Panel,
    PanelMember,
    PanelTask,
    ReviewerProfile,
)


class PanelMemberInline(admin.TabularInline):
    model = PanelMember
    extra = 0


class PanelTaskInline(admin.TabularInline):
    model = PanelTask
    extra = 0


class MeetingInline(admin.TabularInline):
    model = Meeting
    extra = 0


@admin.register(Panel)
class PanelAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    search_fields = ("name",)
    inlines = [PanelMemberInline, PanelTaskInline, MeetingInline]


@admin.register(PanelMember)
class PanelMemberAdmin(admin.ModelAdmin):
    list_display = ("email", "panel", "role", "user")
    list_filter = ("role",)
    search_fields = ("email",)


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("member", "application", "assigned_at")


@admin.register(Declaration)
class DeclarationAdmin(admin.ModelAdmin):
    list_display = ("member", "application", "in_conflict", "competence", "updated_at")


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ("member", "application", "preliminary_grade", "updated_at")


@admin.register(FinalStatement)
class FinalStatementAdmin(admin.ModelAdmin):
    list_display = ("panel", "application", "author", "final_grade", "updated_at")


@admin.register(ReviewerProfile)
class ReviewerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "passport_name", "updated_at")
