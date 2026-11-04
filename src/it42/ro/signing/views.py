from typing import Any

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from it42.common.agenda import Deadline, agenda
from it42.common.formschema import labelled_answers
from it42.common.http import post_required
from it42.ro.accounts.models import User
from it42.ro.members.access import member

from . import services
from .models import RequestDocument, SignatureRequest

S = SignatureRequest.Status

# Dashboard / Organization, "Your decision" half: requests by the organisation's decision.
BOARD_COLUMNS = [
    (S.PENDING, "To accept"),
    (S.SIGNED, "Signed"),
    (S.DECLINED, "Declined"),
    (S.EXPIRED, "Expired"),
]


def _user(request: HttpRequest) -> User:
    user = request.user
    assert isinstance(user, User)  # noqa: S101 (the member gate ran first)
    return user


def funder_name(org_slug: str) -> str:
    return settings.KNOWN_ORGS.get(org_slug, org_slug)


def board(request: HttpRequest) -> HttpResponse:
    membership = member(request)
    today = timezone.localdate()
    sort = "deadline" if request.GET.get("sort") == "deadline" else "recent"
    requests = list(SignatureRequest.objects.filter(research_org=membership.research_org))
    if sort == "deadline":
        requests.sort(key=lambda r: (r.deadline, r.applicant_name))
    else:
        requests.sort(key=lambda r: r.received_at, reverse=True)
    columns: list[dict[str, Any]] = [
        {
            "key": key,
            "title": title,
            "cards": [
                {"req": r, "funder": funder_name(r.org_slug)} for r in requests if r.status == key
            ],
        }
        for key, title in BOARD_COLUMNS
    ]
    pending = [r for r in requests if r.status == S.PENDING]
    next_deadline = min((r.deadline for r in pending if r.deadline >= today), default=None)
    deadlines = [
        Deadline("Organisation sign-off", r.applicant_name, r.deadline, "signoff") for r in pending
    ]
    return render(
        request,
        "ro/board.html",
        {
            "columns": columns,
            "sort": sort,
            "today": today,
            "to_accept": len(pending),
            "next_deadline": next_deadline,
            "feed": _feed(requests),
            **agenda(today, deadlines),
        },
    )


def _feed(requests: list[SignatureRequest], limit: int = 5) -> list[dict[str, Any]]:
    """New requests and decisions, newest first, for the Notifications panel."""
    notes: list[dict[str, Any]] = [
        {
            "icon": "file-text",
            "text": f"{r.applicant_name} applied to {funder_name(r.org_slug)}.",
            "when": r.received_at,
            "request": r,
        }
        for r in requests
    ]
    notes += [
        {
            "icon": "seal-check" if r.status == S.SIGNED else "x",
            "text": f"{r.decided_by} {'signed' if r.status == S.SIGNED else 'declined'} "
            f"{r.applicant_name}'s application.",
            "when": r.decided_at,
            "request": r,
        }
        for r in requests
        if r.decided_at
    ]
    return sorted(notes, key=lambda n: n["when"], reverse=True)[:limit]


def detail(request: HttpRequest, request_id: int) -> HttpResponse:
    membership = member(request)
    signature_request = get_object_or_404(
        SignatureRequest.objects.select_related("decided_by"),
        pk=request_id,
        research_org=membership.research_org,
    )
    today = timezone.localdate()
    return render(
        request,
        "ro/detail.html",
        {
            "req": signature_request,
            "funder": funder_name(signature_request.org_slug),
            "answers": labelled_answers(signature_request.form_schema, signature_request.answers),
            "documents": RequestDocument.objects.filter(request=signature_request),
            "can_decide": signature_request.status == S.PENDING
            and today <= signature_request.deadline,
            "overdue": signature_request.status == S.PENDING and today > signature_request.deadline,
        },
    )


def download(request: HttpRequest, request_id: int, document_id: int) -> FileResponse:
    membership = member(request)
    document = get_object_or_404(
        RequestDocument,
        pk=document_id,
        request_id=request_id,
        request__research_org=membership.research_org,
    )
    return FileResponse(
        document.file.open("rb"),
        as_attachment=True,
        filename=document.original_name,
        content_type="application/pdf",
    )


@post_required
def sign(request: HttpRequest, request_id: int) -> HttpResponse:
    membership = member(request)
    get_object_or_404(SignatureRequest, pk=request_id, research_org=membership.research_org)
    if request.POST.get("confirm") != "on":
        messages.error(request, "Confirm that you sign on behalf of the organisation.")
        return redirect("request_detail", request_id)
    try:
        services.sign(
            request_id,
            membership.research_org,
            _user(request),
            request.POST.get("comment", "").strip(),
        )
    except services.CannotDecide as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Signed. The funder can now review the application.")
    return redirect("request_detail", request_id)


@post_required
def decline(request: HttpRequest, request_id: int) -> HttpResponse:
    membership = member(request)
    get_object_or_404(SignatureRequest, pk=request_id, research_org=membership.research_org)
    try:
        services.decline(
            request_id,
            membership.research_org,
            _user(request),
            request.POST.get("reason", "").strip(),
        )
    except services.CannotDecide as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Declined. The applicant sees your reason.")
    return redirect("request_detail", request_id)
