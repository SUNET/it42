from django.urls import path

from it42.org.applications import views as applications

from . import views

urlpatterns = [
    path("", views.grant_list, name="grant_list"),
    path("new/", views.grant_create, name="grant_create"),
    path("published/", views.published, name="grant_published"),
    path("<int:grant_id>/edit/", views.grant_edit, name="grant_edit"),
    path("<int:grant_id>/publish/", views.grant_publish, name="grant_publish"),
    path("<int:grant_id>/close/", views.grant_close, name="grant_close"),
    path(
        "<int:grant_id>/signature-deadline/",
        views.grant_signature_deadline,
        name="grant_signature_deadline",
    ),
    path("<int:grant_id>/applications/", applications.for_grant, name="grant_applications"),
]
