from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .validators import validate_file_content


class FileContentValidatorTest(SimpleTestCase):
    def test_accepts_pdf_signature(self):
        detected = validate_file_content(
            "report.pdf",
            b"%PDF-1.7\ncontent",
            "application/pdf",
        )
        self.assertEqual(detected, "application/pdf")

    def test_rejects_renamed_text_as_pdf(self):
        with self.assertRaises(ValidationError):
            validate_file_content(
                "report.pdf",
                b"this is not a PDF",
                "application/pdf",
            )

    def test_rejects_unsupported_extension(self):
        with self.assertRaises(ValidationError):
            validate_file_content("payload.exe", b"MZ\x00\x00")
