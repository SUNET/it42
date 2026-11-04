"""The organisation's decision. Each one writes its event to the org in the same
transaction (signature.granted / signature.declined).

The signature is a recorded click: who, when and an optional comment, sent with
``method: "click"`` so that signing through an external system can be added later.
"""

from django.db import transaction
from django.utils import timezone

from it42.common.outbox import emit
from it42.common.routing import ro_to_org
from it42.ro.accounts.models import User

from .models import SignatureRequest

MAX_TEXT = 2000


class CannotDecide(ValueError):
    pass


def _pending(request_id: int, research_org: str) -> SignatureRequest:
    request = SignatureRequest.objects.select_for_update().get(
        pk=request_id, research_org=research_org
    )
    if request.status != SignatureRequest.Status.PENDING:
        status = SignatureRequest.Status(request.status).label.lower()
        raise CannotDecide(f"This request is already {status}.")
    if timezone.localdate() > request.deadline:
        raise CannotDecide("The deadline to sign this application has passed.")
    return request


def _signer(user: User) -> dict[str, str]:
    return {"name": user.get_full_name() or user.username, "email": user.email}


def sign(request_id: int, research_org: str, user: User, comment: str) -> SignatureRequest:
    if len(comment) > MAX_TEXT:
        raise CannotDecide(f"Keep the comment under {MAX_TEXT} characters.")
    with transaction.atomic():
        request = _pending(request_id, research_org)
        request.status = SignatureRequest.Status.SIGNED
        request.decided_by = user
        request.decided_at = timezone.now()
        request.comment = comment
        request.save()
        emit(
            ro_to_org(request.org_slug),
            "signature.granted",
            {
                "application_id": str(request.public_id),
                "signer": _signer(user),
                "signed_at": request.decided_at.isoformat(),
                "comment": comment,
                "method": "click",
            },
            application_id=request.public_id,
        )
    return request


def decline(request_id: int, research_org: str, user: User, reason: str) -> SignatureRequest:
    if not reason or len(reason) > MAX_TEXT:
        raise CannotDecide(f"Give a reason of 1-{MAX_TEXT} characters; the applicant sees it.")
    with transaction.atomic():
        request = _pending(request_id, research_org)
        request.status = SignatureRequest.Status.DECLINED
        request.decided_by = user
        request.decided_at = timezone.now()
        request.comment = reason
        request.save()
        emit(
            ro_to_org(request.org_slug),
            "signature.declined",
            {
                "application_id": str(request.public_id),
                "signer": _signer(user),
                "declined_at": request.decided_at.isoformat(),
                "reason": reason,
            },
            application_id=request.public_id,
        )
    return request
