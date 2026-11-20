"""Chrome checks for board cards. Run with `uv run --with playwright python -m pytest`."""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from django.conf import settings
from django.test import Client, modify_settings
from pytest_django.live_server_helper import LiveServer


@contextmanager
def board_browser(client: Client) -> Iterator[Any]:
    """Use the fixture user's Django session without an external SAML login."""
    api = pytest.importorskip("playwright.sync_api")
    chrome = shutil.which("chromium") or shutil.which("google-chrome")
    if not chrome:
        pytest.skip("Dashboard interaction check requires Chromium or Chrome")
    # Staff and reviewer sites have different middleware. Start after the role fixture is active.
    with (
        modify_settings(ALLOWED_HOSTS={"append": "localhost"}),
        api.sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch(executable_path=chrome)
        server = LiveServer("localhost")
        try:
            page = browser.new_page(base_url=server.url)
            cookie = client.cookies[settings.SESSION_COOKIE_NAME]
            page.context.add_cookies(
                [{"name": cookie.key, "value": cookie.value, "url": server.url}]
            )
            yield page
        finally:
            browser.close()
            server.stop()
