import uuid
from datetime import date, time, timedelta
from typing import Any

from django.conf import settings
from django.db import models

from it42.common.formschema import BASE_FIELD_NAMES

# Default time the administrating organisation has to sign, after the call closes.
SIGNATURE_DAYS = 7
# Time of day a call closes unless the org picks another.
DEFAULT_DEADLINE_TIME = time(17, 0)


def default_signature_deadline(deadline: date) -> date:
    return deadline + timedelta(days=SIGNATURE_DAYS)


def field_count(schema: list[dict[str, Any]]) -> int:
    """Fields the org added: every entry except the three base fields. The builder's
    Form summary and the drafts page show this number."""
    return sum(1 for spec in schema if spec.get("name") not in BASE_FIELD_NAMES)


class Folder(models.Model):
    """A folder on the Grant drafts page; grants may sit in one or none."""

    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Category(models.Model):
    """A tag on a grant (the design's "Clean water", "Hydrology", ...)."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class FormTemplate(models.Model):
    """A saved application form the org loads into new grants. Built-ins (``builtin_key``)
    come with the site (``templates.BUILTIN_TEMPLATES``) and cannot be changed here."""

    public_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=200, blank=True)
    form_schema = models.JSONField(default=list, blank=True)
    builtin_key = models.CharField(max_length=40, unique=True, null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_builtin(self) -> bool:
        """Shipped with the site (``templates.BUILTIN_TEMPLATES``): shown with a
        "Built-in" tag, cannot be renamed or deleted on the site."""
        return bool(self.builtin_key)

    @property
    def field_count(self) -> int:
        """Fields the template adds on top of the base fields ("8 fields" on its card)."""
        return field_count(self.form_schema)


class Grant(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CLOSED = "closed", "Closed"

    public_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField()
    deadline = models.DateField()
    deadline_time = models.TimeField(default=DEFAULT_DEADLINE_TIME, blank=True)
    # Last day the administrating organisation can sign an application (call deadline +
    # SIGNATURE_DAYS unless the org moves it; it may do so at any time). Filled on save.
    signature_deadline = models.DateField(blank=True)
    form_schema = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    folder = models.ForeignKey(
        Folder, null=True, blank=True, on_delete=models.SET_NULL, related_name="grants"
    )
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="grants"
    )
    # The saved template this form was loaded from ("this form is based on it").
    template = models.ForeignKey(
        FormTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name="grants"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.signature_deadline is None and self.deadline is not None:
            self.signature_deadline = default_signature_deadline(self.deadline)
        super().save(*args, **kwargs)

    @property
    def field_count(self) -> int:
        """Fields the org added to this grant's form ("6 fields" on the drafts page)."""
        return field_count(self.form_schema)
