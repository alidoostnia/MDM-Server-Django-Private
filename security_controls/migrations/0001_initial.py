import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sessions", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SecurityPolicy",
            fields=[
                (
                    "singleton_id",
                    models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False),
                ),
                (
                    "password_expiration_days",
                    models.PositiveIntegerField(
                        default=90,
                        help_text="Default number of days before an admin password expires.",
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "session_timeout_minutes",
                    models.PositiveIntegerField(
                        default=15,
                        help_text="Default inactivity timeout for Django admin sessions.",
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "max_failed_login_attempts",
                    models.PositiveIntegerField(
                        default=5,
                        help_text="Failed attempts allowed before login is temporarily locked.",
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "lockout_minutes",
                    models.PositiveIntegerField(
                        default=5,
                        help_text="Login lock duration. The required default is 5 minutes.",
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "password_history_count",
                    models.PositiveIntegerField(
                        default=5,
                        help_text="Number of previous password hashes that cannot be reused.",
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Security policy",
                "verbose_name_plural": "Security policy",
            },
        ),
        migrations.CreateModel(
            name="LoginThrottle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(max_length=100, unique=True)),
                ("failed_attempts", models.PositiveIntegerField(default=0)),
                ("locked_until", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="PasswordHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("password_hash", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="password_history",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [models.Index(fields=["user", "-created_at"], name="security_co_user_id_48cc0f_idx")],
            },
        ),
        migrations.CreateModel(
            name="UserActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("attempted_username", models.CharField(blank=True, max_length=100)),
                (
                    "event",
                    models.CharField(
                        choices=[
                            ("login_success", "Login successful"),
                            ("login_failure", "Login failed"),
                            ("login_blocked", "Login blocked"),
                            ("logout", "Logout"),
                            ("password_change", "Password changed"),
                            ("password_admin_set", "Password set by admin"),
                            ("force_password_change", "Password change forced"),
                            ("session_terminated", "Session terminated"),
                            ("admin_activity", "Admin activity"),
                        ],
                        max_length=32,
                    ),
                ),
                ("success", models.BooleanField(default=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=512)),
                ("path", models.CharField(blank=True, max_length=512)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="activities_performed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "target_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="activities_received",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "User activity",
                "verbose_name_plural": "Users' Activities",
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(fields=["event", "-created_at"], name="security_co_event_26354a_idx"),
                    models.Index(fields=["attempted_username", "-created_at"], name="security_co_attempt_0f64a9_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ActiveSession",
            fields=[],
            options={
                "verbose_name": "Active session",
                "verbose_name_plural": "Active sessions",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("sessions.session",),
        ),
    ]
