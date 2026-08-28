from django.contrib import admin, messages
from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.urls import path
from django.utils import timezone

from devices.forms import ForcedPasswordChangeForm
from devices.models import Account

from .models import ActiveSession, SecurityPolicy, UserActivity
from .services import set_user_password


class SuperuserOnlyAdminMixin:
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser


@admin.register(SecurityPolicy)
class SecurityPolicyAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    fieldsets = (
        ("Password expiration", {"fields": ("password_expiration_days", "password_history_count")}),
        ("Login protection", {"fields": ("max_failed_login_attempts", "lockout_minutes")}),
        ("Sessions", {"fields": ("session_timeout_minutes",)}),
        ("Updated", {"fields": ("updated_at",)}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not SecurityPolicy.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ActiveSession)
class ActiveSessionAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("session_key", "username", "login_time", "ip_address", "user_agent", "expire_date")
    ordering = ("-expire_date",)
    actions = ("terminate_sessions",)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(expire_date__gt=timezone.now())

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def _decoded(self, obj):
        if not hasattr(obj, "_decoded_session"):
            obj._decoded_session = obj.get_decoded()
        return obj._decoded_session

    @admin.display(description="User")
    def username(self, obj):
        user_id = self._decoded(obj).get("_auth_user_id")
        return Account.objects.filter(pk=user_id).values_list("username", flat=True).first() or "Unknown"

    @admin.display(description="Logged in at")
    def login_time(self, obj):
        return self._decoded(obj).get("_login_at", "-")

    @admin.display(description="IP address")
    def ip_address(self, obj):
        return self._decoded(obj).get("_login_ip", "-")

    @admin.display(description="User agent")
    def user_agent(self, obj):
        return self._decoded(obj).get("_login_user_agent", "-")

    def _terminate(self, request, sessions):
        count = 0
        terminated_current = False
        actor = request.user
        for session in sessions:
            decoded = session.get_decoded()
            user_id = decoded.get("_auth_user_id")
            target = Account.objects.filter(pk=user_id).first() if user_id else None
            if user_id:
                Account.objects.filter(
                    pk=user_id, active_session_key=session.session_key
                ).update(active_session_key="")
            UserActivity.record(
                request,
                actor=actor,
                target_user=target,
                event=UserActivity.Event.SESSION_TERMINATED,
                details={"session_key": session.session_key},
            )
            terminated_current = (
                terminated_current or session.session_key == request.session.session_key
            )
            session.delete()
            count += 1
        if terminated_current:
            logout(request)
        return count, terminated_current

    @admin.action(description="Terminate selected sessions and sign out users")
    def terminate_sessions(self, request, queryset):
        count, terminated_current = self._terminate(request, list(queryset))
        self.message_user(request, f"Terminated {count} active session(s).", messages.SUCCESS)
        if terminated_current:
            return redirect("admin:login")

    def delete_model(self, request, obj):
        self._terminate(request, [obj])

    def delete_queryset(self, request, queryset):
        self._terminate(request, list(queryset))


@admin.register(UserActivity)
class UserActivityAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "created_at", "event", "success", "actor", "target_user",
        "attempted_username", "ip_address", "path",
    )
    list_filter = ("event", "success", "created_at")
    search_fields = (
        "actor__username", "target_user__username", "attempted_username",
        "ip_address", "path",
    )
    readonly_fields = (
        "created_at", "event", "success", "actor", "target_user",
        "attempted_username", "ip_address", "user_agent", "path", "details",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def force_password_change_view(request):
    if request.method == "POST":
        form = ForcedPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            set_user_password(request.user, form.cleaned_data["new_password"])
            UserActivity.record(
                request,
                actor=request.user,
                target_user=request.user,
                event=UserActivity.Event.PASSWORD_CHANGE,
            )
            messages.success(request, "Your password was changed successfully.")
            return redirect("admin:index")
    else:
        form = ForcedPasswordChangeForm(request.user)
    context = {
        **admin.site.each_context(request),
        "title": "Change expired password",
        "form": form,
    }
    return render(request, "admin/force_password_change.html", context)


_original_admin_get_urls = admin.site.get_urls


def _security_admin_urls():
    return [
        path(
            "force-password-change/",
            admin.site.admin_view(force_password_change_view),
            name="force_password_change",
        )
    ] + _original_admin_get_urls()


admin.site.get_urls = _security_admin_urls
