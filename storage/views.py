import boto3, uuid
import os
from botocore.exceptions import ClientError, ConnectionError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.conf import settings
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework import status
from django.utils import timezone

from .permissions import CanDeleteFiles, CanUploadFiles, CanReadFiles
from .models import File
from .utils import get_s3_client
from urllib.parse import urlparse, urlunparse
from django.core.exceptions import ValidationError

from .validators import ensure_supported_extension, validate_file_content


@swagger_auto_schema(
    method='post',
    operation_description="Generate a presigned URL for direct file upload to MinIO.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            'file_name': openapi.Schema(
                type=openapi.TYPE_STRING,
                description='Original name of the file (e.g. image.jpg)'
            ),
            'content_type': openapi.Schema(
                type=openapi.TYPE_STRING,
                description='MIME type of the file (e.g. image/jpeg)',
                default='application/octet-stream'
            ),
            'file_size': openapi.Schema(
                type=openapi.TYPE_INTEGER,
                description='Size of the file in bytes',
                example=1048576
            ),
        },
        required=['file_name', 'file_size']
    ),
    responses={
        200: openapi.Response(
            description="Presigned upload URL generated successfully.",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'upload_url': openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="Temporary presigned URL for uploading the file"
                    ),
                    'file_id': openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="UUID of the file record for later download"
                    ),
                }
            )
        ),
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden(Storage Limit Exceeded)",
        500: "Internal Server Error",
    }
)
@api_view(['POST'])
@permission_classes([IsAuthenticated, CanUploadFiles])
def generate_presigned_upload(request):
    account = request.user
    file_name = request.data.get('file_name')
    file_size = request.data.get('file_size')
    content_type = request.data.get('content_type', 'application/octet-stream')
    
    
    if File.objects.filter(owner=account, original_name=file_name).exists():
        return Response({'msg': 'file with this name already exists'}, status=status.HTTP_400_BAD_REQUEST)
    
    if not file_name:
        return Response({'msg': 'file_name required'}, status=status.HTTP_400_BAD_REQUEST)

    if not file_size:
        return Response({'msg': 'file_size required'}, status=status.HTTP_400_BAD_REQUEST)
    
    settings_obj = account.storage_settings
    
    file_size = int(file_size)
    used_mb = settings_obj.total_used_mb()
    limit_mb = settings_obj.storage_limit_mb
    future_usage_mb = used_mb + (file_size / 1024 / 1024)
    
    if future_usage_mb > limit_mb:
        return Response({'msg': 'Storage limit exceeded'}, status=status.HTTP_403_FORBIDDEN)

    try:
        ensure_supported_extension(file_name)
    except ValidationError as exc:
        return Response({'msg': exc.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
    
    file_path = file_name
    dir_name = os.path.dirname(file_path)
    base_name = os.path.basename(file_path)
    uid = uuid.uuid4()
    new_base_name = f"{uid}_{base_name}"
    
    if dir_name:
        object_name = f"{dir_name}/{new_base_name}"
    else:
        object_name = new_base_name
    
    s3 = get_s3_client()
    
    bucket = f"account-{account.account_id}-storage".lower()
        
    try:
        presigned_post = s3.generate_presigned_post(
            Bucket=bucket,
            Key=object_name,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 0, file_size]  # <= Hard limit!
            ],
            ExpiresIn=600
        )
            
        # parsed = urlparse(presigned_post['url'])
        
        # new_url = urlunparse((
        #     urlparse(settings.MINIO_EXTERNAL_ENDPOINT).scheme,
        #     urlparse(settings.MINIO_EXTERNAL_ENDPOINT).netloc,
        #     parsed.path,
        #     parsed.params,
        #     parsed.query,
        #     parsed.fragment
        # ))
        
        # presigned_post['url'] = new_url
        

    except ClientError as e:
        return Response({'msg': 'Could not generate presigned url'}, status=500)
    except ConnectionError:
        return Response({'msg': 'storage service unavailable'}, status=500)
    
    file = File.objects.create(
        owner=account,
        object_name=object_name,
        original_name=file_path,
        content_type=content_type,
        size=file_size,
        uploaded=False
    )
    
    return Response({
        'upload_url': presigned_post,
        'file_id': str(file.file_id)
    })




@swagger_auto_schema(
    method='post',
    operation_description="Mark a file upload as complete after the client has uploaded it to MinIO.\n\n"
                          "This endpoint verifies the file exists in MinIO and updates its metadata in the database.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            'file_id': openapi.Schema(
                type=openapi.TYPE_STRING,
                description='The unique ID of the file record created during presigned upload URL generation.'
            ),
        },
        required=['file_id']
    ),
    responses={
        200: openapi.Response(
            description="File upload verified and marked as complete.",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'msg': openapi.Schema(type=openapi.TYPE_STRING, example='ok')
                }
            )
        ),
        400: "Bad Request (missing or invalid file_id)",
        401: "Unauthorized",
        404: "File or object not found",
        500: "Internal Server Error",
    }
)
@api_view(['POST'])
@permission_classes([IsAuthenticated, CanUploadFiles])
def complete_upload(request):
    account = request.user
    file_id = request.data.get('file_id')
    if not file_id:
        return Response({'msg': 'file_id required'}, status=400)
    try:
        file = File.objects.get(pk=file_id, owner=account)
    except File.DoesNotExist:
        return Response({'msg': 'file not found'}, status=404)
    except Exception:
        return Response({'msg': 'invalid file_id'}, status=400)

    s3 = get_s3_client()
    bucket = f"account-{account.account_id}-storage".lower()
    try:
        head = s3.head_object(Bucket=bucket, Key=file.object_name)
    except ClientError:
        return Response({'msg': 'object not found in storage'}, status=404)

    try:
        stored_object = s3.get_object(
            Bucket=bucket,
            Key=file.object_name,
            Range="bytes=0-65535",
        )
        sample = stored_object["Body"].read(65536)
        verified_type = validate_file_content(
            file.original_name,
            sample,
            head.get("ContentType") or file.content_type,
        )
    except ValidationError as exc:
        try:
            s3.delete_object(Bucket=bucket, Key=file.object_name)
        except ClientError:
            return Response(
                {'msg': 'Upload was rejected, but storage cleanup failed'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        file._skip_storage_delete = True
        file.delete()
        return Response(
            {'msg': f"Upload rejected: {exc.messages[0]}"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except (ClientError, KeyError, AttributeError, TypeError):
        return Response({'msg': 'Could not inspect uploaded file content'}, status=500)

    file.size = head.get('ContentLength')
    file.content_type = verified_type
    file.uploaded = True
    file.uploaded_at = timezone.now()
    file.save(update_fields=("size", "content_type", "uploaded", "uploaded_at"))
    return Response({'msg': 'ok'}, status=200)


@swagger_auto_schema(
    method='post',
    operation_description="Generate a presigned URL for downloading a file from MinIO.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=['file_id'],
        properties={
            'file_id': openapi.Schema(
                type=openapi.TYPE_STRING,
                description='ID of the file to generate a presigned download URL for.'
            ),
        }
    ),
    responses={
        200: openapi.Response(
            description="Presigned download URL generated successfully.",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'download_url': openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description='Temporary presigned URL for downloading the file'
                    )
                }
            )
        ),
        400: "Bad Request",
        401: "Unauthorized",
        404: "File Not Found",
        500: "Internal Server Error",
    },
)    
@api_view(['POST'])
@permission_classes([IsAuthenticated, CanReadFiles])
def get_presigned_download(request):
    account = request.user
    file_id = request.data.get('file_id')
    if file_id:
        try:
            file = File.objects.get(pk=file_id, owner=account, uploaded=True)
        except File.DoesNotExist:
            return Response({'msg': 'file not found'}, status=404)
        object_name = file.object_name
        filename = file.original_name
    else:
        return Response({'msg': 'file_id required'}, status=400)
    
    s3 = get_s3_client()
    bucket = f"account-{account.account_id}-storage".lower()
    try:
        url = s3.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket,
                'Key': object_name,
                'ResponseContentDisposition': f'attachment; filename="{filename}"'
            },
            ExpiresIn=600
        )
        
        # parsed = urlparse(url)
        # url = urlunparse((
        #     urlparse(settings.MINIO_EXTERNAL_ENDPOINT).scheme,
        #     urlparse(settings.MINIO_EXTERNAL_ENDPOINT).netloc,
        #     parsed.path,
        #     parsed.params,
        #     parsed.query,
        #     parsed.fragment
        # ))
        
    except ClientError:
        return Response({'msg': 'could not generate download url'}, status=500)
    except ConnectionError:
        return Response({'msg': 'storage service unavailable'}, status=500)
    
    return Response({
        'download_url': url
    })

@swagger_auto_schema(
    method='get',
    operation_description="List uploaded files for the authenticated user's account.",
    responses={
        200: openapi.Response(
            description="List of uploaded files.",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'files': openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'file_id': openapi.Schema(type=openapi.TYPE_STRING),
                                'original_name': openapi.Schema(type=openapi.TYPE_STRING),
                                'content_type': openapi.Schema(type=openapi.TYPE_STRING),
                                'size': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'uploaded_at': openapi.Schema(type=openapi.TYPE_STRING, format='date-time'),
                            }
                        )
                    )
                }
            )
        ),
        401: "Unauthorized"
    }
)
@api_view(['GET'])
@permission_classes([IsAuthenticated, CanReadFiles])
def list_files(request):
    """
    Return all uploaded files (from DB) for the authenticated user's account.
    """
    account = request.user
    files = File.objects.filter(owner=account, uploaded=True).order_by('-uploaded_at')

    file_list = [
        {
            'file_id': str(f.file_id),
            'original_name': f.original_name,
            'content_type': f.content_type,
            'size': f.size,
            'uploaded_at': f.uploaded_at,
        }
        for f in files
    ]

    return Response({'files': file_list}, status=200)
@swagger_auto_schema(
    method='delete',
    operation_description="Delete a file belonging to the authenticated user from both the database and MinIO.",
    manual_parameters=[
        openapi.Parameter(
            'file_id',
            openapi.IN_PATH,
            description="The unique ID of the file to delete.",
            type=openapi.TYPE_STRING,
            required=True
        )
    ],
    responses={
        200: openapi.Response(
            description="File deleted successfully.",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'msg': openapi.Schema(type=openapi.TYPE_STRING, example='deleted')
                }
            )
        ),
        400: "Bad Request (missing or invalid file_id)",
        401: "Unauthorized",
        404: "File not found",
        500: "Internal Server Error"
    },
)
@api_view(['DELETE'])
@permission_classes([IsAuthenticated, CanDeleteFiles])
def delete_file(request, file_id):
    """
    Deletes a file (from DB and MinIO) for the authenticated user.
    """
    account = request.user

    if not file_id:
        return Response({'msg': 'file_id required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        file = File.objects.get(pk=file_id, owner=account)
    except File.DoesNotExist:
        return Response({'msg': 'file not found'}, status=status.HTTP_404_NOT_FOUND)

    s3 = get_s3_client()
    bucket = f"account-{account.account_id}-storage".lower()

    try:
        s3.delete_object(Bucket=bucket, Key=file.object_name)
    except ClientError:
        # Log but don’t crash — deletion from DB still counts
        pass

    file.delete()
    return Response({'msg': 'deleted'}, status=status.HTTP_200_OK)
