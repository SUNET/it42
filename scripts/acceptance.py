#!/usr/bin/env python3
"""End-to-end acceptance checks against the running stack.

Run from the repository root after `docker compose up -d`:

    uv run python scripts/acceptance.py

It drives the sites like a browser (scripts/lib/browser.py), uses `docker compose`
for the steps a browser can't do (stopping a worker, querying a database), and
finally runs scripts/check-isolation.sh. It can be re-run; it reuses g1 and g2 and
creates fresh grants for the sign-off and reliability checks each time.
"""

import json
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.browser import DOMAIN, DOMAIN_RE, Browser, Page

ROOT = Path(__file__).resolve().parent.parent
G1 = "g1: Sustainable campus research"
G2 = "g2: Open source tools for teaching"
SCHEMA = [
    {"name": "applicant_name", "label": "Your name", "type": "text", "required": True},
    {"name": "applicant_email", "label": "Email address", "type": "email", "required": True},
    # Optional on g1/g2: a2 names none, so those applications go straight to review.
    {
        "name": "administrating_organisation",
        "label": "Administrating organisation",
        "type": "research_org",
        "required": False,
    },
    # Names are derived from the labels by the org when the draft is saved.
    {"label": "The project", "type": "heading"},
    {"label": "Project title", "type": "text", "required": True},
    {"label": "Summary", "type": "textarea", "required": True, "rows": 4},
    {"label": "Budget (SEK)", "type": "number", "required": True, "min": 0},
    {
        "label": "Research area",
        "type": "select",
        "required": True,
        "options": ["Energy", "Water", "Mobility"],
    },
    {"label": "I accept the conditions", "type": "checkbox", "required": True},
]
ANSWERS = {
    "project_title": "Campus solar pilot",
    "summary": "Measure and reduce energy use in two buildings.",
    "budget_sek": "250000",
    "research_area": "Energy",
    "i_accept_the_conditions": "on",
}
# The sign-off grant requires the administrating organisation.
SIGNED_SCHEMA = [{**f, "required": True} if f.get("type") == "research_org" else f for f in SCHEMA]
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"

results: list[tuple[bool, str]] = []


def check(ok: bool, message: str) -> bool:
    results.append((ok, message))
    print(f"  {'\033[32mPASS\033[0m' if ok else '\033[31mFAIL\033[0m'} {message}")
    return ok


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


def run(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(args, cwd=ROOT, input=stdin, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {proc.stderr.strip()[-500:]}")
    return proc.stdout.strip()


def django(service: str, code: str) -> str:
    return run(
        "docker", "compose", "exec", "-T", service,
        "python", "manage.py", "shell", "--no-imports", "-v", "0", "-c", code,
    )  # fmt: skip


def wait_for(condition: Callable[[], Any], timeout: float, interval: float = 0.5) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = condition()
        if value or time.monotonic() >= deadline:
            return value
        time.sleep(interval)


def alerts(page: Page) -> list[str]:
    return re.findall(r'role="alert">([^<]*)', page.body)


def statuses(page: Page) -> list[str]:
    return re.findall(r'data-status="([^"]*)"', page.body)


# --- helpers that act like a user -------------------------------------------------


def ensure_grant(
    browser: Browser,
    site: str,
    title: str,
    description: str,
    schema: list[dict[str, Any]] = SCHEMA,
) -> None:
    grants = browser.get(f"https://{site}/grants/")
    if title in grants.body:
        return
    page = browser.get(f"https://{site}/grants/new/")
    page = browser.submit(
        page,
        "/grants/new/",
        title=title,
        description=description,
        deadline=(date.today() + timedelta(days=60)).isoformat(),
        form_schema=json.dumps(schema),
    )
    # Publish the draft we just created (the newest one is listed first).
    browser.submit(page, "/publish/")


def public_grant_path(title: str) -> str | None:
    calls = Browser().get(f"https://{DOMAIN}/calls/")
    for path, link_title in re.findall(
        r'href="(/grants/o[12]/[0-9a-f-]+/)">([^<]*)</a>', calls.body
    ):
        if link_title.strip() == title:
            return path
    return None


def upload_pdf(browser: Browser) -> str:
    page = browser.get(f"https://{DOMAIN}/profile/")
    existing = re.search(r"acceptance-plan\.pdf", page.body)
    if not existing:
        upload = page.forms()[-1]
        browser.request(
            upload["action"],
            {"csrfmiddlewaretoken": upload["fields"]["csrfmiddlewaretoken"], "upload": "1"},
            files={"file": ("acceptance-plan.pdf", PDF)},
            referer=page.url,
        )
    return "acceptance-plan.pdf"


def apply(browser: Browser, grant_path: str, answers: dict[str, str] = ANSWERS) -> str | None:
    """Apply with the uploaded PDF, if any; return the application id."""
    page = browser.get(f"https://{DOMAIN}{grant_path}apply/")
    match = re.search(r"/my/applications/([0-9a-f-]+)/", page.url)
    if match:  # already applied: the apply page redirects to the application
        return match.group(1)
    doc = re.search(r'name="documents" value="(\d+)"', page.body)
    fields = {**page.form("/apply/")["fields"], **answers, "confirm": "on"}
    if doc:
        fields["documents"] = doc.group(1)
    result = browser.request(page.form("/apply/")["action"], fields, referer=page.url)
    match = re.search(r"/my/applications/([0-9a-f-]+)/", result.url)
    return match.group(1) if match else None


def application_status(browser: Browser, app_id: str) -> str | None:
    found = statuses(browser.get(f"https://{DOMAIN}/my/applications/{app_id}/"))
    return found[0] if found else None


def first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    if match is None:
        raise AssertionError(f"{pattern!r} not found")
    return match.group(1)


def org_application_url(browser: Browser, site: str, grant_title: str, applicant: str) -> str:
    grants = browser.get(f"https://{site}/grants/")
    block = grants.body.split(grant_title, 1)[1]
    grant_path = first_match(r'href="(/grants/\d+/applications/)"', block)
    listing = browser.get(f"https://{site}{grant_path}")
    row = listing.body.split(applicant, 1)[1]
    return f"https://{site}" + first_match(r'href="(/applications/\d+/)"', row)


# --- the checks -------------------------------------------------------------------


def check_setup() -> None:
    section("Setup")
    services = [
        json.loads(line) for line in run("docker", "compose", "ps", "--format", "json").splitlines()
    ]
    unhealthy = [s["Service"] for s in services if "(healthy)" not in s["Status"]]
    check(
        len(services) == 18 and not unhealthy,
        f"{len(services)} services running, unhealthy: {unhealthy or 'none'}",
    )
    for host in (
        DOMAIN,
        f"fo1.{DOMAIN}",
        f"fo2.{DOMAIN}",
        f"fo1-review.{DOMAIN}",
        f"fo2-review.{DOMAIN}",
        f"ro.{DOMAIN}",
        f"idp.{DOMAIN}",
        f"mq.{DOMAIN}",
    ):
        try:
            page = Browser().get(f"https://{host}/")
            check(page.status == 200, f"https://{host}/ loads with a trusted certificate")
        except Exception as exc:
            check(False, f"https://{host}/: {exc}")


def check_grants(staff1: Browser, staff2: Browser) -> None:
    section("Grants")
    for browser, site, subject in (
        (staff1, f"fo1.{DOMAIN}", "staff1"),
        (staff2, f"fo2.{DOMAIN}", "staff2"),
    ):
        browser.login(site, subject)  # ORG_BOOTSTRAP_ADMINS in env/<org>.env makes them admins
        check(
            "Call board" in browser.get(f"https://{site}/").body,
            f"{subject} is an admin on {site} by default",
        )
    ensure_grant(
        staff1, f"fo1.{DOMAIN}", G1, "Funding for research on sustainable campus energy use."
    )
    ensure_grant(
        staff2, f"fo2.{DOMAIN}", G2, "Support for open source software used in university teaching."
    )
    found = wait_for(lambda: public_grant_path(G1) and public_grant_path(G2), timeout=10)
    calls = Browser().get(f"https://{DOMAIN}/calls/").body
    check(
        bool(found) and "Org 1" in calls and "Org 2" in calls,
        f"an anonymous visitor sees g1 (Org 1) and g2 (Org 2) on {DOMAIN}/calls/",
    )


def check_drafts() -> None:
    section("Drafts")
    a3 = Browser()
    a3.login(DOMAIN, "a3")
    path = public_grant_path(G1)
    check(path is not None, "g1 is listed for a3")
    if not path:
        return
    marker = f"Draft {uuid.uuid4().hex[:8]}"
    page = a3.get(f"https://{DOMAIN}{path}apply/")
    form = page.form("/apply/")
    # No confirmation and required fields left empty: a draft keeps the form as it is.
    saved = a3.request(
        form["action"],
        {**form["fields"], "project_title": marker, "summary": "", "save_draft": ""},
        referer=page.url,
    )
    check(
        saved.url.endswith(f"{path}apply/") and f'value="{marker}"' in saved.body,
        "a3 saves an incomplete draft of g1 and gets it back on the form",
    )
    board = a3.get(f"https://{DOMAIN}/my/applications/")
    check(G1 in draft_column(board), "the draft is in the draft column of a3's board")
    delete = board.form("/my/drafts/")
    after = a3.request(delete["action"], delete["fields"], referer=board.url)
    check(G1 not in draft_column(after), "a3 deletes the draft")


def draft_column(page: Page) -> str:
    return page.body.split('id="col-draft"', 1)[-1].split('id="col-submitted"', 1)[0]


def check_applying(a2: Browser) -> dict[str, str]:
    section("Applying")
    a2.login(DOMAIN, "a2")
    upload_pdf(a2)
    ids: dict[str, str] = {}
    started = time.monotonic()
    for key, title in (("g1", G1), ("g2", G2)):
        path = public_grant_path(title)
        app_id = apply(a2, path) if path else None
        check(app_id is not None, f"a2 has an application to {key}")
        if app_id:
            ids[key] = app_id
    acknowledged = wait_for(
        lambda: (
            len(ids) == 2
            and all(application_status(a2, i) not in (None, "submitted") for i in ids.values())
        ),
        timeout=5,
    )
    elapsed = time.monotonic() - started
    listing = statuses(a2.get(f"https://{DOMAIN}/my/applications/"))
    # On a fresh stack both are "received"; on a re-run the review loop has moved g1 on.
    check(
        bool(acknowledged),
        f"/my/applications/ shows both acknowledged by the orgs ({elapsed:.1f}s; {listing})",
    )
    return ids


def check_org_views(staff1: Browser, staff2: Browser, ids: dict[str, str]) -> None:
    section("Org views")
    for browser, site, own, other, own_key, other_key in (
        (staff1, f"fo1.{DOMAIN}", G1, G2, "g1", "g2"),
        (staff2, f"fo2.{DOMAIN}", G2, G1, "g2", "g1"),
    ):
        url = org_application_url(browser, site, own, "Oskar Bergström")
        pages = [browser.get(f"https://{site}{p}").body for p in ("/", "/grants/")]
        pages.append(browser.get(url).body)
        check("Oskar Bergström" in pages[-1], f"{site} staff see a2's {own_key} application")
        leaked = [
            m
            for m in (other, other.split(":")[0] + ":", ids.get(other_key, "-"))
            if any(m in p for p in pages)
        ]
        check(not leaked, f"{site} shows no trace of {other_key} ({leaked or 'nothing found'})")


def check_review_loop(staff1: Browser, a2: Browser, ids: dict[str, str]) -> str:
    """Returns the marker written into the internal review note."""
    section("Review loop")
    token = uuid.uuid4().hex[:8]
    note_marker = f"NOTE-{uuid.uuid4().hex[:12]}"
    url = org_application_url(staff1, f"fo1.{DOMAIN}", G1, "Oskar Bergström")
    page = staff1.get(url)
    page = staff1.submit(page, "/status/", status="under_review")
    page = staff1.submit(page, "/status/", status="needs_info")
    page = staff1.submit(
        page, "/questions/", text=f"Please break down the budget by year ({token})."
    )
    page = staff1.submit(page, "/notes/", text=f"{note_marker}: budget looks padded.")
    check(any("Note added" in a for a in alerts(page)), "staff1 added an internal review note")
    detail_url = f"https://{DOMAIN}/my/applications/{ids['g1']}/"
    seen = wait_for(
        lambda: (
            (p := a2.get(detail_url))
            and token in p.body
            and statuses(p)[:1] == ["needs_info"]
            and p
        ),
        timeout=5,
    )
    check(bool(seen), "a2 sees the new status (Needs info) and the question")
    if seen:
        check(note_marker not in seen.body, "a2 does not see the review note")
        question_form = [f for f in seen.forms() if "/answer/" in f["action"]][-1]
        a2.request(
            question_form["action"],
            {
                **question_form["fields"],
                "answer": f"2027: 150 000 SEK, 2028: 100 000 SEK ({token}).",
            },
            referer=detail_url,
        )
    answered = wait_for(lambda: f"100 000 SEK ({token})" in staff1.get(url).body, timeout=5)
    check(bool(answered), f"a2's answer appears on fo1.{DOMAIN}")
    return note_marker


def _stamp(dt: datetime) -> str:
    """A value for a datetime-local input (interpreted in the server's time zone)."""
    return dt.strftime("%Y-%m-%dT%H:%M")


def check_review_panels(staff1: Browser, note_marker: str) -> None:
    """A panel on fo1 reviews a2's g1 application on fo1-review.it42.vr."""
    section("Review panels")
    site, rsite = f"fo1.{DOMAIN}", f"fo1-review.{DOMAIN}"
    token = uuid.uuid4().hex[:8]
    now = datetime.now()
    day = timedelta(days=1)

    # staff1 creates (or reuses) the panel, seats r1-r3 by email and attaches g1
    panels = staff1.get(f"https://{site}/review/")
    found = re.search(r'href="(/review/\d+/)">\s*<h2[^>]*>Panel g1<', panels.body)
    if found:
        page = staff1.get(f"https://{site}{found.group(1)}")
    else:
        page = staff1.get(f"https://{site}/review/new/")
        page = staff1.submit(page, "/review/new/", name="Panel g1", description="Acceptance panel")
    panel_url = page.url
    check(
        re.fullmatch(rf"https://fo1\.{DOMAIN_RE}/review/\d+/", panel_url) is not None,
        "staff1 has the panel",
    )
    seats = {
        "ingrid.nystrom@umu.se": "chairperson",
        "peter.lund@chalmers.se": "reviewer",
        "sara.ekholm@liu.se": "supporting_admin",
    }
    for email, role in seats.items():
        if f'data-seat="{email}"' not in page.body:
            page = staff1.submit(page, "/seats/add/", email=email, role=role)
    check(
        all(f'data-seat="{e}"' in page.body for e in seats),
        "r1 (chair), r2 (reviewer), r3 (support) seated by email",
    )
    option = re.search(rf'<option value="(\d+)">{re.escape(G1)}</option>', page.body)
    if option:
        page = staff1.submit(page, "/grants/link/", grant_id=option.group(1))
    check(
        G1 in page.body.split('id="grants"', 1)[1].split('id="tasks"', 1)[0],
        "g1 attached to the panel",
    )

    # tasks: all three windows open now; a meeting next week
    def set_task(kind: str, title: str, starts: datetime, ends: datetime) -> None:
        nonlocal page
        page = staff1.get(panel_url)
        if f'data-task="{kind}"' in page.body:
            block = page.body.split(f'data-task="{kind}"', 1)[1]
            form_page = staff1.get(
                f"https://{site}" + first_match(r'href="(/review/\d+/tasks/\d+/edit/)"', block)
            )
        else:
            form_page = staff1.get(f"{panel_url}tasks/new/")
        page = staff1.submit(
            form_page,
            "/tasks/",
            kind=kind,
            title=title,
            starts_at=_stamp(starts),
            ends_at=_stamp(ends),
        )

    set_task("conflict_and_competence", "Conflicts and competence", now - 2 * day, now + 2 * day)
    set_task("assessment", "Assessments and preliminary statements", now - 2 * day, now + 2 * day)
    set_task("final_statement", "Final statements", now - 2 * day, now + 2 * day)
    check(
        page.body.count("data-task=") >= 3 and page.body.count(">open<") >= 3,
        "three tasks are open",
    )
    if "Panel meeting" not in page.body:
        form_page = staff1.get(f"{panel_url}meetings/new/")
        page = staff1.submit(
            form_page,
            "/meetings/",
            title="Panel meeting",
            starts_at=_stamp(now + 7 * day),
            ends_at="",
            location="Room 2",
            notes="",
        )
    check("Panel meeting" in page.body and "Room 2" in page.body, "a meeting is scheduled")

    # assign r1 and r2 to a2's g1 application
    app_id = first_match(
        r"/applications/(\d+)/", org_application_url(staff1, site, G1, "Oskar Bergström")
    )
    assign_page = staff1.get(f"{panel_url}applications/{app_id}/")
    labels = dict(
        re.findall(r'name="seat_(\d+)"[^>]*>\s*<label[^>]*>\s*([^<]*?)\s*<', assign_page.body)
    )
    wanted = {sid for sid, label in labels.items() if label.lower().startswith(("ingrid", "peter"))}
    assign_form = assign_page.form("/assign/")
    page = staff1.request(
        assign_form["action"],
        {
            "csrfmiddlewaretoken": assign_form["fields"]["csrfmiddlewaretoken"],
            **{f"seat_{sid}": "on" for sid in wanted},
        },
        referer=assign_page.url,
    )
    check(
        len(wanted) == 2 and any("2 reviewers assigned" in a for a in alerts(page)),
        "r1 and r2 assigned to a2's application",
    )

    # r1 and r2 review on the reviewer site
    r1, r2, r3 = Browser(), Browser(), Browser()
    app_urls: dict[str, str] = {}
    for name, browser in (("r1", r1), ("r2", r2)):
        home = browser.login(rsite, name)
        check(home.status == 200 and "Panel g1" in home.body, f"{name} sees Panel g1 on {rsite}")
        panel_page = browser.get(
            f"https://{rsite}" + first_match(r'href="(/panels/\d+/)"', home.body)
        )
        app_urls[name] = f"https://{rsite}" + first_match(
            r'href="(/panels/\d+/applications/\d+/)">Oskar', panel_page.body
        )
        app_page = browser.get(app_urls[name])
        check(
            "Campus solar pilot" in app_page.body
            and "acceptance-plan.pdf" in app_page.body
            and note_marker not in app_page.body
            and "Review notes" not in app_page.body
            and "Ask a question" not in app_page.body,
            f"{name} sees the answers and PDF, not the status, questions or review notes",
        )
        app_page = browser.submit(
            app_page, "/declaration/", competence="high" if name == "r1" else "medium"
        )
        app_page = browser.submit(
            app_page,
            "/assessment/",
            assessment=f"ASSESS-{token}-{name}",
            preliminary_statement=f"STATEMENT-{token}-{name}",
            preliminary_grade="8" if name == "r1" else "6",
        )
        check(
            any("Assessment saved" in a for a in alerts(app_page))
            and f"ASSESS-{token}-{name}" in app_page.body,
            f"{name} declared competence and saved an assessment",
        )
    r1_page, r2_page = r1.get(app_urls["r1"]), r2.get(app_urls["r2"])
    check(
        f"ASSESS-{token}-r2" not in r1_page.body and f"ASSESS-{token}-r1" not in r2_page.body,
        "before the deadline each reviewer sees only their own assessment",
    )
    check(
        "Final statement" not in r1_page.body
        and not any("/final/" in f["action"] for f in r1_page.forms()),
        "while the review runs the chairperson sees nothing of the final statement",
    )
    fo_page = staff1.get(f"{panel_url}applications/{app_id}/")
    check(
        f"ASSESS-{token}" not in fo_page.body and "Private to each reviewer" in fo_page.body,
        "the FO cannot read assessments before the deadline",
    )

    # the FO shortens the assessment deadline to the past
    set_task("assessment", "Assessments and preliminary statements", now - 2 * day, now - day)
    r1_page = r1.get(app_urls["r1"])
    check(
        f"ASSESS-{token}-r2" in r1_page.body
        and f"ASSESS-{token}-r1" in r1_page.body
        and not any("/assessment/" in f["action"] for f in r1_page.forms()),
        "after the deadline r1 sees both assessments and can no longer edit",
    )
    csrf = r1_page.forms()[0]["fields"]["csrfmiddlewaretoken"]
    late = r1.request(
        app_urls["r1"] + "assessment/",
        {
            "csrfmiddlewaretoken": csrf,
            "assessment": "late",
            "preliminary_statement": "x",
            "preliminary_grade": "1",
        },
        referer=r1_page.url,
    )
    check(late.status == 403, "a late assessment POST is refused (403)")
    fo_page = staff1.get(f"{panel_url}applications/{app_id}/")
    check(
        f"ASSESS-{token}-r1" in fo_page.body and f"ASSESS-{token}-r2" in fo_page.body,
        "the FO reads both assessments on the panel page",
    )

    # the chairperson writes the final statement
    final = {
        "final_statement": f"Fund it ({token})",
        "final_grade": "9",
        "novelty": "Novel approach",
        "novelty_grade": "8",
        "merits": "Strong record",
        "merits_grade": "7",
        "feasibility": "Realistic plan",
        "feasibility_grade": "8",
        "quality": "High",
        "quality_grade": "9",
    }
    r1_page = r1.submit(r1_page, "/final/", **final)
    check(
        any("Final statement saved" in a for a in alerts(r1_page)),
        "r1 (chairperson) wrote the final statement",
    )
    r2_page = r2.get(app_urls["r2"])
    check(
        f"Fund it ({token})" in r2_page.body
        and not any("/final/" in f["action"] for f in r2_page.forms()),
        "r2 reads the final statement and has no form for it",
    )
    home = r3.login(rsite, "r3")
    r3_page = r3.get(app_urls["r1"])
    check(
        f"ASSESS-{token}-r1" in r3_page.body
        and f"ASSESS-{token}-r2" in r3_page.body
        and f"Fund it ({token})" in r3_page.body
        and "Declarations of the panel" in r3_page.body
        and not any(
            "/assessment/" in f["action"] or "/declaration/" in f["action"] for f in r3_page.forms()
        ),
        "r3 (supporting admin) reads everything and has no review forms",
    )
    denied = r3.request(
        app_urls["r1"] + "assessment/",
        {
            "csrfmiddlewaretoken": r3_page.forms()[0]["fields"]["csrfmiddlewaretoken"],
            "assessment": "x",
            "preliminary_statement": "x",
            "preliminary_grade": "1",
        },
        referer=r3_page.url,
    )
    check(denied.status == 403, "r3 cannot write an assessment (403)")
    check(
        all(
            r1.get(f"https://{rsite}{p}").status == 404
            for p in ("/grants/", "/admin/", "/members/")
        )
        and "Grants" not in r1_page.body.split("</nav>", 1)[0],
        "the reviewer site routes nothing but reviewer work",
    )

    # a4 is on no panel
    a4 = Browser()
    gate = a4.login(rsite, "a4")
    check(
        gate.status == 403
        and "not on any review panel of Org 1" in gate.body
        and "Panel g1" not in gate.body,
        "a4 (on no panel) sees the not-a-reviewer page and no panel data",
    )

    # r2 fills in payment information and uploads a passport; staff1 reads it
    profile = r2.get(f"https://{rsite}/profile/")
    profile = r2.submit(
        profile,
        "/profile/",
        save_profile="1",
        address="Storgatan 1",
        account_holder="Peter Lund",
        bank_name="SEB",
        iban=f"SE{token.upper()}",
        bic="ESSESESS",
        keywords="energy systems, buildings",
    )
    upload = profile.forms()[-1]
    profile = r2.request(
        upload["action"],
        {"csrfmiddlewaretoken": upload["fields"]["csrfmiddlewaretoken"], "upload": "1"},
        files={"passport": ("passport.pdf", PDF)},
        referer=profile.url,
    )
    check(
        "passport.pdf" in profile.body and f"SE{token.upper()}" in profile.body,
        "r2 saved payment information and a passport copy",
    )
    panel_page = staff1.get(panel_url)
    seat_row = panel_page.body.split('data-seat="peter.lund@chalmers.se"', 1)[1]
    seat_url = f"https://{site}" + first_match(r'href="(/review/\d+/seats/\d+/)"', seat_row)
    seat_page = staff1.get(seat_url)
    passport = staff1.get(seat_url + "passport/")
    check(
        f"SE{token.upper()}" in seat_page.body
        and "energy systems" in seat_page.body
        and passport.body.startswith("%PDF"),
        "staff1 (admin) reads r2's payment information and downloads the passport",
    )


def check_not_member() -> None:
    section("Membership gate")
    a3 = Browser()
    page = a3.login(f"fo1.{DOMAIN}", "a3")
    gate = a3.get(f"https://fo1.{DOMAIN}/grants/")
    check(
        page.status == 403 and "Not a member of Org 1" in page.body,
        "a3 (not approved) sees the not-a-member page",
    )
    check(G1 not in gate.body and "Oskar" not in gate.body, "and no Org 1 data")
    page = a3.login(f"ro.{DOMAIN}", "a3")
    check(
        page.status == 403 and "You do not act for a research organisation" in page.body,
        f"a3 (no organisation) sees the not-a-member page on ro.{DOMAIN}",
    )


def ro_request_url(browser: Browser, app_id: str) -> str | None:
    """The request page of an application on the browser's organisation board."""
    board = browser.get(f"https://ro.{DOMAIN}/")
    if f'data-request="{app_id}"' not in board.body:
        return None
    block = board.body.split(f'data-request="{app_id}"', 1)[1]
    return f"https://ro.{DOMAIN}" + first_match(r'href="(/requests/\d+/)"', block)


def wait_status(browser: Browser, app_id: str, status: str) -> bool:
    return bool(wait_for(lambda: application_status(browser, app_id) == status, timeout=10))


def check_signoff(staff1: Browser) -> None:
    """a1 names Uppsala University: sig1 declines, a1 applies again, sig1 signs; a4's
    request expires."""
    section("Organisation sign-off")
    title = f"Sign-off check {time.strftime('%H:%M:%S')}"
    ensure_grant(
        staff1, f"fo1.{DOMAIN}", title, "A grant that needs the organisation's signature.",
        schema=SIGNED_SCHEMA,
    )  # fmt: skip
    path = wait_for(lambda: public_grant_path(title), timeout=10)
    if not check(bool(path), f"'{title}' is published on {DOMAIN}"):
        return
    a1 = Browser()
    a1.login(DOMAIN, "a1")
    form = a1.get(f"https://{DOMAIN}{path}apply/")
    check(
        'data-combobox="true"' in form.body and "Uppsala University" in form.body,
        "the apply form asks for the administrating organisation (type to search)",
    )
    check(apply(a1, path) is None, "a1 cannot leave the required organisation out")
    uu = {**ANSWERS, "administrating_organisation": "uu"}
    first = apply(a1, path, uu)
    if not check(first is not None, "a1 applies naming Uppsala University"):
        return
    assert first is not None
    check(
        wait_status(a1, first, "awaiting_signature"),
        "a1's application waits for Uppsala University's signature",
    )
    fo_url = org_application_url(staff1, f"fo1.{DOMAIN}", title, "Elsa")
    page = staff1.get(fo_url)
    check(
        'data-signoff="awaiting_signature"' in page.body and "Set the status" not in page.body,
        "Org 1 sees it awaiting the signature and cannot review it yet",
    )

    ro1 = Browser()
    ro1.login(f"ro.{DOMAIN}", "ro1")
    people = ro1.get(f"https://ro.{DOMAIN}/people/")
    check(
        people.status == 200 and "Uppsala University" in people.body,
        f"ro1 is Uppsala University's admin on ro.{DOMAIN} (from the directory)",
    )
    if 'data-person="jonas.ek@uu.se"' not in people.body:
        people = ro1.submit(people, "/people/add/", email="jonas.ek@uu.se")
    check('data-person="jonas.ek@uu.se"' in people.body, "ro1 adds sig1 as a signer")
    sig1 = Browser()
    sig1.login(f"ro.{DOMAIN}", "sig1")
    request_url = wait_for(lambda: ro_request_url(sig1, first), timeout=10)
    check(bool(request_url), "sig1 sees a1's application on the Uppsala University board")
    ro2 = Browser()
    ro2.login(f"ro.{DOMAIN}", "ro2")
    check(
        first not in ro2.get(f"https://ro.{DOMAIN}/").body,
        "KTH's admin (ro2) does not see it",
    )
    if not request_url:
        return
    reason = f"Not employed at Uppsala ({uuid.uuid4().hex[:6]})."
    sig1.submit(sig1.get(request_url), "/decline/", reason=reason)
    declined = wait_status(a1, first, "ro_declined")
    detail = a1.get(f"https://{DOMAIN}/my/applications/{first}/").body
    check(declined and reason in detail, "a1 sees the decline and the reason")

    second = apply(a1, path, uu)
    if not check(second not in (None, first), "a1 applies again after the decline"):
        return
    assert second is not None
    wait_status(a1, second, "awaiting_signature")
    comment = f"COMMENT-{uuid.uuid4().hex[:10]}"
    request_url = wait_for(lambda: ro_request_url(sig1, second), timeout=10)
    if not check(bool(request_url), "the new application reaches the Uppsala board"):
        return
    sig1.submit(sig1.get(request_url), "/sign/", comment=comment, confirm="on")
    signed = wait_status(a1, second, "received")
    detail = a1.get(f"https://{DOMAIN}/my/applications/{second}/").body
    check(
        signed and "Signed by Jonas Ek for Uppsala University" in detail,
        "after sig1 signs, a1 sees who signed",
    )
    check(comment not in detail, "and not the signer's comment (it is for the funder)")
    page = staff1.get(org_application_url(staff1, f"fo1.{DOMAIN}", title, "Elsa"))
    check(
        'data-signoff="received"' in page.body
        and "Set the status" in page.body
        and comment in page.body,
        "Org 1 sees it signed, with the comment, and can review it",
    )

    a4 = Browser()
    a4.login(DOMAIN, "a4")
    third = apply(a4, path, uu)
    if not check(third is not None, "a4 applies naming Uppsala University"):
        return
    assert third is not None
    wait_status(a4, third, "awaiting_signature")
    wait_for(lambda: ro_request_url(sig1, third), timeout=10)
    django(
        "o1-web",
        f"""
from datetime import timedelta
from django.utils import timezone
from it42.org.grants.models import Grant
past = timezone.localdate() - timedelta(days=1)
Grant.objects.filter(title={title!r}).update(deadline=past, signature_deadline=past)""",
    )
    run("docker", "compose", "exec", "-T", "o1-worker", "python", "manage.py", "expire_signatures")
    check(
        wait_status(a4, third, "ro_expired"),
        "after the signature deadline the org expires a4's request; a4 sees it",
    )
    expired = wait_for(
        lambda: (url := ro_request_url(sig1, third)) and "Not signed by" in sig1.get(url).body,
        timeout=10,
    )
    check(bool(expired), "and the request is closed on the Uppsala University board")


def check_review_note_isolation(note_marker: str) -> None:
    section("Review notes")
    dump = run("docker", "compose", "exec", "-T", "core-db", "pg_dump", "-U", "core", "core")
    in_org = note_marker in run(
        "docker", "compose", "exec", "-T", "o1-db", "pg_dump", "-U", "o1", "o1"
    )  # fmt: skip
    check(
        in_org and note_marker not in dump,
        f"review note {note_marker} is only in the Org 1 database",
    )


def check_logout() -> None:
    section("Single logout")
    browser = Browser()
    browser.login(DOMAIN, "a1")
    check(browser.has_idp_session(f"fo1.{DOMAIN}"), "after logging in, the IdP session gives SSO")
    page, posted = browser.logout(DOMAIN)
    check(
        posted == [f"https://idp.{DOMAIN}/idp/slo/", f"https://{DOMAIN}/saml2/ls/post/"],
        f"logout went SP -> IdP /idp/slo/ -> SP /saml2/ls/post/ ({posted})",
    )
    check(
        page.url == f"https://{DOMAIN}/"
        and "You have been logged out" in page.body
        and "Log out" not in page.body,
        f"a1 is logged out of {DOMAIN} and lands on the home page with a notice ({page.url})",
    )
    check(
        not browser.has_idp_session(f"fo1.{DOMAIN}"),
        "the IdP session is gone (password asked again)",
    )

    # On an org site, where every page needs a login, logout must not bounce the
    # user straight back to the IdP's login form.
    staff = Browser()
    staff.login(f"fo1.{DOMAIN}", "staff1")
    page, _ = staff.logout(f"fo1.{DOMAIN}")
    check(
        page.url == f"https://fo1.{DOMAIN}/logged-out/" and "You have been logged out" in page.body,
        f"staff1's logout on fo1.{DOMAIN} ends on its logged-out page ({page.url})",
    )
    check(not staff.has_idp_session(DOMAIN), "and staff1's IdP session is gone")


def check_reliability(staff1: Browser, a2: Browser) -> None:
    section("Reliability")
    title = f"Reliability check {time.strftime('%H:%M:%S')}"
    ensure_grant(staff1, f"fo1.{DOMAIN}", title, "A grant created by scripts/acceptance.py.")
    path = wait_for(lambda: public_grant_path(title), timeout=10)
    if not check(bool(path), f"'{title}' is published on {DOMAIN}"):
        return
    run("docker", "compose", "stop", "o1-worker")
    try:
        app_id = apply(a2, path)
        check(app_id is not None, "with o1-worker stopped, a2 still submits to Org 1")
        time.sleep(3)
        status = application_status(a2, app_id) if app_id else None
        check(status == "submitted", f"a2 sees 'submitted' while o1-worker is down (got {status})")
    finally:
        run("docker", "compose", "start", "o1-worker")
    if not app_id:
        return
    received = wait_for(
        lambda: application_status(a2, app_id) == "received", timeout=60, interval=1
    )
    check(bool(received), "after restarting o1-worker the status becomes received")
    count = django(
        "o1-web",
        f"""
from it42.org.applications.models import Application
print(Application.objects.filter(public_id='{app_id}').count())""",
    )
    history = django(
        "core-web",
        f"""
from it42.core.applications.models import StatusChange
print(StatusChange.objects.filter(application__public_id='{app_id}', status='received').count())""",
    )
    check(
        count == "1" and history == "1",
        f"the application arrived exactly once (org rows: {count}, "
        f"core 'received' entries: {history})",
    )


def check_redelivery(ids: dict[str, str]) -> None:
    section("Redelivery")
    event_id = django(
        "o1-web",
        f"""
from it42.common.models import OutboxEvent
e = (OutboxEvent.objects.filter(application_id='{ids["g1"]}', published_at__isnull=False)
     .order_by('-occurred_at').first())
print(e.id if e else '')""",
    )
    if not check(
        bool(event_id), "found an event Org 1 already published about a2's g1 application"
    ):
        return
    state = f"""
from it42.core.applications.models import ApplicationCopy
a = ApplicationCopy.objects.get(public_id='{ids["g1"]}')
print(a.status, a.last_seq, a.status_changes.count(), a.questions.count())"""
    before = django("core-web", state)
    django(
        "o1-worker",
        f"""
from it42.common.models import OutboxEvent
from it42.common.rabbit import connect
from it42.common.management.commands.relay_outbox import publish
connection = connect(); channel = connection.channel(); channel.confirm_delivery()
publish(channel, OutboxEvent.objects.get(id='{event_id}'))
connection.close()""",
    )
    skipped = wait_for(
        lambda: (
            f"skipping duplicate event {event_id}"
            in run("docker", "compose", "logs", "core-worker", "--since", "2m")
        ),
        timeout=10,
    )
    after = django("core-web", state)
    check(bool(skipped), f"the core skipped the redelivered event {event_id}")
    check(before == after, f"nothing changed ({before} -> {after})")


def main() -> int:
    staff1, staff2, a2 = Browser(), Browser(), Browser()
    check_setup()
    check_grants(staff1, staff2)
    ids = check_applying(a2)
    check_drafts()
    if len(ids) == 2:
        check_org_views(staff1, staff2, ids)
        note_marker = check_review_loop(staff1, a2, ids)
        check_review_note_isolation(note_marker)
        check_review_panels(staff1, note_marker)
        check_redelivery(ids)
    check_not_member()
    check_signoff(staff1)
    check_logout()
    check_reliability(staff1, a2)

    section("Isolation (scripts/check-isolation.sh)")
    isolation = subprocess.run([str(ROOT / "scripts/check-isolation.sh")], cwd=ROOT, check=False)
    check(isolation.returncode == 0, "scripts/check-isolation.sh passed")

    failed = [m for ok, m in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
