from unittest.mock import patch
import uuid

from botocore.exceptions import ClientError, EndpointConnectionError
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from devices.models import Account, Device
from storage.models import File, StoragePolicy, StorageSettings


class GeneratePresignedUploadAPITestCase(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(
            android_id="android-123",
            device_name="Test Device",
            imeis="imei-123",
        )
        self.account = Account.objects.create_user(
            username="testuser",
            password="strong-password",
            first_name="Test",
            last_name="User",
            phone_number="09120000000",
            device=self.device,
        )
        self.storage_settings = StorageSettings.objects.create(
            owner=self.account,
            policy=StoragePolicy.FULL_ACCESS,
            storage_limit_mb=10,
        )
        self.url = reverse("generate_presigned_upload")
        self.client.force_authenticate(user=self.account)

    @patch("storage.views.get_s3_client")
    @patch("storage.views.uuid.uuid4")
    def test_generate_presigned_upload_success_creates_file(self, mock_uuid, mock_get_s3_client):
        fixed_uuid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        mock_uuid.return_value = fixed_uuid
        mock_s3 = mock_get_s3_client.return_value
        mock_s3.generate_presigned_post.return_value = {
            "url": "https://minio.example.com",
            "fields": {"key": "some-key"},
        }

        payload = {
            "file_name": "uploads/report.pdf",
            "file_size": 1024,
            "content_type": "application/pdf",
        }
        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["upload_url"], mock_s3.generate_presigned_post.return_value)
        self.assertIn("file_id", response.data)

        file_record = File.objects.get(pk=response.data["file_id"])
        self.assertEqual(file_record.owner, self.account)
        self.assertEqual(file_record.original_name, payload["file_name"])
        self.assertEqual(file_record.content_type, payload["content_type"])
        self.assertEqual(file_record.size, payload["file_size"])
        self.assertFalse(file_record.uploaded)
        self.assertEqual(
            file_record.object_name,
            f"uploads/{fixed_uuid}_report.pdf",
        )

        mock_s3.generate_presigned_post.assert_called_once()
        _, kwargs = mock_s3.generate_presigned_post.call_args
        self.assertEqual(kwargs["Key"], f"uploads/{fixed_uuid}_report.pdf")
        self.assertEqual(
            kwargs["Bucket"],
            f"account-{self.account.account_id}-storage".lower(),
        )

    def test_generate_presigned_upload_missing_file_name(self):
        response = self.client.post(self.url, {"file_size": 100}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["msg"], "file_name required")

    def test_generate_presigned_upload_missing_file_size(self):
        response = self.client.post(self.url, {"file_name": "report.pdf"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["msg"], "file_size required")

    def test_generate_presigned_upload_duplicate_file_name(self):
        File.objects.create(
            owner=self.account,
            object_name="existing.pdf",
            original_name="report.pdf",
            content_type="application/pdf",
            size=100,
            uploaded=True,
        )

        response = self.client.post(
            self.url,
            {"file_name": "report.pdf", "file_size": 100},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["msg"], "file with this name already exists")

    def test_generate_presigned_upload_storage_limit_exceeded(self):
        self.storage_settings.storage_limit_mb = 1
        self.storage_settings.save(update_fields=["storage_limit_mb"])

        response = self.client.post(
            self.url,
            {"file_name": "big.bin", "file_size": 2 * 1024 * 1024},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["msg"], "Storage limit exceeded")
        

class CompleteUploadAPITestCase(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(
            android_id="android-456",
            device_name="Upload Device",
            imeis="imei-456",
        )
        self.account = Account.objects.create_user(
            username="uploader",
            password="strong-password",
            first_name="Upload",
            last_name="User",
            phone_number="09120000001",
            device=self.device,
        )
        self.storage_settings = StorageSettings.objects.create(
            owner=self.account,
            policy=StoragePolicy.FULL_ACCESS,
        )
        self.url = reverse("complete_upload")
        self.client.force_authenticate(user=self.account)

    @patch("storage.views.get_s3_client")
    def test_complete_upload_marks_file_uploaded(self, mock_get_s3_client):
        file_record = File.objects.create(
            owner=self.account,
            object_name="uploads/ready.pdf",
            original_name="ready.pdf",
            content_type="application/pdf",
            size=0,
            uploaded=False,
        )
        mock_s3 = mock_get_s3_client.return_value
        mock_s3.head_object.return_value = {"ContentLength": 2048}

        response = self.client.post(self.url, {"file_id": str(file_record.file_id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        file_record.refresh_from_db()
        self.assertTrue(file_record.uploaded)
        self.assertEqual(file_record.size, 2048)
        self.assertIsNotNone(file_record.uploaded_at)

    def test_complete_upload_missing_file_id(self):
        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["msg"], "file_id required")

    def test_complete_upload_invalid_file_id(self):
        response = self.client.post(self.url, {"file_id": "not-a-uuid"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["msg"], "invalid file_id")

    def test_complete_upload_file_not_found(self):
        response = self.client.post(self.url, {"file_id": str(uuid.uuid4())}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["msg"], "file not found")

    @patch("storage.views.get_s3_client")
    def test_complete_upload_storage_missing_object(self, mock_get_s3_client):
        file_record = File.objects.create(
            owner=self.account,
            object_name="uploads/missing.pdf",
            original_name="missing.pdf",
            content_type="application/pdf",
            size=0,
            uploaded=False,
        )
        mock_s3 = mock_get_s3_client.return_value
        mock_s3.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "HeadObject",
        )

        response = self.client.post(self.url, {"file_id": str(file_record.file_id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["msg"], "object not found in storage")


class PresignedDownloadAPITestCase(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(
            android_id="android-789",
            device_name="Download Device",
            imeis="imei-789",
        )
        self.account = Account.objects.create_user(
            username="downloader",
            password="strong-password",
            first_name="Download",
            last_name="User",
            phone_number="09120000002",
            device=self.device,
        )
        self.storage_settings = StorageSettings.objects.create(
            owner=self.account,
            policy=StoragePolicy.READ_WRITE,
        )
        self.url = reverse("get_presigned_download")
        self.client.force_authenticate(user=self.account)

    @patch("storage.views.get_s3_client")
    def test_presigned_download_success(self, mock_get_s3_client):
        file_record = File.objects.create(
            owner=self.account,
            object_name="uploads/export.csv",
            original_name="export.csv",
            content_type="text/csv",
            size=10,
            uploaded=True,
            uploaded_at=timezone.now(),
        )
        mock_s3 = mock_get_s3_client.return_value
        mock_s3.generate_presigned_url.return_value = "https://minio.example.com/download"

        response = self.client.post(self.url, {"file_id": str(file_record.file_id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["download_url"], "https://minio.example.com/download")

    def test_presigned_download_missing_file_id(self):
        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["msg"], "file_id required")

    def test_presigned_download_file_not_found(self):
        response = self.client.post(self.url, {"file_id": str(uuid.uuid4())}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["msg"], "file not found")

    @patch("storage.views.get_s3_client")
    def test_presigned_download_client_error(self, mock_get_s3_client):
        file_record = File.objects.create(
            owner=self.account,
            object_name="uploads/broken.txt",
            original_name="broken.txt",
            content_type="text/plain",
            size=5,
            uploaded=True,
            uploaded_at=timezone.now(),
        )
        mock_s3 = mock_get_s3_client.return_value
        mock_s3.generate_presigned_url.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "Boom"}},
            "GeneratePresignedUrl",
        )

        response = self.client.post(self.url, {"file_id": str(file_record.file_id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["msg"], "could not generate download url")

    @patch("storage.views.get_s3_client")
    def test_presigned_download_connection_error(self, mock_get_s3_client):
        file_record = File.objects.create(
            owner=self.account,
            object_name="uploads/offline.txt",
            original_name="offline.txt",
            content_type="text/plain",
            size=5,
            uploaded=True,
            uploaded_at=timezone.now(),
        )
        mock_s3 = mock_get_s3_client.return_value
        mock_s3.generate_presigned_url.side_effect = EndpointConnectionError(endpoint_url="http://minio")

        response = self.client.post(self.url, {"file_id": str(file_record.file_id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["msg"], "storage service unavailable")


class ListFilesAPITestCase(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(
            android_id="android-999",
            device_name="List Device",
            imeis="imei-999",
        )
        self.account = Account.objects.create_user(
            username="lister",
            password="strong-password",
            first_name="List",
            last_name="User",
            phone_number="09120000003",
            device=self.device,
        )
        self.storage_settings = StorageSettings.objects.create(
            owner=self.account,
            policy=StoragePolicy.READ_ONLY,
        )
        self.url = reverse("list_files")
        self.client.force_authenticate(user=self.account)

    def test_list_files_returns_uploaded_only_sorted(self):
        earlier = timezone.now() - timezone.timedelta(hours=1)
        later = timezone.now()
        File.objects.create(
            owner=self.account,
            object_name="uploads/old.txt",
            original_name="old.txt",
            content_type="text/plain",
            size=1,
            uploaded=True,
            uploaded_at=earlier,
        )
        File.objects.create(
            owner=self.account,
            object_name="uploads/new.txt",
            original_name="new.txt",
            content_type="text/plain",
            size=2,
            uploaded=True,
            uploaded_at=later,
        )
        File.objects.create(
            owner=self.account,
            object_name="uploads/pending.txt",
            original_name="pending.txt",
            content_type="text/plain",
            size=3,
            uploaded=False,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        files = response.data["files"]
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["original_name"], "new.txt")
        self.assertEqual(files[1]["original_name"], "old.txt")


class DeleteFileAPITestCase(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(
            android_id="android-222",
            device_name="Delete Device",
            imeis="imei-222",
        )
        self.account = Account.objects.create_user(
            username="deleter",
            password="strong-password",
            first_name="Delete",
            last_name="User",
            phone_number="09120000004",
            device=self.device,
        )
        self.storage_settings = StorageSettings.objects.create(
            owner=self.account,
            policy=StoragePolicy.FULL_ACCESS,
        )
        self.url = "delete_file"
        self.client.force_authenticate(user=self.account)

    @patch("storage.views.get_s3_client")
    def test_delete_file_success(self, mock_get_s3_client):
        file_record = File.objects.create(
            owner=self.account,
            object_name="uploads/remove.txt",
            original_name="remove.txt",
            content_type="text/plain",
            size=1,
            uploaded=True,
            uploaded_at=timezone.now(),
        )

        response = self.client.delete(reverse(self.url, args=[file_record.file_id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["msg"], "deleted")
        self.assertFalse(File.objects.filter(pk=file_record.file_id).exists())
        mock_get_s3_client.return_value.delete_object.assert_called_once()

    def test_delete_file_not_found(self):
        response = self.client.delete(reverse(self.url, args=[uuid.uuid4()]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["msg"], "file not found")

    def test_delete_file_forbidden_for_read_write_policy(self):
        self.storage_settings.policy = StoragePolicy.READ_WRITE
        self.storage_settings.save(update_fields=["policy"])
        file_record = File.objects.create(
            owner=self.account,
            object_name="uploads/forbidden.txt",
            original_name="forbidden.txt",
            content_type="text/plain",
            size=1,
            uploaded=True,
            uploaded_at=timezone.now(),
        )

        response = self.client.delete(reverse(self.url, args=[file_record.file_id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)