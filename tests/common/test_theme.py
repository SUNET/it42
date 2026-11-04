from typing import Any

from django.template.loader import render_to_string
from django.test import RequestFactory

from it42.common.theme import darken, is_light, theme


def test_light_and_dark_colours() -> None:
    assert is_light("#ffe680")  # reviewer sites
    assert is_light("#ffffff")
    for color in ("#0d6efd", "#198754", "#6f42c1", "#000000"):
        assert not is_light(color), color


def test_darken_keeps_the_format() -> None:
    assert darken("#ffe680") == "#73683a"


def test_theme_context(settings: Any) -> None:
    request = RequestFactory().get("/")
    settings.THEME_COLOR = "#0d6efd"
    dark = theme(request)
    assert not dark["THEME_IS_LIGHT"]
    assert dark["THEME_ON_PRIMARY"] == "#ffffff" and dark["THEME_ACCENT"] == "#0d6efd"
    settings.THEME_COLOR = "#ffe680"
    light = theme(request)
    assert light["THEME_IS_LIGHT"]
    assert light["THEME_ON_PRIMARY"] == "#212529" and light["THEME_ACCENT"] == "#73683a"
    assert light["THEME_COLOR_RGB"] == "255, 230, 128"


def test_base_template_switches_navbar_text_colour(settings: Any) -> None:
    request = RequestFactory().get("/")
    settings.THEME_COLOR = "#ffe680"
    html = render_to_string("base.html", {}, request=request)
    assert "navbar-light" in html and 'data-bs-theme="light"' in html
    assert "btn-dark" in html and "btn-light" not in html
    settings.THEME_COLOR = "#198754"
    html = render_to_string("base.html", {}, request=request)
    assert "navbar-dark" in html and "btn-light" in html and "btn-dark" not in html
