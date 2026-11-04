from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from it42.common import research_orgs
from it42.common.http import post_required
from it42.ro.accounts.models import User

from .access import admin_required, member
from .models import Membership


@admin_required
def people(request: HttpRequest) -> HttpResponse:
    membership = member(request)
    return render(
        request,
        "ro/people.html",
        {
            "people": Membership.objects.filter(research_org=membership.research_org)
            .select_related("user")
            .order_by("role", "email"),
        },
    )


@post_required
@admin_required
def add_signer(request: HttpRequest) -> HttpResponse:
    membership = member(request)
    email = request.POST.get("email", "").strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, "Enter a valid email address.")
        return redirect("people")
    existing = Membership.objects.filter(email=email).first()
    if existing is not None:
        where = research_orgs.name_of(existing.research_org)
        messages.error(request, f"{email} already acts for {where}.")
        return redirect("people")
    if research_orgs.administered_by(email) is not None:
        messages.error(request, f"{email} is another organisation's admin.")
        return redirect("people")
    # Bind at once if this email has logged in before; otherwise at their first login.
    user = User.objects.filter(email__iexact=email).exclude(sso_subject=None).first()
    if user is not None and Membership.objects.filter(user=user).exists():
        messages.error(request, f"{email} already acts for another organisation.")
        return redirect("people")
    Membership.objects.create(
        email=email,
        research_org=membership.research_org,
        role=Membership.Role.SIGNER,
        user=user,
        added_by=request.user,
    )
    messages.success(
        request, f"{email} can now sign for {research_orgs.name_of(membership.research_org)}."
    )
    return redirect("people")


@post_required
@admin_required
def remove(request: HttpRequest, membership_id: int) -> HttpResponse:
    membership = member(request)
    signer = get_object_or_404(
        Membership,
        pk=membership_id,
        research_org=membership.research_org,
        role=Membership.Role.SIGNER,
    )
    signer.delete()
    messages.success(request, f"{signer.email} can no longer sign.")
    return redirect("people")
