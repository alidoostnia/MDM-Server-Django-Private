from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone
from datetime import timedelta


class SecurityPolicy(models.Model):
    singleton_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    password_expiration_days = models.PositiveIntegerField(
        default=90,
        validators=[MinValueValidator(1)],
        help_text="Default number of days before an admin password expires.",
    )
    session_timeout_minutes = models.PositiveIntegerField(
        default=15,
        validators=[MinValueValidator(1)],
        help_text="Default inactivity timeout for Django admin sessions.",
    )
    max_failed_login_attempts = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1)],
        help_text="Failed attempts allowed before login is temporarily locked.",
    )
    lockout_minutes = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1)],
        help_text="Login lock duration. The required default is 5 minutes.",
    )
    password_history_count = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1)],
        help_text="Number of previous password hashes that cannot be reused.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Security policy"
        verbose_name_plural = "Security policy"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        policy, _ = cls.objects.get_or_create(singleton_id=1)
        return policy

    def __str__(self):
        return "Authentication and session policy"


class PasswordHistory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_history",
    )
    password_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "-created_at"),
                name="security_co_user_id_48cc0f_idx",
            )
        ]


class LoginThrottle(models.Model):
    username = models.CharField(max_length=100, unique=True)
    failed_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def locked_until_for(cls, username):
        record = cls.objects.filter(username__iexact=(username or "").strip()).first()
        if not record or not record.locked_until:
            return None
        if record.locked_until <= timezone.now():
            record.failed_attempts = 0
            record.locked_until = None
            record.save(update_fields=("failed_attempts", "locked_until", "updated_at"))
            return None
        return record.locked_until

    @classmethod
    def register_failure(cls, username, policy=None):
        normalized = (username or "").strip()
        if not normalized:
            return None
        policy = policy or SecurityPolicy.load()
        with transaction.atomic():
            record, _ = cls.objects.select_for_update().get_or_create(username=normalized)
            if record.locked_until and record.locked_until > timezone.now():
                return record.locked_until
            record.failed_attempts = F("failed_attempts") + 1
            record.save(update_fields=("failed_attempts", "updated_at"))
            record.refresh_from_db(fields=("failed_attempts", "locked_until"))
            if record.failed_attempts >= policy.max_failed_login_attempts:
                record.locked_until = timezone.now() + timedelta(
                    minutes=policy.lockout_minutes
                )
                record.save(update_fields=("locked_until", "updated_at"))
            return record.locked_until

    @classmethod
    def reset_for(cls, username):
        cls.objects.filter(username__iexact=(username or "").strip()).delete()


class UserActivity(models.Model):
    class Event(models.TextChoices):
        LOGIN_SUCCESS = "login_success", "Login successful"
        LOGIN_FAILURE = "login_failure", "Login failed"
        LOGIN_BLOCKED = "login_blocked", "Login blocked"
        LOGOUT = "logout", "Logout"
        PASSWORD_CHANGE = "password_change", "Password changed"
        PASSWORD_ADMIN_SET = "password_admin_set", "Password set by admin"
        FORCE_PASSWORD_CHANGE = "force_password_change", "Password change forced"
        SESSION_TERMINATED = "session_terminated", "Session terminated"
        ADMIN_ACTIVITY = "admin_activity", "Admin activity"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="activities_performed",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="activities_received",
    )
    attempted_username = models.CharField(max_length=100, blank=True)
    event = models.CharField(max_length=32, choices=Event.choices)
    success = models.BooleanField(default=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=512, blank=True)
    path = models.CharField(max_length=512, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "User activity"
        verbose_name_plural = "Users' Activities"
        indexes = [
            models.Index(
                fields=("event", "-created_at"),
                name="security_co_event_26354a_idx",
            ),
            models.Index(
                fields=("attempted_username", "-created_at"),
                name="security_co_attempt_0f64a9_idx",
            ),
        ]

    @classmethod
    def record(cls, request=None, **kwargs):
        if request is not None:
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
            kwargs.setdefault("ip_address", (forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR")))
            kwargs.setdefault("user_agent", request.META.get("HTTP_USER_AGENT", "")[:512])
            kwargs.setdefault("path", request.path[:512])
        return cls.objects.create(**kwargs)


class ActiveSession(Session):
    class Meta:
        proxy = True
        verbose_name = "Active session"
        verbose_name_plural = "Active sessions"
