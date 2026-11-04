"""Membership checks for the research organisation site."""

from collections.abc import Callable
from functools import wraps
from typing import Any, Concatenate

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import redirect, render

from it42.common import research_orgs

from .models import Membership

_CACHE_ATTR = "_it42_ro_membership"

# Paths reachable without a membership.
OPEN_PREFIXES = ("/saml2/", "/logout/", "/logged-out/", "/healthz", "/static/", "/admin/")


def membership_of(request: HttpRequest) -> Membership | None:
    """The request user's membership, looked up once per request. A membership of an
    organisation that left the directory counts as none."""
    if not request.user.is_authenticated:
        return None
    if not hasattr(request, _CACHE_ATTR):
        membership = Membership.objects.filter(user_id=request.user.pk).first()
        if membership is not None and research_orgs.get(membership.research_org) is None:
            membership = None
        setattr(request, _CACHE_ATTR, membership)
    cached: Membership | None = getattr(request, _CACHE_ATTR)
    return cached


def member(request: HttpRequest) -> Membership:
    """The membership of a request that passed the gate."""
    membership = membership_of(request)
    if membership is None:
        raise PermissionDenied("Not a member of a research organisation.")
    return membership


class RoMemberGateMiddleware:
    """Every page needs a login and a membership; others see the not-a-member page."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith(OPEN_PREFIXES):
            return self.get_response(request)
        if not request.user.is_authenticated:
            return redirect(f"/saml2/login/?next={request.path}")
        if membership_of(request) is None:
            return render(request, "ro/not_member.html", status=403)
        return self.get_response(request)


def admin_required[**P, R: HttpResponseBase](
    view: Callable[Concatenate[HttpRequest, P], R],
) -> Callable[Concatenate[HttpRequest, P], R]:
    @wraps(view)
    def wrapper(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> R:
        membership = membership_of(request)
        if membership is None or not membership.is_admin:
            raise PermissionDenied("Only the organisation's admin can do this.")
        return view(request, *args, **kwargs)

    return wrapper


def member_context(request: HttpRequest) -> dict[str, Any]:
    membership = membership_of(request)
    org = research_orgs.get(membership.research_org) if membership else None
    return {
        "membership": membership,
        "research_org": org,
        "is_ro_admin": membership is not None and membership.is_admin,
        # Shown under the logo by org/layout.html.
        "ORG_NAME": org.name if org else settings.SITE_NAME,
    }
