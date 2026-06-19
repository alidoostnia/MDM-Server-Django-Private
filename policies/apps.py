from django.apps import AppConfig


class PoliciesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "policies"
    
    def ready(self):
        # import signal handlers
        import policies.signals  # noqa