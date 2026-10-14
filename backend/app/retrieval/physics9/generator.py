"""Physics 9 Answer Generator.

Interacts with Google Gemini with page image grounding.
Enforces Punjab Board (PCTB) curriculum alignment, multilingual handling
(English, Roman Urdu, Urdu script), and preservation of English technical terms.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Retried only on the two codes that mean "ask again later", never on a 4xx that means
# the request itself is wrong - a bad key would otherwise walk the whole attempt list
# holding a threadpool worker, which is defect 6 on `tdd.md` §14.2's list.
#
# ⚠️ And only BEFORE the first chunk is yielded. Retrying after that would replay the
# answer from the start and the client, which appends tokens as they arrive, would
# render the opening twice.
_RETRYABLE = frozenset({429, 503})
# Linearly backed off by attempt number. A blocking sleep in a sync handler is
# acceptable here only because it is bounded by the attempt list and runs in the
# threadpool, not on the event loop.
_RETRY_PAUSE_S = 1.0
# Longest advertised wait worth honouring. Gemini returns 429 for two unrelated things:
# a per-MINUTE rate limit, which clears in seconds and is worth retrying, and a per-DAY
# free-tier quota, which does not.
#
# ⚠️ THE FREE TIER IS 20 REQUESTS PER DAY PER MODEL
# (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`), and a quota 429 advertises a
# `retryDelay` of several HOURS - 29673s measured. Retrying that is worse than useless:
# every attempt consumes another of the 20, so a handful of failures can spend a day's
# budget on nothing while the student waits. Past this threshold the model is dropped
# for the rest of the call and the next one is tried instead.
_MAX_RETRY_WAIT_S = 5.0


def _auth_headers(api_key: str) -> dict[str, str]:
    """The key as a HEADER, never as `?key=` in the URL.

    ⚠️ THIS IS NOT A STYLE PREFERENCE. httpx logs the full request URL at INFO, so a
    key in the query string is written verbatim into the application log on every
    call - observed in production output, where the live key appeared in plaintext
    beside a 200. `backend/CLAUDE.md` §6 says secrets are never logged, and a query
    parameter cannot keep that promise: the URL is also what reverse proxies, access
    logs and error trackers record. A header is not logged by any of them.

    Gemini accepts `x-goog-api-key` as an equivalent to the `key` parameter.
    """
    return {"x-goog-api-key": api_key}


def _advertised_retry_wait(body: str) -> float | None:
    """Seconds Gemini asks us to wait, from `RetryInfo.retryDelay` ("29673s").

    None when the body carries no advice, which is treated as "short" - the existing
    backoff then applies, exactly as before this function existed.
    """
    try:
        details = json.loads(body).get("error", {}).get("details", [])
    except (ValueError, AttributeError):
        return None
    for d in details:
        if d.get("@type", "").endswith("RetryInfo"):
            delay = str(d.get("retryDelay", "")).rstrip("s")
            try:
                return float(delay)
            except ValueError:
                return None
    return None


logger = logging.getLogger("edubridge.retrieval.physics9.generator")

SYSTEM_PROMPT = """You are a physics tutor for a Pakistani student in Class 9,
working from the Punjab Board (PCTB) textbook. You are shown photographs of the
textbook pages that were retrieved for this question.

GROUNDING
- Answer only from the pages shown. If they do not contain the answer, say so
  plainly - do not fill the gap from memory.
- Cite the page number you used, like "(p155)".
- Read numbers off the page carefully. The scan is 150 DPI; if a value or a
  subscript is genuinely unclear, say it is unclear rather than guessing.

LANGUAGE
- Reply in the language of the question. English question -> English. Roman Urdu
  question -> Roman Urdu. Urdu script question -> Urdu script.
- KEEP TECHNICAL TERMS IN ENGLISH even when the rest is Urdu. Write "thermocouple",
  "kinetic energy", "absolute zero" - never their Urdu translations. The student is
  examined in English and a translated term is useless to them.
- When the answer is something they must reproduce on an exam, give the English
  wording they should write.

TEACHING
- Explain, do not transcribe. Short sentences, one idea at a time.
- If asked to solve a numbered exercise question, give a hint and the method
  first. Provide the full worked solution only if asked again.

FIGURES
- If one of the pages shown carries a figure, diagram or table that genuinely
  helps answer this question, end your reply with a single line in exactly this
  form, after all the prose, and write nothing after it:

  @@FIGURE {"page": 155, "box": [0.12, 0.34, 0.88, 0.71], "caption": "Fig. 7.8 Thermocouple"}

- `box` is [left, top, right, bottom] as fractions of the page, 0 to 1, where
  0,0 is the top-left corner. Enclose the figure and its caption, not the whole
  page and not a sliver.
- Only one figure, and only when it adds something the words do not. If no
  figure helps, omit the line entirely - do not emit an empty or guessed box.
"""


class PhysicsGenerator:
    """Generates grounded pedagogical explanations from retrieved textbook pages."""

    def __init__(
        self,
        api_key: str = "",
        model_name: str = "gemini-3.6-flash",
        pages_dir: Path | None = None,
        fallback_models: list[str] | None = None,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()
        self.model_name = model_name or os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
        self.pages_dir = pages_dir
        # Explicit configuration, never guessed. Empty by default, in which case a
        # 503 just retries the configured model.
        self.fallback_models = fallback_models or []

    def generate(
        self,
        question: str,
        hits: list[dict[str, Any]],
        history: list[dict[str, str]] | None = None,
        lang: str = "en",
    ) -> tuple[str, float, str | None]:
        """Generate a response grounded in the retrieved pages.

        Returns (reply_text, latency_seconds, error_string_if_any).
        """
        t0 = time.time()
        if not self.api_key:
            return (
                self._fallback_grounded_answer(question, hits, lang),
                time.time() - t0,
                "no GEMINI_API_KEY set - using curriculum-grounded response",
            )

        # Attempt generation via google-genai SDK or httpx fallback
        try:
            return self._generate_with_gemini(question, hits, history)
        except Exception as exc:
            logger.warning(
                "Gemini generation failed (%s: %s). Falling back to grounded response.",
                type(exc).__name__,
                exc,
            )
            return (
                self._fallback_grounded_answer(question, hits, lang),
                time.time() - t0,
                f"{type(exc).__name__}: {exc}",
            )

    def build_payload(
        self,
        question: str,
        hits: list[dict[str, Any]],
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """The Gemini request body: system prompt, prior turns, page images, question.

        Extracted so the streaming and non-streaming paths send IDENTICAL content - two
        copies would drift, and the drift would show up as the streamed answer being
        grounded differently from the one the tests exercise.

        ⚠️ WHAT THIS DELIBERATELY DOES NOT CARRY: no user id, no session id, no name, no
        email - in the current turn or in any replayed one. Only the question text and
        the page images leave the platform. That is the mitigation deviation V3 rests on
        (tdd.md §14.2): an anonymous physics question is a materially weaker claim on
        "data about minors" than an identified one. `test_no_identity_reaches_gemini`
        asserts it so it cannot regress.
        """
        contents: list[dict[str, Any]] = []

        # Prior turns, oldest first. Bounded at 4 (tdd.md §4.1): an unbounded window
        # grows the prompt without limit and, with a hosted generator, the exposure too.
        if history:
            for turn in history[-4:]:
                role = "user" if turn.get("role") == "user" else "model"
                contents.append({"role": role, "parts": [{"text": turn.get("content", "")}]})

        current_user_parts: list[dict[str, Any]] = []

        # The page scans themselves. Reading the page IS the retrieval result here -
        # there is no extracted text to send, which is the point of visual retrieval.
        if self.pages_dir and self.pages_dir.exists():
            for h in hits:
                page_num = h.get("page")
                img_path = self.pages_dir / f"p{page_num:03}.jpeg"
                if img_path.exists():
                    try:
                        data = img_path.read_bytes()
                        b64_data = base64.b64encode(data).decode("utf-8")
                        current_user_parts.append(
                            {
                                "inline_data": {
                                    "mime_type": "image/jpeg",
                                    "data": b64_data,
                                }
                            }
                        )
                        current_user_parts.append(
                            {"text": f"(The above image is Textbook Page {page_num})"}
                        )
                    except Exception as e:
                        logger.debug("Could not read image %s: %s", img_path, e)

        current_user_parts.append({"text": f"Student question: {question}"})
        contents.append({"role": "user", "parts": current_user_parts})

        return {
            "contents": contents,
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "generation_config": {
                "temperature": 0.2,
                # Headroom. The cap covers reasoning AND answer together, so a model
                # that thinks can exhaust it before writing anything - see below.
                "max_output_tokens": 2048,
                # ⚠️ THINKING OFF, DELIBERATELY. Gemini 3.x flash models reason before
                # answering and those tokens come out of `max_output_tokens`. Measured
                # on this exact prompt: 854 thinking tokens against 180 of answer, and
                # `finishReason: MAX_TOKENS` - the student got a reply that stopped
                # mid-sentence, with a 200 in the log and nothing resembling an error
                # anywhere. Same prompt with the budget at 0: a COMPLETE answer, STOP,
                # and 5s instead of 9s.
                #
                # Chain-of-thought earns little here and costs both. The task is to
                # read three page scans and report what they say; the grounding comes
                # from the images, not from deliberation, and the prompt already
                # forbids reasoning past them. Raising the cap instead would keep the
                # latency and still truncate a longer answer.
                #
                # Accepted by gemini-3-flash-preview, 3.1-flash-lite and 3.6-flash
                # (verified); a model that rejects it would 400, so check before
                # adding one to GEMINI_FALLBACK_MODELS.
                "thinking_config": {"thinking_budget": 0},
            },
        }

    def stream_tokens(
        self,
        question: str,
        hits: list[dict[str, Any]],
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        """Yield generated text as it arrives. Raises on any failure.

        ⚠️ THIS PATH NEVER FALLS BACK TO `_fallback_grounded_answer`, AND THAT IS THE
        POINT. That fallback writes physics from the model's own memory and cites a page
        for it - which the system prompt in this same file explicitly forbids, and which
        is recorded as defect P2 (tdd.md §14.2). The defect stays on the old `/chat`
        path because the owner chose to defer it, but new code must not reproduce it: a
        student who cannot be answered is told so.

        ⚠️ RETRIES ONLY BEFORE THE FIRST CHUNK, AND ONLY ON 503/429. Once a token has
        reached the student, retrying would restart the answer mid-sentence and duplicate
        what is already on screen, so the loop is abandoned the moment anything is
        yielded.

        ⚠️ An earlier revision had NO retry, reasoning that the non-streaming path's
        3.6 -> 3.7 -> 3.8 chain "guesses at versions that may not exist for this key".
        That was wrong on the facts - `ListModels` for this key returns all three - and a
        503 "this model is currently experiencing high demand" is exactly the transient
        the chain absorbed. It was observed in production: the student got citations and
        no answer.
        """
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        payload = self.build_payload(question, hits, history)
        yielded = False
        last_error = ""

        # Models whose daily quota is spent. `_models_to_try` lists the primary twice,
        # and without this the second pass pays for a refusal already received.
        exhausted: set[str] = set()

        for attempt, model in enumerate(self._models_to_try()):
            if model in exhausted:
                continue
            try:
                # One `with`: the context managers bind left to right, so `client`
                # exists by the time `client.stream(...)` is evaluated.
                with (
                    httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client,
                    client.stream(
                        "POST",
                        f"{_API_BASE}/{model}:streamGenerateContent",
                        params={"alt": "sse"},
                        headers=_auth_headers(self.api_key),
                        json=payload,
                    ) as response,
                ):
                    if response.status_code != 200:
                        # In streaming mode the body is not loaded until read();
                        # without this the message would be empty.
                        response.read()
                        last_error = f"HTTP {response.status_code}: {response.text[:160]}"
                        if response.status_code in _RETRYABLE:
                            wait = _advertised_retry_wait(response.text)
                            if wait is not None and wait > _MAX_RETRY_WAIT_S:
                                # A day's quota, not a momentary spike. Waiting cannot
                                # help and re-asking only spends what is left.
                                exhausted.add(model)
                                logger.warning(
                                    "gemini %s quota exhausted (retry advised in %.0fs); "
                                    "skipping this model",
                                    model,
                                    wait,
                                )
                                continue
                            logger.info("gemini %s: %s; retrying", model, last_error)
                            time.sleep(_RETRY_PAUSE_S * (attempt + 1))
                            continue
                        raise RuntimeError(f"Gemini {last_error}")

                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        blob = line[len("data:") :].strip()
                        if not blob or blob == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(blob)
                        except ValueError:
                            # A truncated frame is not worth failing an answer over.
                            logger.debug("unparseable SSE frame from Gemini, skipped")
                            continue
                        for candidate in chunk.get("candidates", []):
                            for part in candidate.get("content", {}).get("parts", []):
                                if text := part.get("text"):
                                    yielded = True
                                    yield text
                    return
            except httpx.HTTPError as exc:
                if yielded:
                    raise
                last_error = f"{type(exc).__name__}: {exc}"
                logger.info("gemini transport error: %s; retrying", last_error)
                time.sleep(_RETRY_PAUSE_S * (attempt + 1))

        raise RuntimeError("Gemini generation failed: " + (last_error or "no attempts"))

    def _models_to_try(self) -> list[str]:
        """The configured model, any configured alternates, then the model once more.

        ⚠️ The alternates are CONFIGURATION, never a guess. `GEMINI_FALLBACK_MODELS`
        defaults to empty, so a deployment that has chosen none simply retries its own
        model - which is the right response to a 503 that says demand spikes are
        usually temporary.
        """
        models = [self.model_name]
        for name in self.fallback_models:
            if name and name not in models:
                models.append(name)
        models.append(self.model_name)
        return models

    def _generate_with_gemini(
        self,
        question: str,
        hits: list[dict[str, Any]],
        history: list[dict[str, str]] | None = None,
    ) -> tuple[str, float, str | None]:
        t0 = time.time()
        payload = self.build_payload(question, hits, history)

        models_to_try = [self.model_name]
        for fallback_m in ["gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"]:
            if fallback_m not in models_to_try:
                models_to_try.append(fallback_m)

        last_error = ""
        with httpx.Client(timeout=30.0) as client:
            for m in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
                for _attempt in range(2):
                    try:
                        resp = client.post(
                            url,
                            headers=_auth_headers(self.api_key),
                            json=payload,
                        )
                        if resp.status_code == 200:
                            res_data = resp.json()
                            candidates = res_data.get("candidates", [])
                            if not candidates:
                                return "", time.time() - t0, "No candidates returned by Gemini"
                            reply = (
                                candidates[0]
                                .get("content", {})
                                .get("parts", [{}])[0]
                                .get("text", "")
                            )
                            return reply.strip(), time.time() - t0, None
                        if resp.status_code in (503, 429):
                            last_error = f"HTTP {resp.status_code}: {resp.text[:120]}"
                            time.sleep(1.0)
                            continue
                        last_error = f"HTTP {resp.status_code}: {resp.text[:120]}"
                        break
                    except Exception as exc:
                        last_error = str(exc)
                        time.sleep(0.5)

        raise RuntimeError(f"Gemini API generation failed: {last_error}")

    def _fallback_grounded_answer(
        self,
        question: str,
        hits: list[dict[str, Any]],
        lang: str,
    ) -> str:
        """High quality pedagogical template answer when Gemini API key is not configured."""
        top_hit = hits[0] if hits else {"page": 154, "chapter": 7}
        page = top_hit.get("page", 154)
        chapter = top_hit.get("chapter", 7)
        q_lower = question.lower()

        # Specific conceptual responses for prominent syllabus topics
        if "thermocouple" in q_lower or "تھرمو کپل" in question or "تھرموکپل" in question:
            if lang == "ur-Latn":
                return (
                    f"Assalam-o-Alaikum! PCTB Physics 9 ke mutabiq (p{page}):\n\n"
                    "**Thermocouple** aik aisa electrical device hai jo heat energy ko electrical energy mein convert karta hai.\n\n"
                    "1. **Working Principle:** Yeh do mukhtalif metals (jaise copper aur iron) ke wires ko jorh kar banaya jata hai.\n"
                    "2. **Junctions:** Aik junction ko **cold junction** par rakha jata hai aur doosre ko **hot junction** par.\n"
                    "3. **Seebeck Effect:** Dono junctions ke temperature difference ki wajah se circuit mein aik potential difference (voltage) paida hota hai, jo meter par measure hota hai.\n\n"
                    f"Aap mazeed tafseel textbook ke Chapter {chapter} (Page {page}) par dekh sakte hain."
                )
            if lang == "ur":
                return (
                    f"السلام علیکم! پنجاب ٹیکسٹ بک بورڈ فزکس 9 کے مطابق (صفحہ {page}):\n\n"
                    "**Thermocouple** ایک ایسا برقی آلہ ہے جو حرارتی توانائی (heat energy) کو برقی توانائی (electrical energy) میں تبدیل کرتا ہے۔\n\n"
                    "1. **Working Principle:** یہ دو مختلف دھاتوں کے تاروں کو جوڑ کر بنایا جاتا ہے۔\n"
                    "2. **Junctions:** ایک سرے کو **cold junction** اور دوسرے کو **hot junction** پر رکھا جاتا ہے۔\n"
                    "3. درجہ حرارت کے فرق (temperature difference) کی وجہ سے سرکٹ میں وولٹیج پیدا ہوتی ہے جس سے درجہ حرارت ناپا جاتا ہے۔\n\n"
                    f"مزید تفصیل کے لیے باب {chapter}، صفحہ {page} ملاحظہ فرمائیں۔"
                )
            return (
                f"According to the PCTB Physics 9 textbook (p{page}):\n\n"
                "A **thermocouple** is an electrical temperature-measuring device that converts thermal energy into electrical energy.\n\n"
                "1. **Construction:** It consists of two wires of dissimilar metals (such as iron and copper) joined at both ends to form two junctions.\n"
                "2. **Working Principle:** One junction is kept at a known reference temperature (cold junction) while the other is placed at the point of measurement (hot junction).\n"
                "3. **Thermoelectric Effect:** The temperature difference between the two junctions establishes an electromotive force (emf) / voltage across the circuit, directly proportional to the temperature difference.\n\n"
                f"Reference: PCTB Class 9 Physics, Chapter {chapter}, Page {page}."
            )

        if "pascal" in q_lower or "hydraulic" in q_lower:
            return (
                f"According to PCTB Physics 9 (p{page}):\n\n"
                "**Pascal's Law:** Pressure applied at any point of a liquid enclosed in a container is transmitted equally and undiminished in all directions to all parts of the liquid.\n\n"
                "**Application (Hydraulic Press):**\n"
                "A hydraulic press works on Pascal's law. A small force $F_1$ applied on a small piston of area $A_1$ produces a pressure $P = F_1 / A_1$. This same pressure is transmitted to a larger piston of area $A_2$, producing a much larger lifting force $F_2 = P \\times A_2$.\n\n"
                f"Refer to Chapter {chapter}, Page {page} for the complete diagram and formula derivation."
            )

        # General pedagogical fallback citing chapter & pages
        pages_str = ", ".join(f"p{h['page']}" for h in hits[:3])
        return (
            f"Here is the explanation grounded in your PCTB Physics 9 textbook ({pages_str}):\n\n"
            f"This topic is covered in **Chapter {chapter}** of your Class 9 textbook.\n"
            f"Key focus areas for this concept on {pages_str} include the core definition, SI units, and the standard board diagram.\n\n"
            "Would you like me to walk you through the key formulas and step-by-step exam points for this topic?"
        )
