"""Researcher profile: personal details, the CV sections and PDFs.

Every CV section is a ``CVEntry`` subclass. Entries typed by hand have ``source=manual``
and no ORCID put-code; entries created by an ORCID import carry the put-code of the ORCID
item they came from so a re-import can update them in place. Once a researcher edits an
imported entry it becomes ``orcid_edited`` and is never touched by an import again.
"""

import uuid
from typing import Any

from django.conf import settings
from django.db import models

from .fields import PartialDateField, partial_date_display
from .orcid import validate_orcid


class Gender(models.TextChoices):
    WOMAN = "woman", "Woman"
    MAN = "man", "Man"
    NON_BINARY = "non_binary", "Non-binary"
    PREFER_NOT_TO_SAY = "prefer_not_to_say", "Prefer not to say"


class AcademicTitle(models.TextChoices):
    PROFESSOR = "professor", "Professor"
    ASSOCIATE_PROFESSOR = "associate_professor", "Associate professor (docent)"
    SENIOR_LECTURER = "senior_lecturer", "Senior lecturer"
    LECTURER = "lecturer", "Lecturer"
    POSTDOC = "postdoc", "Postdoctoral researcher"
    RESEARCHER = "researcher", "Researcher"
    PHD_STUDENT = "phd_student", "Doctoral student"
    OTHER = "other", "Other"


class Profile(models.Model):
    """One per user; "My details" in the reference CV plus ORCID-only person data."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    user_id: int
    first_name = models.CharField(max_length=128, blank=True)
    last_name = models.CharField(max_length=128, blank=True)
    orcid = models.CharField(
        "ORCID iD",
        max_length=19,
        blank=True,
        validators=[validate_orcid],
        help_text="For example 0000-0002-1825-0097.",
    )
    secondary_email = models.EmailField(blank=True)
    phone = models.CharField("Mobile phone", max_length=50, blank=True)
    telephone = models.CharField(max_length=50, blank=True)
    homepage = models.URLField(max_length=2048, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, choices=Gender.choices, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    country_of_activity = models.CharField(max_length=100, blank=True)
    academic_title = models.CharField(max_length=30, choices=AcademicTitle.choices, blank=True)
    other_academic_title = models.CharField(max_length=128, blank=True)
    address = models.TextField(blank=True)
    bio = models.TextField("Biography", blank=True)
    research_areas = models.JSONField(default=list, blank=True)  # list[str], shown as tags
    orcid_person = models.JSONField(default=dict, blank=True)
    orcid_imported_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.full_name or str(self.user)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Source(models.TextChoices):
    MANUAL = "manual", "Entered by hand"
    ORCID = "orcid", "From ORCID"
    ORCID_EDITED = "orcid_edited", "From ORCID, edited"


def _range(start: str, end: str, *, present: bool = False) -> str:
    """Date range for the details line: "2012-03 to 2015", "2012 to present" or ""."""
    left = partial_date_display(start)
    right = "present" if present else partial_date_display(end)
    if left and right:
        return f"{left} to {right}"
    return left or right


def _join(*parts: Any) -> str:
    return ", ".join(str(p) for p in parts if p not in ("", None))


def _year(value: int | None) -> str:
    return str(value) if value else ""


class CVEntry(models.Model):
    """Base for every CV section; see the module docstring for the source rules."""

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    profile_id: int
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    orcid_put_code = models.BigIntegerField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["sort_order", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "orcid_put_code"],
                condition=models.Q(orcid_put_code__isnull=False),
                name="%(app_label)s_%(class)s_put_code",
            )
        ]

    def __str__(self) -> str:
        return self.summary()

    @property
    def is_imported(self) -> bool:
        return self.source != Source.MANUAL

    @property
    def source_label(self) -> str:
        return str(Source(self.source).label)

    def summary(self) -> str:
        """Headline of the list row."""
        raise NotImplementedError

    def details(self) -> str:
        """Second line of the list row (may be empty)."""
        return ""

    def span(self) -> tuple[str, str, bool]:
        """``(start, end, ongoing)`` as partial dates, for the Dates column and sorting."""
        return "", "", False

    def dates(self) -> str:
        """Years for the Academic CV table: "2016 to 2021" (en dash), "2021 to present", "2024"."""
        start, end, ongoing = self.span()
        first, last = start[:4], "present" if ongoing else end[:4]
        if first and last and first != last:
            return f"{first} \N{EN DASH} {last}"
        return first or last

    def sort_date(self) -> str:
        """The partial date the table sorts on: the start, else the end."""
        start, end, ongoing = self.span()
        return start or ("9999" if ongoing else end)


class BasicEducation(CVEntry):
    class Degree(models.TextChoices):
        BACHELOR = "bachelor", "Bachelor's degree"
        MASTER = "master", "Master's degree"
        PROFESSIONAL = "professional", "Professional degree"
        OTHER = "other", "Other"

    university = models.CharField(max_length=256)
    department = models.CharField(max_length=256, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    subject = models.CharField(max_length=256, blank=True)
    degree = models.CharField(max_length=20, choices=Degree.choices, default=Degree.OTHER)
    other_degree = models.CharField(max_length=128, blank=True)
    specialist_training = models.BooleanField(default=False)
    specialist_training_year = models.PositiveIntegerField(null=True, blank=True)
    specialist_training_description = models.CharField(max_length=250, blank=True)

    def span(self) -> tuple[str, str, bool]:
        return _year(self.year), "", False

    def summary(self) -> str:
        degree = self.other_degree if self.degree == self.Degree.OTHER else ""
        return _join(degree or self.Degree(self.degree).label, self.subject)

    def details(self) -> str:
        return _join(self.university, self.department, self.year)


class ResearchEducation(CVEntry):
    class Kind(models.TextChoices):
        LICENTIATE = "licentiate", "Licentiate degree"
        PHD = "phd", "Doctoral degree"
        COMPETENCE = "competence", "Equivalent research competence"

    university = models.CharField(max_length=256)
    department = models.CharField(max_length=256, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PHD)
    subject = models.CharField(max_length=256, blank=True)
    degree_date = PartialDateField()
    thesis_title = models.CharField(max_length=250, blank=True)
    thesis_title_en = models.CharField("Thesis title (English)", max_length=250, blank=True)
    isbn = models.CharField("ISBN", max_length=128, blank=True)
    supervisor_first_name = models.CharField(max_length=128, blank=True)
    supervisor_last_name = models.CharField(max_length=128, blank=True)
    competence_date = PartialDateField()
    competence_description_sv = models.TextField(
        "Competence description (Swedish)", max_length=1000, blank=True
    )
    competence_description_en = models.TextField(
        "Competence description (English)", max_length=1000, blank=True
    )

    def span(self) -> tuple[str, str, bool]:
        return self.degree_date or self.competence_date, "", False

    def summary(self) -> str:
        return _join(self.Kind(self.kind).label, self.subject)

    def details(self) -> str:
        when = partial_date_display(self.degree_date or self.competence_date)
        return _join(self.university, self.department, when, self.thesis_title)


class Position(models.TextChoices):
    PROFESSOR = "professor", "Professor"
    ASSOCIATE_PROFESSOR = "associate_professor", "Associate professor"
    SENIOR_LECTURER = "senior_lecturer", "Senior lecturer"
    LECTURER = "lecturer", "Lecturer"
    POSTDOC = "postdoc", "Postdoctoral researcher"
    RESEARCHER = "researcher", "Researcher"
    PHD_STUDENT = "phd_student", "Doctoral student"
    OTHER = "other", "Other"


class Employment(CVEntry):
    class Form(models.TextChoices):
        PERMANENT = "permanent", "Permanent"
        FIXED_TERM = "fixed_term", "Fixed term"
        HOURLY = "hourly", "Hourly"
        OTHER = "other", "Other"

    employer = models.CharField(max_length=256)
    department = models.CharField(max_length=256, blank=True)
    position = models.CharField(max_length=30, choices=Position.choices, default=Position.OTHER)
    other_position = models.CharField(max_length=128, blank=True)
    form_of_employment = models.CharField(max_length=20, choices=Form.choices, blank=True)
    is_present = models.BooleanField("Current position", default=False)
    research_share = models.PositiveSmallIntegerField(
        "Share of research (%)", null=True, blank=True
    )
    start_date = PartialDateField()
    end_date = PartialDateField()
    other_information = models.CharField(max_length=256, blank=True)

    def span(self) -> tuple[str, str, bool]:
        return self.start_date, self.end_date, self.is_present

    def summary(self) -> str:
        position = self.other_position if self.position == Position.OTHER else ""
        return _join(position or Position(self.position).label, self.employer)

    def details(self) -> str:
        return _join(
            self.department, _range(self.start_date, self.end_date, present=self.is_present)
        )


class PostdocPeriod(CVEntry):
    host = models.CharField("Host organisation", max_length=256)
    department = models.CharField(max_length=256, blank=True)
    subject = models.CharField(max_length=256, blank=True)
    start_date = PartialDateField()
    end_date = PartialDateField()
    months = models.PositiveSmallIntegerField(null=True, blank=True)

    def span(self) -> tuple[str, str, bool]:
        return self.start_date, self.end_date, False

    def summary(self) -> str:
        return _join(self.host, self.subject)

    def details(self) -> str:
        months = f"{self.months} months" if self.months else ""
        return _join(self.department, _range(self.start_date, self.end_date), months)


class ResearchExchange(CVEntry):
    class Kind(models.TextChoices):
        RESEARCH_VISIT = "research_visit", "Research visit"
        SABBATICAL = "sabbatical", "Sabbatical"
        GUEST_RESEARCHER = "guest_researcher", "Guest researcher"
        INVITED_POSITION = "invited_position", "Invited position"
        OTHER = "other", "Other"

    host = models.CharField("Host organisation", max_length=256)
    department = models.CharField(max_length=256, blank=True)
    subject = models.CharField(max_length=256, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.RESEARCH_VISIT)
    custom_kind = models.CharField("Describe the exchange", max_length=128, blank=True)
    start_date = PartialDateField()
    end_date = PartialDateField()
    months = models.PositiveSmallIntegerField(null=True, blank=True)

    def span(self) -> tuple[str, str, bool]:
        return self.start_date, self.end_date, False

    def summary(self) -> str:
        return _join(self.custom_kind or self.Kind(self.kind).label, self.host)

    def details(self) -> str:
        months = f"{self.months} months" if self.months else ""
        return _join(self.department, self.subject, _range(self.start_date, self.end_date), months)


class ResearchInterruption(CVEntry):
    start_date = PartialDateField()
    end_date = PartialDateField()
    description = models.CharField(max_length=1000, blank=True)

    def span(self) -> tuple[str, str, bool]:
        return self.start_date, self.end_date, False

    def summary(self) -> str:
        return _range(self.start_date, self.end_date) or "Interruption"

    def details(self) -> str:
        return self.description


class AssociateProfessorship(CVEntry):
    university = models.CharField(max_length=256)
    department = models.CharField(max_length=256, blank=True)
    subject = models.CharField(max_length=256, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)

    def span(self) -> tuple[str, str, bool]:
        return _year(self.year), "", False

    def summary(self) -> str:
        return _join(self.subject or "Docent", self.university)

    def details(self) -> str:
        return _join(self.department, self.year)


class Supervision(CVEntry):
    class Kind(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        GROUP = "group", "Group"

    class SupervisedType(models.TextChoices):
        PHD = "phd", "Doctoral student"
        LICENTIATE = "licentiate", "Licentiate student"
        POSTDOC = "postdoc", "Postdoc"
        MASTER = "master", "Master's student"
        OTHER = "other", "Other"

    class Role(models.TextChoices):
        MAIN_SUPERVISOR = "main_supervisor", "Main supervisor"
        CO_SUPERVISOR = "co_supervisor", "Co-supervisor"
        MENTOR = "mentor", "Mentor"
        OTHER = "other", "Other"

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.INDIVIDUAL)
    supervisor_university = models.CharField(max_length=256, blank=True)
    supervisor_department = models.CharField(max_length=256, blank=True)
    person_university = models.CharField(max_length=256, blank=True)
    person_department = models.CharField(max_length=256, blank=True)
    first_name = models.CharField(max_length=128, blank=True)
    last_name = models.CharField(max_length=128, blank=True)
    end_year = models.PositiveIntegerField(null=True, blank=True)
    supervised_type = models.CharField(
        max_length=20, choices=SupervisedType.choices, default=SupervisedType.PHD
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MAIN_SUPERVISOR)
    number_of_people = models.PositiveSmallIntegerField(null=True, blank=True)

    def span(self) -> tuple[str, str, bool]:
        return "", _year(self.end_year), False

    def summary(self) -> str:
        who = f"{self.first_name} {self.last_name}".strip()
        if self.kind == self.Kind.GROUP:
            label = self.SupervisedType(self.supervised_type).label
            who = f"{self.number_of_people or ''} {label}s".strip()
        return _join(self.Role(self.role).label, who)

    def details(self) -> str:
        return _join(
            self.SupervisedType(self.supervised_type).label
            if self.kind == self.Kind.INDIVIDUAL
            else "",
            self.person_university,
            self.end_year,
        )


class AwardedGrant(CVEntry):
    class Role(models.TextChoices):
        APPLICANT = "applicant", "Applicant"
        CO_APPLICANT = "co_applicant", "Co-applicant"

    funder = models.CharField(max_length=512)
    country = models.CharField(max_length=100, blank=True)
    applicant = models.CharField(max_length=512, blank=True)
    project_title = models.CharField(max_length=512, blank=True)
    reference_number = models.CharField(max_length=512, blank=True)
    start_year = models.PositiveIntegerField(null=True, blank=True)
    end_year = models.PositiveIntegerField(null=True, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.APPLICANT)
    amount = models.BigIntegerField(null=True, blank=True)
    own_share = models.BigIntegerField("Own share of the amount", null=True, blank=True)
    currency = models.CharField(max_length=3, default="SEK")

    def span(self) -> tuple[str, str, bool]:
        return _year(self.start_year), _year(self.end_year), False

    def summary(self) -> str:
        return _join(self.project_title or self.funder, self.funder if self.project_title else "")

    def details(self) -> str:
        years = _range(str(self.start_year or ""), str(self.end_year or ""))
        amount = f"{self.amount:,} {self.currency}".replace(",", " ") if self.amount else ""
        return _join(self.Role(self.role).label, years, amount, self.reference_number)


class Award(CVEntry):
    year = models.PositiveIntegerField(null=True, blank=True)
    country = models.CharField(max_length=100, blank=True)
    award = models.CharField(max_length=512)
    issuer = models.CharField(max_length=512, blank=True)
    description = models.TextField(max_length=5000, blank=True)

    def span(self) -> tuple[str, str, bool]:
        return _year(self.year), "", False

    def summary(self) -> str:
        return self.award

    def details(self) -> str:
        return _join(self.issuer, self.country, self.year)


class OtherMerit(CVEntry):
    start_year = models.PositiveIntegerField(null=True, blank=True)
    end_year = models.PositiveIntegerField(null=True, blank=True)
    title = models.CharField(max_length=512)
    description = models.TextField(max_length=1024, blank=True)

    def span(self) -> tuple[str, str, bool]:
        return _year(self.start_year), _year(self.end_year), False

    def summary(self) -> str:
        return self.title

    def details(self) -> str:
        years = _range(str(self.start_year or ""), str(self.end_year or ""))
        return _join(years, self.description)


class IntellectualProperty(CVEntry):
    class Kind(models.TextChoices):
        PATENT = "patent", "Patent"
        DESIGN = "design", "Registered design"
        TRADEMARK = "trademark", "Trademark"
        SOFTWARE = "software", "Software"
        OTHER = "other", "Other"

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PATENT)
    other_kind = models.CharField(max_length=128, blank=True)
    title = models.CharField(max_length=512, blank=True)
    number = models.CharField(max_length=128, blank=True)
    date_approved = PartialDateField()
    classification = models.CharField(max_length=200, blank=True)
    licensed = models.BooleanField(default=False)
    licensee_type = models.CharField(max_length=128, blank=True)

    def span(self) -> tuple[str, str, bool]:
        return self.date_approved, "", False

    def summary(self) -> str:
        kind = self.other_kind if self.kind == self.Kind.OTHER else ""
        return _join(kind or self.Kind(self.kind).label, self.title or self.number)

    def details(self) -> str:
        licence = (
            f"licensed to {self.licensee_type}" if self.licensed and self.licensee_type else ""
        )
        return _join(
            self.number if self.title else "",
            partial_date_display(self.date_approved),
            self.classification,
            licence,
        )


class Publication(CVEntry):
    class Category(models.TextChoices):
        PEER_REVIEWED = "peer_reviewed", "Peer reviewed"
        NOT_PEER_REVIEWED = "not_peer_reviewed", "Not peer reviewed"

    class Form(models.TextChoices):
        BOOK = "book", "Book"
        BOOK_CHAPTER = "book_chapter", "Book chapter"
        JOURNAL_ARTICLE = "journal_article", "Journal article"
        CONFERENCE = "conference", "Conference contribution"
        EDITORSHIP = "editorship", "Editorship"
        OTHER_LITERATURE = "other_literature", "Other literature"
        REVIEW_ARTICLE = "review_article", "Review article"
        PROCEEDINGS = "proceedings", "Proceedings"
        PREPRINT = "preprint", "Preprint"
        THESIS = "thesis", "Thesis"
        REPORT = "report", "Report"
        DATASET = "dataset", "Dataset"
        SOFTWARE = "software", "Software"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        PUBLISHED = "published", "Published"

    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.PEER_REVIEWED
    )
    form = models.CharField(max_length=20, choices=Form.choices, default=Form.JOURNAL_ARTICLE)
    title = models.TextField()
    authors = models.JSONField(default=list, blank=True)
    editors = models.JSONField(default=list, blank=True)
    publisher = models.CharField(max_length=128, blank=True)
    place = models.CharField(max_length=128, blank=True)
    journal = models.TextField("Journal or series", blank=True)
    volume = models.CharField(max_length=128, blank=True)
    issue = models.CharField(max_length=128, blank=True)
    first_page = models.CharField(max_length=128, blank=True)
    last_page = models.CharField(max_length=128, blank=True)
    isbn = models.CharField("ISBN", max_length=128, blank=True)
    doi = models.CharField("DOI", max_length=256, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PUBLISHED)
    publication_date = PartialDateField()
    open_access = models.BooleanField(default=False)
    link = models.URLField(max_length=512, blank=True)
    abstract = models.TextField(blank=True)
    orcid_work_type = models.CharField(max_length=50, blank=True, editable=False)

    def span(self) -> tuple[str, str, bool]:
        return self.publication_date, "", False

    def summary(self) -> str:
        return self.title

    def details(self) -> str:
        authors = ", ".join(a for a in self.authors if isinstance(a, str))
        return _join(
            authors,
            self.journal or self.publisher,
            partial_date_display(self.publication_date),
            self.Form(self.form).label,
        )


def document_path(instance: "Document", filename: str) -> str:
    return f"documents/{instance.user_id}/{uuid.uuid4().hex}.pdf"


class Document(models.Model):
    """A PDF uploaded by an applicant, attachable to applications."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents"
    )
    file = models.FileField(upload_to=document_path)
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    user_id: int

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return self.original_name


class OrcidImport(models.Model):
    """One ORCID import, run in the background by ``run_orcid_imports``.

    The runner fetches and maps the record into ``items`` (staged, nothing written to the
    CV) and moves on to ``review``; the researcher includes, excludes or edits items and
    presses Done (``applied``) or Cancel (``cancelled``). A ``failed`` import shows its
    error until the researcher closes it (``dismissed``). ``stage``/``progress`` drive
    the loader dialog.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        REVIEW = "review", "Ready to review"
        APPLIED = "applied", "Applied"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"
        DISMISSED = "dismissed", "Failed, closed by the researcher"

    ACTIVE = (Status.QUEUED, Status.RUNNING, Status.REVIEW)

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    profile_id: int
    orcid = models.CharField(max_length=19)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    stage = models.CharField(max_length=20, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True)
    # Staged result: see services.stage_items for the item shape.
    items = models.JSONField(default=list, blank=True)
    keywords = models.JSONField(default=list, blank=True)  # [{"text": ..., "include": ...}]
    profile_fields = models.JSONField(default=dict, blank=True)
    person = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile"],
                condition=models.Q(status__in=["queued", "running", "review"]),
                name="core_profiles_one_active_orcid_import",
            )
        ]

    def __str__(self) -> str:
        return f"ORCID import {self.orcid} ({self.status})"

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE
