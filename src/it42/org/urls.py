from django.contrib import admin
from django.urls import include, path

from it42.common.views import healthz, logged_out, logout_view
from it42.org.grants import views as grants

urlpatterns = [
    path("", grants.dashboard, name="home"),
    path("healthz", healthz),
    path("logout/", logout_view, name="logout"),
    path("logged-out/", logged_out, name="logged_out"),
    path("members/", include("it42.org.members.urls")),
    path("grants/", include("it42.org.grants.urls")),
    path("applications/", include("it42.org.applications.urls")),
    path("review/", include("it42.org.review.urls")),
    # Replaces djangosaml2's GET-based logout route with the POST-only view.
    path("saml2/logout/", logout_view, name="saml2_logout"),
    path("saml2/", include("djangosaml2.urls")),
    path("admin/", admin.site.urls),
]
