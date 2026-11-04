from django.urls import path

from . import views

urlpatterns = [
    path("<int:request_id>/", views.detail, name="request_detail"),
    path("<int:request_id>/sign/", views.sign, name="request_sign"),
    path("<int:request_id>/decline/", views.decline, name="request_decline"),
    path(
        "<int:request_id>/documents/<int:document_id>/",
        views.download,
        name="request_document",
    ),
]
