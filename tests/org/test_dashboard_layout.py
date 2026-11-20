import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client

from it42.org.grants.models import Grant


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
