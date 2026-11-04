import uuid

from django.conf import settings
from django.db import models

from it42.common.statuses import NOT_REVIEWABLE, STATUS_MAX_LENGTH, ApplicationStatus
from it42.org.grants.models import Grant


class Application(models.Model):
    """An application received from the core. ``public_id`` was assigned by the core."""

    public_id = models.UUIDField(unique=True)
    grant = models.ForeignKey(Grant, on_delete=models.PROTECT, related_name="applications")
    applicant_subject = models.CharField(max_length=255)
    applicant_name = models.CharField(max_length=200)
    applicant_email = models.EmailField(blank=True)
    answers = models.JSONField(default=dict)
    # The administrating organisation (research_orgs slug) that has to sign first; ""
    # when the applicant named none.
    research_org = models.SlugField(max_length=32, blank=True)
    status = models.CharField(
        max_length=STATUS_MAX_LENGTH,
        choices=ApplicationStatus.choices,
        default=ApplicationStatus.RECEIVED,
    )
    # The organisation's decision, as reported by the RO zone: who signed or declined,
    # when, and their comment or reason.
    signed_by = models.CharField(max_length=200, blank=True)
    signed_by_email = models.EmailField(blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signature_note = models.TextField(blank=True)
    submitted_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Last sequence number used on an event about this application sent to the core.
    seq = models.PositiveIntegerField(default=0)
    grant_id: int

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"{self.applicant_name} -> {self.grant}"

    @property
    def reviewable(self) -> bool:
        return self.status not in NOT_REVIEWABLE

    def next_seq(self) -> int:
        """Reserve the next sequence number. Call inside a transaction on a locked row."""
        self.seq += 1
        return self.seq


def application_document_path(instance: "ApplicationDocument", filename: str) -> str:
    return f"applications/{instance.application.public_id}/{uuid.uuid4().hex}.pdf"


class ApplicationDocument(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="documents")
    file = models.FileField(upload_to=application_document_path)
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.original_name


class Question(models.Model):
    public_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    asked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    asked_at = models.DateTimeField(auto_now_add=True)
    answer = models.TextField(blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["asked_at"]

    def __str__(self) -> str:
        return self.text[:60]


class ReviewNote(models.Model):
    """Org-internal. Never part of any event; stays in the org database."""

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="review_notes"
    )
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.text[:60]
