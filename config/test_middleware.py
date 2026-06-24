from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from .middleware import SecurityHeadersMiddleware


class SecurityHeadersMiddlewareTest(SimpleTestCase):
    def test_adds_required_security_headers(self):
        middleware = SecurityHeadersMiddleware(lambda request: HttpResponse())

        response = middleware(RequestFactory().get("/"))

        self.assertEqual(
            response["Content-Security-Policy"],
            SecurityHeadersMiddleware.CONTENT_SECURITY_POLICY,
        )
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-XSS-Protection"], "1; mode=block")
        self.assertEqual(
            response["Cache-Control"], SecurityHeadersMiddleware.CACHE_CONTROL
        )
        self.assertEqual(response["Pragma"], "no-cache")
        self.assertEqual(response["Expires"], "0")
