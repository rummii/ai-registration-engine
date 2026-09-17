"""Cloud Storage helpers for Telegram voucher photos.

The bucket is private. Vouchers are streamed back through an admin-only route in
``app.py`` rather than served by signed URL, so the Cloud Run runtime service
account does not need ``roles/iam.serviceAccountTokenCreator`` on itself.

``google.cloud.storage`` is imported lazily: tests and local runs then need
neither the library installed nor Application Default Credentials present.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from config import MAX_VOUCHER_BYTES, VOUCHER_BUCKET

logger = logging.getLogger(__name__)

_client = None


class VoucherError(RuntimeError):
    """Raised when a voucher cannot be stored or retrieved."""


def is_configured() -> bool:
    """True when a destination bucket is configured."""
    return bool(VOUCHER_BUCKET)


def reset_client() -> None:
    """Drop the cached client. Used by tests."""
    global _client
    _client = None


def _get_client():
    global _client
    if _client is None:
        try:
            from google.cloud import storage
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise VoucherError(
                "google-cloud-storage is not installed; voucher upload is unavailable."
            ) from exc

        try:
            _client = storage.Client()
        except Exception as exc:  # pragma: no cover - depends on credentials
            raise VoucherError(f"Could not create a Cloud Storage client: {exc}") from exc
    return _client


def sanitize_chat_id(chat_id) -> str:
    """Reduce a chat id to a filename-safe token."""
    return re.sub(r"[^0-9A-Za-z_-]", "", str(chat_id)) or "unknown"


def build_object_name(chat_id, when: datetime | None = None, extension: str = "jpg") -> str:
    """Build a month-partitioned object name.

    Mirrors the old bot's ``<timestamp>_<chat_id>.jpg`` naming but nests by year
    and month so a listing stays navigable.
    """
    when = when or datetime.now(timezone.utc)
    return (
        f"vouchers/{when.strftime('%Y')}/{when.strftime('%m')}/"
        f"{when.strftime('%Y%m%d_%H%M%S')}_{sanitize_chat_id(chat_id)}.{extension}"
    )


def upload_voucher(
    data: bytes,
    *,
    chat_id,
    content_type: str = "image/jpeg",
    when: datetime | None = None,
) -> str:
    """Store a voucher photo and return its object name.

    Raises VoucherError when the bucket is unconfigured, the payload is empty or
    oversized, or the upload fails.
    """
    if not is_configured():
        raise VoucherError("No voucher bucket is configured.")
    if not data:
        raise VoucherError("The voucher payload is empty.")
    if len(data) > MAX_VOUCHER_BYTES:
        raise VoucherError(
            f"The voucher is larger than the {MAX_VOUCHER_BYTES // (1024 * 1024)} MB limit."
        )

    object_name = build_object_name(chat_id, when=when)
    try:
        bucket = _get_client().bucket(VOUCHER_BUCKET)
        bucket.blob(object_name).upload_from_string(data, content_type=content_type)
    except VoucherError:
        raise
    except Exception as exc:
        raise VoucherError(f"Could not upload the voucher: {exc}") from exc

    logger.info("Stored voucher %s", object_name)
    return object_name


_VOUCHER_NAME = re.compile(r"^vouchers/\d{4}/\d{2}/[0-9A-Za-z_.-]+$")


def is_valid_object_name(object_name: str) -> bool:
    """Reject anything that is not a name this module could have produced.

    Guards the admin download route against traversal and against being used to
    read arbitrary objects from the bucket.
    """
    return bool(object_name) and bool(_VOUCHER_NAME.match(object_name))


def download_voucher(object_name: str) -> bytes:
    """Fetch a stored voucher, raising VoucherError on any failure."""
    if not is_valid_object_name(object_name):
        raise VoucherError("Refusing to fetch an unexpected object name.")
    if not is_configured():
        raise VoucherError("No voucher bucket is configured.")

    try:
        blob = _get_client().bucket(VOUCHER_BUCKET).blob(object_name)
        return blob.download_as_bytes()
    except VoucherError:
        raise
    except Exception as exc:
        raise VoucherError(f"Could not download the voucher: {exc}") from exc


def content_type_for(object_name: str) -> str:
    """Best-effort content type from the object extension."""
    lowered = object_name.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".pdf"):
        return "application/pdf"
    return "image/jpeg"
