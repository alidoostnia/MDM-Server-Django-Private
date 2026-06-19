from django.core.exceptions import ValidationError
from jsonschema import validate as jsonschema_validate, ValidationError as JSONSchemaError
from datetime import datetime, timezone

def validate_trigger_fields(instance_or_data, model_cls):
    get = instance_or_data.get if isinstance(instance_or_data, dict) else getattr
    tk = get("trigger_kind_id")

    if tk == model_cls.TriggerKind.INTERVAL or tk == model_cls.TriggerKind.ALWAYS:
        if model_cls.__name__ == "Action":
            raise ValidationError("Interval and Always triggers are not allowed for Actions.")
    
    if tk == model_cls.TriggerKind.REGEX and not get("regex"):
        raise ValidationError("Regex field is required for Regex Trigger.")
    
    if tk == model_cls.TriggerKind.INTERVAL and not get("interval_time"):
        raise ValidationError("Interval Time is required for Interval Trigger.")

    if tk == model_cls.TriggerKind.EXACT_TIME:
        exact_time = get("exact_time")
        if not exact_time:
            raise ValidationError("Exact Time is required for Exact Time Trigger.")
        # ensure it's not in the past
        now = datetime.now(timezone.utc)
        if exact_time < now:
            raise ValidationError("Exact Time cannot be in the past.")

def validate_action_input_schema(action_type, input_value):
    if not action_type or not action_type.input_schema:
        return

    schema = action_type.input_schema
    value = input_value if input_value is not None else {}

    try:
        jsonschema_validate(instance=value, schema=schema)
    except JSONSchemaError as exc:
        raise ValidationError({
            "input": f"Input does not match schema: {exc.message}"
        })


def validate_duplicate_action(instance, model_cls):
    filters = {
        "action_type": getattr(instance, "action_type", None),
        "name": getattr(instance, "name", None),
        "input": getattr(instance, "input", None),
        "trigger_kind_id": getattr(instance, "trigger_kind_id", None),
    }

    duplicates = model_cls.objects.filter(**filters)

    if getattr(instance, "regex", None):
        duplicates = duplicates.filter(regex=instance.regex)
    if getattr(instance, "exact_time", None):
        duplicates = duplicates.filter(exact_time=instance.exact_time)

    if instance.pk:
        duplicates = duplicates.exclude(pk=instance.pk)

    if duplicates.exists():
        raise ValidationError("An identical Action already exists.")