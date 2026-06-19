from rest_framework.permissions import BasePermission
from .models import StoragePolicy

def is_admin(user):
    return user.is_superuser or user.is_staff

class CanUploadFiles(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if is_admin(user):
            return True
        
        storage_settings = getattr(user, "storage_settings", None)
        policy = getattr(storage_settings, "policy", None)
        return user.is_authenticated and policy in [
            StoragePolicy.READ_WRITE,
            StoragePolicy.FULL_ACCESS
        ]

class CanDeleteFiles(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if is_admin(user):
            return True
        
        storage_settings = getattr(user, "storage_settings", None)
        policy = getattr(storage_settings, "policy", None)
        return user.is_authenticated and policy == StoragePolicy.FULL_ACCESS

class CanReadFiles(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated
