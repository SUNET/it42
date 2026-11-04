"""Applicant-side state changes. Each writes its event in the same transaction."""

import base64
import uuid
from typing import Any

from django.db import transaction
from django.utils import timezone

from it42.common.formschema import research_org_of
from it42.common.outbox import emit
from it42.common.pdf import check_pdf_bytes
from it42.common.routing import core_to_org
from it42.common.statuses import ApplicationStatus
from it42.core.accounts.models import User
from it42.core.catalog.models import PublicGrant
from it42.core.profiles.models import Document, Profile

from .models import ApplicationCopy, ApplicationDraft, QuestionCopy, StatusChange


def applicant_name(user: User) -> str:
    profile = Profile.objects.filter(user=user).first()
    return (profile.full_name if profile else "") or user.get_full_name() or user.username


def save_draft(user: User, grant: PublicGrant, data: dict[str, Any]) -> ApplicationDraft:
    """Keep the form as it is, valid or not. Nothing is sent to the org."""
    draft, _ = ApplicationDraft.objects.update_or_create(
        user=user, grant=grant, defaults={"data": data}
    )
    return draft


def submit(
    user: User, grant: PublicGrant, answers: dict[str, Any], documents: list[Document]
) -> ApplicationCopy:
    """Store the application as submitted and queue application.submitted.

    Raises IntegrityError if the user already has a live application to this grant (one
    its organisation declined or let expire does not count).
    """
    attachments = []
    for document in documents:
        with document.file.open("rb") as fh:
            content = fh.read()
        # The file on disk must still be the PDF that was validated at upload.
        if check_pdf_bytes(content) != document.sha256:
            raise ValueError(f"{document.original_name} changed since it was uploaded")
        attachments.append(
            {
                "name": document.original_name,
                "sha256": document.sha256,
                "content": base64.b64encode(content).decode(),
            }
        )
    now = timezone.now()
    with transaction.atomic():
        draft = ApplicationDraft.objects.filter(user=user, grant=grant).first()
        application = ApplicationCopy.objects.create(
            public_id=uuid.uuid4(),
            user=user,
            org_slug=grant.org_slug,
            grant=grant,
            answers=answers,
            research_org=research_org_of(grant.form_schema, answers),
            documents=[{"name": a["name"], "sha256": a["sha256"]} for a in attachments],
            status=ApplicationStatus.SUBMITTED,
            submitted_at=now,
            draft_started_at=draft.created_at if draft else None,
        )
        if draft:
            draft.delete()
        StatusChange.objects.create(
            application=application, status=ApplicationStatus.SUBMITTED, changed_at=now
        )
        emit(
            core_to_org(grant.org_slug),
            "application.submitted",
            {
                "application_id": str(application.public_id),
                "grant_public_id": str(grant.grant_public_id),
                "applicant": {
                    "subject": user.sso_subject,
                    "name": applicant_name(user),
                    "email": user.email,
                },
                "answers": answers,
                "submitted_at": now.isoformat(),
                "documents": attachments,
            },
            application_id=application.public_id,
            grant_id=grant.grant_public_id,
        )
    return application


def answer_question(question_id: int, user: User, answer: str) -> QuestionCopy:
    with transaction.atomic():
        question = (
            QuestionCopy.objects.select_for_update()
            .select_related("application")
            .get(pk=question_id, application__user=user)
        )
        if question.answered_at is not None:
            raise ValueError("This question is already answered.")
        question.answer = answer
        question.answered_at = timezone.now()
        question.save(update_fields=["answer", "answered_at"])
        application = question.application
        emit(
            core_to_org(application.org_slug),
            "question.answered",
            {
                "application_id": str(application.public_id),
                "question_id": str(question.question_public_id),
                "answer": answer,
            },
            application_id=application.public_id,
        )
    return question
