"""The researcher profile page.

``/profile/`` is one page with tabs; Edit profile, Edit data, the ORCID iD dialog and the
ORCID import's loader and review are dialogs rendered by the server over that page, so
every step works without JavaScript. The import itself runs in ``core-orcid``.
"""

import json
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from it42.common.http import post_required

from .forms import (
    DocumentUploadForm,
    OrcidStartForm,
    PersonalInfoForm,
    ProfileForm,
    ResearchAreasForm,
)
from .importer import STAGES
from .models import CVEntry, Document, OrcidImport, Profile, Source
from .sections import SECTIONS, Section
from .services import PROFILE_FIELDS, apply_review, clear_orcid, describe
from .stats import (
    current_employment,
    cv_rows,
    key_facts,
    load_cv,
    profile_steps,
    record_tiles,
    sort_rows,
)

Status = OrcidImport.Status
SORTS = {"newest": "Newest first", "oldest": "Oldest first", "section": "Section A–Z"}  # noqa: RUF001
REVIEW_SHOWN = 3  # rows shown per section in the review before "Show all"


def profile_for(user: object) -> Profile:
    profile, _ = Profile.objects.get_or_create(
        user=user,
        defaults={
            "first_name": getattr(user, "first_name", "") or "",
            "last_name": getattr(user, "last_name", "") or "",
        },
    )
    return profile


def section_or_404(key: str) -> Section:
    try:
        return SECTIONS[key]
    except KeyError as exc:
        raise Http404("No such section") from exc


def section_url(section: Section) -> str:
    return f"{reverse('profile_data')}#{section.key}"


def renumber(entries: list[CVEntry], model: type[CVEntry]) -> None:
    """Make ``sort_order`` equal to the list position; called inside a transaction."""
    for index, entry in enumerate(entries):
        entry.sort_order = index
    model.objects.bulk_update(entries, ["sort_order"])


def visible_import(profile: Profile) -> OrcidImport | None:
    """The import whose dialog the page shows: an active one, or a failure not yet seen."""
    job = OrcidImport.objects.filter(profile=profile).first()
    if job is None:
        return None
    if job.is_active or job.status == Status.FAILED:
        return job
    return None


def review_groups(job: OrcidImport) -> list[dict[str, Any]]:
    """Review items by section, with the first rows shown and the rest folded."""
    groups = []
    for key, section in SECTIONS.items():
        items = [i for i in job.items if i["section"] == key]
        if not items:
            continue
        # New and changed rows first: they are what needs a decision.
        items.sort(key=lambda i: (i["state"] == "on_cv", i["n"]))
        groups.append(
            {
                "section": section,
                "items": items[:REVIEW_SHOWN],
                "more": items[REVIEW_SHOWN:],
                "count": len(items),
            }
        )
    return groups


def page_context(request: HttpRequest, profile: Profile, **extra: Any) -> dict[str, Any]:
    """Everything the tab page needs, private or public."""
    cv = load_cv(profile)
    rows = cv_rows(cv)
    documents = list(Document.objects.filter(user_id=profile.user_id))
    query = request.GET.get("q", "").strip()
    chosen = request.GET.get("section", "")
    chosen = chosen if chosen in SECTIONS else ""
    order = request.GET.get("sort", "newest")
    order = order if order in SORTS else "newest"
    newest = {id(row): index for index, row in enumerate(rows)}  # rows come newest first
    table = [
        (
            row,
            (not chosen or row.section.key == chosen)
            and (not query or query.casefold() in row.search_text),
            newest[id(row)],
        )
        for row in sort_rows(rows, order)
    ]
    steps = profile_steps(profile, bool(rows), bool(documents))
    done = sum(s.done for s in steps)
    updated = max(
        [r.entry.updated_at for r in rows]
        + ([profile.orcid_imported_at] if profile.orcid_imported_at else []),
        default=None,
    )
    return {
        "profile": profile,
        "employment": current_employment(cv),
        "sections": [(section, cv[key]) for key, section in SECTIONS.items()],
        "rows": rows,
        "table_rows": table,
        "shown_count": sum(1 for _, visible, _ in table if visible),
        "chips": [(s, len(cv[key])) for key, s in SECTIONS.items() if cv[key]],
        "cv_query": query,
        "cv_section": chosen,
        "cv_sort": order,
        "sorts": SORTS,
        "facts": key_facts(cv),
        "tiles": record_tiles(cv),
        "documents": documents,
        "steps": steps,
        "steps_done": done,
        "steps_total": len(steps),
        "steps_percent": round(100 * done / len(steps)),
        "next_step": next((s for s in steps if not s.done), None),
        "last_updated": updated,
        **extra,
    }


def render_profile(
    request: HttpRequest, profile: Profile, overlay: str = "", **extra: Any
) -> HttpResponse:
    job = visible_import(profile)
    if job is not None and not overlay:
        overlay = {
            Status.QUEUED: "orcid_loader",
            Status.RUNNING: "orcid_loader",
            Status.REVIEW: "orcid_review",
        }.get(Status(job.status), "orcid_failed")
    context = page_context(request, profile, overlay=overlay, job=job, **extra)
    context.setdefault("personal_form", PersonalInfoForm(instance=profile))
    context.setdefault("upload", DocumentUploadForm())
    context["editing_personal"] = context.get("editing_personal") or (
        request.GET.get("edit") == "personal"
    )
    if job is not None and overlay in ("orcid_loader", "orcid_failed"):
        context["stage_text"] = STAGES.get(job.stage, STAGES["queued"])
    if job is not None and overlay == "orcid_review":
        context["groups"] = review_groups(job)
        context["review_open"] = sum(1 for i in job.items if i["state"] != "on_cv" and i["include"])
        context["review_total"] = sum(1 for i in job.items if i["state"] != "on_cv")
        adds = {key: 0 for key in SECTIONS}
        for i in job.items:
            if i["state"] == "new" and i["include"]:
                adds[i["section"]] += 1
        context["review_adds"] = [(SECTIONS[k], n) for k, n in adds.items() if n]
        context["review_fills"] = [
            name.replace("_", " ")
            for name in PROFILE_FIELDS
            if job.profile_fields.get(name) and not getattr(profile, name)
        ]
    return render(request, "core/profiles/profile.html", context)


@login_required
def profile(request: HttpRequest) -> HttpResponse:
    instance = profile_for(request.user)
    extra: dict[str, Any] = {}
    if request.method == "POST" and "save_personal" in request.POST:
        form = PersonalInfoForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Personal info saved.")
            return redirect(f"{reverse('profile')}#personal")
        extra = {"personal_form": form, "editing_personal": True}
    elif request.method == "POST" and "upload" in request.POST:
        upload = DocumentUploadForm(request.POST, request.FILES)
        if upload.is_valid():
            original = upload.cleaned_data["file"].name[:255]
            document = Document(
                user=request.user,
                original_name=original,
                sha256=upload.sha256,
                size=len(upload.content),
            )
            document.file.save(original, ContentFile(upload.content), save=True)
            messages.success(request, f"Uploaded {original}.")
            return redirect(f"{reverse('profile')}#cv-upload")
        extra = {"upload": upload}
    return render_profile(request, instance, **extra)


@login_required
def profile_edit(request: HttpRequest) -> HttpResponse:
    instance = profile_for(request.user)
    form = ProfileForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile saved.")
        return redirect("profile")
    return render_profile(request, instance, "edit_profile", form=form)


@login_required
def profile_data(request: HttpRequest) -> HttpResponse:
    instance = profile_for(request.user)
    areas_form = ResearchAreasForm(
        request.POST or None, initial={"areas": "\n".join(instance.research_areas)}
    )
    if request.method == "POST" and areas_form.is_valid():
        instance.research_areas = areas_form.cleaned_data["areas"]
        instance.save(update_fields=["research_areas"])
        messages.success(request, "Research areas saved.")
        return redirect(f"{reverse('profile_data')}#areas")
    return render_profile(request, instance, "edit_data", areas_form=areas_form)


@login_required
def profile_public(request: HttpRequest) -> HttpResponse:
    instance = profile_for(request.user)
    return render(request, "core/profiles/public.html", page_context(request, instance))


@login_required
def cv_add(request: HttpRequest, section: str) -> HttpResponse:
    sec = section_or_404(section)
    owner = profile_for(request.user)
    form = sec.form(request.POST or None)
    form.instance.profile = owner
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        last = sec.model.objects.filter(profile=owner).order_by("-sort_order").first()
        entry.sort_order = last.sort_order + 1 if last else 0
        entry.save()
        messages.success(request, f"Added the {sec.singular}.")
        return redirect(section_url(sec))
    return render(
        request,
        "core/profiles/entry_form.html",
        {"form": form, "section": sec, "entry": None},
    )


@login_required
def cv_edit(request: HttpRequest, section: str, entry_id: int) -> HttpResponse:
    sec = section_or_404(section)
    owner = profile_for(request.user)
    entry = get_object_or_404(sec.model, pk=entry_id, profile=owner)
    form = sec.form(request.POST or None, instance=entry)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        if saved.source == Source.ORCID and form.has_changed():
            saved.source = Source.ORCID_EDITED
        saved.save()
        messages.success(request, f"Saved the {sec.singular}.")
        return redirect(section_url(sec))
    return render(
        request,
        "core/profiles/entry_form.html",
        {"form": form, "section": sec, "entry": entry},
    )


@post_required
@login_required
def cv_delete(request: HttpRequest, section: str, entry_id: int) -> HttpResponse:
    sec = section_or_404(section)
    entry = get_object_or_404(sec.model, pk=entry_id, profile=profile_for(request.user))
    entry.delete()
    messages.success(request, f"Deleted the {sec.singular}.")
    return redirect(section_url(sec))


@post_required
@login_required
def cv_move(request: HttpRequest, section: str, entry_id: int) -> HttpResponse:
    """Move one entry up or down: the keyboard and no-JavaScript path."""
    sec = section_or_404(section)
    owner = profile_for(request.user)
    direction = request.POST.get("direction")
    if direction not in ("up", "down"):
        return HttpResponseBadRequest("direction must be up or down")
    with transaction.atomic():
        entries = list(sec.model.objects.select_for_update().filter(profile=owner))
        ids = [e.pk for e in entries]
        if entry_id not in ids:
            raise Http404("No such entry")
        index = ids.index(entry_id)
        target = index - 1 if direction == "up" else index + 1
        if 0 <= target < len(entries):
            entries[index], entries[target] = entries[target], entries[index]
        renumber(entries, sec.model)
    return redirect(section_url(sec))


@post_required
@login_required
def cv_reorder(request: HttpRequest, section: str) -> HttpResponse:
    """Store a full new order posted by ``sortable.js`` as ``{"order": [ids]}``."""
    sec = section_or_404(section)
    owner = profile_for(request.user)
    try:
        order = json.loads(request.body.decode())["order"]
        wanted = [int(x) for x in order]
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return HttpResponseBadRequest("expected a JSON object with an order list")
    with transaction.atomic():
        entries = {e.pk: e for e in sec.model.objects.select_for_update().filter(profile=owner)}
        if sorted(wanted) != sorted(entries) or len(set(wanted)) != len(wanted):
            return HttpResponseBadRequest("the order must list every entry exactly once")
        renumber([entries[pk] for pk in wanted], sec.model)
    return JsonResponse({"ok": True})


# ORCID import ------------------------------------------------------------------------


def job_for(request: HttpRequest, import_id: object) -> OrcidImport:
    return get_object_or_404(OrcidImport, public_id=import_id, profile=profile_for(request.user))


def locked_review(request: HttpRequest, import_id: object) -> OrcidImport:
    """The import, locked, if it waits for a review; call inside a transaction."""
    job = job_for(request, import_id)
    job = OrcidImport.objects.select_for_update().get(pk=job.pk)
    if job.status != Status.REVIEW:
        raise Http404("This import is not waiting for a review")
    return job


def item_of(job: OrcidImport, n: int) -> dict[str, Any]:
    if not 0 <= n < len(job.items) or job.items[n]["state"] == "on_cv":
        raise Http404("No such item")
    return job.items[n]


@login_required
def orcid_start(request: HttpRequest) -> HttpResponse:
    """GET: the ORCID iD dialog. POST: queue an import for the background runner."""
    owner = profile_for(request.user)
    form = OrcidStartForm(request.POST or None, initial={"orcid": owner.orcid})
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                OrcidImport.objects.filter(profile=owner, status=Status.FAILED).update(
                    status=Status.DISMISSED
                )
                OrcidImport.objects.create(
                    profile=owner, orcid=form.cleaned_data["orcid"], stage="queued"
                )
        except IntegrityError:
            messages.info(request, "An ORCID import is already in progress.")
        return redirect("profile")
    return render_profile(request, owner, "orcid_start", orcid_form=form)


@login_required
def orcid_status(request: HttpRequest, import_id: object) -> HttpResponse:
    job = job_for(request, import_id)
    return JsonResponse(
        {
            "status": job.status,
            "stage": STAGES.get(job.stage, STAGES["queued"]),
            "progress": job.progress,
            "error": job.error,
        }
    )


@post_required
@login_required
def orcid_cancel(request: HttpRequest, import_id: object) -> HttpResponse:
    """Cancel a running import, discard one under review, or close a failure."""
    job = job_for(request, import_id)
    with transaction.atomic():
        job = OrcidImport.objects.select_for_update().get(pk=job.pk)
        if job.is_active:
            job.status, job.finished_at = Status.CANCELLED, timezone.now()
            job.save(update_fields=["status", "finished_at", "updated_at"])
            messages.info(request, "ORCID import cancelled. Nothing was changed.")
        elif job.status == Status.FAILED:
            job.status = Status.DISMISSED
            job.save(update_fields=["status", "updated_at"])
        elif job.status == Status.APPLIED:
            messages.info(request, "This ORCID import was already added to your profile.")
    return redirect("profile")


@post_required
@login_required
def orcid_item(request: HttpRequest, import_id: object, n: int) -> HttpResponse:
    """Include or exclude one new or changed item."""
    action = request.POST.get("action")
    if action not in ("include", "exclude"):
        return HttpResponseBadRequest("action must be include or exclude")
    with transaction.atomic():
        job = locked_review(request, import_id)
        item_of(job, n)["include"] = action == "include"
        job.save(update_fields=["items", "updated_at"])
    return redirect(f"{reverse('profile')}#item-{n}")


@login_required
def orcid_item_edit(request: HttpRequest, import_id: object, n: int) -> HttpResponse:
    """Edit a staged item on its section's form before it is added."""
    owner = profile_for(request.user)
    job = job_for(request, import_id)
    if job.status != Status.REVIEW:
        return redirect("profile")
    item = item_of(job, n)
    sec = SECTIONS[item["section"]]
    form = sec.form(request.POST or None, instance=sec.model(profile=owner, **item["fields"]))
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        names = set(item["fields"]) | set(form.fields)
        fields = {name: getattr(entry, name) for name in sorted(names)}
        with transaction.atomic():
            job = locked_review(request, import_id)
            item = item_of(job, n)
            item.update(fields=fields, include=True, edited=True, **describe(sec.key, fields))
            job.save(update_fields=["items", "updated_at"])
        return redirect(f"{reverse('profile')}#item-{n}")
    return render_profile(request, owner, "orcid_item", item=item, item_section=sec, item_form=form)


@post_required
@login_required
def orcid_keyword(request: HttpRequest, import_id: object, n: int) -> HttpResponse:
    with transaction.atomic():
        job = locked_review(request, import_id)
        if not 0 <= n < len(job.keywords):
            raise Http404("No such keyword")
        job.keywords[n]["include"] = not job.keywords[n]["include"]
        job.save(update_fields=["keywords", "updated_at"])
    return redirect(f"{reverse('profile')}#areas-review")


@post_required
@login_required
def orcid_done(request: HttpRequest, import_id: object) -> HttpResponse:
    job = job_for(request, import_id)
    try:
        summary = apply_review(job)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, summary.message())
    return redirect("profile")


@post_required
@login_required
def orcid_clear(request: HttpRequest) -> HttpResponse:
    deleted = clear_orcid(profile_for(request.user))
    messages.success(request, f"Removed {deleted} imported entries; edited ones were kept.")
    return redirect(f"{reverse('profile_data')}#orcid")


@post_required
@login_required
def delete_document(request: HttpRequest, document_id: int) -> HttpResponse:
    document = get_object_or_404(Document, pk=document_id, user_id=request.user.pk)
    document.file.delete(save=False)
    document.delete()
    messages.success(request, f"Deleted {document.original_name}.")
    return redirect(f"{reverse('profile')}#cv-upload")
