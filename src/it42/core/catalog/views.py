import re
from datetime import timedelta
from pathlib import Path

import markdown
from django.conf import settings
from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from it42.common.statuses import ENDED_BEFORE_REVIEW
from it42.core.applications.models import ApplicationCopy, ApplicationDraft

from .models import PublicGrant

# Calls closing within this many days are "closing soon"; published within NEW_DAYS, "new".
CLOSING_SOON_DAYS = 14
NEW_DAYS = 7
# Static text pages: templates/core/pages/<slug>.md (Markdown with Meta-Data headers).
PAGES_DIR = Path(settings.BASE_DIR) / "templates" / "core" / "pages"
PAGE_SLUG = re.compile(r"^[a-z0-9-]+$")
# "N min read" next to "Last updated": words per minute of an average reader.
READING_WPM = 200


def is_open(grant: PublicGrant) -> bool:
    return grant.status == PublicGrant.Status.OPEN and grant.deadline >= timezone.localdate()


def open_grants() -> QuerySet[PublicGrant]:
    return PublicGrant.objects.filter(
        status=PublicGrant.Status.OPEN, deadline__gte=timezone.localdate()
    )


def funders() -> list[dict[str, str]]:
    """Every org on the platform, from the core's own KNOWN_ORGS (never event payloads)."""
    colors: dict[str, str] = settings.ORG_COLORS
    return [
        {"slug": slug, "name": name, "color": colors.get(slug, "#6c757d")}
        for slug, name in settings.KNOWN_ORGS.items()
    ]


def home(request: HttpRequest) -> HttpResponse:
    return render(request, "core/home.html", {"grants": open_grants()[:4], "funders": funders()})


def calls(request: HttpRequest) -> HttpResponse:
    grants = open_grants()
    query = request.GET.get("q", "").strip()[:200]
    funder = request.GET.get("funder", "")
    if funder not in settings.KNOWN_ORGS:
        funder = ""
    filtered = grants
    if query:
        filtered = filtered.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(org_name__icontains=query)
        )
    if funder:
        filtered = filtered.filter(org_slug=funder)
    today = timezone.localdate()
    context = {
        "query": query,
        "funder": funder,
        "funders": funders(),
        "total": grants.count(),
        "results": filtered,
        "filtering": bool(query or funder),
        "closing_soon": grants.filter(deadline__lte=today + timedelta(days=CLOSING_SOON_DAYS))[:4],
        "new_grants": grants.filter(
            published_at__gte=timezone.now() - timedelta(days=NEW_DAYS)
        ).order_by("-published_at")[:4],
    }
    return render(request, "core/catalog/list.html", context)


def grant_detail(request: HttpRequest, org_slug: str, grant_id: str) -> HttpResponse:
    grant = get_object_or_404(PublicGrant, org_slug=org_slug, grant_public_id=grant_id)
    application = draft = None
    if request.user.is_authenticated:
        application = (
            ApplicationCopy.objects.filter(user_id=request.user.pk, grant=grant)
            .exclude(status__in=ENDED_BEFORE_REVIEW)
            .first()
        )
        draft = ApplicationDraft.objects.filter(user_id=request.user.pk, grant=grant).first()
    similar = open_grants().filter(org_slug=org_slug).exclude(pk=grant.pk)[:4]
    return render(
        request,
        "core/catalog/detail.html",
        {
            "grant": grant,
            "is_open": is_open(grant),
            "application": application,
            "draft": draft,
            "similar": similar,
        },
    )


def text_page(request: HttpRequest, slug: str) -> HttpResponse:
    path = PAGES_DIR / f"{slug}.md"
    if not PAGE_SLUG.match(slug) or not path.is_file():
        raise Http404("No such page")
    md = markdown.Markdown(extensions=["meta", "tables", "toc"], output_format="html")
    source = path.read_text(encoding="utf-8")
    body = md.convert(source)
    meta: dict[str, list[str]] = getattr(md, "Meta", {})
    toc: list[dict[str, object]] = getattr(md, "toc_tokens", [])
    return render(
        request,
        "core/pages/page.html",
        {
            "body": body,
            "title": " ".join(meta.get("title", [slug.title()])),
            "lead": " ".join(meta.get("lead", [])),
            "eyebrow": " ".join(meta.get("eyebrow", [])),
            "updated": " ".join(meta.get("updated", [])),
            "notice": " ".join(meta.get("notice", [])),
            "read_minutes": max(1, round(len(source.split()) / READING_WPM)),
            "toc": [t for t in toc if t.get("level") == 2],
        },
    )
