import json
from pathlib import Path

from django.core.exceptions import ValidationError


EXTENSION_TYPES = {
    ".pdf": {"application/pdf"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".gif": {"image/gif"},
    ".webp": {"image/webp"},
    ".bmp": {"image/bmp"},
    ".zip": {"application/zip"},
    ".docx": {"application/zip"},
    ".xlsx": {"application/zip"},
    ".pptx": {"application/zip"},
    ".apk": {"application/zip"},
    ".txt": {"text/plain"},
    ".csv": {"text/plain"},
    ".log": {"text/plain"},
    ".json": {"application/json"},
    ".xml": {"application/xml"},
    ".mp3": {"audio/mpeg"},
    ".wav": {"audio/wav"},
    ".mp4": {"video/mp4"},
    ".gz": {"application/gzip"},
    ".7z": {"application/x-7z-compressed"},
    ".rar": {"application/vnd.rar"},
}

MIME_ALIASES = {
    "application/x-zip-compressed": "application/zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "application/zip",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "application/zip",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "application/zip",
    "application/vnd.android.package-archive": "application/zip",
    "text/csv": "text/plain",
    "text/xml": "application/xml",
    "audio/x-wav": "audio/wav",
}


def ensure_supported_extension(filename):
    extension = Path(filename or "").suffix.lower()
    if extension not in EXTENSION_TYPES:
        raise ValidationError(
            f"Files with the '{extension or '[none]'}' extension are not allowed because their content cannot be verified."
        )
    return extension


def detect_content_type(content):
    if not isinstance(content, (bytes, bytearray)) or not content:
        raise ValidationError("The uploaded file is empty or could not be inspected.")
    data = bytes(content)
    stripped = data.lstrip()

    if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "application/zip"
    if data.startswith(b"\x1f\x8b"):
        return "application/gzip"
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "application/x-7z-compressed"
    if data.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
        return "application/vnd.rar"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"ID3") or (len(data) > 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "video/mp4"

    if b"\x00" in data:
        raise ValidationError("The file content does not match a recognized safe file type.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("The file content does not match a recognized safe file type.") from exc

    if stripped.startswith((b"{", b"[")):
        try:
            json.loads(text)
        except json.JSONDecodeError:
            if len(data) < 65536:
                raise ValidationError("The uploaded JSON content is invalid.")
        return "application/json"
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<"):
        return "application/xml"
    return "text/plain"


def validate_file_content(filename, content, declared_type=None):
    extension = ensure_supported_extension(filename)
    detected = detect_content_type(content)
    if detected not in EXTENSION_TYPES[extension]:
        raise ValidationError(
            f"The file content ({detected}) does not match the '{extension}' extension."
        )

    declared = (declared_type or "").split(";", 1)[0].strip().lower()
    declared = MIME_ALIASES.get(declared, declared)
    if declared and declared != "application/octet-stream" and declared != detected:
        raise ValidationError(
            f"The declared content type ({declared_type}) does not match the verified content ({detected})."
        )
    return detected
