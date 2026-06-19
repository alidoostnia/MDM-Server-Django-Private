import boto3
from django.conf import settings
from botocore.config import Config

def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=settings.MINIO_ENDPOINT,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        region_name=settings.MINIO_REGION,
        config=Config(
            signature_version='s3v4',
            connect_timeout=2,   #connection timeout seconds
            read_timeout=2,      #read timeout seconds
            retries={'max_attempts': 0}  #disable long retry loops
        ),
    )
