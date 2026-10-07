"""Quiz generation, validation, and grading on the student's materials.

The answer key is generated once (``primary_key``) and stored server-side
only; clients receive ``to_client_view`` (no key, no explanations). Grading
happens against the stored key, and explanations/sources are revealed with
the grade. Key stability is asserted via ``key_sha`` (identical inputs ->
identical hash) so the key never silently changes between runs.
"""
from __future__ import annotations

import hashlib
import json
import re

from src import config

QUIZ_SCHEMA_HINT = (
    "Reply with STRICT JSON only: {\"questions\": [{\"question\": str, "
    "\"options\": [4 strings], \"key\": <int 0-3>, \"explain\": str, "
    "\"chunk_ref\": \"<chunk id>\"}]}."
)

QUIZ_SYSTEM_PROMPT = (
    "You write practice quiz questions for a student based ONLY on the provided "
    "course material excerpts. Write factual multiple-choice questions "
    "(4 options, exactly one correct). The \"key\" is the index of the correct "
    "option. \"chunk_ref\" must be the chunk id whose text supports the correct "
    "answer, and \"explain\" must quote that support. Do not repeat questions.\n"
    + QUIZ_SCHEMA_HINT
)


def _build_quiz_messages(material_title: str, chunks: list[dict], n: int) -> list[dict]:
    blocks = "\n\n".join(
        f"[{c['chunk_id']}] {c['doc_title']} (slide/page {c['page_no']}):\n{c['text'][:700]}"
        for c in chunks[: max(8, n * 3)]
    )
    user = (
        f"Material: {material_title}\n\nWrite {n} multiple-choice questions "
        f"from this material:\n\n{blocks}\n\n{QUIZ_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


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


def generate_quiz(material_title: str, chunks: list[dict], n: int,
                  topic: str = "", chat_fn=None) -> dict:
    """Generate a quiz from the selected chunks. The key stays server-side."""
    if chat_fn is None:
        from src.embeddings import chat as chat_fn
    raw = chat_fn(_build_quiz_messages(material_title, chunks, n))
    obj = parse_quiz_response(raw)
    chunk_ids = {c["chunk_id"] for c in chunks}
    valid, errors = validate_quiz(obj, n, chunk_ids)
    qs = obj.get("questions", [])
    if not valid:
        raise ValueError(f"quiz failed validation: {errors}")
    keys = [q["key"] for q in qs]
    return {
        "quiz_id": quiz_id(material_title, topic, n),
        "material_title": material_title,
        "topic": topic,
        "n": n,
        "questions": qs,
        "primary_key": keys,
        "key_sha": key_sha(keys),
        "raw": raw,
    }


def to_client_view(quiz: dict) -> dict:
    """Client-safe view: no key, no explanations, no raw."""
    return {
        "quiz_id": quiz["quiz_id"],
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
    """Grade answers against the stored key; reveal explanations server-side."""
    results = []
    correct = 0
    for i, q in enumerate(quiz["questions"]):
        given = answers.get(i)
        right = given == q["key"]
        correct += int(right)
        results.append(
            {
                "id": i,
                "question": q["question"],
                "your_answer": given,
                "correct": right,
                "explanation": q["explain"],
                "chunk_ref": q["chunk_ref"],
            }
        )
    return {
        "score": correct,
        "total": len(quiz["questions"]),
        "correct": [r["id"] for r in results if r["correct"]],
        "details": results,
    }
