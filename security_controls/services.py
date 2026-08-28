from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import PasswordHistory, SecurityPolicy


def validate_password_history(user, raw_password):
    if user and user.pk:
        if user.check_password(raw_password):
            raise ValidationError("You cannot reuse your current password.")
        policy = SecurityPolicy.load()
        previous = PasswordHistory.objects.filter(user=user).order_by("-created_at")[
            : policy.password_history_count
        ]
        if any(check_password(raw_password, item.password_hash) for item in previous):
            raise ValidationError(
                f"You cannot reuse any of your last {policy.password_history_count} passwords."
            )


def retain_previous_password(user, encoded_password):
    if not encoded_password:
        return
    PasswordHistory.objects.create(user=user, password_hash=encoded_password)
    keep = SecurityPolicy.load().password_history_count
    retained_ids = list(
        PasswordHistory.objects.filter(user=user)
        .order_by("-created_at")
        .values_list("pk", flat=True)[:keep]
    )
    PasswordHistory.objects.filter(user=user).exclude(pk__in=retained_ids).delete()


def set_user_password(user, raw_password, previous_hash=None):
    previous_hash = previous_hash if previous_hash is not None else user.password
    user.set_password(raw_password)
    user.password_changed_at = timezone.now()
    user.must_change_password = False
    user.save(update_fields=("password", "password_changed_at", "must_change_password"))
    retain_previous_password(user, previous_hash)
