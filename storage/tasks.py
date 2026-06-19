import os
import uuid
import logging
from django.utils import timezone
import boto3
from django.conf import settings
from celery import shared_task

from .models import File
from .utils import get_s3_client

@shared_task(bind=True, max_retries=5, default_retry_delay=5)
def delete_minio_object(self, account_id, object_name):
    bucket_name = f"account-{account_id}-storage".lower()

    try:
        s3 = get_s3_client()

        s3.delete_object(Bucket=bucket_name, Key=object_name)
        logging.info(f"Deleted object '{object_name}' from bucket '{bucket_name}'")

    except Exception as exc:
        logging.error(f"Error deleting object '{object_name}': {exc}")
        raise self.retry(exc=exc)

@shared_task(bind=True, max_retries=5, default_retry_delay=5)
def upload_minio_object(self, file_id, account_id, file_content, original_name, content_type):
    try:
        file_obj = File.objects.get(file_id=file_id)
        
        bucket = f"account-{account_id}-storage".lower()
        s3 = get_s3_client()
        
        dir_name = os.path.dirname(original_name)
        base_name = os.path.basename(original_name)
        
        uid = uuid.uuid4()
        new_base_name = f"{uid}_{base_name}"
        
        if dir_name:
            object_name = f"{dir_name}/{new_base_name}"
        else:
            object_name = new_base_name
        
        # Upload from memory using BytesIO
        from io import BytesIO
        s3.upload_fileobj(
            BytesIO(file_content),
            bucket,
            object_name,
            ExtraArgs={
                "ContentType": content_type or "application/octet-stream"
            }
        )
        
        file_obj.object_name = object_name
        file_obj.original_name = original_name
        file_obj.size = len(file_content)
        file_obj.uploaded = True
        file_obj.uploaded_at = timezone.now()
        file_obj.save()
        
        logging.info(f"Uploaded file {object_name}")
        
    except Exception as exc:
        logging.error(f"Upload error for {file_id}: {exc}")
        raise self.retry(exc=exc)