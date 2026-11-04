"""PDF upload checks shared by both zones."""

import hashlib

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

PDF_MAGIC = b"%PDF-"


def check_pdf_bytes(content: bytes) -> str:
    """Validate raw PDF bytes; return their SHA-256 hex digest."""
    if len(content) > settings.MAX_PDF_BYTES:
        raise ValidationError("The file is larger than 5 MB.")
    if not content.startswith(PDF_MAGIC):
        raise ValidationError("The file is not a PDF.")
    return hashlib.sha256(content).hexdigest()


def check_pdf_upload(upload: UploadedFile) -> tuple[bytes, str]:
    """Read and validate an uploaded PDF. Returns (content, sha256)."""
    if upload.size is not None and upload.size > settings.MAX_PDF_BYTES:
        raise ValidationError("The file is larger than 5 MB.")
    content = b"".join(upload.chunks())
    return content, check_pdf_bytes(content)
