from django.urls import path

from it42.org.applications import views as applications

from . import views

urlpatterns = [
    path("", views.grant_list, name="grant_list"),
    path("new/", views.grant_create, name="grant_create"),
    path("board/action/", views.board_action, name="board_action"),
    path("archive/", views.archive, name="grant_archive"),
    path("drafts/", views.grant_drafts, name="grant_drafts"),
    path("published/", views.published, name="grant_published"),
    path(
        "<int:grant_id>/published/", views.grant_published_preview, name="grant_published_preview"
    ),
    path("<int:grant_id>/edit/", views.grant_edit, name="grant_edit"),
    path("<int:grant_id>/publish/", views.grant_publish, name="grant_publish"),
    path("<int:grant_id>/close/", views.grant_close, name="grant_close"),
    path("<int:grant_id>/duplicate/", views.grant_duplicate, name="grant_duplicate"),
    path(
        "<int:grant_id>/signature-deadline/",
        views.grant_signature_deadline,
        name="grant_signature_deadline",
    ),
    path("<int:grant_id>/applications/", applications.for_grant, name="grant_applications"),
    path("folders/new/", views.folder_create, name="folder_create"),
    path("folders/<int:folder_id>/rename/", views.folder_rename, name="folder_rename"),
    path("folders/<int:folder_id>/delete/", views.folder_delete, name="folder_delete"),
    path("categories/", views.category_list, name="category_list"),
    path("categories/new/", views.category_create, name="category_create"),
    path("categories/<int:category_id>/rename/", views.category_rename, name="category_rename"),
    path("categories/<int:category_id>/delete/", views.category_delete, name="category_delete"),
    path("templates/", views.template_list, name="template_list"),
    path("templates/<int:template_id>/rename/", views.template_rename, name="template_rename"),
    path("templates/<int:template_id>/delete/", views.template_delete, name="template_delete"),
]
