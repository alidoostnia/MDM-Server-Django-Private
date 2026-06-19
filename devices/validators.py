from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError

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