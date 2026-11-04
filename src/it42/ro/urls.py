from django.contrib import admin
from django.urls import include, path

from it42.common.views import healthz, logged_out, logout_view
from it42.ro.signing import views as signing

urlpatterns = [
    path("", signing.board, name="home"),
    path("healthz", healthz),
    path("logout/", logout_view, name="logout"),
    path("logged-out/", logged_out, name="logged_out"),
    path("requests/", include("it42.ro.signing.urls")),
    path("people/", include("it42.ro.members.urls")),
    # Replaces djangosaml2's GET-based logout route with the POST-only view.
    path("saml2/logout/", logout_view, name="saml2_logout"),
    path("saml2/", include("djangosaml2.urls")),
    path("admin/", admin.site.urls),
]
