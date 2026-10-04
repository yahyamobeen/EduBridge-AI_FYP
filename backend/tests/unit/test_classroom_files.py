"""
Classroom files (Phase 6) — everything decided before a byte reaches storage,
and storage following the transaction. No database: the hooks are exercised on
an in-memory SQLite session, because what is under test is SQLAlchemy's
commit and rollback events, not PostgreSQL.
"""

import asyncio
import io
import re
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import pytest
from botocore.stub import Stubber
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.classroom import storage
from app.classroom.files import (
    DOCX,
    PPTX,
    download_headers,
    material_key,
    read_bounded_body,
    sanitize_filename,
    sniff_type,
    submission_key,
)
from app.core.errors import AppError

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def _zip(*names: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name in names:
            archive.writestr(name, "<x/>")
    return buf.getvalue()


def _reason(caught: pytest.ExceptionInfo) -> str:
    assert isinstance(caught.value, AppError)
    assert caught.value.code == "VALIDATION_ERROR"
    return caught.value.details["reason"]


class TestTheTypeComesFromTheBytes:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            (PDF, "application/pdf"),
            (PNG, "image/png"),
            (JPEG, "image/jpeg"),
            (_zip("[Content_Types].xml", "word/document.xml"), DOCX),
            (_zip("[Content_Types].xml", "ppt/presentation.xml"), PPTX),
        ],
        ids=["pdf", "png", "jpeg", "docx", "pptx"],
    )
    def test_each_accepted_type_is_recognised(self, data, expected):
        assert sniff_type(data) == expected

    @pytest.mark.parametrize(
        "data",
        [
            _zip("[Content_Types].xml", "word/document.xml", "word/vbaProject.bin"),
            _zip("readme.txt"),
            b"PK\x03\x04 not really a zip",
            b"MZ\x90\x00 an executable",
            b"<html><script>alert(1)</script>",
        ],
        ids=["macro docx", "plain zip", "broken zip", "executable", "html"],
    )
    def test_anything_else_is_refused(self, data):
        with pytest.raises(AppError) as caught:
            sniff_type(data)
        assert _reason(caught) == "unsupported_type"


class TestTheNameIsMadeSafe:
    @pytest.mark.parametrize(
        ("raw", "content_type", "expected"),
        [
            ("../../etc/passwd", "application/pdf", "passwd.pdf"),
            ("C:\\Users\\aisha\\Lab report.docx", DOCX, "Lab report.docx"),
            # U+202E RIGHT-TO-LEFT OVERRIDE: displays as "invoiceexe.pdf".
            ("invoice\u202efdp.exe", "application/pdf", "invoicefdp.pdf"),
            ("photo.pdf", "image/png", "photo.png"),  # the extension follows the bytes
            ("%D8%A7%D9%85%D8%AA%D8%AD%D8%A7%D9%86.pdf", "application/pdf", "امتحان.pdf"),
            ("...", "application/pdf", "file.pdf"),
            ("", "image/jpeg", "file.jpg"),
        ],
        ids=[
            "traversal",
            "windows path",
            "bidi override",
            "wrong extension",
            "urdu",
            "dots",
            "empty",
        ],
    )
    def test_names(self, raw, content_type, expected):
        assert sanitize_filename(raw, content_type) == expected

    def test_a_long_name_is_cut_to_fit_the_database(self):
        assert len(sanitize_filename("x" * 400 + ".pdf", "application/pdf")) <= 255


class _Upload:
    """Just what read_bounded_body touches: headers and the body stream."""

    def __init__(self, length: str | None, *chunks: bytes) -> None:
        self.headers = {} if length is None else {"content-length": length}
        self._chunks = chunks
        self.read = False

    async def stream(self):
        self.read = True
        for chunk in self._chunks:
            yield chunk


def _read(upload: _Upload, limit: int = 100) -> bytes:
    return asyncio.run(read_bounded_body(upload, limit))  # type: ignore[arg-type]


class TestTheBodyIsCounted:
    def test_an_exact_body_is_returned(self):
        assert _read(_Upload("6", b"abc", b"def")) == b"abcdef"

    @pytest.mark.parametrize(
        ("upload", "reason"),
        [
            (_Upload(None, b"abc"), "length_required"),
            (_Upload("chunked", b"abc"), "length_required"),
            (_Upload("0"), "empty"),
            (_Upload("10", b"abc"), "length_mismatch"),  # cut short — the proxy truncation
            (_Upload("2", b"abc"), "length_mismatch"),  # more than declared
        ],
        ids=["no length", "not a number", "empty", "short", "long"],
    )
    def test_refusals(self, upload, reason):
        with pytest.raises(AppError) as caught:
            _read(upload)
        assert _reason(caught) == reason

    def test_too_large_is_refused_before_reading_anything(self):
        upload = _Upload("101", b"x" * 101)
        with pytest.raises(AppError) as caught:
            _read(upload)
        assert _reason(caught) == "too_large"
        assert upload.read is False


class TestKeysAndHeaders:
    def test_keys_have_the_shape_the_database_requires(self):
        space, student = uuid4(), uuid4()
        assert re.fullmatch(rf"s/{space}/[0-9a-f]{{32}}", material_key(space))
        assert re.fullmatch(rf"u/{space}/{student}/[0-9a-f]{{32}}", submission_key(space, student))
        assert material_key(space) != material_key(space)

    def test_a_download_is_an_attachment_in_a_sandbox(self):
        headers = download_headers('امتحان "final".pdf', 1234)
        disposition = headers["Content-Disposition"]
        assert disposition.startswith("attachment; ")
        assert 'filename="final.pdf"' in disposition  # ASCII fallback, no quotes
        assert "filename*=UTF-8''%D8%A7" in disposition  # the exact name, encoded
        assert headers["Content-Length"] == "1234"
        assert "sandbox" in headers["Content-Security-Policy"]
        assert headers["Cache-Control"] == "private, no-store"


class TestInMemoryStorage:
    def test_round_trip_in_chunks(self):
        store = storage.InMemoryObjectStorage()
        data = b"x" * (storage.CHUNK * 2 + 5)
        store.put("k", data, "application/pdf")
        chunks = list(store.open("k"))
        assert b"".join(chunks) == data
        assert len(chunks) == 3

    def test_a_missing_object_fails_before_any_byte_is_sent(self):
        with pytest.raises(storage.MissingObjectError):
            storage.InMemoryObjectStorage().open("nope")


class _SentError(Exception):
    """Stops a request at the moment it would go on the wire."""


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setattr(
        storage,
        "get_settings",
        lambda: SimpleNamespace(
            storage_bucket="classroom-files",
            storage_s3_endpoint="https://storage.example.test/storage/v1/s3",
            storage_s3_region="ap-southeast-2",
            storage_s3_access_key_id="test-key-id",
            storage_s3_secret_access_key="test-secret",  # noqa: S106 -- a placeholder, never sent
        ),
    )
    return storage.S3ObjectStorage()


class TestS3Requests:
    """
    Two ways Supabase's S3 endpoint differs from S3, both measured 2026-10-05
    against the real bucket. Neither shows up against an in-memory store.
    """

    def test_a_missing_object_is_recognised_by_its_404(self, s3):
        # Supabase answers 404 with <Code>NoSuchKey</Code>, but inside a
        # namespaced <Error> element, which botocore parses to an EMPTY code.
        stubber = Stubber(s3._client)
        stubber.add_client_error(
            "get_object", service_error_code="", service_message="", http_status_code=404
        )
        with stubber, pytest.raises(storage.MissingObjectError):
            s3.open("s/space/object")

    def test_a_batch_delete_labels_its_body_as_xml(self, s3):
        # With no Content-Type, DeleteObjects is answered 400 "must have
        # required property 'Body'" — the XML body is not read — and botocore
        # sends none. Every deletion would fail, and only in a log line.
        sent: dict[str, str | None] = {}

        def capture(request, **_):
            value = request.headers.get("Content-Type")
            sent["content_type"] = value.decode() if isinstance(value, bytes) else value
            raise _SentError

        s3._client.meta.events.register("before-send.s3.DeleteObjects", capture)
        with pytest.raises(_SentError):
            s3.delete_many(["s/space/object"])
        assert sent["content_type"] == "application/xml"


@pytest.fixture
def store(monkeypatch):
    fake = storage.InMemoryObjectStorage()
    monkeypatch.setattr(storage, "get_object_storage", lambda: fake)
    return fake


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    with Session(engine) as s:
        s.execute(text("SELECT 1"))  # begin a transaction, as a request does
        yield s


class TestStorageFollowsTheTransaction:
    def test_an_upload_survives_a_commit(self, store, session):
        store.put("k", b"data", "application/pdf")
        storage.track_upload(session, "k")
        session.commit()
        storage.drain_storage_cleanup()
        assert "k" in store.objects

    def test_an_upload_is_removed_on_rollback(self, store, session):
        store.put("k", b"data", "application/pdf")
        storage.track_upload(session, "k")
        session.rollback()
        storage.drain_storage_cleanup()
        assert "k" not in store.objects

    def test_a_deletion_waits_for_the_commit(self, store, session):
        store.put("k", b"data", "application/pdf")
        storage.delete_after_commit(session, ["k"])
        storage.drain_storage_cleanup()
        assert "k" in store.objects  # nothing has committed yet
        session.commit()
        storage.drain_storage_cleanup()
        assert "k" not in store.objects

    def test_a_deletion_is_forgotten_on_rollback(self, store, session):
        store.put("k", b"data", "application/pdf")
        storage.delete_after_commit(session, ["k"])
        session.rollback()
        session.execute(text("SELECT 1"))
        session.commit()  # a later commit on the same session must not delete it
        storage.drain_storage_cleanup()
        assert "k" in store.objects
