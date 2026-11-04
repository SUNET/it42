from django.contrib import admin
from django.urls import include, path

from it42.common.views import healthz, logged_out, logout_view
from it42.core.applications import views as applications
from it42.core.catalog import views as catalog
from it42.core.profiles import views as profiles

urlpatterns = [
    path("", catalog.home, name="home"),
    path("calls/", catalog.calls, name="calls"),
    path("pages/<slug:slug>/", catalog.text_page, name="text_page"),
    path("grants/<slug:org_slug>/<uuid:grant_id>/", catalog.grant_detail, name="grant_detail"),
    path("grants/<slug:org_slug>/<uuid:grant_id>/apply/", applications.apply, name="apply"),
    path("my/applications/", applications.my_applications, name="my_applications"),
    path("my/applications/<uuid:public_id>/", applications.my_application, name="my_application"),
    path("my/drafts/<int:draft_id>/delete/", applications.delete_draft, name="delete_draft"),
    path(
        "my/questions/<int:question_id>/answer/",
        applications.answer_question,
        name="answer_question",
    ),
    path("profile/", profiles.profile, name="profile"),
    path("profile/cv/<slug:section>/add/", profiles.cv_add, name="cv_add"),
    path("profile/cv/<slug:section>/<int:entry_id>/edit/", profiles.cv_edit, name="cv_edit"),
    path("profile/cv/<slug:section>/<int:entry_id>/delete/", profiles.cv_delete, name="cv_delete"),
    path("profile/cv/<slug:section>/<int:entry_id>/move/", profiles.cv_move, name="cv_move"),
    path("profile/cv/<slug:section>/reorder/", profiles.cv_reorder, name="cv_reorder"),
    path("profile/edit/", profiles.profile_edit, name="profile_edit"),
    path("profile/data/", profiles.profile_data, name="profile_data"),
    path("profile/public/", profiles.profile_public, name="profile_public"),
    path("profile/orcid/", profiles.orcid_start, name="orcid_start"),
    path("profile/orcid/clear/", profiles.orcid_clear, name="orcid_clear"),
    path("profile/orcid/<uuid:import_id>/status/", profiles.orcid_status, name="orcid_status"),
    path("profile/orcid/<uuid:import_id>/cancel/", profiles.orcid_cancel, name="orcid_cancel"),
    path("profile/orcid/<uuid:import_id>/done/", profiles.orcid_done, name="orcid_done"),
    path("profile/orcid/<uuid:import_id>/item/<int:n>/", profiles.orcid_item, name="orcid_item"),
    path(
        "profile/orcid/<uuid:import_id>/item/<int:n>/edit/",
        profiles.orcid_item_edit,
        name="orcid_item_edit",
    ),
    path(
        "profile/orcid/<uuid:import_id>/keyword/<int:n>/",
        profiles.orcid_keyword,
        name="orcid_keyword",
    ),
    path(
        "profile/documents/<int:document_id>/delete/",
        profiles.delete_document,
        name="delete_document",
    ),
    path("healthz", healthz),
    path("logout/", logout_view, name="logout"),
    path("logged-out/", logged_out, name="logged_out"),
    # Replaces djangosaml2's GET-based logout route with the POST-only view.
    path("saml2/logout/", logout_view, name="saml2_logout"),
    path("saml2/", include("djangosaml2.urls")),
    path("admin/", admin.site.urls),
]
