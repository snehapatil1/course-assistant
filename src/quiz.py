"""Quiz generation, validation, and grading on the student's materials.

The answer key is generated once (``primary_key``) and stored server-side
only; clients receive ``to_client_view`` (no key, no explanations). Grading
happens against the stored key, and explanations/sources are revealed with
the grade. Key stability is asserted via ``key_sha`` (identical inputs ->
identical hash) so the key never silently changes between runs.
Each generated quiz also carries a per-generation unique ``quiz_id`` (identical
material/topic/count never overwrite a stored answer key) and a server-side
``chunk_map`` of stored source metadata, so grading feedback cites real
document titles, slide/page numbers, and supporting excerpts.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets

from src import config

TOPIC_STOPWORDS = {
    "about", "after", "all", "also", "an", "and", "any", "are", "been", "before",
    "between", "both", "but", "can", "could", "did", "does", "each", "for", "from",
    "had", "has", "have", "how", "into", "its", "just", "may", "more", "most",
    "much", "not", "off", "only", "other", "our", "out", "over", "should", "such",
    "than", "that", "the", "their", "then", "there", "these", "they", "this",
    "those", "through", "use", "using", "was", "were", "what", "when", "where",
    "which", "while", "who", "will", "with", "would", "your",
}


def _topic_tokens(topic: str) -> list[str]:
    """Meaningful search tokens from a topic string (words + consecutive pairs).

    E.g. ``"context window quantization"`` -> ['context', 'window', 'quantization',
    'context window', 'window quantization']. Empty when the topic has no
    meaningful tokens, in which case ranking is skipped entirely.
    """
    words = [w for w in re.findall(r"[a-z0-9]+", topic.lower()) if len(w) > 2
             and w not in TOPIC_STOPWORDS]
    tokens = list(words)
    tokens += [f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)]
    return tokens


def _topic_score(text: str, tokens: list[str]) -> int:
    """Sum of topic-token occurrences in a chunk (word-boundary matching)."""
    lowered = f" {text.lower()} "
    total = 0
    for tok in tokens:
        if " " in tok:  # phrase: bonus x2
            total += 2 * len(re.findall(rf"(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])", lowered))
        else:
            total += len(re.findall(rf"(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])", lowered))
    return total


def select_topic_chunks(chunks: list[dict], topic: str, k: int) -> tuple[list[dict], bool]:
    """Order chunks by topic relevance (keyword scoring) and keep the top k.

    Deterministic and endpoint-free, so quiz generation stays reproducible
    (temperature 0 + identical inputs -> identical questions). Returns
    (top_k_chunks, has_hits): has_hits is False when the topic has meaningful
    tokens but not one chunk mentions any of them - the caller should tell the
    student the topic is not covered by the selected material.
    """
    tokens = _topic_tokens(topic)
    ranked = chunks
    has_hits = True
    if tokens:
        scored = sorted(
            ((_topic_score(c.get("text", ""), tokens), i, c) for i, c in enumerate(chunks)),
            key=lambda t: (-t[0], t[1]),
        )
        ranked = [c for s, _, c in scored]
        has_hits = scored[0][0] > 0 if scored else True
    return ranked[:k], has_hits

QUIZ_SCHEMA_HINT = (
    "Reply with STRICT JSON only: {\"questions\": [{\"question\": str, "
    "\"options\": [4 strings], \"key\": <int 0-3>, \"explain\": str, "
    "\"chunk_ref\": \"<source block number, e.g. '3'>\"}]}."
)

QUIZ_SYSTEM_PROMPT = (
    "You write practice quiz questions for a student based ONLY on the provided "
    "course material excerpts. Write factual multiple-choice questions "
    "(4 options, exactly one correct). The \"key\" is the index of the correct "
    "option. \"chunk_ref\" must be the bracketed number [i] of the source block "
    "that supports the correct answer (just the number as a string, e.g. \"3\"), "
    "and \"explain\" must quote that support. Do not repeat questions.\n"
    + QUIZ_SCHEMA_HINT
)


def _build_quiz_messages(material_title: str, chunks: list[dict], n: int,
                         topic: str = "") -> list[dict]:
    """Evidence blocks are labelled [1], [2], ... because models corrupt long
    chunk ids (spaces/dashes); the labels are mapped back in generate_quiz.
    ``chunks`` is expected to be the TOPIC-RANKED top-k selection (see
    select_topic_chunks); the topic itself is passed explicitly so the model
    writes about it rather than the whole deck.
    """
    selected = chunks[: max(8, n * 3)]
    blocks = "\n\n".join(
        f"[{i}] {c['doc_title']} (slide/page {c['page_no']}):\n{c['text'][:700]}"
        for i, c in enumerate(selected, start=1)
    )
    if topic.strip():
        focus = (f"Topic: {topic}. The questions MUST concern this topic. "
                 "Only use the provided blocks that are relevant to it.")
    else:
        focus = "No specific topic - cover the material broadly."
    user = (
        f"Material: {material_title}\n\n{focus}\n\nWrite {n} multiple-choice "
        f"questions from this material.\n\n{blocks}\n\n{QUIZ_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _resolve_chunk_refs(obj: dict, chunks: list[dict], n: int) -> None:
    """Map the model's chunk_ref choices (block numbers or ids) to canonical
    chunk ids, in place. Accepts: the exact block label, the exact chunk id,
    or a unique prefix of one."""
    selected = chunks[: max(8, n * 3)]
    by_label = {str(i + 1): c["chunk_id"] for i, c in enumerate(selected)}
    for q in obj.get("questions", []):
        ref = str(q.get("chunk_ref", "")).strip()
        if ref in by_label:
            q["chunk_ref"] = by_label[ref]
            continue
        if any(c["chunk_id"] == ref for c in selected):
            continue  # already canonical
        matches = [c["chunk_id"] for c in selected if c["chunk_id"].startswith(ref)]
        if len(matches) == 1:
            q["chunk_ref"] = matches[0]


def parse_quiz_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in quiz response: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def validate_quiz(quiz: dict, expected_n: int, chunk_ids: set[str]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    questions = quiz.get("questions", []) if isinstance(quiz, dict) else []
    if not isinstance(questions, list):
        return False, ["'questions' must be a list"]
    if len(questions) != expected_n:
        errors.append(f"expected {expected_n} questions, got {len(questions)}")
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            errors.append(f"question[{i}] not an object")
            continue
        if not str(q.get("question", "")).strip():
            errors.append(f"question[{i}] missing text")
        opts = q.get("options")
        if not isinstance(opts, list) or len(opts) < 2:
            errors.append(f"question[{i}] needs >=2 options")
        key = q.get("key")
        if not isinstance(key, int) or not (isinstance(opts, list) and 0 <= key < len(opts)):
            errors.append(f"question[{i}] key out of range or not an int")
        if not str(q.get("explain", "")).strip():
            errors.append(f"question[{i}] missing explanation")
        if q.get("chunk_ref") not in chunk_ids:
            errors.append(f"question[{i}] chunk_ref not in provided chunks")
    return (len(errors) == 0), errors


def key_sha(keys: list[int]) -> str:
    return hashlib.sha256(json.dumps(keys, sort_keys=True).encode()).hexdigest()


def quiz_id(material_title: str, topic: str, n: int) -> str:
    return hashlib.sha256(
        f"{material_title}|{topic}|{n}".encode()
    ).hexdigest()[:12]


def _excerpt(text: str, limit: int = 300) -> str:
    """Collapse whitespace and trim a stored chunk's text for display.

    The excerpt must come from the STORED chunk text - never from the model's
    explanation string - so every quoted support can be traced to the source.
    """
    flat = " ".join(str(text).split())
    if not flat:
        return ""
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "…"


def build_chunk_map(chunks: list[dict]) -> dict[str, dict]:
    """Resolve display metadata for every provided chunk, from stored fields.

    The map is stored server-side with the generated quiz so grading can cite
    the real document title, slide/page number, and an excerpt of the actual
    chunk text. Missing fields stay empty (never invented) and the UI renders
    a safe fallback for unresolvable refs.
    """
    return {
        c["chunk_id"]: {
            "doc_title": str(c.get("doc_title") or ""),
            "kind": str(c.get("kind") or "page"),
            "page_no": c.get("page_no"),
            "excerpt": _excerpt(c.get("text", "")),
        }
        for c in chunks
        if c.get("chunk_id")
    }


def generate_quiz(material_title: str, chunks: list[dict], n: int,
                  topic: str = "", chat_fn=None) -> dict:
    """Generate a quiz from the selected chunks. The key stays server-side.

    The model references evidence by short block numbers; refs are mapped to
    canonical chunk ids and validated. One automatic regeneration is attempted
    if the first pass fails validation (models sometimes ignore the labels).
    Each generated quiz gets a unique ``quiz_id`` plus a server-side
    ``chunk_map`` of stored source metadata used by ``grade`` for citations.
    """
    if chat_fn is None:
        from src.embeddings import chat as chat_fn
    # Rank chunks by topic relevance before anything touches the model: with a
    # topic, the top of the window must be the blocks that actually mention it,
    # otherwise the model writes about whatever comes first in page order.
    ranked, topic_covered = select_topic_chunks(
        chunks, topic, k=max(8, n * 3))
    chunk_ids = {c["chunk_id"] for c in chunks}

    last_errors: list[str] = []
    for attempt in range(2):
        messages = _build_quiz_messages(material_title, ranked, n, topic=topic)
        raw = chat_fn(messages)
        if not raw.strip():
            # reasoning models can swallow the budget and return nothing; retry
            # once with a much larger allowance before giving up
            try:
                raw = chat_fn(messages, max_tokens=8192)
            except TypeError:
                raw = ""
        if not raw.strip():
            raise ValueError("quiz model returned an empty response; try fewer "
                             "questions or a shorter material selection")
        try:
            obj = parse_quiz_response(raw)
        except ValueError as exc:
            last_errors = [str(exc)]
            continue
        _resolve_chunk_refs(obj, ranked, n)
        valid, errors = validate_quiz(obj, n, chunk_ids)
        if valid:
            qs = obj.get("questions", [])
            keys = [q["key"] for q in qs]
            return {
                # Unique per generation: quiz_id() alone is a deterministic
                # fingerprint of (material, topic, n), so two quizzes with
                # identical inputs would collide as store keys and one quiz's
                # answer key could silently overwrite the other's.
                "quiz_id": f"{quiz_id(material_title, topic, n)}-{secrets.token_hex(4)}",
                "canonical_id": quiz_id(material_title, topic, n),
                "material_title": material_title,
                "topic": topic,
                "n": n,
                "questions": qs,
                "primary_key": keys,
                "key_sha": key_sha(keys),
                # Stored chunk metadata (title/slide/excerpt) for grading
                # citations; excluded from the client view.
                "chunk_map": build_chunk_map(chunks),
                "raw": raw,
                "topic_note": ("" if topic_covered
                               else (f"The topic '{topic}' is not covered by the "
                                     "selected material; questions were drawn from "
                                     "the closest available blocks.")),
            }
        last_errors = errors
    raise ValueError(f"quiz failed validation after retry: {last_errors}")


def to_client_view(quiz: dict) -> dict:
    """Client-safe view: no key, no explanations, no raw."""
    return {
        "quiz_id": quiz["quiz_id"],
        "canonical_id": quiz.get("canonical_id", quiz["quiz_id"]),
        "material_title": quiz["material_title"],
        "topic": quiz["topic"],
        "n": quiz["n"],
        "key_sha": quiz["key_sha"],
        "questions": [
            {"id": i, "question": q["question"], "options": q["options"]}
            for i, q in enumerate(quiz["questions"])
        ],
    }


def grade(quiz: dict, answers: dict[int, int]) -> dict:
    """Grade answers against the stored key; reveal explanations server-side.

    Each result's ``source`` is resolved from the chunk_map stored at
    generation time - the REAL document title, slide/page number, and chunk
    text - never from the model's explanation string. Unresolvable refs
    degrade to {"resolved": False} so the UI can render an honest fallback.
    """
    chunk_map = quiz.get("chunk_map") or {}
    results = []
    correct = 0
    for i, q in enumerate(quiz["questions"]):
        given = answers.get(i)
        right = given == q["key"]
        correct += int(right)
        src = chunk_map.get(q["chunk_ref"])
        results.append(
            {
                "id": i,
                "question": q["question"],
                "your_answer": given,
                "correct": right,
                "explanation": q["explain"],
                "chunk_ref": q["chunk_ref"],
                "source": ({"resolved": True, **src} if src else {"resolved": False}),
            }
        )
    return {
        "score": correct,
        "total": len(quiz["questions"]),
        "correct": [r["id"] for r in results if r["correct"]],
        "details": results,
    }
