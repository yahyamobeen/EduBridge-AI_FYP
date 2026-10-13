"""Server-Sent Events for the tutor (tdd.md §3.2, §3.2a).

`tdd.md` has specified SSE for `/api/tutor/ask` since v0.1, in three separate places; the
pilot shipped a non-streaming JSON body because no schema was ever written down. This is
the first streaming endpoint in the backend, so it sets the pattern.

No new dependency. `sse-starlette` exists, but one route hand-rolling four frame types is
less code than a package (CLAUDE.md §3.2), and the frame format is six lines.

⚠️ THE TRANSACTION BOUNDARY IS THE SUBTLE PART. Both sides of the exchange are written at
the END of the stream, in the session the request already holds, so one commit covers
both. The consequence is deliberate: a client that disconnects mid-answer leaves NEITHER
turn, never a question paired with a truncated reply attributed to the tutor. Writing the
question up front would be the obvious alternative and it leaves an orphan - a transcript
showing the student asking and the tutor silent, which reads like the tutor refused.

⚠️ This relies on FastAPI finalising dependencies-with-yield AFTER the response body is
streamed. Measured true on fastapi 0.141.1 / starlette 1.3.1, and asserted by
`test_dependency_outlives_the_stream` - because this ordering CHANGED once already in
fastapi 0.106, and if it changes again every transcript silently stops being saved.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.tutor import service as tutor_service

logger = logging.getLogger("edubridge.tutor.streaming")


def frame(event: str, data: dict[str, Any]) -> bytes:
    """One SSE frame.

    `ensure_ascii=False` keeps Urdu legible on the wire rather than expanding every
    character into a `\\uXXXX` escape; the response declares utf-8. JSON encoding is
    what makes this safe regardless - a literal newline inside `data:` would terminate
    the frame early, and `json.dumps` escapes newlines inside strings.
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


# Set on the response, not here, but kept next to the frame format they belong with.
# `no-cache` stops a shared cache holding a student's answer. `X-Accel-Buffering: no` is
# the one that matters in production: a buffering reverse proxy holds the whole body and
# turns a streamed answer back into a single slow response, which looks exactly like the
# model being slow and is diagnosed by nobody.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-store",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def event_stream(
    db: Session,
    session_id: UUID,
    question: str,
    hits: list[dict[str, Any]],
    retriever: str,
    timings: dict[str, float],
    token_source: Iterator[str],
    intent: str = "retrieve",
) -> Iterator[bytes]:
    """Emit `pages`, then `token` per chunk, then `done`. Persist before `done`.

    `hits` is already retrieved: retrieval runs in the handler so that a total retrieval
    failure is an ordinary HTTP error with a §7.3 envelope. Once the first byte is on the
    wire that is no longer possible, which is why everything that can fail outright
    happens before this generator is iterated.
    """
    # Citations first, before a single token. They are the part a student can act on
    # immediately, and they make the wait legible instead of blank.
    yield frame(
        "pages",
        {
            "pages": hits,
            "retriever": retriever,
            # ⚠️ Separate from `retriever` on purpose. `heuristic` + `reference` is a
            # correct exercise lookup; `heuristic` + `retrieve` is a degraded answer
            # because the retrieval service was unreachable. Without this the client
            # cannot tell them apart and would either alarm on both or neither.
            # `reused` means no retrieval ran at all - a follow-up on the same pages.
            "intent": intent,
            "timings": timings,
        },
    )

    chunks: list[str] = []
    gen_error: str | None = None
    try:
        for chunk in token_source:
            chunks.append(chunk)
            yield frame("token", {"text": chunk})
    except Exception as exc:
        # Mid-stream failure. The status line is long gone, so this cannot become a 503;
        # it is reported on `done` and the client renders the citations it already has
        # plus a "could not answer" state. Nothing is fabricated to fill the gap.
        gen_error = "MODEL_UNAVAILABLE"
        logger.warning("generation failed mid-stream (%s: %s)", type(exc).__name__, exc)

    reply = "".join(chunks)

    message_id: UUID | None = None
    if reply:
        # Both turns, together, at the end - see this module's docstring.
        tutor_service.append_message(db, session_id, "user", question)
        message_id = tutor_service.append_message(db, session_id, "assistant", reply, pages=hits)

    yield frame(
        "done",
        {
            "session_id": str(session_id),
            "message_id": str(message_id) if message_id else None,
            "timings": timings,
            "error": gen_error,
        },
    )
