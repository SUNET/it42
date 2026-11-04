from django.contrib import admin

from .models import (
    AssociateProfessorship,
    Award,
    AwardedGrant,
    BasicEducation,
    CVEntry,
    Document,
    Employment,
    IntellectualProperty,
    OtherMerit,
    PostdocPeriod,
    Profile,
    Publication,
    ResearchEducation,
    ResearchExchange,
    ResearchInterruption,
    Supervision,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "first_name", "last_name", "orcid", "phone")
    search_fields = ("user__sso_subject", "first_name", "last_name", "orcid")


class CVEntryAdmin(admin.ModelAdmin):
    list_display = ("__str__", "profile", "source", "sort_order", "orcid_put_code")
    list_filter = ("source",)
    search_fields = ("profile__user__sso_subject", "profile__last_name")


SECTION_MODELS: tuple[type[CVEntry], ...] = (
    BasicEducation,
    ResearchEducation,
    Employment,
    PostdocPeriod,
    ResearchExchange,
    ResearchInterruption,
    AssociateProfessorship,
    Supervision,
    AwardedGrant,
    Award,
    OtherMerit,
    IntellectualProperty,
    Publication,
)

for model in SECTION_MODELS:
    admin.site.register(model, CVEntryAdmin)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "user", "size", "sha256", "uploaded_at")
    search_fields = ("original_name", "sha256", "user__sso_subject")
