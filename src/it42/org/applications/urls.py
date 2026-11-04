from django.urls import path

from . import views

urlpatterns = [
    path("<int:application_id>/", views.detail, name="application_detail"),
    path("<int:application_id>/status/", views.set_status, name="application_status"),
    path("<int:application_id>/questions/", views.ask, name="application_ask"),
    path("<int:application_id>/notes/", views.note, name="application_note"),
    path(
        "<int:application_id>/documents/<int:document_id>/",
        views.download,
        name="application_document",
    ),
]
