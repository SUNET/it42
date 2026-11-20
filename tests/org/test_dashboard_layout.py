import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client

from it42.org.grants.models import Grant
from tests.board_browser import board_browser, check_unsaved_card_text


@pytest.mark.parametrize("size", ["1440,900", "600,640"])
def test_dashboard_scrolls_between_navigation_panels(
    size: str, tmp_path: Path, admin_client: Client, make_grant: Callable[..., Grant]
) -> None:
    chrome = shutil.which("chromium") or shutil.which("google-chrome")
    if not chrome:
        pytest.skip("Dashboard layout check requires Chromium or Chrome")

    for index in range(12):
        make_grant(f"Call {index}")
    response = admin_client.get("/")
    assert response.status_code == 200
    static = Path(settings.STATICFILES_DIRS[0]).as_uri()
    html = response.content.decode().replace('"/static/', f'"{static}/')
    # In the compact layout, also check the dashboard with the calendar expanded.
    check = """
    <script>
      const content = document.querySelector(".it-app-content");
      const panel = document.querySelector(".it-panel");
      if (panel.classList.contains("is-collapsed")) {
        document.querySelector('.it-panel-toggle[aria-controls="' + panel.id + '"]').click();
      }
      const bars = Array.from(document.querySelectorAll(".it-sidebar, .it-topbar, .it-panel"));
      const tops = () => bars.map(bar => bar.getBoundingClientRect().top).join();
      const before = tops();
      const cards = content.querySelectorAll(".it-app-card h3 a");
      cards[cards.length - 1].focus();
      const card = document.activeElement.getBoundingClientRect();
      const pane = content.getBoundingClientRect();
      const visible = bars.every(bar => {
        const rect = bar.getBoundingClientRect();
        return rect.height > 0 && rect.top >= 0 && rect.bottom <= innerHeight;
      });
      if (content.scrollTop > 0 && card.top >= pane.top && card.bottom <= pane.bottom &&
          visible && before === tops() && document.documentElement.scrollHeight === innerHeight) {
        document.title = "Dashboard scroll passed";
      }
    </script>
    """
    page = tmp_path / "dashboard.html"
    page.write_text(html.replace("</body>", check + "</body>"))
    result = subprocess.run(  # noqa: S603
        [
            chrome,
            "--headless",
            f"--user-data-dir={tmp_path / 'browser'}",
            f"--window-size={size}",
            "--dump-dom",
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert "<title>Dashboard scroll passed</title>" in result.stdout


@pytest.mark.parametrize(
    ("destination", "site", "expected"),
    [
        ("iframe", "same-origin", "SAMEORIGIN"),
        ("iframe", "same-site", "DENY"),
        ("iframe", "cross-site", "DENY"),
        ("document", "same-origin", "DENY"),
    ],
)
def test_card_framing_is_limited_to_its_board(
    destination: str,
    site: str,
    expected: str,
    admin_client: Client,
    make_grant: Callable[..., Grant],
) -> None:
    """Only the same site's card request can embed this otherwise standalone view."""
    grant = make_grant()
    path = f"/grants/{grant.pk}/applications/"
    response = admin_client.get(
        path, {"board_card": "1"}, headers={"Sec-Fetch-Dest": destination, "Sec-Fetch-Site": site}
    )
    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == expected
    assert (b'<base target="_top">' in response.content) == (expected == "SAMEORIGIN")
    assert admin_client.get(path).headers["X-Frame-Options"] == "DENY"


@pytest.mark.django_db(transaction=True)
def test_application_opens_over_the_board(
    admin_client: Client, make_application, tmp_path: Path
) -> None:
    """Exercise the real board link, card tabs, backdrop, keyboard and focus restoration."""
    application = make_application(name="Sam Rivera")
    with board_browser(admin_client) as page:
        for width, height in [(1920, 1024), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.goto("/?sort=deadline")
            link = page.get_by_role("link", name=application.applicant_name, exact=True).first
            link.focus()
            board = page.locator(".it-board")
            scroll = board.evaluate("(el) => [el.scrollLeft, el.closest('main').scrollTop]")
            link.press("Enter")
            dialog = page.get_by_role("dialog")
            frame = dialog.frame_locator("iframe")
            reviews = frame.get_by_role("tab", name="Reviews")
            reviews.wait_for()
            page.screenshot(path=tmp_path / f"granter-card-{width}.png")
            reviews.click()
            assert reviews.get_attribute("aria-selected") == "true"
            assert dialog.evaluate("(el) => el.matches(':modal')")
            assert page.url.endswith("/?sort=deadline")
            frame.get_by_role("tab", name="Proposal").click()
            page.get_by_role("button", name="Expand card").click()
            page.get_by_role("button", name="Restore card size").click()
            page.mouse.click(2, 2)
            dialog.wait_for(state="hidden")
            assert link.evaluate("(el) => el === document.activeElement")
            assert board.evaluate("(el) => [el.scrollLeft, el.closest('main').scrollTop]") == scroll
            link.press("Enter")
            frame.get_by_role("tab", name="Proposal").press("Escape")
            dialog.wait_for(state="hidden")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("tab", "label"), [("Questions", "Ask a question"), ("Activity", "Internal note")]
)
def test_granter_card_protects_unsaved_text(admin_client, make_application, tab, label) -> None:
    application = make_application()
    with board_browser(admin_client) as page:
        page.goto("/")
        page.get_by_role("link", name=application.applicant_name, exact=True).first.click()
        frame = page.get_by_role("dialog").frame_locator("iframe")
        frame.get_by_role("tab", name=tab).click()
        field = frame.get_by_role("textbox", name=label)
        check_unsaved_card_text(page, field, lambda: page.mouse.click(2, 2))


@pytest.mark.django_db(transaction=True)
def test_escape_closes_field_menu_before_card(admin_client, make_grant) -> None:
    grant = make_grant("Editable grant", status=Grant.Status.DRAFT)
    with board_browser(admin_client) as page:
        page.goto("/")
        page.get_by_role("link", name=grant.title, exact=True).click()
        dialog = page.get_by_role("dialog")
        frame = dialog.frame_locator("iframe")
        toggle = frame.locator("[data-add-toggle]")
        toggle.click()
        frame.locator("[data-add-menu] button").first.press("Escape")
        assert dialog.is_visible()
        assert toggle.get_attribute("aria-expanded") == "false"
        assert toggle.evaluate("(el) => el === document.activeElement")
        toggle.press("Escape")
        dialog.wait_for(state="hidden")
