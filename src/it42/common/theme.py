"""Site theme: name, primary colour and the text colour that is readable on it."""

from typing import Any

from django.conf import settings
from django.http import HttpRequest


def parse_hex(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2 relative luminance (0 = black, 1 = white)."""

    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def is_light(color: str) -> bool:
    """True for colours that need dark text on top (the reviewer sites' light yellow)."""
    return relative_luminance(parse_hex(color)) > 0.5


def darken(color: str, factor: float = 0.45) -> str:
    """A darker shade for links and outlines when the primary colour is light."""
    r, g, b = (round(v * factor) for v in parse_hex(color))
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_string(color: str) -> str:
    return ", ".join(str(v) for v in parse_hex(color))


def theme(request: HttpRequest) -> dict[str, Any]:
    """Expose the site's name and colours to every template."""
    color: str = settings.THEME_COLOR
    light = is_light(color)
    accent = darken(color) if light else color
    return {
        "SITE_NAME": settings.SITE_NAME,
        "THEME_COLOR": color,
        "THEME_COLOR_RGB": rgb_string(color),
        "THEME_IS_LIGHT": light,
        "THEME_ON_PRIMARY": "#212529" if light else "#ffffff",
        "THEME_ACCENT": accent,
        "THEME_ACCENT_RGB": rgb_string(accent),
        "APP_ROLE": settings.APP_ROLE,
        "SITE_ROLE": getattr(settings, "SITE_ROLE", "staff"),
    }
