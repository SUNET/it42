"""A minimal scripted browser for end-to-end checks against the running stack.

It keeps cookies, follows redirects, submits HTML forms and logs in through the
IdP. The sites live under DOMAIN (IT42_DOMAIN from the environment or .env, default
it42.vr), and those names resolve to 127.0.0.1 even without /etc/hosts. TLS is verified
against the system trust store (the mkcert CA, or Let's Encrypt on a server).
"""

import html
import http.cookiejar
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _setting(name: str, default: str) -> str:
    """``name`` from the environment, else from the repository's .env, else ``default``."""
    if os.environ.get(name):
        return os.environ[name]
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return default


DOMAIN = _setting("IT42_DOMAIN", "it42.vr")
DOMAIN_RE = re.escape(DOMAIN)
_real_getaddrinfo = socket.getaddrinfo


def _getaddrinfo(
    host: bytes | str | None,
    port: bytes | str | int | None,
    family: int = 0,
    type: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> list[Any]:
    if isinstance(host, str) and (host == DOMAIN or host.endswith(f".{DOMAIN}")):
        host = "127.0.0.1"
    return _real_getaddrinfo(host, port, family, type, proto, flags)


setattr(socket, "getaddrinfo", _getaddrinfo)  # noqa: B010 (monkeypatch)


def _idp_password(username: str) -> str:
    """Use an explicit test password, else the local import's generated credentials."""
    if password := _setting("IDP_PASSWORD", ""):
        return password
    credentials = Path(__file__).resolve().parents[2] / "secrets/idp-import-passwords.txt"
    if credentials.exists():
        prefix = f"{username}: generated password (shown once): "
        for line in credentials.read_text().splitlines():
            if line.startswith(prefix):
                return line.removeprefix(prefix)
    raise ValueError(f"No test password for {username}; import users or set IDP_PASSWORD")


@dataclass
class Page:
    url: str
    status: int
    body: str

    def forms(self) -> list[dict[str, Any]]:
        found = []
        for match in re.finditer(r"<form\b([^>]*)>(.*?)</form>", self.body, re.S | re.I):
            attrs, inner = match.groups()
            action = _attr(attrs, "action") or self.url
            fields: dict[str, str] = {}
            for tag in re.finditer(r"<(input|textarea|select)\b([^>]*)>", inner, re.I):
                name = _attr(tag.group(2), "name")
                if name and (_attr(tag.group(2), "type") or "").lower() not in {"submit", "file"}:
                    fields[name] = _attr(tag.group(2), "value") or ""
            found.append(
                {
                    "action": urllib.parse.urljoin(self.url, html.unescape(action)),
                    "method": (_attr(attrs, "method") or "get").lower(),
                    "fields": fields,
                }
            )
        return found

    def form(self, action_contains: str = "") -> dict[str, Any]:
        for form in self.forms():
            if action_contains in form["action"]:
                return form
        raise AssertionError(f"no form with action containing {action_contains!r} on {self.url}")

    def text(self) -> str:
        return html.unescape(re.sub(r"<[^>]+>", " ", self.body))


def _attr(attrs: str, name: str) -> str | None:
    match = re.search(rf'\b{name}\s*=\s*"([^"]*)"', attrs, re.I) or re.search(
        rf"\b{name}\s*=\s*'([^']*)'", attrs, re.I
    )
    return html.unescape(match.group(1)) if match else None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


@dataclass
class Browser:
    jar: http.cookiejar.CookieJar = field(default_factory=http.cookiejar.CookieJar)

    def __post_init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect()
        )

    def request(
        self,
        url: str,
        data: dict[str, str] | None = None,
        *,
        follow: bool = True,
        files: dict[str, tuple[str, bytes]] | None = None,
        referer: str | None = None,
    ) -> Page:
        for _ in range(15):
            headers = {"User-Agent": "it42-e2e"}
            body: bytes | None = None
            if files:
                boundary = "it42boundary7MA4YWxk"
                body = _multipart(data or {}, files, boundary)
                headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            elif data is not None:
                body = urllib.parse.urlencode(data).encode()
            if body is not None:
                headers["Referer"] = referer or url
                headers["Origin"] = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))
            req = urllib.request.Request(url, data=body, headers=headers)
            try:
                with self._opener.open(req, timeout=20) as resp:
                    return Page(resp.geturl(), resp.status, resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as err:
                if err.code in (301, 302, 303, 307, 308) and follow:
                    url = urllib.parse.urljoin(url, err.headers["Location"])
                    data, files = None, None
                    continue
                return Page(url, err.code, err.read().decode("utf-8", "replace"))
        raise AssertionError("too many redirects")

    def get(self, url: str, **kwargs: Any) -> Page:
        return self.request(url, **kwargs)

    def submit(self, page: Page, action_contains: str = "", **overrides: str) -> Page:
        form = page.form(action_contains)
        fields = {**form["fields"], **overrides}
        if form["method"] == "get":
            return self.get(form["action"] + "?" + urllib.parse.urlencode(fields))
        return self.request(form["action"], fields, referer=page.url)

    def login(self, site: str, username: str, next_path: str = "/") -> Page:
        """SP-initiated SSO: SP -> IdP login form -> auto-POST to the SP's ACS."""
        page = self.get(f"https://{site}/saml2/login/?next={urllib.parse.quote(next_path)}")
        if "/saml2/acs/" not in page.body:
            assert f"idp.{DOMAIN}" in page.url, f"expected the IdP login form, got {page.url}"
            page = self.submit(
                page, f"idp.{DOMAIN}", username=username, password=_idp_password(username)
            )
        acs = page.form("/saml2/acs/")
        return self.request(acs["action"], acs["fields"], referer=f"https://idp.{DOMAIN}/idp/sso/")

    def logout(self, site: str) -> tuple[Page, list[str]]:
        """Use the site's Log out button and follow the SAML single logout round trip.

        Returns the final page and the URLs the SAML forms were posted to.
        """
        home = self.get(f"https://{site}/")
        form = home.form("/logout/")
        page = self.request(form["action"], form["fields"], referer=home.url)
        return _follow_auto_posts(self, page)

    def has_idp_session(self, site: str) -> bool:
        """True if starting a login on ``site`` skips the IdP's password form."""
        page = self.get(f"https://{site}/saml2/login/?next=/")
        return "/saml2/acs/" in page.body


def _follow_auto_posts(browser: "Browser", page: Page, limit: int = 5) -> tuple[Page, list[str]]:
    """Submit SAML auto-POST forms (SAMLRequest/SAMLResponse) like a browser's script would.

    Returns the final page and the URLs that were posted to.
    """
    posted: list[str] = []
    for _ in range(limit):
        forms = [
            f for f in page.forms() if "SAMLRequest" in f["fields"] or "SAMLResponse" in f["fields"]
        ]
        if not forms:
            break
        form = forms[0]
        posted.append(form["action"])
        page = browser.request(form["action"], form["fields"], referer=page.url)
    return page, posted


def _multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes]], boundary: str) -> bytes:
    out = b""
    for name, value in fields.items():
        out += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        ).encode()
    for name, (filename, content) in files.items():
        out += (
            (
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{name}"; filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n'
            ).encode()
            + content
            + b"\r\n"
        )
    return out + f"--{boundary}--\r\n".encode()
