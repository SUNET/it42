"""The ordered registry of CV sections; views, templates and the importer all use it."""

from dataclasses import dataclass

from . import cv_forms
from .cv_forms import EntryForm
from .models import (
    AssociateProfessorship,
    Award,
    AwardedGrant,
    BasicEducation,
    CVEntry,
    Employment,
    IntellectualProperty,
    OtherMerit,
    PostdocPeriod,
    Publication,
    ResearchEducation,
    ResearchExchange,
    ResearchInterruption,
    Supervision,
)


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    short: str  # label of the Academic CV table's section chip
    singular: str
    model: type[CVEntry]
    form: type[EntryForm]
    orcid_source: str = ""  # which ORCID activities feed this section ("" = none)


_SECTIONS = (
    Section("basic_education", "Basic education", "Education", "degree", BasicEducation,
            cv_forms.BasicEducationForm, "education"),
    Section("research_education", "Research education", "Doctorate", "research degree",
            ResearchEducation, cv_forms.ResearchEducationForm, "education (doctoral)"),
    Section("employment", "Employments", "Employment", "employment", Employment,
            cv_forms.EmploymentForm, "employment"),
    Section("postdoc", "Postdoctoral periods", "Postdoc", "postdoctoral period",
            PostdocPeriod, cv_forms.PostdocPeriodForm),
    Section("exchange", "Research exchanges", "Exchanges", "research exchange",
            ResearchExchange, cv_forms.ResearchExchangeForm, "invited positions"),
    Section("interruption", "Interruptions in research", "Interruptions", "interruption",
            ResearchInterruption, cv_forms.ResearchInterruptionForm),
    Section("docent", "Associate professorships (docent)", "Docent", "associate professorship",
            AssociateProfessorship, cv_forms.AssociateProfessorshipForm, "qualifications"),
    Section("supervision", "Supervision", "Supervision", "supervision", Supervision,
            cv_forms.SupervisionForm),
    Section("grant", "Awarded grants", "Grants", "grant", AwardedGrant,
            cv_forms.AwardedGrantForm, "fundings"),
    Section("award", "Awards and distinctions", "Awards", "award", Award, cv_forms.AwardForm,
            "distinctions"),
    Section("merit", "Other merits", "Other merits", "merit", OtherMerit,
            cv_forms.OtherMeritForm, "memberships, services, qualifications, peer reviews"),
    Section("ip", "Intellectual property", "Intellectual property",
            "intellectual property right", IntellectualProperty,
            cv_forms.IntellectualPropertyForm, "works (patents)"),
    Section("publication", "Publications", "Publications", "publication", Publication,
            cv_forms.PublicationForm, "works"),
)  # fmt: skip

SECTIONS: dict[str, Section] = {section.key: section for section in _SECTIONS}
