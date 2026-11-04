from django.urls import path

from . import views

urlpatterns = [
    path("", views.people, name="people"),
    path("add/", views.add_signer, name="people_add"),
    path("<int:membership_id>/remove/", views.remove, name="people_remove"),
]
