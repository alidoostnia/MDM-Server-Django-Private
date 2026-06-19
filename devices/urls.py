from django.urls import path
from .views import AccountLoginAPIView, AccountLogoutAPIView, AccountTokenRefreshAPIView

urlpatterns = [
    path("login/", AccountLoginAPIView.as_view(), name="account-login"),
    path("logout/", AccountLogoutAPIView.as_view(), name="account-logout"),
    path("refresh/", AccountTokenRefreshAPIView.as_view(), name="token-refresh"),
]