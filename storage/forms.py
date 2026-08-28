from django import forms
from .models import File
from django.core.exceptions import ValidationError
from .validators import validate_file_content

class FileAdminForm(forms.ModelForm):
    upload_file = forms.FileField(required=True)

    class Meta:
        model = File
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        upload_file = cleaned_data.get('upload_file')
        original_name = cleaned_data.get('original_name')
        
        if upload_file and original_name:
            # Check extension match
            if '.' in original_name:
                entered_ext = original_name.rsplit('.', 1)[1].lower()
            else:
                entered_ext = ''
            if '.' in upload_file.name:
                uploaded_ext = upload_file.name.rsplit('.', 1)[1].lower()
            else:
                uploaded_ext = ''

            if entered_ext != uploaded_ext:
                self.add_error(
                    'original_name',
                    f"Extension mismatch: expected '.{uploaded_ext}' but got '.{entered_ext}'."
                )
            else:
                content = upload_file.read()
                upload_file.seek(0)
                try:
                    cleaned_data["content_type"] = validate_file_content(
                        original_name,
                        content,
                        upload_file.content_type,
                    )
                except ValidationError as exc:
                    self.add_error("upload_file", exc)
        return cleaned_data
