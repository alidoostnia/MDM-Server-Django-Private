from django.urls import reverse


CAPTCHA_SCRIPT = r"""
<script>
(function () {
    const passwordInput = document.getElementById("id_password") ||
        document.querySelector('input[name="password"]');
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
