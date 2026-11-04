"""Staff-site routes, mounted under /review/."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.panel_list, name="panel_list"),
    path("new/", views.panel_create, name="panel_create"),
    path("<int:panel_id>/", views.panel_detail, name="panel_detail"),
    path("<int:panel_id>/edit/", views.panel_edit, name="panel_edit"),
    path("<int:panel_id>/delete/", views.panel_delete, name="panel_delete"),
    path("<int:panel_id>/seats/add/", views.seat_add, name="seat_add"),
    path("<int:panel_id>/seats/<int:seat_id>/", views.seat_detail, name="seat_detail"),
    path("<int:panel_id>/seats/<int:seat_id>/role/", views.seat_role, name="seat_role"),
    path("<int:panel_id>/seats/<int:seat_id>/remove/", views.seat_remove, name="seat_remove"),
    path("<int:panel_id>/seats/<int:seat_id>/passport/", views.seat_passport, name="seat_passport"),
    path("<int:panel_id>/grants/link/", views.grant_link, name="panel_grant_link"),
    path(
        "<int:panel_id>/grants/<int:grant_id>/unlink/",
        views.grant_unlink,
        name="panel_grant_unlink",
    ),
    path("<int:panel_id>/review/close/", views.review_close, name="panel_review_close"),
    path("<int:panel_id>/review/reopen/", views.review_reopen, name="panel_review_reopen"),
    path("<int:panel_id>/tasks/new/", views.task_create, name="task_create"),
    path("<int:panel_id>/tasks/<int:task_id>/edit/", views.task_edit, name="task_edit"),
    path("<int:panel_id>/tasks/<int:task_id>/delete/", views.task_delete, name="task_delete"),
    path("<int:panel_id>/meetings/new/", views.meeting_create, name="meeting_create"),
    path("<int:panel_id>/meetings/<int:meeting_id>/edit/", views.meeting_edit, name="meeting_edit"),
    path(
        "<int:panel_id>/meetings/<int:meeting_id>/delete/",
        views.meeting_delete,
        name="meeting_delete",
    ),
    path(
        "<int:panel_id>/applications/<int:application_id>/",
        views.panel_application,
        name="panel_application",
    ),
    path(
        "<int:panel_id>/applications/<int:application_id>/assign/",
        views.assign,
        name="panel_assign",
    ),
]
