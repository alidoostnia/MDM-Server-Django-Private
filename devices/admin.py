from django.contrib import admin
from .models import Department, Device, Account
from django.utils.html import format_html
from .forms import AccountChangeForm, AccountCreationForm, AdminCaptchaAuthenticationForm
from django.contrib.auth.admin import UserAdmin
from django.urls import path, reverse
from django.contrib import messages
from django.conf import settings
from urllib.parse import urlparse, urlunparse
from botocore.exceptions import ClientError, EndpointConnectionError, ConnectionError
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from storage.utils import get_s3_client

from storage.models import File
from storage.admin import StorageSettingsInline

from .tasks import create_minio_bucket, delete_minio_bucket
from policies.models import Command
from policies.tasks import send_command_to_device
from policies.deletion_context import allow_policydevice_delete

# admin.site.site_header = "MDM Admin Panel"
# admin.site.site_title = "Admin Dashboard"
# admin.site.index_title = "Admin Dashboard"
admin.site.index_template = "admin/custom_index.html"
admin.site.login_form = AdminCaptchaAuthenticationForm


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "device_count")
    search_fields = ("name",)
    actions = ("send_read_all_to_department_devices",)

    def device_count(self, obj):
        return obj.devices.count()
    device_count.short_description = "Devices"

    @admin.action(description="Send READ_ALL command to all devices in selected departments")
    def send_read_all_to_department_devices(self, request, queryset):
        queued = 0
        for department in queryset:
            for device in department.devices.all():
                with transaction.atomic():
                    cmd = Command.objects.create(
                        device=device,
                        command_type=Command.COMMAND_READ_ALL,
                        status=Command.STATUS_PENDING,
                    )
                send_command_to_device.delay(str(cmd.pk))
                queued += 1
        self.message_user(request, f"Queued {queued} READ_ALL commands for selected departments.", level=messages.SUCCESS)

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("device_name", "department", "android_id", "imeis", "status", "last_seen", "delete_all_policies_button")
    search_fields = ("device_name", "android_id", "imeis", "department__name")
    readonly_fields = ("device_id", "last_seen", "status")
    list_filter = ("department", "status", "last_seen")

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<uuid:device_id>/delete_all_policies/",
                self.admin_site.admin_view(self.delete_all_policies_view),
                name="devices_device_delete_all_policies",
            ),
        ]
        return custom_urls + urls

    @admin.display(description="Policies")
    def delete_all_policies_button(self, obj):
        if not obj or not obj.pk:
            return "-"
        url = reverse("admin:devices_device_delete_all_policies", args=[str(obj.pk)])
        return format_html('<a class="button admin-action-button" href="{}">Delete All Policies</a>', url)

    def delete_all_policies_view(self, request, device_id):
        device = get_object_or_404(Device, pk=device_id)

        with transaction.atomic():
            cmd = Command.objects.create(
                device=device,
                command_type=Command.COMMAND_DELETE_ALL,
                status=Command.STATUS_PENDING,
            )

        send_command_to_device.delay(str(cmd.pk))
        self.message_user(request, f"DELETE_ALL queued for device {device}.", level=messages.SUCCESS)
        return redirect("admin:devices_device_changelist")
    
    def delete_model(self, request, obj):
        with transaction.atomic():
            with allow_policydevice_delete():
                obj.delete()


    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            with allow_policydevice_delete():
                queryset.delete()
    
@admin.register(Account)
class AccountAdmin(UserAdmin):
    model = Account
    list_display = ("username", "first_name", "last_name", "phone_number", "national_id", "is_staff", "is_active", "device_link", "bucket_created", "storage_link", "storage_settings_link")
    list_filter = ("is_staff", "is_active", "bucket_created")
    search_fields = ("username", "phone_number", "national_id")
    ordering = ("username",)
    inlines = [StorageSettingsInline]
    actions = ["admin_create_bucket", "admin_delete_bucket"]

    
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email", "phone_number", "national_id", "device")}),
        ("Permissions", {"fields": ("is_staff", "is_active", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login",)}),
        ("Storage Info", {"fields": ("bucket_created",)}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "first_name", "last_name", "email", "phone_number", "national_id",  "device", "password1", "password2", "is_staff", "is_active"),
        }),
    )
    
    @admin.display(description="Storage Settings")
    def storage_settings_link(self, obj):
        if hasattr(obj, "storage_settings"):
            url = reverse("admin:storage_storagesettings_change", args=[obj.storage_settings.id])
            return format_html('<a href="{}">Edit</a>', url)
        return "-"
    

    @admin.display(description="Device")
    def device_link(self, obj):
        if obj.device:
            url = f"/admin/{obj.device._meta.app_label}/{obj.device._meta.model_name}/{obj.device.pk}/change/"
            return format_html('<a href="{}">{}</a>', url, obj.device.device_name)
        return "-"
    
    @admin.display(description="Storage")
    def storage_link(self, obj):
        url = reverse("admin:devices_account-storage", args=[obj.pk])
        return format_html('<a href="{}">View Storage</a>', url)
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("<path:object_id>/storage/", self.admin_site.admin_view(self.view_storage),
                name="devices_account-storage"),
            path("<path:object_id>/storage/generate-download/", self.admin_site.admin_view(self.generate_download),
                name="devices_account-storage-download"),
            path("<path:object_id>/storage/delete-object/",
                self.admin_site.admin_view(self.delete_object),
                name="devices_account-storage-delete"),
        ]
        return custom_urls + urls
    
    def view_storage(self, request, object_id):
        request.current_app = self.admin_site.name
        
        account = self.get_object(request, object_id)
        if not account:
            self.message_user(request, "Account not found.", level=messages.ERROR)
            return redirect("admin:devices_account_changelist")

        prefix = request.GET.get("prefix", "")
        bucket = f"account-{account.account_id}-storage".lower()
        s3 = get_s3_client()
        
        parts = []
        if prefix:
            tokens = prefix.split("/")
            current = ""
            for t in tokens:
                if t:
                    current += t + "/"
                    parts.append({"name": t, "path": current})
        
        folders = []
        files_in_bucket = []
        error = None

        try:
            resp = s3.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                Delimiter="/"     # <-- this groups folders
            )

            folders = resp.get("CommonPrefixes", [])
            files_in_bucket = resp.get("Contents", [])
        except (EndpointConnectionError, ConnectionError):
            error = "MinIO is offline or unreachable."
        except ClientError as exc:
            error = f"Storage error: {exc}"

        files = File.objects.filter(owner=account).order_by("-created_at")
        
        context = dict(
            self.admin_site.each_context(request),
            account=account,
            bucket=bucket,
            prefix=prefix,
            folders=folders,
            objects=files_in_bucket,
            files=files,
            parts=parts,
            opts=self.model._meta,
            error=error,
            title=f"Storage for {account.username}",
        )
        return render(request, "admin/storage/minio_storage_list.html", context)
    
    def generate_download(self, request, object_id):
        account = self.get_object(request, object_id)
        if not account:
            self.message_user(request, "Account not found.", level=messages.ERROR)
            return redirect("admin:devices_account_changelist")

        object_key = request.POST.get("object_key")
        if not object_key:
            self.message_user(request, "object_key is required.", level=messages.ERROR)
            return redirect(reverse("admin:devices_account-storage", args=[object_id]))

        bucket = f"account-{account.account_id}-storage".lower()
        s3 = get_s3_client()

        try:
            url = s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket, 
                    "Key": object_key,
                    'ResponseContentDisposition': f'attachment; filename="{object_key.split("/")[-1]}"'
                },
                ExpiresIn=300,
            )
            
            
        except (EndpointConnectionError, ConnectionError):
            self.message_user(request, "MinIO is offline or unreachable.", level=messages.ERROR)
            return redirect(reverse("admin:devices_account-storage", args=[object_id]))
        except ClientError as exc:
            self.message_user(request, f"Could not generate URL: {exc}", level=messages.ERROR)
            return redirect(reverse("admin:devices_account-storage", args=[object_id]))

        return redirect(url)
    
    @admin.action(description="Create MinIO bucket")
    def admin_create_bucket(self, request, queryset):
        for account in queryset:
            create_minio_bucket.delay(account.account_id)
        self.message_user(request, "Bucket creation task queued.")
    
    @admin.action(description="Delete MinIO bucket")
    def admin_delete_bucket(self, request, queryset):
        for account in queryset:
            delete_minio_bucket.delay(account.account_id)
        self.message_user(request, "Bucket deletion task queued.")
    
    
    def delete_object(self, request, object_id):
        account = self.get_object(request, object_id)
        object_key = request.POST.get("object_key")

        if not object_key:
            self.message_user(request, "object_key missing.", messages.ERROR)
            return redirect(reverse("admin:devices_account-storage", args=[object_id]))

        bucket = f"account-{account.account_id}-storage".lower()
        s3 = get_s3_client()

        # Delete from MinIO
        try:
            s3.delete_object(Bucket=bucket, Key=object_key)
        except Exception as exc:
            self.message_user(request, f"MinIO delete failed: {exc}", messages.ERROR)
            return redirect(reverse("admin:devices_account-storage", args=[object_id]))

        # Delete DB entry if exists
        File.objects.filter(object_name=object_key, owner=account).delete()

        self.message_user(request, "File deleted successfully.", messages.SUCCESS)
        return redirect(reverse("admin:devices_account-storage", args=[object_id]))
