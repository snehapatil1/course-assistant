"""Grounded Q&A: build the vision prompt from retrieved evidence, call the
class chat endpoint, parse the structured ``{answer, sources}`` response,
and validate it (strict JSON schema + sources actually support the answer).

Generic: evidence comes from whatever the student uploaded. When the answer
is not in the materials (or evidence is too thin), the model is instructed
to say so instead of inventing.

Implements the grounded-QA acceptance criteria:
``4-grounded-qa-answer-sources-as-validated-structured-output-vision-capable-no-invented-citations``

1. Chat completion returns STRICT JSON ``{answer, sources[]}`` validated
   against a formal JSON schema (``ANSWER_JSON_SCHEMA``, draft-07).
2. Every source carries ``doc`` + ``page_no`` + a non-empty ``excerpt``;
   the support check pins each source to the provided evidence and requires
   the excerpt to actually overlap retrieved text (fabricated doc/page/
   excerpt rejected).
3. "Not found in the provided materials." is the only legitimate no-answer;
   grounded answers MUST cite at least one source -> never invented answers.
4. Vision path: ``include_images=True`` sends the retrieved page/slide
   images to the model; diagrams/charts are answered from the image.
5. Empty-completion fallback ladder: retry with a larger token budget, then
   with images stripped, before giving up honestly (ValueError to the UI).
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import jsonschema

from src import config

NOT_FOUND_MARKER = "Not found in the provided materials."

ANSWER_JSON_SCHEMA_HINT = (
    'Reply with STRICT JSON only: {"answer": "<plain text answer>", '
    '"sources": [{"doc": "<doc id>", "page_no": <int>, "excerpt": "<quoted short excerpt>"}]}. '
    "Return ONLY valid JSON - no prose, no markdown fences. "
    "Every source must be evidence actually provided above (doc + page_no + a short "
    "verbatim-ish excerpt). "
    f"If the question is not answerable from the evidence, set answer to exactly: "
    f"{NOT_FOUND_MARKER!r} and sources to []."
)

SYSTEM_PROMPT = (
    "You are a course assistant for a student. Answer ONLY from the provided evidence "
    "(document excerpts and page/slide images). When asked to explain a slide's picture, "
    "diagram, or chart, describe what the image actually shows. Never invent facts, "
    "page numbers, or citations. If the evidence does not contain the information, say "
    "that it is not in the materials.\n" + ANSWER_JSON_SCHEMA_HINT
)

# Formal JSON schema the model's payload must satisfy (draft-07). The schema is
# strict on purpose: exactly {answer, sources[]}, and each source exactly
# {doc, page_no, excerpt} - display metadata (doc_title, kind, image_path) is
# resolved server-side from the pinned evidence, never trusted from the model.
ANSWER_JSON_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["answer", "sources"],
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string", "minLength": 1},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["doc", "page_no", "excerpt"],
                "additionalProperties": False,
                "properties": {
                    "doc": {"type": "string", "minLength": 1},
                    "page_no": {"type": "integer", "minimum": 1},
                    # a source without an actual excerpt is not a source
                    "excerpt": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}


def _norm(text: str) -> str:
    return " ".join(str(text).strip().split()).rstrip(".").casefold()


def is_not_found(answer: str) -> bool:
    """True when the model used the agreed honest-refusal phrasing."""
    return bool(answer) and _norm(answer) == _norm(NOT_FOUND_MARKER)


def _mime_for(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    return "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"


def _data_uri(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    return f"data:{_mime_for(path)};base64,{base64.b64encode(raw).decode('ascii')}"


def build_messages(question: str, candidates: list, include_images: bool = True) -> list[dict]:
    """Build chat messages: text evidence + (image parts when PNGs exist)."""
    blocks = []
    for i, c in enumerate(candidates, start=1):
        excerpt = " ".join(c.text.split())[:900]
        loc = f"slide {c.page_no}" if c.kind == "slide" else f"page {c.page_no}"
        blocks.append(f"[{i}] {c.doc_title} ({loc}, doc {c.doc!r}):\n{excerpt}")

    user_parts: list[dict] = [{"type": "text", "text": (
        f"Question: {question}\n\nEvidence:\n" + "\n\n".join(blocks)
        + "\n\nAnswer with STRICT JSON per the schema (answer + sources using [n] refs)."
    )}]
    if include_images:
        for c in candidates:
            img = config.PROJECT_ROOT / c.image_path
            if img.exists():
                user_parts.append({"type": "image_url",
                                   "image_url": {"url": _data_uri(img)}})
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_parts},
    ]


def count_images(messages: list[dict]) -> int:
    """Number of image parts attached to the user message (vision evidence sent)."""
    content = messages[1]["content"] if len(messages) > 1 else []
    if isinstance(content, str):
        return 0
    return sum(1 for p in content if isinstance(p, dict) and p.get("type") == "image_url")


def parse_json_response(text: str) -> dict:
    """Robustly parse a JSON object out of a model response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in model response: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def _significant_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{3,}", text.lower())}


def excerpt_overlaps(excerpt: str, candidates: list) -> bool:
    """Support check: does the excerpt actually echo the retrieved evidence?"""
    if not str(excerpt).strip():
        return False
    union = set().union(*[_significant_tokens(c.text) for c in candidates]) if candidates else set()
    return bool(_significant_tokens(excerpt) & union)


def _schema_errors(obj: dict) -> list[str]:
    """Validate the model payload against the formal JSON schema."""
    try:
        errors = sorted(
            jsonschema.Draft7Validator(ANSWER_JSON_SCHEMA).iter_errors(obj),
            key=lambda e: list(e.absolute_path),
        )
    except Exception as exc:  # defensive: the schema itself is fixed
        return [f"internal schema validation error: {exc}"]
    out = []
    for err in errors:
        path = ".".join(str(p) for p in err.absolute_path) or "$"
        out.append(f"{path}: {err.message}")
    return out


def validate_answer(obj: dict, candidates: list) -> tuple[bool, list[str]]:
    """Strict schema + support check. Errors are a list (empty = valid)."""
    errors: list[str] = []

    if not isinstance(obj, dict):
        return False, ["response is not a JSON object"]

    errors.extend(_schema_errors(obj))
    answer = obj.get("answer")
    sources = obj.get("sources", [])

    if isinstance(answer, str) and not is_not_found(answer) and not sources:
        # a grounded answer MUST point at evidence; empty sources on a real
        # answer is the "invented answer" failure mode
        errors.append("grounded answer must cite at least one source (sources is "
                      f"empty); use {NOT_FOUND_MARKER!r} for 'not in materials'")
    if isinstance(answer, str) and is_not_found(answer) and sources:
        errors.append(f"honest refusal ({NOT_FOUND_MARKER!r}) must have sources == []")

    # support checks (independent of the schema pass, so fabrications are still
    # flagged even when a minor schema issue exists)
    if isinstance(sources, list):
        for i, s in enumerate(sources):
            if not isinstance(s, dict):
                errors.append(f"sources[{i}] is not an object")
                continue
            doc = s.get("doc")
            page = s.get("page_no")
            excerpt = str(s.get("excerpt", ""))
            if not (isinstance(doc, str) and isinstance(page, int)):
                continue  # schema pass already reported the type problem
            pinned = any(cand.doc == doc and cand.page_no == page for cand in candidates)
            if not pinned:
                if len(_significant_tokens(excerpt)
                       - set().union(*[_significant_tokens(c.text) for c in candidates])) >= 3:
                    errors.append(
                        f"sources[{i}] cites ({doc}, page {page}) with a fabricated excerpt"
                    )
                else:
                    errors.append(f"sources[{i}] cites ({doc}, page {page}) not in evidence")
            elif excerpt and not excerpt_overlaps(excerpt, candidates):
                # even a pinned source must actually echo the retrieved evidence
                errors.append(f"sources[{i}] excerpt has no overlap with evidence")

    return (len(errors) == 0), errors


def _enrich_sources(sources: list[dict], candidates: list) -> list[dict]:
    """Attach display metadata resolved from the pinned evidence (server truth).

    The model only ever sends {doc, page_no, excerpt}; doc_title/kind/
    image_path/chunk_id come from the candidate we pinned it to.
    """
    by_page = {(c.doc, c.page_no): c for c in candidates}
    for s in sources or []:
        if not isinstance(s, dict):
            continue
        cand = by_page.get((s.get("doc"), s.get("page_no")))
        if cand is not None:
            s.setdefault("doc_title", cand.doc_title)
            s.setdefault("kind", cand.kind)
            s.setdefault("image_path", cand.image_path)
            s.setdefault("chunk_id", cand.chunk_id)
    return sources


class EmptyResponseError(ValueError):
    """Raised when every fallback rung of the empty-completion ladder failed.

    Carries ``ladder`` (rungs tried) so callers can record what happened.
    """

    def __init__(self, message: str, ladder: dict):
        super().__init__(message)
        self.ladder = ladder


def _chat_with_ladder(messages: list[dict], no_image_messages: list[dict] | None,
                      chat_fn, temperature: float | None) -> tuple[str, dict]:
    """Empty-completion fallback ladder (acceptance criterion 5).

    Rung 1: normal call. Rung 2: SAME messages again with a larger token
    budget (reasoning models can burn the budget and return empty). Rung 3:
    images stripped (smaller context) plus the larger budget. Returns
    ``(raw, ladder_info)``; raises nothing - the caller decides what to do
    when every rung came back empty.
    """
    rung_used = 0
    retried = False
    images_stripped = False
    raw = ""
    # (messages variant, bump token budget): rung 2 re-sends the same messages
    # with a bigger budget; rung 3 (when images were attached) drops them.
    attempts = [(messages, False), (messages, True)]
    if no_image_messages is not None and no_image_messages is not messages:
        attempts.append((no_image_messages, True))

    def _call(msgs: list[dict], **kwargs) -> str:
        try:
            return chat_fn(msgs, **kwargs)
        except TypeError:
            return ""  # stub/plain fn without the kwarg: rung unusable, keep others

    for rung, (msgs, big_budget) in enumerate(attempts, start=1):
        kwargs: dict = {"max_tokens": 8192} if big_budget else {}
        if rung > 1:
            retried = True
        if rung >= 3:
            images_stripped = True
        if temperature is not None:
            kwargs["temperature"] = temperature
        raw = _call(msgs, **kwargs)
        if raw.strip():
            rung_used = rung
            break
    if not raw.strip():
        rung_used = len(attempts)
    return raw, {
        "rungs_used": rung_used,
        "retried": retried,
        "images_stripped": images_stripped,
    }


def answer_question(question: str, candidates: list,
                    chat_fn=None, include_images: bool = True,
                    temperature: float | None = None) -> dict:
    """Run the full Q&A round trip; returns answer + validated sources.

    ``temperature``: passed to the chat endpoint when not None (the eval
    harness passes 0.0 for reproducibility); the default lets the chat client
    use ``config.LLM_TEMPERATURE``.
    """
    if chat_fn is None:
        from src.embeddings import chat as chat_fn
    messages = build_messages(question, candidates, include_images=include_images)
    no_image_messages = (None if not include_images
                         else build_messages(question, candidates, include_images=False))
    raw, ladder = _chat_with_ladder(messages, no_image_messages, chat_fn, temperature)
    if not raw.strip():
        raise EmptyResponseError(
            "model returned an empty response on every fallback rung "
            "(budget + images stripped); please retry the question "
            "(or ask a shorter one)", ladder)
    obj = parse_json_response(raw)
    valid, errors = validate_answer(obj, candidates)
    sources = obj.get("sources", []) if isinstance(obj, dict) else []
    return {
        "answer": obj.get("answer", "") if isinstance(obj, dict) else "",
        "sources": _enrich_sources(sources, candidates),
        "raw": raw,
        "valid": valid,
        "validation_errors": errors,
        "ladder": ladder,
        "images_sent": count_images(messages) if not ladder["images_stripped"] else 0,
        "temperature_used": temperature if temperature is not None else config.LLM_TEMPERATURE,
    }
