"""ROOT_URLCONF of the reviewer site (SITE_ROLE=review).

Only reviewer work: panels, applications to review, the reviewer profile and the
login/logout plumbing. No grants, members, applications admin or Django admin.
"""

from django.urls import include, path

from it42.common.views import healthz, logged_out, logout_view

from . import site_views as views

urlpatterns = [
    path("", views.my_panels, name="home"),
    path("healthz", healthz),
    path("logout/", logout_view, name="logout"),
    path("logged-out/", logged_out, name="logged_out"),
    path("panels/<int:panel_id>/", views.panel_detail, name="review_panel"),
    path(
        "panels/<int:panel_id>/applications/<int:application_id>/",
        views.application_detail,
        name="review_application",
    ),
    path(
        "panels/<int:panel_id>/applications/<int:application_id>/declaration/",
        views.declare,
        name="review_declare",
    ),
    path(
        "panels/<int:panel_id>/applications/<int:application_id>/assessment/",
        views.assess,
        name="review_assess",
    ),
    path(
        "panels/<int:panel_id>/applications/<int:application_id>/final/",
        views.final,
        name="review_final",
    ),
    path(
        "panels/<int:panel_id>/applications/<int:application_id>/notes/",
        views.add_note,
        name="review_note",
    ),
    path(
        "panels/<int:panel_id>/applications/<int:application_id>/notes/<int:note_id>/delete/",
        views.delete_note,
        name="review_note_delete",
    ),
    path(
        "panels/<int:panel_id>/applications/<int:application_id>/documents/<int:document_id>/",
        views.document,
        name="review_document",
    ),
    path("panels/<int:panel_id>/meetings/new/", views.meeting_create, name="review_meeting_create"),
    path(
        "panels/<int:panel_id>/meetings/<int:meeting_id>/edit/",
        views.meeting_edit,
        name="review_meeting_edit",
    ),
    path(
        "panels/<int:panel_id>/meetings/<int:meeting_id>/delete/",
        views.meeting_delete,
        name="review_meeting_delete",
    ),
    path("panels/<int:panel_id>/tasks/new/", views.task_create, name="review_task_create"),
    path(
        "panels/<int:panel_id>/tasks/<int:task_id>/edit/",
        views.task_edit,
        name="review_task_edit",
    ),
    path(
        "panels/<int:panel_id>/tasks/<int:task_id>/delete/",
        views.task_delete,
        name="review_task_delete",
    ),
    path("profile/", views.profile, name="review_profile"),
    path("profile/passport/", views.passport, name="review_passport"),
    path("profile/passport/delete/", views.passport_delete, name="review_passport_delete"),
    # Replaces djangosaml2's GET-based logout route with the POST-only view.
    path("saml2/logout/", logout_view, name="saml2_logout"),
    path("saml2/", include("djangosaml2.urls")),
]
