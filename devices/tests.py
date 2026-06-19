from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from devices.models import Account, Device


class AccountLoginAPITestCase(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(
            android_id="android-123",
            device_name="Test Device",
            imeis="imei-123",
        )
        self.account = Account.objects.create_user(
            username="testuser",
            password="strong-password",
            first_name="Test",
            last_name="User",
            phone_number="09120000000",
            device=self.device,
        )
        self.url = reverse("account-login")

    def test_login_success_returns_tokens_and_device(self):
        response = self.client.post(
            self.url,
            {
                "username": "testuser",
                "password": "strong-password",
                "imei": "imei-123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["device_id"], str(self.device.device_id))
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertIn("access_exp", response.data)
        self.assertIn("refresh_exp", response.data)

    def test_login_invalid_username_returns_401(self):
        response = self.client.post(
            self.url,
            {
                "username": "missinguser",
                "password": "strong-password",
                "imei": "imei-123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"], "Invalid username or password")

    def test_login_invalid_password_returns_401(self):
        response = self.client.post(
            self.url,
            {
                "username": "testuser",
                "password": "wrong-password",
                "imei": "imei-123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"], "Invalid username or password")

    def test_login_missing_fields_returns_400(self):
        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", response.data)
        self.assertIn("password", response.data)
        self.assertIn("imei", response.data)

    def test_login_requires_device_for_non_staff(self):
        account = Account.objects.create_user(
            username="nodevice",
            password="strong-password",
            first_name="No",
            last_name="Device",
            phone_number="09120000001",
            device=None,
        )

        response = self.client.post(
            self.url,
            {
                "username": account.username,
                "password": "strong-password",
                "imei": "imei-any",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "DEVICE_REQUIRED")

    def test_login_allows_staff_without_device(self):
        account = Account.objects.create_user(
            username="staffuser",
            password="strong-password",
            first_name="Staff",
            last_name="User",
            phone_number="09120000002",
            is_staff=True,
            device=None,
        )

        response = self.client.post(
            self.url,
            {
                "username": account.username,
                "password": "strong-password",
                "imei": "imei-any",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["device_id"])
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_updates_last_login(self):
        self.account.last_login = None
        self.account.save(update_fields=["last_login"])

        response = self.client.post(
            self.url,
            {
                "username": "testuser",
                "password": "strong-password",
                "imei": "imei-123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_login)

    def test_login_rejects_when_imei_mismatches(self):
        response = self.client.post(
            self.url,
            {
                "username": "testuser",
                "password": "strong-password",
                "imei": "wrong-imei",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "DEVICE_MISMATCH")


class AccountTokenRefreshAPITestCase(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(
            android_id="android-456",
            device_name="Refresh Device",
            imeis="imei-456",
        )
        self.account = Account.objects.create_user(
            username="refresher",
            password="strong-password",
            first_name="Refresh",
            last_name="User",
            phone_number="09120000003",
            device=self.device,
        )
        self.url = reverse("token-refresh")

    def test_refresh_success_returns_new_tokens(self):
        refresh = RefreshToken.for_user(self.account)

        response = self.client.post(
            self.url,
            {"refresh": str(refresh)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertIn("access_exp", response.data)
        self.assertIn("refresh_exp", response.data)
        self.assertNotEqual(str(refresh), response.data["refresh"])

    def test_refresh_missing_token_returns_400(self):
        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Refresh token is required")

    def test_refresh_invalid_token_returns_401(self):
        response = self.client.post(
            self.url,
            {"refresh": "invalid.token.value"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"], "Invalid or expired refresh token")


class AccountLogoutAPITestCase(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(
            android_id="android-789",
            device_name="Logout Device",
            imeis="imei-789",
        )
        self.account = Account.objects.create_user(
            username="logoutuser",
            password="strong-password",
            first_name="Logout",
            last_name="User",
            phone_number="09120000004",
            device=self.device,
        )
        self.url = reverse("account-logout")

    def test_logout_requires_imei(self):
        response = self.client.post(
            self.url,
            {"username": "logoutuser", "password": "strong-password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("imei", response.data)

    def test_logout_with_valid_credentials_and_device_identifiers_succeeds(self):
        response = self.client.post(
            self.url,
            {
                "username": "logoutuser",
                "password": "strong-password",
                "imei": "imei-789",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Logged out successfully")

    def test_logout_with_invalid_imei_returns_401(self):
        response = self.client.post(
            self.url,
            {
                "username": "logoutuser",
                "password": "strong-password",
                "imei": "wrong-imei",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "DEVICE_MISMATCH")