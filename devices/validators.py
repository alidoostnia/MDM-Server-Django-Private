from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
import re

iran_phone_validator = RegexValidator(
    regex=r"^09\d{9}$",
    message="Enter a valid Iranian mobile number (11 digits, starting with 09).",
)

def validate_non_empty_str(value):
    if value is None or str(value).strip() == "":
        raise ValidationError("This field cannot be blank.")
    
national_id_validator = RegexValidator(
    regex=r'^\d{10}$',
    message="National ID must be exactly 10 digits."
)


class ComplexityPasswordValidator:
    """Require a letter, a number, and a non-alphanumeric character."""

    def validate(self, password, user=None):
        if len(password or "") < 8:
            raise ValidationError("The password must contain at least 8 characters.")
        if not re.search(r"[A-Za-z]", password):
            raise ValidationError("The password must contain at least one letter.")
        if not re.search(r"\d", password):
            raise ValidationError("The password must contain at least one number.")
        if not re.search(r"[^A-Za-z0-9]", password):
            raise ValidationError("The password must contain at least one special character.")

    def get_help_text(self):
        return (
            "Your password must contain at least 8 characters, including at least "
            "one letter, one number, and one special character."
        )
