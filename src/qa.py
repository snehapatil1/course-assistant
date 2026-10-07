"""Grounded Q&A: build the vision prompt from retrieved evidence, call the
class chat endpoint, parse the structured ``{answer, sources}`` response,
and validate it (schema + sources actually support the answer).

Generic: evidence comes from whatever the student uploaded. When the answer
is not in the materials (or evidence is too thin), the model is instructed
to say so instead of inventing.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from src import config

ANSWER_JSON_SCHEMA_HINT = (
    'Reply with STRICT JSON only: {"answer": "<plain text answer>", '
    '"sources": [{"doc": "<doc id>", "page_no": <int>, "excerpt": "<quoted short excerpt>"}]}. '
    "Use sources only for evidence actually provided above; if the question is not "
    "answerable from the evidence, set answer to exactly: Not found in the provided materials."
    " and sources to []."
)

SYSTEM_PROMPT = (
    "You are a course assistant for a student. Answer ONLY from the provided evidence "
    "(document excerpts and page/slide images). When asked to explain a slide's picture, "
    "diagram, or chart, describe what the image actually shows. Never invent facts, "
    "page numbers, or citations. If the evidence does not contain the information, say "
    "that it is not in the materials.\n" + ANSWER_JSON_SCHEMA_HINT
)


def _data_uri(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    return f"data:image/png;base64,{base64.b64encode(raw).decode('ascii')}"


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


def validate_answer(obj: dict, candidates: list) -> tuple[bool, list[str]]:
    """Schema + support check. Errors are returned as a list (empty = valid)."""
    errors: list[str] = []

    if not isinstance(obj, dict):
        return False, ["response is not a JSON object"]
    answer = obj.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        errors.append("'answer' must be a non-empty string")
    sources = obj.get("sources", [])
    if not isinstance(sources, list):
        errors.append("'sources' must be a list")
        sources = []

    cands = {c.chunk_id: c for c in candidates}
    cand_texts = [c.text for c in candidates]
    allowed = {"chunk_id", "doc", "doc_title", "page_no", "excerpt", "kind"}
    for i, s in enumerate(sources):
        if not isinstance(s, dict):
            errors.append(f"sources[{i}] is not an object")
            continue
        unknown = set(s) - allowed
        if unknown:
            errors.append(f"sources[{i}] has unknown fields {sorted(unknown)}")
        doc = s.get("doc")
        page = s.get("page_no")
        excerpt = str(s.get("excerpt", ""))
        # support check: the source must pin to a provided evidence item
        if doc is None or page is None:
            errors.append(f"sources[{i}] missing doc/page_no")
            continue
        pinned = any(
            cand.doc == doc and cand.page_no == page for cand in candidates
        )
        overlap = (_significant_tokens(excerpt) & set().union(
            *[_significant_tokens(t) for t in cand_texts]
        )) if excerpt else set()
        if not pinned:
            if len(_significant_tokens(excerpt) - set().union(
                    *[_significant_tokens(t) for t in cand_texts])) >= 3:
                errors.append(
                    f"sources[{i}] cites ({doc}, page {page}) with a fabricated excerpt"
                )
            else:
                errors.append(f"sources[{i}] cites ({doc}, page {page}) not in evidence")
        if excerpt and not overlap:
            # even a pinned source must actually echo the retrieved evidence
            errors.append(f"sources[{i}] excerpt has no overlap with evidence")

    return (len(errors) == 0), errors


def answer_question(question: str, candidates: list,
                    chat_fn=None, include_images: bool = True) -> dict:
    """Run the full Q&A round trip; returns answer + validated sources."""
    if chat_fn is None:
        from src.embeddings import chat as chat_fn
    messages = build_messages(question, candidates, include_images=include_images)
    raw = chat_fn(messages)
    if not raw.strip():
        # reasoning models can swallow the budget and return nothing; retry
        # once with a much larger allowance before giving up
        try:
            raw = chat_fn(messages, max_tokens=8192)
        except TypeError:
            raw = ""
    if not raw.strip():
        raise ValueError("model returned an empty response; please retry the "
                         "question (or ask a shorter one)")
    obj = parse_json_response(raw)
    valid, errors = validate_answer(obj, candidates)
    sources = obj.get("sources", []) if isinstance(obj, dict) else []
    return {
        "answer": obj.get("answer", "") if isinstance(obj, dict) else "",
        "sources": sources,
        "raw": raw,
        "valid": valid,
        "validation_errors": errors,
    }
