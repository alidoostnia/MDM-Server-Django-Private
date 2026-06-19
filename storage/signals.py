from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import File
from .tasks import delete_minio_object

@receiver(post_delete, sender=File)
def delete_object_from_minio(sender, instance: File, **kwargs):
    delete_minio_object.delay(instance.owner.account_id, instance.object_name)