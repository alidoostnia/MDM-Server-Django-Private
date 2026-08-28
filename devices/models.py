from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
import uuid
from datetime import timedelta
from django.utils import timezone
from .validators import national_id_validator
#------------------Department----------------
class Department(models.Model):
    department_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "Department"

    def __str__(self):
        return self.name

# ------------------ Device ------------------
class Device(models.Model):
    device_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    android_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    device_name = models.CharField(max_length=100, unique=True)
    imeis = models.CharField(max_length=100, unique=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        related_name="devices",
        null=True,
        blank=True,
    )
    
    STATUS_UNKNOWN = "UNKNOWN"
    STATUS_ONLINE = "ONLINE"
    STATUS_OFFLINE = "OFFLINE"
    STATUS_CHOICES = [
        (STATUS_UNKNOWN, "Unknown"),
        (STATUS_ONLINE, "Online"),
        (STATUS_OFFLINE, "Offline"),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_UNKNOWN)
    last_seen = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        db_table = "Device"
    
    def __str__(self):
        return str(self.device_name)
    
    def mark_seen(self, when=None):
        self.last_seen = when or timezone.now()
        self.status = self.STATUS_ONLINE
        self.save(update_fields=["last_seen", "status"])



# ------------------ Account ------------------
class AccountManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("Username required")
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(username, password, **extra_fields)

class Account(AbstractBaseUser, PermissionsMixin):
    account_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=100, unique=True)
    password = models.CharField(max_length=128)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=11, unique=True)
    national_id = models.CharField(max_length=10, unique=True, null=True, blank=True, validators=[national_id_validator])
    email = models.EmailField(unique=True, null=True, blank=True)
    device = models.OneToOneField(Device, on_delete=models.CASCADE, related_name="account",  null=True, blank=True)
    bucket_created = models.BooleanField(default=False)
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(default=timezone.now)
    must_change_password = models.BooleanField(
        default=False,
        help_text="Require this user to choose a new password at the next admin login.",
    )
    password_expiration_days = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Optional per-user override. Leave blank to use the Settings policy.",
    )
    session_timeout_minutes = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Optional per-user override. Leave blank to use the Settings policy.",
    )
    active_session_key = models.CharField(max_length=40, blank=True, default="", editable=False)
    
    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []
    
    objects = AccountManager()
    
    class Meta:
        db_table = "Account"
        
    def set_password(self, raw_password):
        super().set_password(raw_password)

    def password_is_expired(self, policy=None):
        if self.must_change_password:
            return True
        if policy is None:
            from security_controls.models import SecurityPolicy
            policy = SecurityPolicy.load()
        days = self.password_expiration_days
        if days is None:
            days = policy.password_expiration_days
        return timezone.now() >= self.password_changed_at + timedelta(days=days)
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
    
    def __str__(self):
        return str(self.username)

