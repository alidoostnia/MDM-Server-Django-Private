from django.conf import settings


def admin_theme_colors(request):
    return {
        "ADMIN_THEME_COLORS": settings.ADMIN_THEME_COLORS,
    }