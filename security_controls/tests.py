from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from devices.forms import AccountChangeForm, ForcedPasswordChangeForm
from devices.models import Account

from .models import ActiveSession, LoginThrottle, PasswordHistory, SecurityPolicy, UserActivity
from .services import set_user_password, validate_password_history


class PasswordSecurityTest(TestCase):
    def setUp(self):
        self.user = Account.objects.create_user(
            username="security-admin",
            password="Initial1!",
            first_name="Security",
            last_name="Admin",
            phone_number="09121111111",
            is_staff=True,
        )
        SecurityPolicy.objects.create(
            password_expiration_days=90,
            session_timeout_minutes=15,
            max_failed_login_attempts=2,
            lockout_minutes=5,
            password_history_count=3,
        )

    def test_complexity_validator_requires_all_character_classes(self):
        with self.assertRaises(ValidationError):
            validate_password("onlyletters!", self.user)
        validate_password("Valid123!", self.user)

    def test_previous_password_hash_cannot_be_reused(self):
        set_user_password(self.user, "Second123!")
        self.assertEqual(PasswordHistory.objects.filter(user=self.user).count(), 1)
        with self.assertRaises(ValidationError):
            validate_password_history(self.user, "Initial1!")

    def test_password_expiration_uses_per_user_override(self):
        self.user.password_changed_at = timezone.now() - timedelta(days=3)
        self.user.password_expiration_days = 2
        self.user.save(update_fields=("password_changed_at", "password_expiration_days"))
        self.assertTrue(self.user.password_is_expired(SecurityPolicy.load()))

    def test_account_change_without_password_preserves_hash(self):
        original_hash = self.user.password
        form = AccountChangeForm(
            {
                "username": self.user.username,
                "first_name": self.user.first_name,
                "last_name": self.user.last_name,
                "phone_number": self.user.phone_number,
                "password": "",
                "password_confirmation": "",
                "is_active": "on",
                "is_staff": "on",
            },
            instance=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        changed = form.save()
        self.assertEqual(changed.password, original_hash)

    def test_forced_change_requires_current_password_and_history_safe_password(self):
        form = ForcedPasswordChangeForm(
            self.user,
            {
                "current_password": "Initial1!",
                "new_password": "Replacement2@",
                "new_password_confirmation": "Replacement2@",
            },
        )
        self.assertTrue(form.is_valid(), form.errors)


class LoginThrottleTest(TestCase):
    def setUp(self):
        self.policy = SecurityPolicy.objects.create(
            max_failed_login_attempts=2,
            lockout_minutes=5,
        )

    def test_user_is_locked_for_five_minutes_at_configured_limit(self):
        self.assertIsNone(LoginThrottle.register_failure("locked-user", self.policy))
        locked_until = LoginThrottle.register_failure("locked-user", self.policy)
        self.assertIsNotNone(locked_until)
        remaining = locked_until - timezone.now()
        self.assertGreater(remaining, timedelta(minutes=4, seconds=55))
        self.assertLessEqual(remaining, timedelta(minutes=5))


class AdminSessionPolicyTest(TestCase):
    def setUp(self):
        self.user = Account.objects.create_superuser(
            username="session-admin",
            password="Session1!",
            first_name="Session",
            last_name="Admin",
            phone_number="09122222222",
        )
        SecurityPolicy.objects.create(
            password_expiration_days=90,
            session_timeout_minutes=7,
        )

    def test_second_parallel_session_is_rejected(self):
        self.client.force_login(self.user)
        first_response = self.client.get(reverse("admin:index"))
        self.assertEqual(first_response.status_code, 200)
        self.user.refresh_from_db()
        first_key = self.user.active_session_key
        self.assertTrue(first_key)

        from django.test import Client

        second_client = Client()
        second_client.force_login(self.user)
        second_response = second_client.get(reverse("admin:index"))

        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(second_response.url, reverse("admin:login"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.active_session_key, first_key)

    def test_expired_password_is_redirected_to_forced_change(self):
        self.user.password_changed_at = timezone.now() - timedelta(days=100)
        self.user.save(update_fields=("password_changed_at",))
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:index"))

        self.assertRedirects(
            response,
            reverse("admin:force_password_change"),
            fetch_redirect_response=False,
        )

    def test_configured_timeout_and_admin_activity_are_recorded(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(self.client.session.get_expiry_age(), 7 * 60)
        self.assertTrue(ActiveSession.objects.filter(session_key=self.client.session.session_key).exists())
        self.assertTrue(
            UserActivity.objects.filter(
                actor=self.user,
                event=UserActivity.Event.ADMIN_ACTIVITY,
            ).exists()
        )
