"""Signature requests from the orgs, one per application that names an administrating
organisation. They hold a copy of the application as the org received it, so the signer
sees exactly what the org will review."""

import uuid

from django.conf import settings
from django.db import models


class SignatureRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "To accept"
        SIGNED = "signed", "Signed"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"

    # The application's id, shared with the core and the org.
    public_id = models.UUIDField(unique=True)
    # The org that asked (from the arrival queue) and the organisation that must sign.
    org_slug = models.SlugField(max_length=16)
    research_org = models.SlugField(max_length=32)
    grant_public_id = models.UUIDField()
    grant_title = models.CharField(max_length=200)
    applicant_subject = models.CharField(max_length=255)
    applicant_name = models.CharField(max_length=200)
    applicant_email = models.EmailField(blank=True)
    answers = models.JSONField(default=dict)
    form_schema = models.JSONField(default=list)
    submitted_at = models.DateTimeField()
    # Last day to sign; the org may move it (signature.deadline_changed).
    deadline = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    # The signer's comment, or the reason for declining.
    comment = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    decided_by_id: int | None

    class Meta:
        ordering = ["deadline", "-received_at"]

    def __str__(self) -> str:
        return f"{self.applicant_name} -> {self.grant_title}"


def request_document_path(instance: "RequestDocument", filename: str) -> str:
    return f"requests/{instance.request.public_id}/{uuid.uuid4().hex}.pdf"


class RequestDocument(models.Model):
    request = models.ForeignKey(
        SignatureRequest, on_delete=models.CASCADE, related_name="documents"
    )
    file = models.FileField(upload_to=request_document_path)
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.original_name
