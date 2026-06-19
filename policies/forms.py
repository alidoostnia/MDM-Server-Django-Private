# admin.py (or forms.py)
from django import forms
from django.core.exceptions import ValidationError
from .models import Action, Policy

from .validators import (
    validate_trigger_fields,
    validate_action_input_schema,
    validate_duplicate_action
)

class PolicyAdminForm(forms.ModelForm):
    class Meta:
        model = Policy
        fields = "__all__"
    
    def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if "trigger_kind_id" in self.fields:
                self.fields["trigger_kind_id"].label = "Trigger kind"

class ActionAdminForm(forms.ModelForm):
    class Meta:
        model = Action
        fields = "__all__"


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "input" in self.fields:
            self.fields["input"].widget = forms.HiddenInput()
        if "trigger_kind_id" in self.fields:
            self.fields["trigger_kind_id"].label = "Trigger kind"

            disallowed_kinds = {Action.TriggerKind.ALWAYS, Action.TriggerKind.INTERVAL}
            current_value = getattr(self.instance, "trigger_kind_id", None)

            self.fields["trigger_kind_id"].choices = [
                (value, label)
                for value, label in self.fields["trigger_kind_id"].choices
                if value in ("", current_value) or value not in disallowed_kinds
            ]

    def clean(self):
        cleaned = super().clean()
        validate_trigger_fields(cleaned, Action)
        validate_action_input_schema(cleaned.get("action_type"), cleaned.get("input"))
        temp_instance = Action(**cleaned)
        if self.instance.pk:
            temp_instance.pk = self.instance.pk
        validate_duplicate_action(temp_instance, Action)
    
        return cleaned