from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import get_password_validators, validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.safestring import mark_safe

from captcha.fields import CaptchaField

from security_controls.models import LoginThrottle, SecurityPolicy, UserActivity
from security_controls.services import validate_password_history

from .models import Account
from .validators import iran_phone_validator


def _disable_autocomplete(form):
    for name, field in form.fields.items():
        if "username" in name.lower() or "password" in name.lower():
            field.widget.attrs["autocomplete"] = "off"


class AdminCaptchaAuthenticationForm(AuthenticationForm):
    """Require CAPTCHA, throttle failures, and audit every admin login attempt."""

    captcha = CaptchaField(label="Verification code")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _disable_autocomplete(self)

    def clean(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if "captcha" not in self.cleaned_data:
            captcha_errors = self._errors.get("captcha")
            if captcha_errors:
                self.add_error(None, captcha_errors[0])
                UserActivity.record(
                    self.request,
                    attempted_username=username,
                    event=UserActivity.Event.LOGIN_FAILURE,
                    success=False,
                    details={"reason": "captcha"},
                )
            return self.cleaned_data

        locked_until = LoginThrottle.locked_until_for(username)
        if locked_until:
            UserActivity.record(
                self.request,
                attempted_username=username,
                event=UserActivity.Event.LOGIN_BLOCKED,
                success=False,
                details={"locked_until": locked_until.isoformat()},
            )
            raise ValidationError(
                f"Login is temporarily locked until {timezone.localtime(locked_until):%Y-%m-%d %H:%M:%S}."
            )

        try:
            cleaned = super().clean()
        except ValidationError:
            # Policy failures have a user_cache. Only bad credentials increase the counter.
            if self.user_cache is None:
                locked_until = LoginThrottle.register_failure(username, SecurityPolicy.load())
                reason = "invalid_credentials"
            else:
                locked_until = None
                reason = "active_session"
            UserActivity.record(
                self.request,
                target_user=self.user_cache,
                attempted_username=username,
                event=(
                    UserActivity.Event.LOGIN_BLOCKED
                    if locked_until or self.user_cache is not None
                    else UserActivity.Event.LOGIN_FAILURE
                ),
                success=False,
                details={
                    "reason": reason,
                    "locked_until": locked_until.isoformat() if locked_until else None,
                },
            )
            raise

        LoginThrottle.reset_for(username)
        user = self.get_user()
        UserActivity.record(
            self.request,
            actor=user,
            target_user=user,
            attempted_username=username,
            event=UserActivity.Event.LOGIN_SUCCESS,
        )
        previous_login = (
            timezone.localtime(user.last_login).strftime("%Y-%m-%d %H:%M:%S")
            if user.last_login
            else "first login"
        )
        forwarded = self.request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip_address = forwarded.split(",")[0].strip() or self.request.META.get("REMOTE_ADDR", "unknown")
        roles = ", ".join(user.groups.values_list("name", flat=True)) or (
            "Superuser" if user.is_superuser else "Staff"
        )
        messages.success(
            self.request,
            "Successful login — user: {user}; IP: {ip}; previous login: {previous}; "
            "role(s): {roles}. You are responsible for protecting sensitive information, "
            "using it only for authorized duties, and signing out when finished.".format(
                user=user.username,
                ip=ip_address,
                previous=previous_login,
                roles=roles,
            ),
        )
        return cleaned

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.active_session_key:
            active = Session.objects.filter(
                session_key=user.active_session_key,
                expire_date__gt=timezone.now(),
            ).exists()
            if active:
                raise ValidationError(
                    "This user already has an active session. Ask an administrator to terminate it first.",
                    code="active_session",
                )
            Account.objects.filter(pk=user.pk).update(active_session_key="")
            user.active_session_key = ""


class AccountCreationForm(forms.ModelForm):
    password_help_text = mark_safe(
        "<br>".join(v.get_help_text() for v in get_password_validators(settings.AUTH_PASSWORD_VALIDATORS))
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
        strip=False,
        help_text=password_help_text,
    )
    password_confirmation = forms.CharField(
        label="Password confirmation",
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
        strip=False,
        help_text="Enter the same password as before, for verification.",
    )
    phone_number = forms.CharField(validators=[iran_phone_validator])

    class Meta:
        model = Account
        fields = "__all__"
        widgets = {"username": forms.TextInput(attrs={"autocomplete": "off"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _disable_autocomplete(self)

    def clean_password_confirmation(self):
        password = self.cleaned_data.get("password")
        confirmation = self.cleaned_data.get("password_confirmation")
        if password != confirmation:
            raise ValidationError("Passwords do not match.")
        validate_password(password, self.instance)
        return confirmation

    def save(self, commit=True):
        account = super().save(commit=False)
        account.set_password(self.cleaned_data["password"])
        account.password_changed_at = timezone.now()
        account.must_change_password = True
        if commit:
            account.save()
            self.save_m2m()
        return account


class AccountChangeForm(forms.ModelForm):
    password_help_text = mark_safe(
        "Leave blank to keep the current password.<br><br>"
        + "<br>".join(v.get_help_text() for v in get_password_validators(settings.AUTH_PASSWORD_VALIDATORS))
    )
    password = forms.CharField(
        label="New password",
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
        required=False,
        strip=False,
        help_text=password_help_text,
    )
    password_confirmation = forms.CharField(
        label="New password confirmation",
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
        required=False,
        strip=False,
        help_text="Enter the same new password for confirmation.",
    )
    phone_number = forms.CharField(validators=[iran_phone_validator])

    class Meta:
        model = Account
        fields = "__all__"
        widgets = {"username": forms.TextInput(attrs={"autocomplete": "off"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_password = self.instance.password
        if "password_changed_at" in self.fields:
            self.fields["password_changed_at"].disabled = True
            self.fields["password_changed_at"].required = False
        _disable_autocomplete(self)

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        confirmation = cleaned.get("password_confirmation")
        if password or confirmation:
            if not password or not confirmation:
                raise ValidationError("Both new password fields are required to change the password.")
            if password != confirmation:
                raise ValidationError("The two password fields didn't match.")
            validate_password(password, self.instance)
            validate_password_history(self.instance, password)
        return cleaned

    def save(self, commit=True):
        account = super().save(commit=False)
        new_password = self.cleaned_data.get("password")
        if new_password:
            account.set_password(new_password)
            account.password_changed_at = timezone.now()
        else:
            account.password = self._original_password
        if commit:
            account.save()
            self.save_m2m()
        return account


class ForcedPasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}), strip=False
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}), strip=False
    )
    new_password_confirmation = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}), strip=False
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        _disable_autocomplete(self)

    def clean_current_password(self):
        password = self.cleaned_data["current_password"]
        if not self.user.check_password(password):
            raise ValidationError("The current password is incorrect.")
        return password

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("new_password")
        confirmation = cleaned.get("new_password_confirmation")
        if password and confirmation and password != confirmation:
            self.add_error("new_password_confirmation", "The two passwords do not match.")
        if password:
            validate_password(password, self.user)
            validate_password_history(self.user, password)
        return cleaned
