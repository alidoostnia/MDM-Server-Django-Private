# admin.py
import tempfile
import os
import uuid
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import ValidationError
from .models import File, StorageSettings
from .tasks import upload_minio_object
from django.contrib import messages
from .forms import FileAdminForm

@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ('original_name','owner','uploaded','size','uploaded_at','object_name')
    readonly_fields = ('object_name','uploaded','size','uploaded_at')
    search_fields = ('original_name','object_name','owner__username')
    form = FileAdminForm
    autocomplete_fields = ("owner",)
    list_filter = ("owner",)

    
    def save_model(self, request, obj, form, change):
        upload = form.cleaned_data.get("upload_file")
        
        # Set temporary object_name
        if not obj.object_name:
            obj.object_name = f"pending_{uuid.uuid4().hex}"
        
        super().save_model(request, obj, form, change)
        
        if upload:
            entered_name = obj.original_name
            
            file_content = upload.read()
            
            obj.uploaded = False
            obj.size = len(file_content)
            obj.save(update_fields=['uploaded', 'size'])
            
            # Send to Celery for upload to MinIO
            upload_minio_object.delay(
                str(obj.file_id),
                obj.owner.account_id,
                file_content,
                entered_name,
                obj.content_type,
            )

@admin.register(StorageSettings)
class StorageSettingsAdmin(admin.ModelAdmin):
    list_display = ("owner", "policy", 'storage_limit_mb', 'current_usage')
    list_filter = ("policy",)
    search_fields = ("owner__username", "owner__phone_number")
    
    @admin.display(description="Used MB")
    def current_usage(self, obj):
        return f"{obj.total_used_mb():.2f} MB"

class StorageSettingsInline(admin.StackedInline):
    model = StorageSettings
    can_delete = False
    extra = 0
    fk_name = "owner"
