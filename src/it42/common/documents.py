"""PDFs that travel base64-encoded inside events (application.submitted,
signature.requested). The receiving zone checks every one before storing it."""

import base64
import binascii

from django.conf import settings
from django.core.exceptions import ValidationError

from .events import RejectEvent
from .pdf import check_pdf_bytes


def _name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise RejectEvent("document name must be a string of at most 255 characters")
    return value.strip()


def decode_documents(raw: object) -> list[tuple[str, str, bytes]]:
    """``[(name, sha256, content)]`` from an event's ``documents`` list, or RejectEvent
    when a document is malformed, not a PDF, too large or does not match its sha256."""
    if not isinstance(raw, list) or len(raw) > settings.MAX_ATTACHMENTS:
        raise RejectEvent(f"documents must be a list of at most {settings.MAX_ATTACHMENTS}")
    documents = []
    for item in raw:
        if not isinstance(item, dict):
            raise RejectEvent("each document must be an object")
        name = _name(item.get("name"))
        try:
            content = base64.b64decode(item.get("content", ""), validate=True)
            sha256 = check_pdf_bytes(content)
        except (binascii.Error, TypeError, ValueError) as exc:
            raise RejectEvent(f"document {name!r} is not valid base64") from exc
        except ValidationError as exc:
            raise RejectEvent(f"document {name!r}: {exc.messages[0]}") from exc
        if sha256 != item.get("sha256"):
            raise RejectEvent(f"document {name!r} does not match its sha256")
        documents.append((name, sha256, content))
    return documents


def encode_documents(documents: list[tuple[str, str, bytes]]) -> list[dict[str, str]]:
    return [
        {"name": name, "sha256": sha256, "content": base64.b64encode(content).decode()}
        for name, sha256, content in documents
    ]
