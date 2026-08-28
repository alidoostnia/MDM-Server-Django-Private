from django.contrib import messages
from django.contrib.auth import logout
from django.db import transaction
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone


class AdminSecurityMiddleware:
    """Enforce admin password/session policy and record administrative activity."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from devices.models import Account
        from security_controls.models import SecurityPolicy, UserActivity

        starting_user = request.user if request.user.is_authenticated else None
        policy = None
        current_session_key = request.session.session_key

        if starting_user:
            policy = SecurityPolicy.load()
            if not current_session_key:
                request.session.save()
                current_session_key = request.session.session_key

            # A session key that does not own the account's single-session slot
            # is immediately signed out.
            if (
                starting_user.active_session_key
                and starting_user.active_session_key != current_session_key
            ):
                logout(request)
                messages.error(request, "Your session is no longer active. Please sign in again.")
                return HttpResponseRedirect(reverse("admin:login"))

            if not starting_user.active_session_key:
                Account.objects.filter(pk=starting_user.pk).update(
                    active_session_key=current_session_key
                )
                starting_user.active_session_key = current_session_key

            timeout = starting_user.session_timeout_minutes or policy.session_timeout_minutes
            request.session.set_expiry(timeout * 60)
            request.session.setdefault("_login_at", timezone.now().isoformat())
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
            request.session.setdefault(
                "_login_ip",
                forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", ""),
            )
            request.session.setdefault(
                "_login_user_agent", request.META.get("HTTP_USER_AGENT", "")[:512]
            )

            allowed_paths = {
                reverse("admin:force_password_change"),
                reverse("admin:logout"),
            }
            if (
                request.path.startswith(reverse("admin:index"))
                and request.path not in allowed_paths
                and starting_user.password_is_expired(policy)
            ):
                messages.warning(request, "You must change your expired password before using the admin panel.")
                return HttpResponseRedirect(reverse("admin:force_password_change"))

        response = self.get_response(request)
        ending_user = request.user if request.user.is_authenticated else None

        # A successful login claims the one allowed session atomically. A rare
        # concurrent second login is rejected even if both passed the form check.
        if not starting_user and ending_user and request.session.session_key:
            session_key = request.session.session_key
            blocked = False
            with transaction.atomic():
                locked_user = Account.objects.select_for_update().get(pk=ending_user.pk)
                if locked_user.active_session_key and locked_user.active_session_key != session_key:
                    blocked = True
                else:
                    locked_user.active_session_key = session_key
                    locked_user.save(update_fields=("active_session_key",))
            if blocked:
                UserActivity.record(
                    request,
                    target_user=ending_user,
                    attempted_username=ending_user.username,
                    event=UserActivity.Event.LOGIN_BLOCKED,
                    success=False,
                    details={"reason": "concurrent_session"},
                )
                logout(request)
                messages.error(request, "A parallel login was blocked because this user already has an active session.")
                return HttpResponseRedirect(reverse("admin:login"))

            timeout = ending_user.session_timeout_minutes or SecurityPolicy.load().session_timeout_minutes
            request.session.set_expiry(timeout * 60)
            request.session["_login_at"] = timezone.now().isoformat()
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
            request.session["_login_ip"] = (
                forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
            )
            request.session["_login_user_agent"] = request.META.get("HTTP_USER_AGENT", "")[:512]

        if starting_user and not ending_user:
            Account.objects.filter(
                pk=starting_user.pk,
                active_session_key=current_session_key,
            ).update(active_session_key="")
            UserActivity.record(
                request,
                actor=starting_user,
                target_user=starting_user,
                event=UserActivity.Event.LOGOUT,
            )

        actor = ending_user or starting_user
        excluded = {
            reverse("admin:login"),
            reverse("admin:logout"),
            reverse("admin:force_password_change"),
        }
        if actor and request.path.startswith(reverse("admin:index")) and request.path not in excluded:
            UserActivity.record(
                request,
                actor=actor,
                event=UserActivity.Event.ADMIN_ACTIVITY,
                success=response.status_code < 400,
                details={
                    "method": request.method,
                    "status_code": response.status_code,
                    "view": getattr(request.resolver_match, "view_name", "") if request.resolver_match else "",
                },
            )

        return response


class SecurityHeadersMiddleware:
    """Apply the project's security and no-cache response headers."""

    CONTENT_SECURITY_POLICY = (
        "default-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; "
        "frame-src 'self'; "
        "form-action 'self'; "
        "upgrade-insecure-requests; "
        "block-all-mixed-content"
    )
    CACHE_CONTROL = (
        "must-revalidate, pre-check=0, post-check=0, max-age=0, s-maxage=0"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.pop("Server", None)
        response.headers.pop("X-Powered-By", None)
        response["Content-Security-Policy"] = self.CONTENT_SECURITY_POLICY
        response["Referrer-Policy"] = "same-origin"
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        # Kept for compliance with legacy clients; modern browsers ignore it.
        response["X-XSS-Protection"] = "1; mode=block"
        response["Cache-Control"] = self.CACHE_CONTROL
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response


CAPTCHA_SCRIPT = r"""
<script>
(function () {
    const passwordInput = document.getElementById("id_password") ||
        document.querySelector('input[name="password"]');
    const usernameInput = document.getElementById("id_username") ||
        document.querySelector('input[name="username"]');
    if (usernameInput) usernameInput.setAttribute("autocomplete", "off");
    if (passwordInput) passwordInput.setAttribute("autocomplete", "off");
    const loginForm = passwordInput && passwordInput.closest("form");
    if (loginForm) loginForm.setAttribute("autocomplete", "off");
    if (!passwordInput || document.querySelector(".admin-captcha-row")) return;

    const passwordRow = passwordInput.closest(".input-group") || passwordInput.parentElement;
    const captchaRow = document.createElement("div");
    captchaRow.className = "input-group mb-3 admin-captcha-row";

    const captchaImage = document.createElement("img");
    captchaImage.alt = "Verification code";
    captchaImage.style.height = "38px";
    captchaImage.style.width = "auto";
    captchaImage.style.borderRadius = ".25rem 0 0 .25rem";

    const captchaKey = document.createElement("input");
    captchaKey.type = "hidden";
    captchaKey.name = "captcha_0";

    const captchaAnswer = document.createElement("input");
    captchaAnswer.type = "text";
    captchaAnswer.name = "captcha_1";
    captchaAnswer.className = "form-control";
    captchaAnswer.placeholder = "Verification code";
    captchaAnswer.autocomplete = "off";
    captchaAnswer.required = true;
    captchaAnswer.setAttribute("aria-label", "Verification code");

    captchaRow.append(captchaImage, captchaKey, captchaAnswer);
    passwordRow.insertAdjacentElement("afterend", captchaRow);

    fetch("/captcha/refresh/", {headers: {"X-Requested-With": "XMLHttpRequest"}})
        .then(function (response) {
            if (!response.ok) throw new Error("Unable to load CAPTCHA");
            return response.json();
        })
        .then(function (challenge) {
            captchaKey.value = challenge.key;
            captchaImage.src = challenge.image_url;
        })
        .catch(function () {
            captchaAnswer.disabled = true;
            captchaAnswer.placeholder = "Unable to load verification code";
        });
}());
</script>
"""


class AdminLoginCaptchaMiddleware:
    """Add the CAPTCHA control without replacing Jazzmin's login template."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        login_path = reverse("admin:login")

        if request.path != login_path or response.status_code != 200:
            return response
        if "text/html" not in response.get("Content-Type", ""):
            return response

        charset = response.charset
        html = response.content.decode(charset)
        if "</body>" not in html or "admin-captcha-row" in html:
            return response

        response.content = html.replace("</body>", CAPTCHA_SCRIPT + "</body>", 1).encode(charset)
        response.headers.pop("Content-Length", None)
        return response
