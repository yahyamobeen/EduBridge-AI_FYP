"""
Classroom files — the database and storage side (classroom Phase 6).

`files.py` decides whether bytes are acceptable; this module decides whether the
CALLER may store, read or remove them, and keeps the bucket in step with the
rows:

  * UPLOAD stores the object FIRST and writes its row SECOND, through an `app.*`
    function that checks membership, the graded/turned-in lock and the quotas
    under a short lock. If the database refuses, the object is deleted at once;
    if the request later rolls back, `track_upload` deletes it. So no lock is
    ever held while a 5 MB body crosses the network.
  * DOWNLOAD reads the row under the caller's Row-Level Security — the same
    visibility as the post or the work it belongs to — and only then streams
    the object.
  * DELETE removes the row, and the object only once that commits.
  * VIEW (Phase 6b) reads the row exactly as DOWNLOAD does, then hands out a
    five-minute link that shows a PDF or an image in a new tab, on the storage
    service's domain. The link is a bearer pass: it is never stored or logged.

Who may see a file is decided by the policies in 20261004150000, never here: a
read that RLS hides is the same 403 as an id that does not exist.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.classroom import storage
from app.classroom.files import VIEWABLE, describe, file_error, material_key, submission_key
from app.classroom.service import require_owner
from app.core.errors import forbidden_scope, validation_error

Parent = Literal["announcement", "assignment"]

# How long a view link works. Long enough for a slow phone to open and page
# through a 5 MB PDF (a viewer can fetch it in ranges as it scrolls); short
# enough that a copied link is soon useless (owner decision 2026-10-05).
VIEW_LINK_SECONDS = 300

_META = "id, filename, content_type, size_bytes, created_at"

# Outcomes from the writing functions that are a state of the work rather than
# a bad file. `graded` and `turned_in` match the Phase 4 submission refusals.
_STATE_MESSAGES = {
    "graded": "Your teacher has graded this work, so it can no longer change.",
    "turned_in": "Unsubmit the work before changing its files.",
    "too_many_files": "There are already as many files here as are allowed.",
    "submission_quota": "These files together are larger than one piece of work may be.",
    "classroom_quota": "This classroom has used all of its file storage.",
}


def _refuse(outcome: str) -> Exception:
    if outcome in _STATE_MESSAGES:
        return validation_error(message=_STATE_MESSAGES[outcome], details={"reason": outcome})
    return forbidden_scope()


# ── listing (used by the announcement and assignment responses) ─────────────


def attachments_for_announcements(db: Session, ids: list[UUID]) -> dict[UUID, list[dict]]:
    if not ids:
        return {}
    rows = (
        db.execute(
            text(
                f"SELECT announcement_id, {_META} FROM material_attachment "  # noqa: S608 -- literal
                "WHERE announcement_id = ANY(:ids) ORDER BY created_at, id"
            ),
            {"ids": ids},
        )
        .mappings()
        .all()
    )
    grouped: dict[UUID, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["announcement_id"], []).append(_meta(r))
    return grouped


def attachments_for_assignment(db: Session, assignment_id: UUID) -> list[dict]:
    rows = db.execute(
        text(
            f"SELECT {_META} FROM material_attachment "  # noqa: S608 -- fixed literal
            "WHERE assignment_id = :a ORDER BY created_at, id"
        ),
        {"a": assignment_id},
    ).mappings()
    return [_meta(r) for r in rows]


def files_for_submission(db: Session, assignment_id: UUID, student_id: UUID) -> list[dict]:
    """RLS returns the teacher nothing until the work is turned in."""
    rows = db.execute(
        text(
            "SELECT f.id, f.filename, f.content_type, f.size_bytes, f.created_at "
            "  FROM submission_file f "
            "  JOIN assignment_submission s ON s.id = f.submission_id "
            " WHERE s.assignment_id = :a AND s.student_id = :u "
            " ORDER BY f.created_at, f.id"
        ),
        {"a": assignment_id, "u": student_id},
    ).mappings()
    return [_meta(r) for r in rows]


def _meta(r: Any) -> dict:
    return {k: r[k] for k in ("id", "filename", "content_type", "size_bytes", "created_at")}


# ── upload ──────────────────────────────────────────────────────────────────


def submission_upload_space(db: Session, assignment_id: UUID) -> UUID:
    """
    A cheap check BEFORE the body is read, so an outsider never gets to send
    5 MB: the assignment is live in a classroom the caller is a member of. The
    authoritative check is `app.add_submission_file`.
    """
    space_id = db.execute(
        text(
            "SELECT a.space_id FROM assignment a "
            " WHERE a.id = :a AND a.space_id IN (SELECT app.my_member_space_ids())"
        ),
        {"a": assignment_id},
    ).scalar_one_or_none()
    if space_id is None:
        raise forbidden_scope()
    return space_id


def material_upload_space(db: Session, parent: Parent, parent_id: UUID) -> UUID:
    table = "announcement" if parent == "announcement" else "assignment"
    space_id = db.execute(
        text(f"SELECT space_id FROM {table} WHERE id = :id"),  # noqa: S608 -- one of two literals
        {"id": parent_id},
    ).scalar_one_or_none()
    if space_id is None:
        raise forbidden_scope()
    require_owner(db, space_id)  # owner of a NON-archived classroom
    return space_id


def _store(
    db: Session, table: str, key: str, data: bytes, meta: dict, call: str, params: dict
) -> dict:
    storage.get_object_storage().put(key, data, meta["content_type"])
    try:
        row = db.execute(text(call), params).mappings().one()
    except Exception:
        storage.delete_now([key])  # the row was never written
        raise
    if row["outcome"] != "added":
        storage.delete_now([key])
        raise _refuse(row["outcome"])
    storage.track_upload(db, key)  # deleted again if this transaction rolls back
    return (
        db.execute(
            text(f"SELECT {_META} FROM {table} WHERE id = :id"),  # noqa: S608 -- one of two literals
            {"id": row["new_file_id"]},
        )
        .mappings()
        .one()
    )


def store_submission_file(
    db: Session, user_id: UUID, assignment_id: UUID, space_id: UUID, data: bytes, raw_name: str
) -> dict:
    meta = describe(data, raw_name)
    key = submission_key(space_id, user_id)
    row = _store(
        db,
        "submission_file",
        key,
        data,
        meta,
        "SELECT outcome, new_file_id FROM app.add_submission_file(:a, :k, :n, :t, :s, :h)",
        {
            "a": assignment_id,
            "k": key,
            "n": meta["filename"],
            "t": meta["content_type"],
            "s": meta["size"],
            "h": meta["sha256"],
        },
    )
    return _meta(row)


def store_material(
    db: Session, parent: Parent, parent_id: UUID, space_id: UUID, data: bytes, raw_name: str
) -> dict:
    meta = describe(data, raw_name)
    key = material_key(space_id)
    row = _store(
        db,
        "material_attachment",
        key,
        data,
        meta,
        "SELECT outcome, new_file_id "
        "  FROM app.add_material_attachment(:ann, :asg, :k, :n, :t, :s, :h)",
        {
            "ann": parent_id if parent == "announcement" else None,
            "asg": parent_id if parent == "assignment" else None,
            "k": key,
            "n": meta["filename"],
            "t": meta["content_type"],
            "s": meta["size"],
            "h": meta["sha256"],
        },
    )
    return _meta(row)


# ── download ────────────────────────────────────────────────────────────────


def readable_file(db: Session, kind: Literal["submission", "material"], file_id: UUID) -> dict:
    """The row, if the caller's RLS shows it; otherwise the usual 403."""
    table = "submission_file" if kind == "submission" else "material_attachment"
    row = (
        db.execute(
            text(
                f"SELECT object_key, filename, content_type, size_bytes FROM {table} "  # noqa: S608
                "WHERE id = :id"
            ),
            {"id": file_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise forbidden_scope()
    return dict(row)


def view_link(db: Session, kind: Literal["submission", "material"], file_id: UUID) -> dict:
    """
    Read the row under RLS first — a file the caller cannot see is the usual
    403 — and only then sign a link. Office files are download-only.
    """
    meta = readable_file(db, kind, file_id)
    if meta["content_type"] not in VIEWABLE:
        raise file_error("not_viewable")
    # Taken before signing, so the link outlives the time reported, never the reverse.
    expires_at = datetime.now(UTC) + timedelta(seconds=VIEW_LINK_SECONDS)
    url = storage.get_object_storage().view_url(
        meta["object_key"], meta["filename"], meta["content_type"], VIEW_LINK_SECONDS
    )
    return {"url": url, "expires_at": expires_at}


# ── delete ──────────────────────────────────────────────────────────────────


def remove_submission_file(db: Session, file_id: UUID) -> None:
    row = (
        db.execute(
            text("SELECT outcome, removed_object_key FROM app.remove_submission_file(:id)"),
            {"id": file_id},
        )
        .mappings()
        .one()
    )
    if row["outcome"] != "removed":
        raise _refuse(row["outcome"])
    storage.delete_after_commit(db, [row["removed_object_key"]])


def remove_material(db: Session, file_id: UUID) -> None:
    # Under RLS: only the owner of an ACTIVE classroom deletes (material_owner_delete).
    key = db.execute(
        text("DELETE FROM material_attachment WHERE id = :id RETURNING object_key"),
        {"id": file_id},
    ).scalar_one_or_none()
    if key is None:
        raise forbidden_scope()
    storage.delete_after_commit(db, [key])


def material_keys_of_announcement(db: Session, announcement_id: UUID) -> list[str]:
    """Read BEFORE the announcement is deleted: the cascade removes the rows, not the objects."""
    return list(
        db.execute(
            text("SELECT object_key FROM material_attachment WHERE announcement_id = :id"),
            {"id": announcement_id},
        ).scalars()
    )
