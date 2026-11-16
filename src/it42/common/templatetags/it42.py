import functools
from datetime import date, datetime, time

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

from it42.common import research_orgs
from it42.common.statuses import STATUS_BADGES, ApplicationStatus

register = template.Library()


@register.inclusion_tag("includes/status_badge.html")
def status_badge(status: str) -> dict[str, str]:
    try:
        choice = ApplicationStatus(status)
    except ValueError:
        return {"badge": "secondary", "label": status}
    return {"badge": STATUS_BADGES[choice], "label": str(choice.label)}


@register.inclusion_tag("includes/org_badge.html")
def org_badge(org_slug: str, name: str) -> dict[str, str]:
    colors: dict[str, str] = getattr(settings, "ORG_COLORS", {})
    return {"name": name, "color": colors.get(org_slug, "#6c757d")}


@functools.cache
def _icon_svg(name: str) -> str:
    path = finders.find(f"vendor/phosphor/{name}.svg")
    if not isinstance(path, str):
        raise template.TemplateSyntaxError(f"No vendored Phosphor icon {name!r}")
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


@register.simple_tag
def icon(name: str, css_class: str = "", label: str = "") -> SafeString:
    """Inline a vendored Phosphor icon (static/vendor/phosphor, MIT). Decorative unless
    ``label`` is given."""
    svg = _icon_svg(name)
    a11y = format_html('role="img" aria-label="{}"', label) if label else 'aria-hidden="true"'
    attrs = format_html('class="it-icon {}" {} focusable="false"', css_class, mark_safe(a11y))  # noqa: S308
    return mark_safe(svg.replace("<svg ", f"<svg {attrs} ", 1))  # noqa: S308


# Design pill per status (Dashboard / Applicant board): css modifier and label.
STATUS_PILLS = {
    ApplicationStatus.SUBMITTED: "grey",
    ApplicationStatus.AWAITING_SIGNATURE: "violet",
    ApplicationStatus.RO_DECLINED: "red",
    ApplicationStatus.RO_EXPIRED: "grey",
    ApplicationStatus.RECEIVED: "green",
    ApplicationStatus.UNDER_REVIEW: "yellow",
    ApplicationStatus.NEEDS_INFO: "peach",
    ApplicationStatus.APPROVED: "solid-green",
    ApplicationStatus.REJECTED: "red",
}


@register.inclusion_tag("includes/status_pill.html")
def status_pill(status: str) -> dict[str, str]:
    try:
        choice = ApplicationStatus(status)
    except ValueError:
        return {"tone": "grey", "label": status}
    return {"tone": STATUS_PILLS[choice], "label": str(choice.label)}


@register.filter
def initials(name: str) -> str:
    """Up to two initials for an avatar circle."""
    return "".join(part[0] for part in str(name).split()[:2]).upper() or "?"


@register.filter
def days_until(value: date) -> int:
    return (value - timezone.localdate()).days


@register.simple_tag
def org_color(org_slug: str) -> str:
    colors: dict[str, str] = getattr(settings, "ORG_COLORS", {})
    return colors.get(org_slug, "#6c757d")


@register.filter
def relday(value: datetime | date) -> str:
    """'today', 'tomorrow', 'in 3 days', 'yesterday' or '4 days ago' for a date or time."""
    day = timezone.localdate(value) if isinstance(value, datetime) else value
    delta = (day - timezone.localdate()).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    return f"in {delta} days" if delta > 0 else f"{-delta} days ago"


@register.filter
def research_org_name(slug: str) -> str:
    """A research organisation's name from the directory (the slug if unknown)."""
    return research_orgs.name_of(slug) if slug else ""


@register.filter
def amount(value: object) -> str:
    """A money amount with thousands separators: ``42000`` -> ``42 000``."""
    from it42.common.formschema import format_amount

    try:
        return format_amount(str(value))
    except (ArithmeticError, ValueError):
        return str(value)


@register.filter
def closing_timezone(value: date | None, at_time: time | None = None) -> str:
    """Use the deadline's daylight-saving offset, not today's offset."""
    if not value:
        return timezone.get_current_timezone_name()
    return timezone.make_aware(datetime.combine(value, at_time or time(17))).tzname() or ""
