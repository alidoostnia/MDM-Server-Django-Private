from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password, get_password_validators
from django.core.exceptions import ValidationError
from django.conf import settings
from django.utils.safestring import mark_safe


from .models import Account
from .validators import iran_phone_validator
from captcha.fields import CaptchaField


class AdminCaptchaAuthenticationForm(AuthenticationForm):
    """Require a local CAPTCHA before checking admin credentials."""

    captcha = CaptchaField(label="Verification code")

    def clean(self):
        if "captcha" not in self.cleaned_data:
            captcha_errors = self._errors.get("captcha")
            if captcha_errors:
                self.add_error(None, captcha_errors[0])
            return self.cleaned_data
        return super().clean()


class AccountCreationForm(forms.ModelForm):
    password_help_text = mark_safe("<br>".join([
    v.get_help_text() for v in get_password_validators(settings.AUTH_PASSWORD_VALIDATORS)
    ]))
    
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput,
        strip=False,
        help_text=password_help_text
    )
    password_confirmation = forms.CharField(
        label="Password confirmation",
        widget=forms.PasswordInput,
        strip=False,
        help_text="Enter the same password as before, for verification.",
    )
    phone_number = forms.CharField(validators=[iran_phone_validator])

    class Meta:
        model = Account
        fields = ("username", "first_name", "last_name", "phone_number", "device")

    def clean_password_confirmation(self):
        p1 = self.cleaned_data.get("password")
        p2 = self.cleaned_data.get("password_confirmation")
        if p1 != p2:
            raise ValidationError("Passwords do not match.")
        validate_password(p1)
        return p2

    def save(self, commit=True):
        account = super().save(commit=False)
        raw = self.cleaned_data["password"]
        account.set_password(raw)
        if commit:
            account.save()
        return account


class AccountChangeForm(forms.ModelForm):
    password_help_text = mark_safe(
            "Leave blank to keep current password.<br><br>" + "<br>".join([
                v.get_help_text() for v in get_password_validators(settings.AUTH_PASSWORD_VALIDATORS)
            ])
        )
    password = forms.CharField(
        label="New password",
        widget=forms.PasswordInput,
        required=False,
        strip=False,
        help_text=password_help_text
    )    

    password_confirmation = forms.CharField(
        label="New password confirmation",
        widget=forms.PasswordInput,
        required=False,
        strip=False,
        help_text="Enter the same new password for confirmation.",
    )
    
    phone_number = forms.CharField(validators=[iran_phone_validator])

    class Meta:
        model = Account
        fields = ("username", "first_name", "last_name", "phone_number", "device")

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password")
        p2 = cleaned.get("password_confirmation")
        if p1 or p2:
            # if either provided, require both and validate
            if not p1 or not p2:
                raise ValidationError("Both new password fields are required to change the password.")
            if p1 != p2:
                raise ValidationError("The two password fields didn't match.")

            validate_password(p1)
        return cleaned

    def save(self, commit=True):
        account = super().save(commit=False)
        new_pass = self.cleaned_data.get("password")
        if new_pass:
            account.set_password(new_pass)
        if commit:
            account.save()
        return account
