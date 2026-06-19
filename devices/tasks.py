import time, json
import boto3

from celery import shared_task
from django.conf import settings
from pymongo import MongoClient, ASCENDING

from .models import Account
from storage.models import StorageSettings
from storage.utils import get_s3_client
import logging

def get_db():
    client = MongoClient(settings.MONGO_URI)
    dbname = settings.MONGO_URI.rsplit("/", 1)[-1].split("?")[0] or "mdm_logs"
    return client[dbname]

@shared_task(bind=True, max_retries=5, default_retry_delay=5)
def store_log(self, agent_id, payload):
    try:
        db = get_db()
        logs = db[settings.LOGS_COLLECTION]
        # payload is expected dict
        doc = {"agentId": agent_id, "ts": int(time.time()), **payload}
        logs.insert_one(doc)
    except Exception as exc:
        raise self.retry(exc=exc)

@shared_task(bind=True, max_retries=5, default_retry_delay=10)
def create_minio_bucket(self, account_id):
    try:
        try:
            account = Account.objects.get(pk=account_id)
        except Account.DoesNotExist:
            logging.error(f"Account {account_id} does not exist. Cannot create bucket.")
            return
        
        storage_settings, created_policy = StorageSettings.objects.get_or_create(owner=account)
        
        if created_policy:
            logging.info(f"StorageSettings created for Account {account.account_id}.")
        else:
            logging.info(f"StorageSettings already existed for Account {account.account_id}.")
        
        bucket_name = f"account-{account.account_id}-storage".lower()

        s3 = get_s3_client()

        s3.create_bucket(Bucket=bucket_name)
        account.bucket_created = True
        account.save(update_fields=["bucket_created"])
        
        logging.info(f"Created MinIO bucket '{bucket_name}' for Account {account.account_id}.")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        logging.warning(f"Bucket '{bucket_name}' already exists for Account {account.account_id}.")
    except Exception as exc:
        # Retry 5 times (Celery beat)
        raise self.retry(exc=exc) 

@shared_task(bind=True, max_retries=5, default_retry_delay=10)
def delete_minio_bucket(self, account_id):
    try:
        bucket_name = f"account-{account_id}-storage".lower()

        s3 = get_s3_client()

        # First: delete all objects inside the bucket
        objects = s3.list_objects_v2(Bucket=bucket_name).get("Contents", [])

        if objects:
            delete_list = [{"Key": obj["Key"]} for obj in objects]
            s3.delete_objects(Bucket=bucket_name, Delete={"Objects": delete_list})

        # Second: delete the bucket itself
        s3.delete_bucket(Bucket=bucket_name)

        logging.info(f"Deleted MinIO bucket '{bucket_name}' for Account {account_id}.")
        
        try:
            account = Account.objects.get(pk=account_id)
            account.bucket_created = False
            account.save(update_fields=["bucket_created"])
        except Account.DoesNotExist:
            logging.warning(f"Account {account_id} does not exist. Cannot update bucket_created flag.")
        
    except s3.exceptions.NoSuchBucket:
        logging.warning(f"Bucket '{bucket_name}' does not exist for Account {account_id}.")
    except Exception as exc:
        raise self.retry(exc=exc)