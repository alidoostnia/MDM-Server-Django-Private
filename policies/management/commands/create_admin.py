from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
import os
import logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Create superuser from env variables"

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.environ.get("DJANGO_ADMIN_USER")
        email = os.environ.get("DJANGO_ADMIN_EMAIL", "")
        password = os.environ.get("DJANGO_ADMIN_PASSWORD")
        
        if not username or not password:
            logger.error("DJANGO_ADMIN_USER or DJANGO_ADMIN_PASSWORD not set")
            return

        user, created = User.objects.get_or_create(username=username, defaults={"email": email})
        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.save()
        
        if created:
            logger.info(f"Superuser '{username}' created successfully")
        else:
            logger.info(f"Superuser '{username}' updated successfully")