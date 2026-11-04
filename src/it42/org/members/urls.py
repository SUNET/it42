from django.urls import path

from . import views

urlpatterns = [
    path("", views.members, name="members"),
    path("approve/<int:user_id>/", views.approve, name="member_approve"),
    path("<int:membership_id>/role/", views.set_role, name="member_role"),
    path("<int:membership_id>/remove/", views.remove, name="member_remove"),
]
