import boto3
from django.conf import settings
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Account
from storage.models import StorageSettings
from .tasks import create_minio_bucket, delete_minio_bucket
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Account)
def create_s3_bucket_for_account(sender, instance: Account, created: bool, **kwargs):
    """
    On Account creation:
    - Create a MinIO bucket for the user
    - Create StorageSettings (default policy)
    """
    if created:
        transaction.on_commit(lambda: create_minio_bucket.delay(instance.account_id))
        logger.info(f"Triggered MinIO bucket creation for Account {instance.account_id}.")

@receiver(post_delete, sender=Account)
def delete_minio_bucket_on_user_delete(sender, instance, **kwargs):
    transaction.on_commit(lambda: delete_minio_bucket.delay(instance.account_id))
    logger.info(f"Triggered MinIO bucket deletion for Account {instance.account_id}.")