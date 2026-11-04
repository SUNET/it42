"""Membership checks for org sites."""

from collections.abc import Callable
from functools import wraps
from typing import Any, Concatenate

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import redirect, render

from .models import Membership

_CACHE_ATTR = "_it42_membership"

# Paths reachable without an approved membership.
OPEN_PREFIXES = ("/saml2/", "/logout/", "/logged-out/", "/healthz", "/static/", "/admin/")


def membership_of(request: HttpRequest) -> Membership | None:
    """The request user's approved membership, looked up once per request."""
    if not request.user.is_authenticated:
        return None
    if not hasattr(request, _CACHE_ATTR):
        setattr(request, _CACHE_ATTR, Membership.objects.filter(user_id=request.user.pk).first())
    cached: Membership | None = getattr(request, _CACHE_ATTR)
    return cached


class MembershipGateMiddleware:
    """Every org page needs a login and an approved membership.

    Logged-in users without a membership get the not-a-member page and no data.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith(OPEN_PREFIXES):
            return self.get_response(request)
        if not request.user.is_authenticated:
            return redirect(f"/saml2/login/?next={request.path}")
        if membership_of(request) is None:
            return render(request, "org/not_member.html", status=403)
        return self.get_response(request)


def admin_required[**P, R: HttpResponseBase](
    view: Callable[Concatenate[HttpRequest, P], R],
) -> Callable[Concatenate[HttpRequest, P], R]:
    @wraps(view)
    def wrapper(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> R:
        membership = membership_of(request)
        if membership is None or not membership.is_admin:
            raise PermissionDenied("Only org admins can do this.")
        return view(request, *args, **kwargs)

    return wrapper


def membership_context(request: HttpRequest) -> dict[str, Any]:
    membership = membership_of(request)
    return {
        "membership": membership,
        "is_member": membership is not None,
        "is_org_admin": membership is not None and membership.is_admin,
    }
