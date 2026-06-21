from django.test import SimpleTestCase

from .forms import AdminCaptchaAuthenticationForm


class AdminCaptchaAuthenticationFormTest(SimpleTestCase):
    def test_login_fields_disable_autocomplete(self):
        form = AdminCaptchaAuthenticationForm()

        self.assertEqual(form.fields["username"].widget.attrs["autocomplete"], "off")
        self.assertEqual(form.fields["password"].widget.attrs["autocomplete"], "off")
        self.assertIn('autocomplete="off"', str(form["username"]))
        self.assertIn('autocomplete="off"', str(form["password"]))
