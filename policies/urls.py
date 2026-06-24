from django.urls import path
from . import views

urlpatterns = [
    path("push-notifications/", views.create_external_push_notification, name="external-push-notification"),
]
