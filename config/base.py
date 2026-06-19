from datetime import timedelta
from pathlib import Path
import environ
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"),
]

# Read .env file
env = environ.Env()
# environ.Env.read_env(os.path.join(BASE_DIR, ".env"))
ENV_FILE = os.environ.get("DJANGO_ENV_FILE", ".env")

env_path = os.path.join(BASE_DIR, ENV_FILE)
if os.path.exists(env_path):
    environ.Env.read_env(env_path)

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('DJANGO_SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DJANGO_DEBUG', default=True)

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",")

CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": "/var/log/django/app.log",
            "formatter": "verbose",
            "level": "INFO",
        },
        "errors": {
            "class": "logging.FileHandler",
            "filename": "/var/log/django/errors.log",
            "formatter": "verbose",
            "level": "ERROR",
        },
    },
    'loggers': {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": True,
        },
        "django.request": {
            "handlers": ["console", "errors"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console", "errors"],
            "level": "ERROR",
            "propagate": False,
        },
        "policies.management": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "devices.management": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
    
    'root': {
        'handlers': ['console', 'file', 'errors'],
        'level': 'INFO',
    },
}


# Application definition

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    'rest_framework_simplejwt.token_blacklist',
    'drf_yasg',
    "captcha",
    
    # Local apps
    "devices",
    "policies",
    "logs",
    "storage",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "config.middleware.AdminLoginCaptchaMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ["templates/"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.admin_theme_colors",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env("POSTGRES_DB"),
        'USER': env("POSTGRES_USER"),
        'PASSWORD': env("POSTGRES_PASSWORD"),
        'HOST': env("POSTGRES_HOST"),
        'PORT': env("POSTGRES_PORT"),
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Asia/Tehran"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
}

SIMPLE_JWT = {
    "USER_ID_FIELD": "account_id",
    "USER_ID_CLAIM": "account_id",
    "ACCESS_TOKEN_LIFETIME": timedelta(days=1) if DEBUG else timedelta(minutes=5),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1), 
    "BLACKLIST_AFTER_ROTATION": True,
    "ROTATE_REFRESH_TOKENS": True,
}

AUTH_USER_MODEL = "devices.Account"

# Local CAPTCHA used only by the Django admin login.
CAPTCHA_LENGTH = 5
CAPTCHA_TIMEOUT = 5
CAPTCHA_NOISE_FUNCTIONS = (
    "captcha.helpers.noise_arcs",
    "captcha.helpers.noise_dots",
)

ADMIN_THEME_COLORS = {
    "primary": env("ADMIN_THEME_PRIMARY", default="#2F9A57"),
    "primary_hover": env("ADMIN_THEME_PRIMARY_HOVER", default="#28884C"),
    "primary_soft": env("ADMIN_THEME_PRIMARY_SOFT", default="#CFE8D7"),
    "secondary": env("ADMIN_THEME_SECONDARY", default="#63B67A"),
    "tertiary": env("ADMIN_THEME_TERTIARY", default="#88C89A"),
    "accent": env("ADMIN_THEME_ACCENT", default="#3CA57F"),

    # Softer background (not white)
    "background": env("ADMIN_THEME_BACKGROUND", default="#E7F1EB"),
    "surface": env("ADMIN_THEME_SURFACE", default="#F1F8F3"),
    "surface_elevated": env("ADMIN_THEME_SURFACE_ELEVATED", default="#E2EFE7"),
    "surface_variant": env("ADMIN_THEME_SURFACE_VARIANT", default="#DCEBE2"),
    "primary_container": env("ADMIN_THEME_PRIMARY_CONTAINER", default="#D3E7DA"),

    # Softer borders
    "border": env("ADMIN_THEME_BORDER", default="#BDD6C7"),
    "outline": env("ADMIN_THEME_OUTLINE", default="#A8C5B4"),

    # Status colors (slightly muted)
    "success": env("ADMIN_THEME_SUCCESS", default="#2E7D32"),
    "warning": env("ADMIN_THEME_WARNING", default="#D98C00"),
    "danger": env("ADMIN_THEME_DANGER", default="#C74A4A"),
    "info": env("ADMIN_THEME_INFO", default="#1E88E5"),

    # Dark text but not black
    "on_primary": env("ADMIN_THEME_ON_PRIMARY", default="#FFFFFF"),
    "on_secondary": env("ADMIN_THEME_ON_SECONDARY", default="#0F2B1C"),
    "on_tertiary": env("ADMIN_THEME_ON_TERITIARY", default="#0F2B1C"),

    "on_background": env("ADMIN_THEME_ON_BACKGROUND", default="#183126"),
    "on_surface": env("ADMIN_THEME_ON_SURFACE", default="#1D3A2C"),
    "on_muted": env("ADMIN_THEME_ON_MUTED", default="#5F7D6E"),
}


JAZZMIN_SETTINGS = {
    "site_title": "Beheshti MDM Admin Dashboard",
    "site_header": "Beheshti MDM Admin Panel",
    "site_brand": "Beheshti MDM",
    "welcome_sign": "Beheshti MDM Admin Panel",
    "site_logo": "admin/img/mdm_icon.jpg",        # sidebar/header logo
    "login_logo": "admin/img/mdm_icon.jpg",       # login page logo
    "site_icon": "admin/img/mdm_icon.jpg",        # browser tab favicon
    "site_logo_classes": "img-circle elevation-2",  # optional styling
    "icons": {
        "auth": "fas fa-user-lock",
        "auth.user": "fas fa-user",
        "auth.group": "fas fa-users",
        "devices": "fas fa-user-shield",
        "devices.department": "fas fa-building",
        "devices.account": "fas fa-users-cog",
        "devices.device": "fas fa-mobile-alt",
        "policies": "fas fa-shield-alt",
        "policies.module": "fas fa-puzzle-piece",
        "policies.actiontype": "fas fa-tags",
        "policies.policy": "fas fa-scroll",
        "policies.action": "fas fa-bolt",
        "policies.policydevice": "fas fa-link",
        "policies.command": "fas fa-terminal",
        "policies.devicepolicysnapshot": "fas fa-camera",
        "storage": "fas fa-database",
        "storage.file": "fas fa-file-upload",
        "storage.storagesettings": "fas fa-sliders-h",
        "logs": "fas fa-file-alt",
        "logs.fakedevicelogsmodel": "fas fa-clipboard-list",
        "policies.pushnotificationlauncher": "fas fa-bell",
    },
    "hide_models": ["auth.group"],
    "hide_apps": ["token_blacklist"],
    "order_with_respect_to": [
        "auth",
        "auth.user",
        "devices",
        "policies",
        "policies.policy",
        "policies.action",
        "policies.command",
        "policies.module",
        "policies.actiontype",
        "policies.policydevice",
        "policies.devicepolicysnapshot",
        "storage",
        "storage.file",
        "storage.storagesettings",
        "logs",
        "logs.fakedevicelogsmodel",
    ],
    "custom_css": "admin/css/theme.css",
}

JAZZMIN_UI_TWEAKS = {
    "theme": "default",
    "light_mode_theme": "default",
}


# swagger settings
SWAGGER_SETTINGS = {
    'SECURITY_DEFINITIONS': {
        'Bearer': {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'JWT authorization using Bearer token. Example: "Bearer {your_token}"',
        }
    },
}

# MongoDB settings
MONGO_URI = env('MONGO_URI', default='mongodb://localhost:27017/mdm_logs')
LOGS_COLLECTION = env('LOGS_COLLECTION', default='device_logs')
# STATUS_COLLECTION = env('STATUS_COLLECTION', default='device_status')
LOGS_PER_PAGE = 50

# MQTT settings
MQTT_HOST = env('MQTT_HOST', default='localhost')
MQTT_PORT = env.int('MQTT_PORT', default=1883)
MQTT_USERNAME = env('MQTT_USERNAME', default=None)
MQTT_PASSWORD = env('MQTT_PASSWORD', default=None)

# Celery settings
CELERY_BROKER_URL = env('CELERY_BROKER_URL')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND')

# Helpful options for reliability
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_REJECT_ON_WORKER_LOST = True

# Minio settings
MINIO_ENDPOINT = env('MINIO_ENDPOINT', default="http://minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD")
MINIO_REGION = os.getenv("MINIO_REGION", "us-east-1")
MINIO_USE_SSL = MINIO_ENDPOINT.startswith("https")
