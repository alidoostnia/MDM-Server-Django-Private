from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("devices", "0007_account_national_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="active_session_key",
            field=models.CharField(blank=True, default="", editable=False, max_length=40),
        ),
        migrations.AddField(
            model_name="account",
            name="must_change_password",
            field=models.BooleanField(
                default=False,
                help_text="Require this user to choose a new password at the next admin login.",
            ),
        ),
        migrations.AddField(
            model_name="account",
            name="password_changed_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="account",
            name="password_expiration_days",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Optional per-user override. Leave blank to use the Settings policy.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="account",
            name="session_timeout_minutes",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Optional per-user override. Leave blank to use the Settings policy.",
                null=True,
            ),
        ),
    ]
