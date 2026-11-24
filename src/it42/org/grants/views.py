import json
from collections import defaultdict
from typing import Any

from django import forms
from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from it42.common.agenda import Deadline, agenda
from it42.common.formpresentation import application_presentation
from it42.common.forms import BootstrapForm
from it42.common.formschema import (
    ADMIN_ORG_FIELD,
    BASE_FIELD_NAMES,
    CURRENCIES,
    DEFAULT_FIELD_NAMES,
    MAX_BUDGET_LINES,
    MAX_FIELDS,
    MAX_OPTIONS,
    MAX_WORDS_LIMIT,
    OPTIONAL_BASE_FIELDS,
    WIDGETS,
    SchemaError,
    build_form,
)
from it42.common.http import board_card, post_required
from it42.common.statuses import NOT_REVIEWABLE, ApplicationStatus
from it42.common.theme import core_site_host
from it42.org.applications.models import Application, Question
from it42.org.members.access import admin_required, membership_of
from it42.org.review.models import Assessment, Assignment, Meeting, PanelTask
from it42.org.review.services import grant_panels

from . import board, services
from .forms import GrantForm, NameForm, SignatureDeadlineForm, clean_schema
from .models import Category, Folder, FormTemplate, Grant, field_count
from .templates import starting_template


def dashboard(request: HttpRequest) -> HttpResponse:
    """Staff work queues, with the organisation's notifications and agenda alongside."""
    membership = membership_of(request)
    grants, context = board.board_context(request, bool(membership and membership.is_admin))
    return render(
        request,
        "org/dashboard.html",
        {
            **context,
            "feed": _feed(),
            **agenda(timezone.localdate(), org_deadlines(grants)),
        },
    )


@post_required
def board_action(request: HttpRequest) -> HttpResponse:
    """Return to the same filtered board after an individual or bulk action."""
    membership = membership_of(request)
    assert membership is not None  # noqa: S101 (staff membership gate)
    action = request.POST.get("action", "")
    try:
        services.change_board_items(
            request.POST.getlist("card"),
            action,
            owner_id=membership.user.pk,
            is_admin=membership.is_admin,
            text=request.POST.get("note", "").strip(),
            tag=request.POST.get("tag", ""),
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            {
                "archive": "Archived.",
                "pause": "Call paused on the board.",
                "resume": "Call resumed.",
                "tag": "Call tag updated.",
                "note": "Personal note updated.",
            }[action],
        )
    return redirect(reverse("home", query=request.GET))


def archive(request: HttpRequest) -> HttpResponse:
    applications = Application.objects.filter(archive_at__lte=timezone.now())
    query = request.GET.get("q", "").strip()
    if query:
        applications = applications.filter(
            Q(answers__project_title__icontains=query)
            | Q(applicant_name__icontains=query)
            | Q(grant__title__icontains=query)
        )
    outcomes = {ApplicationStatus.APPROVED: "Accepted", ApplicationStatus.REJECTED: "Declined"}
    counts = dict(applications.order_by().values_list("status").annotate(total=Count("pk")))
    total = sum(counts.values())
    current = request.GET.get("status", "")
    if current in outcomes:
        applications = applications.filter(status=current)
    else:
        current = ""
    sort = "oldest" if request.GET.get("sort") == "oldest" else "newest"
    order = "decision_time" if sort == "oldest" else "-decision_time"
    return render(
        request,
        "org/grants/archive.html",
        {
            "applications": applications.select_related("grant", "decided_by")
            .annotate(
                question_count=Count("questions"),
                decision_time=Coalesce("decided_at", "archive_at"),
            )
            .order_by(order, "pk"),
            "total": total,
            "tabs": [(key, label, counts.get(key, 0)) for key, label in outcomes.items()],
            "current": current,
            "query": query,
            "sort": sort,
            "feed": _feed(),
            **agenda(timezone.localdate(), org_deadlines(list(Grant.objects.all()))),
        },
    )


def _feed(limit: int = 5) -> list[dict[str, Any]]:
    """Latest applications and answered questions for the Notifications panel."""
    received = [
        {
            "icon": "file-text",
            "text": f"{a.applicant_name} applied to {a.grant.title}.",
            "when": a.received_at,
            "application": a,
        }
        for a in Application.objects.select_related("grant").order_by("-received_at")[:limit]
    ]
    answered = [
        {
            "icon": "chat-circle-dots",
            "text": f"{q.application.applicant_name} answered a question.",
            "when": q.answered_at,
            "application": q.application,
        }
        for q in Question.objects.exclude(answered_at=None)
        .select_related("application")
        .order_by("-answered_at")[:limit]
    ]
    return sorted(received + answered, key=lambda n: n["when"], reverse=True)[:limit]


def org_deadlines(grants: list[Grant]) -> list[Deadline]:
    """Dated items of the org: published grants' deadlines, review task ends, meetings."""
    items = [
        Deadline("Call closes", g.title, g.deadline, "call")
        for g in grants
        if g.status == Grant.Status.PUBLISHED
    ]
    waiting = set(
        Application.objects.filter(status=ApplicationStatus.AWAITING_SIGNATURE).values_list(
            "grant_id", flat=True
        )
    )
    items += [
        Deadline("Organisation sign-off", g.title, g.signature_deadline, "signoff")
        for g in grants
        if g.status == Grant.Status.PUBLISHED or g.pk in waiting
    ]
    items += [
        Deadline(t.title, t.panel.name, timezone.localdate(t.ends_at), "task")
        for t in PanelTask.objects.select_related("panel")
    ]
    items += [
        Deadline(m.title, m.panel.name, timezone.localdate(m.starts_at), "meeting")
        for m in Meeting.objects.select_related("panel")
    ]
    return items


def templates_with_use() -> list[FormTemplate]:
    """Saved templates, built-ins first, each with ``used`` (grants based on it)."""
    builtins = {"standard-research-grant": 0, "small-grant-quick-apply": 1, "fellowship": 2}
    return sorted(
        FormTemplate.objects.annotate(used=Count("grants")),
        key=lambda template: (builtins.get(template.builtin_key, 3), template.name),
    )


def builder_config(templates: list[FormTemplate], grant: Grant | None) -> dict[str, Any]:
    """What the builder needs: the palette, the locked base fields (``optional`` lists
    the locked fields whose Required switch stays editable), the names badged
    "Default", the saved templates and the blank form."""
    return {
        "widgets": [
            {
                "type": field_type,
                "label": w["label"],
                "hint": w["hint"],
                "icon": w["icon"],
                "group": w["group"],
                "keys": list(w["keys"]),
                "palette": w.get("palette", True),
            }
            for field_type, w in WIDGETS.items()
        ],
        "locked": list(BASE_FIELD_NAMES),
        "optional": list(OPTIONAL_BASE_FIELDS),
        "defaults": list(DEFAULT_FIELD_NAMES),
        "type_names": {"research_org": ADMIN_ORG_FIELD},
        "max_fields": MAX_FIELDS,
        "max_options": MAX_OPTIONS,
        "max_words": MAX_WORDS_LIMIT,
        "max_budget_lines": MAX_BUDGET_LINES,
        "currencies": list(CURRENCIES),
        "templates": [
            {
                "id": t.pk,
                "name": t.name,
                "description": t.description,
                "field_count": t.field_count,
                "used": getattr(t, "used", 0),  # the annotation from templates_with_use
                "builtin": t.is_builtin,
                "schema": t.form_schema,
            }
            for t in templates
        ],
        "based_on": getattr(grant, "template_id", None),
        "start": starting_template(),
        "timezone": timezone.get_current_timezone_name(),
    }


def form_summary(schema: list[dict[str, Any]]) -> dict[str, int]:
    """The builder's Form summary: fields the org added, how many are required and how
    many of the defaults are still there."""
    return {
        "fields": field_count(schema),
        "required": sum(
            1 for s in schema if s.get("required") and s.get("name") not in BASE_FIELD_NAMES
        ),
        "defaults": sum(1 for s in schema if s.get("name") in DEFAULT_FIELD_NAMES),
    }


def _builder(request: HttpRequest, form: GrantForm, grant: Grant | None) -> HttpResponse:
    """Render the form builder page for a new (``grant`` None) or existing draft: the
    palette groups (server-rendered, so icons come through ``{% icon %}``), the saved
    templates, the JSON config for the JavaScript and the Form summary counts computed
    from whatever schema the form currently holds (posted or saved)."""
    templates = templates_with_use()
    palette = [w for w in WIDGETS.values() if w.get("palette", True)]
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for field_type, w in WIDGETS.items():
        if w.get("palette", True):
            groups.setdefault(w["group"], []).append((field_type, w))
    schema = form["form_schema"].value()
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except ValueError:
            schema = []
    if not isinstance(schema, list):
        schema = []
    return render(
        request,
        "org/grants/form.html",
        {
            "form": form,
            "grant": grant,
            "action_url": reverse("grant_edit", args=[grant.pk])
            if grant
            else reverse("grant_create"),
            "builder_config": builder_config(templates, grant),
            "templates": templates,
            "palette_groups": [{"name": name, "items": items} for name, items in groups.items()],
            "palette_count": len(palette),
            "summary": form_summary([s for s in schema if isinstance(s, dict)]),
            "active": "grant_drafts",
        },
    )


def _save_grant(request: HttpRequest, grant: Grant | None) -> HttpResponse:
    """Create or edit a draft. The builder's buttons submit the same form with
    ``?action=``: ``save`` (default), ``publish`` (save, then publish), ``template``
    (save, then also save the form as a template named ``template_name``) or
    ``preview`` (render the posted form as applicants see it, saving nothing)."""
    action = request.GET.get("action", "save")
    form = GrantForm(request.POST or None, instance=grant)
    if request.method != "POST":
        return _builder(request, form, grant)
    if action == "preview":
        return _preview(request, form, grant)
    name_form = None
    if action == "template":
        name_form = NameForm(request.POST, taken=FormTemplate.objects.all())
        if not name_form.is_valid():
            messages.error(request, _name_error(name_form))
    if not form.is_valid() or (name_form is not None and not name_form.is_valid()):
        return _builder(request, form, grant)
    saved = form.save(commit=False)
    if grant is None:
        saved.created_by = request.user
        saved.save()
    else:
        # Write only builder fields so a concurrent board pause is preserved.
        saved.save(update_fields=[*form.Meta.fields, "updated_at"])
    if action == "template" and name_form is not None:
        template = FormTemplate.objects.create(
            name=name_form.cleaned_data["name"],
            form_schema=saved.form_schema,
            created_by=request.user,
        )
        saved.template = template
        saved.save(update_fields=["template", "updated_at"])
        messages.success(request, f"Draft saved and “{template.name}” added to your templates.")
        return redirect("grant_edit", saved.pk)
    if action == "publish":
        try:
            services.publish(saved.pk)
        except services.InvalidTransition as exc:
            messages.error(request, f"Draft saved, but not published: {exc}")
            return redirect("grant_edit", saved.pk)
        messages.success(request, f"“{saved.title}” is published.")
        return redirect("grant_published_preview", saved.pk)
    messages.success(
        request,
        "Draft updated." if grant else f"Draft saved. Publish it to show it on {core_site_host()}.",
    )
    return redirect("grant_list")


def _preview(request: HttpRequest, form: GrantForm, grant: Grant | None) -> HttpResponse:
    """The posted form as an applicant will see it (design "Grants / Applicant view -
    Preview"); nothing is saved. ``?embed=1`` is the builder's overlay (an iframe): the
    page then has no bar of its own, and an unusable schema is a 400 with the reason
    instead of the builder page, so the JavaScript can show it."""
    embed = request.GET.get("embed") == "1"
    raw = form["form_schema"].value()
    try:
        schema = clean_schema(json.loads(raw) if isinstance(raw, str) else raw)
    except (ValueError, SchemaError) as exc:
        if embed:
            return HttpResponseBadRequest(f"The form cannot be previewed yet: {exc}")
        messages.error(request, f"The form cannot be previewed yet: {exc}")
        form.full_clean()
        return _builder(request, form, grant)
    # The dates the builder posted, for the "Closes" chip; an unparsable one is left out.
    date_field, time_field = forms.DateField(required=False), forms.TimeField(required=False)
    try:
        preview_grant = {
            "deadline": date_field.clean(request.POST.get("deadline") or None),
            "deadline_time": time_field.clean(request.POST.get("deadline_time") or None),
        }
    except forms.ValidationError:
        preview_grant = {"deadline": None, "deadline_time": None}
    # BootstrapForm, as the core's apply form: the same widget classes applicants get.
    applicant_form = build_form(schema, BootstrapForm)()
    return render(
        request,
        "org/grants/preview.html",
        {
            "grant": preview_grant,
            "title": request.POST.get("title") or (grant.title if grant else "New grant"),
            "description": request.POST.get("description", ""),
            "org_name": settings.ORG_NAME,
            **application_presentation(schema, applicant_form),
            "embed": embed,
            "back_url": reverse("grant_edit", args=[grant.pk])
            if grant
            else reverse("grant_create"),
        },
    )


@admin_required
def grant_published_preview(request: HttpRequest, grant_id: int) -> HttpResponse:
    grant = get_object_or_404(Grant, pk=grant_id, status=Grant.Status.PUBLISHED)
    form = build_form(grant.form_schema, BootstrapForm)()
    return render(
        request,
        "org/grants/preview.html",
        {
            "grant": grant,
            "title": grant.title,
            "description": grant.description,
            "org_name": settings.ORG_NAME,
            "published_preview": True,
            "back_url": reverse("grant_applications", args=[grant.pk]),
            "public_url": f"{settings.CORE_SITE_URL}/grants/{settings.ORG_SLUG}/{grant.public_id}/",
            **application_presentation(grant.form_schema, form),
        },
    )


def published(request: HttpRequest) -> HttpResponse:
    """Published grants (Dashboard / Granter - Published grants): every grant that is open
    or closed, with its applications, how many passed sign-off, how many are fully
    reviewed and each review panel's progress."""
    sort = "deadline" if request.GET.get("sort") == "deadline" else "recent"
    today = timezone.localdate()
    grants = list(
        Grant.objects.exclude(status=Grant.Status.DRAFT).annotate(
            application_count=Count("applications", distinct=True),
            eligible_count=Count(
                "applications",
                filter=~Q(applications__status__in=NOT_REVIEWABLE),
                distinct=True,
            ),
            today_count=Count(
                "applications", filter=Q(applications__received_at__date=today), distinct=True
            ),
        )
    )
    if sort == "deadline":
        grants.sort(key=lambda g: (g.deadline, g.title))
    else:
        grants.sort(key=lambda g: g.updated_at, reverse=True)
    panels = grant_panels([g.pk for g in grants])
    reviewed = _reviewed_counts([g.pk for g in grants])
    cards = [
        {
            "grant": grant,
            "panels": panels[grant.pk],
            "reviewers": sum(p.reviewers for p in panels[grant.pk]),
            "reviewed": reviewed.get(grant.pk, 0),
        }
        for grant in grants
    ]
    upcoming = [g.deadline for g in grants if g.status == Grant.Status.PUBLISHED]
    return render(
        request,
        "org/grants/published.html",
        {
            "cards": cards,
            "sort": sort,
            "next_deadline": min((d for d in upcoming if d >= today), default=None),
            "totals": {
                "applications": Application.objects.filter(grant__in=grants).count(),
                "panels": len({p.panel.pk for ps in panels.values() for p in ps}),
            },
        },
    )


def _reviewed_counts(grant_ids: list[int]) -> dict[int, int]:
    """grant id -> applications whose every assigned reviewer has sent an assessment."""
    assigned: dict[int, set[int]] = defaultdict(set)
    for application_id, member_id in Assignment.objects.filter(
        application__grant_id__in=grant_ids
    ).values_list("application_id", "member_id"):
        assigned[application_id].add(member_id)
    assessed: dict[int, set[int]] = defaultdict(set)
    for application_id, member_id in Assessment.objects.filter(
        application__grant_id__in=grant_ids
    ).values_list("application_id", "member_id"):
        assessed[application_id].add(member_id)
    counts: dict[int, int] = defaultdict(int)
    grant_of = dict(Application.objects.filter(pk__in=assigned).values_list("pk", "grant_id"))
    for application_id, members in assigned.items():
        if members <= assessed[application_id]:
            counts[grant_of[application_id]] += 1
    return counts


def grant_list(request: HttpRequest) -> HttpResponse:
    grants = Grant.objects.annotate(application_count=Count("applications"))
    return render(request, "org/grants/list.html", {"grants": grants})


@admin_required
def grant_create(request: HttpRequest) -> HttpResponse:
    """New grant: the builder page, and on POST whatever ``?action=`` asks (see
    ``_save_grant``)."""
    return _save_grant(request, None)


@admin_required
@board_card
def grant_edit(request: HttpRequest, grant_id: int) -> HttpResponse:
    grant = get_object_or_404(Grant, pk=grant_id)
    if grant.status != Grant.Status.DRAFT:
        messages.error(request, "Only drafts can be edited.")
        return redirect("grant_list")
    # Same page and actions as grant_create, for this draft.
    return _save_grant(request, grant)


@post_required
@admin_required
def grant_duplicate(request: HttpRequest, grant_id: int) -> HttpResponse:
    """A new draft with the same form, folder, category and template."""
    source = get_object_or_404(Grant, pk=grant_id)
    # The builder posts its current state; a list-page duplicate has no form payload.
    if "form_schema" in request.POST:
        form = GrantForm(request.POST, instance=source)
        if not form.is_valid():
            return _builder(request, form, source)
        source = form.save(commit=False)
    copy = Grant.objects.create(
        title=f"Copy of {source.title}"[:200],
        description=source.description,
        deadline=max(source.deadline, timezone.localdate()),
        deadline_time=source.deadline_time,
        form_schema=source.form_schema,
        folder=source.folder,
        category=source.category,
        template=source.template,
        created_by=request.user,
    )
    messages.success(request, f"“{copy.title}” was created as a new draft.")
    return redirect("grant_edit", copy.pk)


def grant_drafts(request: HttpRequest) -> HttpResponse:
    """Grant drafts (Grants / Drafts): folders, then the grants of one folder (or all)
    filtered by status."""
    folders = list(
        Folder.objects.annotate(
            grant_count=Count("grants"),
            published_count=Count("grants", filter=~Q(grants__status=Grant.Status.DRAFT)),
        )
    )
    folder = None
    if raw := request.GET.get("folder"):
        folder = next((f for f in folders if str(f.pk) == raw), None)
    status = request.GET.get("status", "all")
    if status not in ("all", "published", "unpublished"):
        status = "all"
    grants = Grant.objects.select_related("category", "folder")
    if folder is not None:
        grants = grants.filter(folder=folder)
    if status == "published":
        grants = grants.exclude(status=Grant.Status.DRAFT)
    elif status == "unpublished":
        grants = grants.filter(status=Grant.Status.DRAFT)
    grants = list(grants.order_by("-updated_at"))
    return render(
        request,
        "org/grants/drafts.html",
        {
            "folders": folders,
            "folder": folder,
            "status": status,
            "grants": grants,
            "total": Grant.objects.count(),
            "folder_form": NameForm(),
            "active": "grant_drafts",
        },
    )


def _name_error(form: NameForm) -> str:
    """The message for a refused name (empty or already taken), for messages.error."""
    return " ".join(str(e) for e in form.errors.get("name", [])) or "Enter a name."


def _name_action(
    request: HttpRequest, instance: Any, taken: Any, what: str, back: str
) -> HttpResponse:
    """Rename ``instance`` (a folder, category or template) from the posted ``name``,
    refusing a name another row of ``taken`` already uses, then go back to ``back``."""
    form = NameForm(request.POST, taken=taken.exclude(pk=instance.pk))
    if form.is_valid():
        instance.name = form.cleaned_data["name"]
        instance.save(update_fields=["name"])
        messages.success(request, f"{what} renamed to “{instance.name}”.")
    else:
        messages.error(request, _name_error(form))
    return redirect(back)


@post_required
@admin_required
def folder_create(request: HttpRequest) -> HttpResponse:
    """New folder from the drafts page; opens it on success."""
    form = NameForm(request.POST, taken=Folder.objects.all())
    if form.is_valid():
        folder = Folder.objects.create(name=form.cleaned_data["name"])
        messages.success(request, f"Folder “{folder.name}” created.")
        return redirect(f"{reverse('grant_drafts')}?folder={folder.pk}")
    messages.error(request, _name_error(form))
    return redirect("grant_drafts")


@post_required
@admin_required
def folder_rename(request: HttpRequest, folder_id: int) -> HttpResponse:
    """Rename a folder (the "…" menu on its card)."""
    folder = get_object_or_404(Folder, pk=folder_id)
    return _name_action(request, folder, Folder.objects.all(), "Folder", "grant_drafts")


@post_required
@admin_required
def folder_delete(request: HttpRequest, folder_id: int) -> HttpResponse:
    """Delete a folder; its grants stay (``Grant.folder`` is SET_NULL)."""
    folder = get_object_or_404(Folder, pk=folder_id)
    folder.delete()  # its grants keep existing, with no folder
    messages.success(request, f"Folder “{folder.name}” deleted. Its grants are kept.")
    return redirect("grant_drafts")


def category_list(request: HttpRequest) -> HttpResponse:
    """Categories with how many grants use each, plus the add form (admins)."""
    return render(
        request,
        "org/grants/categories.html",
        {
            "categories": Category.objects.annotate(grant_count=Count("grants")),
            "form": NameForm(),
            "active": "grant_drafts",
        },
    )


@post_required
@admin_required
def category_create(request: HttpRequest) -> HttpResponse:
    """New category from the categories page."""
    form = NameForm(request.POST, taken=Category.objects.all())
    if form.is_valid():
        category = Category.objects.create(name=form.cleaned_data["name"])
        messages.success(request, f"Category “{category.name}” created.")
    else:
        messages.error(request, _name_error(form))
    return redirect("category_list")


@post_required
@admin_required
def category_rename(request: HttpRequest, category_id: int) -> HttpResponse:
    """Rename a category; grants show the new name at once."""
    category = get_object_or_404(Category, pk=category_id)
    return _name_action(request, category, Category.objects.all(), "Category", "category_list")


@post_required
@admin_required
def category_delete(request: HttpRequest, category_id: int) -> HttpResponse:
    """Delete a category; grants that had it end up without one (SET_NULL)."""
    category = get_object_or_404(Category, pk=category_id)
    category.delete()
    messages.success(request, f"Category “{category.name}” deleted.")
    return redirect("category_list")


def template_list(request: HttpRequest) -> HttpResponse:
    """Saved templates with their use counts; rename/delete for the org's own ones."""
    return render(
        request,
        "org/grants/templates_list.html",
        {"templates": templates_with_use(), "active": "grant_drafts"},
    )


@post_required
@admin_required
def template_rename(request: HttpRequest, template_id: int) -> HttpResponse:
    """Rename one of the org's own templates (built-ins are refused)."""
    template = get_object_or_404(FormTemplate, pk=template_id)
    if template.is_builtin:
        messages.error(request, "Built-in templates cannot be renamed.")
        return redirect("template_list")
    return _name_action(request, template, FormTemplate.objects.all(), "Template", "template_list")


@post_required
@admin_required
def template_delete(request: HttpRequest, template_id: int) -> HttpResponse:
    """Delete one of the org's own templates (built-ins are refused). Grants based on
    it keep their forms; only their "based on" link goes (SET_NULL)."""
    template = get_object_or_404(FormTemplate, pk=template_id)
    if template.is_builtin:
        messages.error(request, "Built-in templates cannot be deleted.")
        return redirect("template_list")
    template.delete()  # grants based on it keep their forms
    messages.success(request, f"Template “{template.name}” deleted.")
    return redirect("template_list")


@post_required
@admin_required
def grant_publish(request: HttpRequest, grant_id: int) -> HttpResponse:
    get_object_or_404(Grant, pk=grant_id)
    try:
        grant = services.publish(grant_id)
    except services.InvalidTransition as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"“{grant.title}” is published.")
    return redirect("grant_list")


@post_required
@admin_required
def grant_close(request: HttpRequest, grant_id: int) -> HttpResponse:
    get_object_or_404(Grant, pk=grant_id)
    try:
        grant = services.close(grant_id)
    except services.InvalidTransition as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"“{grant.title}” is closed for new applications.")
    return redirect("grant_list")


@post_required
@admin_required
def grant_signature_deadline(request: HttpRequest, grant_id: int) -> HttpResponse:
    grant = get_object_or_404(Grant, pk=grant_id)
    form = SignatureDeadlineForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a valid date.")
    else:
        try:
            told = services.set_signature_deadline(
                grant.pk, form.cleaned_data["signature_deadline"]
            )
        except services.InvalidTransition as exc:
            messages.error(request, str(exc))
        else:
            note = f" {told} open request{'s' if told != 1 else ''} updated." if told else ""
            messages.success(request, f"Organisations can now sign until the new date.{note}")
    return redirect("grant_applications", grant.pk)
