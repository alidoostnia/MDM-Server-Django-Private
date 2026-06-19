# models.py
import uuid
from django.db import models
from django.conf import settings

class File(models.Model):
    file_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="files")
    object_name = models.CharField(max_length=1024, unique=True)  # the S3/MinIO key
    original_name = models.CharField(max_length=512)
    content_type = models.CharField(max_length=255, blank=True, null=True)
    size = models.BigIntegerField(default=0)
    uploaded = models.BooleanField(default=False)  # set True after you verify object exists
    created_at = models.DateTimeField(auto_now_add=True)
    uploaded_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'original_name'], name='unique_owner_originalname')
        ]
        
class StoragePolicy(models.TextChoices):
    READ_ONLY = 'read_only', 'Read Only'
    READ_WRITE = 'read_write', 'Read & Write' # no delete permision
    FULL_ACCESS = 'full_access', 'Full Access'


class StorageSettings(models.Model):
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="storage_settings"
    )
    policy = models.CharField(
        max_length=32,
        choices=StoragePolicy.choices,
        default=StoragePolicy.FULL_ACCESS
    )
    
    storage_limit_mb = models.PositiveIntegerField(
        default=2048,  # 2GB
        help_text="Total storage limit for this account in megabytes."
    )
    
    def total_used_bytes(self):
        return sum(f.size for f in self.owner.files.all())
    
    def total_used_mb(self):
        return self.total_used_bytes() / (1024 * 1024)