from django.conf import settings
from django.db import models
from django.db.models import Q

from it42.common.statuses import ENDED_BEFORE_REVIEW, STATUS_MAX_LENGTH, ApplicationStatus
from it42.core.catalog.models import PublicGrant


class ApplicationCopy(models.Model):
    """The applicant's side of an application. ``public_id`` is shared with the org."""

    public_id = models.UUIDField(unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="applications"
    )
    org_slug = models.SlugField(max_length=16)
    grant = models.ForeignKey(PublicGrant, on_delete=models.PROTECT, related_name="applications")
    answers = models.JSONField(default=dict)
    # [{"name": ..., "sha256": ...}]; the PDFs themselves travel in the event.
    documents = models.JSONField(default=list)
    status = models.CharField(
        max_length=STATUS_MAX_LENGTH,
        choices=ApplicationStatus.choices,
        default=ApplicationStatus.SUBMITTED,
    )
    # The administrating organisation named in the answers (research_orgs slug, "" for
    # none) and the applicant-visible part of its RO-authenticated decision.
    research_org = models.SlugField(max_length=32, blank=True)
    signed_by = models.CharField(max_length=200, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField()
    # When the applicant saved the first draft of it (core only, never in an event).
    draft_started_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Highest org sequence number applied; older or repeated org events are ignored.
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            # One live application per grant; one the organisation declined or let expire
            # does not count, so the applicant can apply again.
            models.UniqueConstraint(
                fields=["user", "grant"],
                condition=~Q(status__in=ENDED_BEFORE_REVIEW),
                name="one_application_per_grant",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.grant}"


class StatusChange(models.Model):
    """Status history shown to the applicant."""

    application = models.ForeignKey(
        ApplicationCopy, on_delete=models.CASCADE, related_name="status_changes"
    )
    status = models.CharField(max_length=STATUS_MAX_LENGTH, choices=ApplicationStatus.choices)
    seq = models.PositiveIntegerField(default=0)
    changed_at = models.DateTimeField()
    application_id: int

    class Meta:
        ordering = ["changed_at", "seq"]

    def __str__(self) -> str:
        return f"{self.application_id}: {self.status}"


class QuestionCopy(models.Model):
    application = models.ForeignKey(
        ApplicationCopy, on_delete=models.CASCADE, related_name="questions"
    )
    question_public_id = models.UUIDField(unique=True)
    text = models.TextField()
    asked_at = models.DateTimeField()
    answer = models.TextField(blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    application_id: int

    class Meta:
        ordering = ["asked_at"]

    def __str__(self) -> str:
        return self.text[:60]


class ApplicationDraft(models.Model):
    """An unfinished application. Core only: it never leaves this zone, and submitting
    it replaces it with an ApplicationCopy in the same transaction."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="drafts"
    )
    grant = models.ForeignKey(PublicGrant, on_delete=models.CASCADE, related_name="drafts")
    # Raw form values by field name, as the widgets read them (str, list or bool), so the
    # form can be shown again exactly as it was, even when it does not validate yet.
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    user_id: int
    grant_id: int

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "grant"], name="one_draft_per_grant")
        ]

    def __str__(self) -> str:
        return f"draft {self.user_id} -> {self.grant_id}"
