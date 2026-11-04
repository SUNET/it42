"""Review panels: seats, schedule, assignments and the review content itself.

Everything here is org-internal. Nothing is ever sent to the core or shown to an
applicant. The rules for who may read or write what live in ``access.py``; the models
only hold the data and the time-window helpers.
"""

import uuid
from datetime import datetime
from typing import Any

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from it42.common.statuses import NOT_REVIEWABLE
from it42.org.applications.models import Application
from it42.org.grants.models import Grant

GRADE_VALIDATORS = [MinValueValidator(0), MaxValueValidator(10)]


class Panel(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    grants = models.ManyToManyField(Grant, blank=True, related_name="+")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    # Set by an FO admin to end the review phase before the assessment task's deadline.
    review_closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by_id: int

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def applications(self) -> models.QuerySet[Application]:
        """Every reviewable application of the panel's grants, newest first. Applications
        still waiting for (or refused) their organisation's signature are left out."""
        return (
            Application.objects.filter(grant__in=self.grants.all())
            .exclude(status__in=NOT_REVIEWABLE)
            .select_related("grant")
        )

    def task(self, kind: str) -> "PanelTask | None":
        return PanelTask.objects.filter(panel=self, kind=kind).first()

    def task_open(self, kind: str, now: datetime) -> bool:
        task = self.task(kind)
        return task is not None and task.is_open(now)

    def review_done(self, now: datetime) -> bool:
        """The assessment task has ended, or an FO admin ended the review early."""
        if self.review_closed_at is not None and self.review_closed_at <= now:
            return True
        task = self.task(PanelTask.Kind.ASSESSMENT)
        return task is not None and task.has_ended(now)

    def final_phase_started(self, now: datetime) -> bool:
        """The review is done and the final-statement task has begun (open or over).

        Until then nothing about the final statement is shown on either site.
        """
        task = self.task(PanelTask.Kind.FINAL)
        return task is not None and task.starts_at <= now and self.review_done(now)

    def assessments_shared(self, now: datetime) -> bool:
        """Assessments are private to their authors until the review is done."""
        return self.review_done(now)


class PanelMember(models.Model):
    """A seat on a panel, created with an email; bound to a user at their login."""

    class Role(models.TextChoices):
        CHAIR = "chairperson", "Chairperson"
        REVIEWER = "reviewer", "Reviewer"
        EXTERNAL = "external_reviewer", "External reviewer"
        SUPPORT = "supporting_admin", "Supporting admin"

    REVIEWING_ROLES = frozenset({Role.CHAIR, Role.REVIEWER, Role.EXTERNAL})
    SEES_ALL_ROLES = frozenset({Role.CHAIR, Role.SUPPORT})

    panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="members")
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.REVIEWER)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    added_at = models.DateTimeField(auto_now_add=True)
    panel_id: int
    user_id: int | None

    class Meta:
        ordering = ["email"]
        constraints = [
            models.UniqueConstraint(fields=["panel", "email"], name="org_review_seat_email_once"),
        ]
        indexes = [models.Index(fields=["email"], name="org_review_seat_email_idx")]

    def __str__(self) -> str:
        return f"{self.email} ({self.role_label})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def role_label(self) -> str:
        return str(self.Role(self.role).label)

    @property
    def is_chair(self) -> bool:
        return self.role == self.Role.CHAIR

    @property
    def is_support(self) -> bool:
        return self.role == self.Role.SUPPORT

    @property
    def reviews(self) -> bool:
        """Roles that assess applications and declare conflicts."""
        return self.role in self.REVIEWING_ROLES

    @property
    def sees_all(self) -> bool:
        """Roles that see every application of the panel, assigned or not."""
        return self.role in self.SEES_ALL_ROLES

    @property
    def display_name(self) -> str:
        user = self.user
        if user is not None:
            full = user.get_full_name()
            if full:
                return full
        return self.email


class Meeting(models.Model):
    panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="meetings")
    title = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    panel_id: int

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="org_review_meeting_window",
            )
        ]

    def __str__(self) -> str:
        return self.title


class PanelTask(models.Model):
    """A dated task for the panel. The special kinds gate what reviewers may write."""

    class Kind(models.TextChoices):
        CONFLICT = "conflict_and_competence", "Conflict of interest and competence level"
        ASSESSMENT = "assessment", "Writing assessment and preliminary statement"
        FINAL = "final_statement", "Final statement"
        OTHER = "other", "Other"

    panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="tasks")
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    title = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    panel_id: int

    class Meta:
        ordering = ["starts_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["panel", "kind"],
                condition=~Q(kind="other"),
                name="org_review_task_kind_once",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="org_review_task_window"
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def kind_label(self) -> str:
        return str(self.Kind(self.kind).label)

    def is_open(self, now: datetime) -> bool:
        return self.starts_at <= now < self.ends_at

    def has_ended(self, now: datetime) -> bool:
        return now >= self.ends_at

    def state(self, now: datetime) -> str:
        if now < self.starts_at:
            return "upcoming"
        return "open" if now < self.ends_at else "ended"


class Assignment(models.Model):
    """A panel member assigned to review one application. Set by the FO."""

    member = models.ForeignKey(PanelMember, on_delete=models.CASCADE, related_name="assignments")
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="+")
    assigned_at = models.DateTimeField(auto_now_add=True)
    member_id: int
    application_id: int

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["member", "application"], name="org_review_assignment_once"
            )
        ]

    def __str__(self) -> str:
        return f"{self.member} -> {self.application}"


class Declaration(models.Model):
    """Conflict of interest and competence level, one per member and application."""

    class Competence(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    member = models.ForeignKey(PanelMember, on_delete=models.CASCADE, related_name="declarations")
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="+")
    in_conflict = models.BooleanField(default=False)
    conflict_reason = models.TextField(blank=True)
    competence = models.CharField(max_length=8, choices=Competence.choices)
    updated_at = models.DateTimeField(auto_now=True)
    member_id: int
    application_id: int

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["member", "application"], name="org_review_declaration_once"
            )
        ]

    def __str__(self) -> str:
        return f"{self.member} on {self.application}"

    @property
    def competence_label(self) -> str:
        return str(self.Competence(self.competence).label)


class Assessment(models.Model):
    """A reviewer's assessment and preliminary statement for one application."""

    member = models.ForeignKey(PanelMember, on_delete=models.CASCADE, related_name="assessments")
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="+")
    assessment = models.TextField()
    preliminary_statement = models.TextField()
    preliminary_grade = models.PositiveSmallIntegerField(validators=GRADE_VALIDATORS)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    member_id: int
    application_id: int

    class Meta:
        ordering = ["member__email"]
        constraints = [
            models.UniqueConstraint(
                fields=["member", "application"], name="org_review_assessment_once"
            ),
            models.CheckConstraint(
                condition=Q(preliminary_grade__lte=10), name="org_review_assessment_grade"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.member} on {self.application}"


class FinalStatement(models.Model):
    """The chairperson's final statement for one application, five parts with grades."""

    SECTIONS: list[tuple[str, str, str]] = [
        ("final_statement", "final_grade", "Final statement"),
        ("novelty", "novelty_grade", "Novelty and originality"),
        ("merits", "merits_grade", "Merits of the applicant"),
        ("feasibility", "feasibility_grade", "Feasibility"),
        ("quality", "quality_grade", "Overall assessment of the application's scientific quality"),
    ]

    panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="final_statements")
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="+")
    author = models.ForeignKey(
        PanelMember, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    final_statement = models.TextField()
    final_grade = models.PositiveSmallIntegerField(validators=GRADE_VALIDATORS)
    novelty = models.TextField()
    novelty_grade = models.PositiveSmallIntegerField(validators=GRADE_VALIDATORS)
    merits = models.TextField()
    merits_grade = models.PositiveSmallIntegerField(validators=GRADE_VALIDATORS)
    feasibility = models.TextField()
    feasibility_grade = models.PositiveSmallIntegerField(validators=GRADE_VALIDATORS)
    quality = models.TextField()
    quality_grade = models.PositiveSmallIntegerField(validators=GRADE_VALIDATORS)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    panel_id: int
    application_id: int
    author_id: int | None

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["panel", "application"], name="org_review_final_once"),
            models.CheckConstraint(
                condition=Q(final_grade__lte=10)
                & Q(novelty_grade__lte=10)
                & Q(merits_grade__lte=10)
                & Q(feasibility_grade__lte=10)
                & Q(quality_grade__lte=10),
                name="org_review_final_grades",
            ),
        ]

    def __str__(self) -> str:
        return f"Final statement on {self.application}"

    def rows(self) -> list[tuple[str, str, int]]:
        """(label, text, grade) per section, for read-only rendering."""
        return [
            (label, getattr(self, text), getattr(self, grade))
            for text, grade, label in self.SECTIONS
        ]


class ReviewerNote(models.Model):
    """A reviewer's private note on one application ("My notes"). Only its author ever
    reads it: never shown to the panel, the FO staff site or the applicant, never emitted."""

    member = models.ForeignKey(PanelMember, on_delete=models.CASCADE, related_name="notes")
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="+")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    member_id: int
    application_id: int

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.text[:60]


def passport_path(instance: "ReviewerProfile", filename: str) -> str:
    return f"passports/{instance.user_id}/{uuid.uuid4().hex}.pdf"


class ReviewerProfile(models.Model):
    """Payment details, passport and topics of a reviewer. FO admins may read it."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    address = models.TextField(blank=True)
    account_holder = models.CharField(max_length=200, blank=True)
    bank_name = models.CharField(max_length=200, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    bic = models.CharField("BIC / SWIFT", max_length=11, blank=True)
    keywords = models.TextField(
        blank=True,
        help_text="Comma-separated topics you can review, for example: photonics, lasers",
    )
    passport = models.FileField(upload_to=passport_path, blank=True)
    passport_name = models.CharField(max_length=255, blank=True)
    passport_sha256 = models.CharField(max_length=64, blank=True)
    passport_size = models.PositiveIntegerField(default=0)
    passport_uploaded_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    user_id: int

    def __str__(self) -> str:
        return f"Reviewer profile of {self.user}"

    @property
    def keyword_list(self) -> list[str]:
        return [k.strip() for k in self.keywords.split(",") if k.strip()]

    @property
    def has_payment_info(self) -> bool:
        return any([self.address, self.account_holder, self.bank_name, self.iban, self.bic])

    def clear_passport(self) -> None:
        if self.passport:
            self.passport.delete(save=False)
        self.passport_name = ""
        self.passport_sha256 = ""
        self.passport_size = 0
        self.passport_uploaded_at = None
