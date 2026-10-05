"""
File content — classroom Phase 6 (prd.md CL-8). Pure: no database, no storage,
so every rule here is unit-tested without either.

What a file must survive before it is stored:

  * its SIZE is counted against `Content-Length`, which must be present and
    must equal what arrives. Starlette's multipart parser puts no cap on a file
    part, so uploads are a raw body; and the Next.js `/api` proxy silently
    TRUNCATES a body past 10 MB — a truncated PDF still starts with `%PDF-`, so
    only the length comparison can tell;
  * its TYPE is read from its first bytes, never from its name or the declared
    Content-Type, and a Word or PowerPoint file carrying macros is refused;
  * its NAME is reduced to a plain base name with no path, no control or
    bidirectional-override characters (the "exe.pdf" trick), and an extension
    forced to match the detected type.

Downloads are always `attachment` with a sandboxing CSP: a file is never
rendered inside the application. Since Phase 6b a PDF or an image can also be
VIEWED — in a new tab, on the storage service's own domain, through a short-lived
link (`file_service.view_link`); Office files stay download-only (owner decision
2026-10-05).
"""

import hashlib
import io
import unicodedata
import zipfile
from pathlib import PurePosixPath
from urllib.parse import quote, unquote
from uuid import UUID, uuid4

from fastapi import Request

from app.core.errors import AppError, validation_error

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
EXTENSION = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    DOCX: "docx",
    PPTX: "pptx",
}
# What a browser can show by itself. Word and PowerPoint cannot be, and the
# online viewers that could would hand a student's file to a third party.
VIEWABLE = frozenset({"application/pdf", "image/png", "image/jpeg"})

# A real document has dozens of zip entries; thousands is the shape of a zip
# bomb or something that is not an Office file at all.
_MAX_ZIP_ENTRIES = 5000

_MESSAGES = {
    "length_required": "The upload did not say how large it is.",
    "length_mismatch": "The upload was cut short or padded. Try again.",
    "empty": "The file is empty.",
    "too_large": "The file is too large.",
    "unsupported_type": (
        "Only PDF, PNG, JPEG, Word (.docx) and PowerPoint (.pptx) files are accepted."
    ),
    "not_viewable": "This kind of file can only be downloaded.",
}


def file_error(reason: str) -> AppError:
    """`400 VALIDATION_ERROR` with `details.reason` — no new error codes (RULES B3)."""
    return validation_error(
        message=_MESSAGES.get(reason, "The file was not accepted."), details={"reason": reason}
    )


async def read_bounded_body(request: Request, max_bytes: int) -> bytes:
    raw = request.headers.get("content-length", "")
    if not raw.isdigit():
        raise file_error("length_required")
    declared = int(raw)
    if declared == 0:
        raise file_error("empty")
    if declared > max_bytes:
        raise file_error("too_large")  # refused before a single byte is read
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > declared:
            raise file_error("length_mismatch")
    if len(buf) != declared:
        raise file_error("length_mismatch")
    return bytes(buf)


def sniff_type(data: bytes) -> str:
    """The stored content type, from the bytes alone."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"PK\x03\x04"):
        try:
            # The central directory only: nothing is decompressed.
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
        except zipfile.BadZipFile:
            raise file_error("unsupported_type") from None
        if len(names) > _MAX_ZIP_ENTRIES or any(
            n.lower().endswith("vbaproject.bin") for n in names
        ):
            raise file_error("unsupported_type")  # macros, or not an Office file
        if "[Content_Types].xml" in names and "word/document.xml" in names:
            return DOCX
        if "[Content_Types].xml" in names and "ppt/presentation.xml" in names:
            return PPTX
    raise file_error("unsupported_type")


def sanitize_filename(raw_header: str, content_type: str) -> str:
    """A safe display name: the client's base name, cleaned, with the RIGHT extension."""
    name = unicodedata.normalize("NFC", unquote(raw_header))
    # Cc: control characters. Cf: format characters, which include the
    # bidirectional overrides U+202A–U+202E and U+2066–U+2069.
    name = "".join(ch for ch in name if unicodedata.category(ch) not in ("Cc", "Cf"))
    name = PurePosixPath(name.replace("\\", "/")).name.strip(" .")
    stem = PurePosixPath(name).stem.strip(" .")[:200] or "file"
    return f"{stem}.{EXTENSION[content_type]}"


def describe(data: bytes, raw_name: str) -> dict:
    content_type = sniff_type(data)
    return {
        "content_type": content_type,
        "filename": sanitize_filename(raw_name, content_type),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


# Object keys. The database holds each to its owner (ck_material_key,
# ck_subfile_key); the random part is never derived from the file name.
def material_key(space_id: UUID) -> str:
    return f"s/{space_id}/{uuid4().hex}"


def submission_key(space_id: UUID, student_id: UUID) -> str:
    return f"u/{space_id}/{student_id}/{uuid4().hex}"


def content_disposition(filename: str, *, inline: bool = False) -> str:
    """An ASCII fallback name plus the exact UTF-8 one (RFC 6266)."""
    ascii_name = (
        filename.encode("ascii", "ignore").decode().replace('"', "").replace("\\", "").strip()
        or "file"
    )
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def download_headers(filename: str, size: int) -> dict[str, str]:
    """Always `attachment`, in a sandbox: a download is never rendered by the app."""
    return {
        "Content-Disposition": content_disposition(filename),
        "Content-Length": str(size),
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
