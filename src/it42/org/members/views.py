from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from it42.common.http import post_required
from it42.org.review.models import PanelMember

from .access import admin_required
from .models import Membership

User = get_user_model()


def _role(request: HttpRequest) -> str:
    role = request.POST.get("role", Membership.Role.STAFF)
    return role if role in Membership.Role.values else Membership.Role.STAFF


@admin_required
def members(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "org/members/list.html",
        {
            "members": Membership.objects.select_related("user", "approved_by").order_by(
                "user__username"
            ),
            # Panel reviewers log in on the reviewer site and are not staff candidates.
            "pending": User.objects.filter(membership__isnull=True, is_active=True)
            .exclude(sso_subject=None)
            .exclude(pk__in=PanelMember.objects.exclude(user=None).values("user_id"))
            .order_by("date_joined"),
            "roles": Membership.Role.choices,
        },
    )


@post_required
@admin_required
def approve(request: HttpRequest, user_id: int) -> HttpResponse:
    user = get_object_or_404(User, pk=user_id, membership__isnull=True)
    Membership.objects.create(
        user=user, role=_role(request), approved_by=request.user, approved_at=timezone.now()
    )
    messages.success(request, f"{user} is now a member.")
    return redirect("members")


@post_required
@admin_required
def set_role(request: HttpRequest, membership_id: int) -> HttpResponse:
    with transaction.atomic():
        membership = get_object_or_404(Membership.objects.select_for_update(), pk=membership_id)
        new_role = _role(request)
        if membership.is_admin and new_role != Membership.Role.ADMIN and _last_admin(membership):
            messages.error(request, "An org needs at least one admin.")
        else:
            membership.role = new_role
            membership.save(update_fields=["role"])
            messages.success(
                request, f"{membership.user} is now {Membership.Role(membership.role).label}."
            )
    return redirect("members")


@post_required
@admin_required
def remove(request: HttpRequest, membership_id: int) -> HttpResponse:
    with transaction.atomic():
        membership = get_object_or_404(Membership.objects.select_for_update(), pk=membership_id)
        if membership.is_admin and _last_admin(membership):
            messages.error(request, "An org needs at least one admin.")
        else:
            membership.delete()
            messages.success(request, f"{membership.user} is no longer a member.")
    return redirect("members")


def _last_admin(membership: Membership) -> bool:
    others = Membership.objects.filter(role=Membership.Role.ADMIN).exclude(pk=membership.pk)
    return not others.exists()
