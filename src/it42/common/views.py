from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import redirect, render
from djangosaml2.views import LogoutInitView, _get_subject_id


def healthz(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok", content_type="text/plain")


def logged_out(request: HttpRequest) -> HttpResponse:
    """Where logout ends (LOGOUT_REDIRECT_URL); public on every site.

    The core sends the visitor on to its public home page with a notice. An org or RO
    site's home page needs a login and would bounce straight back to the IdP's login form,
    so those sites show this page in their own role design (staff, reviewer or
    organisation) instead, with a link to the public IT42 site.
    """
    if settings.APP_ROLE == "core":
        messages.info(
            request,
            "You have been logged out of IT42 and of the identity provider. "
            "The next login asks for your password again.",
        )
        return redirect("home")
    if settings.APP_ROLE == "ro":
        base_template = "ro/base.html"
    elif getattr(settings, "SITE_ROLE", "staff") == "review":
        base_template = "org/review/site/base.html"
    else:
        base_template = "org/base.html"
    return render(
        request,
        "org/logged_out.html",
        {"base_template": base_template, "CORE_SITE_URL": settings.CORE_SITE_URL},
    )


class SamlLogoutView(LogoutInitView):
    """Log out of this site and of the IdP (SAML single logout, HTTP-POST).

    POST only, with Django's CSRF check: djangosaml2 starts logout on a GET,
    which any third-party page could trigger. Sessions that did not come
    from the IdP (for example an admin login) are logged out locally.
    """

    http_method_names = ["post"]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        saml_session = getattr(request, "saml_session", None)
        if saml_session is None or _get_subject_id(saml_session) is None:
            logout(request)
            return HttpResponseRedirect(settings.LOGOUT_REDIRECT_URL)
        # Builds a signed LogoutRequest and returns an auto-submitting form that
        # POSTs it to the IdP; the IdP ends its session and POSTs a signed
        # LogoutResponse back to /saml2/ls/post/.
        return self.get(request, *args, **kwargs)

    def http_method_not_allowed(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        return HttpResponseNotAllowed(["POST"])


logout_view = SamlLogoutView.as_view()
