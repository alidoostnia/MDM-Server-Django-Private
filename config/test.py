from .base import *
from django.conf import settings

DEBUG = True

# Fast tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Disable real side effects
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Safety: fake external services
MINIO_ENDPOINT = "http://fake-minio"
MQTT_HOST = "fake-mqtt"


assert "test" in settings.DATABASES["default"]["NAME"]