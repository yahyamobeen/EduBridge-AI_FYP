"""
Object storage for classroom files (classroom Phase 6, owner decision 8).

The same shape as `app/auth/email.py`: a Protocol, an in-memory implementation
for tests and local work, the real one, a cached factory, and Session hooks so
storage FOLLOWS THE DATABASE TRANSACTION — the lesson of finding D1, applied to
objects instead of emails:

  * an object stored during a request that then ROLLS BACK is deleted, so a
    failed request leaves no orphan behind (`track_upload`);
  * an object whose row was deleted is removed only once that deletion
    COMMITS, so a failed request never loses a file whose row survived
    (`delete_after_commit`).

Deletion runs off the request thread, after the response, and a failure is
logged rather than raised: an orphaned object costs storage, while a crashed
worker would lose every later deletion silently.

⚠️ CALLERS GO THROUGH `storage.get_object_storage()`, never a name imported
   from here: `tests/integration/conftest.py` replaces the factory so no test
   can reach real storage, and a captured reference would slip past it.
"""

import logging
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger("edubridge.storage")

# Downloads are streamed in chunks of this size (plan R8): a whole file is
# never held in memory on the way out.
CHUNK = 64 * 1024


class MissingObjectError(Exception):
    """A row points at an object storage does not have — an integrity fault."""


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def open(self, key: str) -> Iterator[bytes]:
        """Opens the object NOW (so a missing one fails before any byte is sent)
        and returns its content in chunks."""
        ...

    def delete_many(self, keys: list[str]) -> None: ...


class InMemoryObjectStorage:
    """Tests and local development. Refused in production (config.py)."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    def open(self, key: str) -> Iterator[bytes]:
        if key not in self.objects:
            raise MissingObjectError(key)
        data = self.objects[key][0]
        return iter([data[i : i + CHUNK] for i in range(0, len(data), CHUNK)])

    def delete_many(self, keys: list[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)


class S3ObjectStorage:
    """Supabase Storage over the S3 protocol, with storage-only access keys."""

    def __init__(self) -> None:
        # Imported here so nothing that never stores a file pays for botocore.
        import boto3
        from botocore.config import Config

        settings = get_settings()
        self._bucket = settings.storage_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.storage_s3_endpoint,
            region_name=settings.storage_s3_region,
            aws_access_key_id=settings.storage_s3_access_key_id,
            aws_secret_access_key=settings.storage_s3_secret_access_key,
            config=Config(
                # Supabase's S3 endpoint is path-style only.
                s3={"addressing_style": "path"},
                # botocore 1.36+ adds checksum headers to every upload by default,
                # which S3-compatible services do not all accept. Only when the
                # operation requires one.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        # Supabase reads a request's XML body only when it is labelled as XML,
        # and botocore sends DeleteObjects with no Content-Type: the endpoint
        # then answers 400 "must have required property 'Body'" and deletes
        # nothing (measured against the real bucket, 2026-10-05).
        self._client.meta.events.register("before-sign.s3.DeleteObjects", _label_xml_body)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def open(self, key: str) -> Iterator[bytes]:
        from botocore.exceptions import ClientError

        try:
            body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
        except ClientError as exc:
            # The status, not the code: Supabase puts its <Error> body in a
            # namespace, which botocore parses to an EMPTY code (measured
            # 2026-10-05) — while the 404 is always there.
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                raise MissingObjectError(key) from None
            raise
        return _chunks(body)

    def delete_many(self, keys: list[str]) -> None:
        for i in range(0, len(keys), 1000):  # the DeleteObjects limit
            self._client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": k} for k in keys[i : i + 1000]], "Quiet": True},
            )


def _label_xml_body(request: Any, **_: Any) -> None:
    if "Content-Type" not in request.headers:
        request.headers["Content-Type"] = "application/xml"


def _chunks(body: Any) -> Iterator[bytes]:
    try:
        yield from body.iter_chunks(chunk_size=CHUNK)
    finally:
        body.close()


@lru_cache
def get_object_storage() -> ObjectStorage:
    if get_settings().storage_provider == "s3":
        return S3ObjectStorage()
    return InMemoryObjectStorage()


# ── deletion, following the transaction ────────────────────────────────────

_UPLOADED = "edubridge_storage_uploaded"  # delete if the transaction ROLLS BACK
_DOOMED = "edubridge_storage_doomed"  # delete only once the transaction COMMITS

_executor: ThreadPoolExecutor | None = None
_pending: list[Future] = []


def _pool() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="edubridge-storage")
    return _executor


def _delete(keys: list[str]) -> None:
    try:
        get_object_storage().delete_many(keys)
    except Exception:  # noqa: BLE001 -- an orphan is recoverable; a dead worker is silent
        logger.exception("storage cleanup failed for %d object(s)", len(keys))


def delete_now(keys: list[str]) -> None:
    """For an object stored a moment ago whose row the database then refused."""
    if keys:
        _delete(keys)


def track_upload(session: Session, key: str) -> None:
    """The object is stored and its row written: delete it if the row is rolled back."""
    session.info.setdefault(_UPLOADED, []).append(key)


def delete_after_commit(session: Session, keys: list[str]) -> None:
    """The rows are deleted: remove the objects once — and only if — that commits."""
    if keys:
        session.info.setdefault(_DOOMED, []).extend(keys)


@event.listens_for(Session, "after_commit")
def _on_commit(session: Session) -> None:
    session.info.pop(_UPLOADED, None)  # the rows survived: keep their objects
    if keys := session.info.pop(_DOOMED, []):
        _pending.append(_pool().submit(_delete, keys))


@event.listens_for(Session, "after_soft_rollback")
def _on_rollback(session: Session, previous_transaction: object) -> None:
    # `after_soft_rollback`, not `after_rollback` — the reason is in email.py.
    session.info.pop(_DOOMED, None)  # the rows survived: keep their objects
    if keys := session.info.pop(_UPLOADED, []):
        _pending.append(_pool().submit(_delete, keys))


def drain_storage_cleanup(timeout: float = 10.0) -> None:
    """Block until queued deletions finish: tests, and a graceful shutdown."""
    pending, _pending[:] = list(_pending), []
    for future in pending:
        future.result(timeout=timeout)
