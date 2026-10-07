"""Repeatable checks for the quiz engine (fixed key, hidden solutions, grading)."""
from __future__ import annotations

import json

from src import quiz

GOOD_RESPONSE = json.dumps({
    "questions": [
        {
            "question": "What does quantization reduce?",
            "options": ["Model size", "Context length", "Token cost", "Latency"],
            "key": 0,
            "explain": "Quantization reduces model size (slide 15).",
            "chunk_ref": "deck__p0015__c0001",
        },
        {
            "question": "Which pair powers RAG?",
            "options": ["Retrieval + generation", "Fine-tuning only", "RLHF only", "Inference only"],
            "key": 0,
            "explain": "RAG combines retrieval with generation.",
            "chunk_ref": "notes__p0002__c0001",
        },
    ]
})

CHUNKS = [
    {"chunk_id": "deck__p0015__c0001", "doc_title": "Deck", "page_no": 15,
     "text": "Quantization reduces model size."},
    {"chunk_id": "notes__p0002__c0001", "doc_title": "Notes", "page_no": 2,
     "text": "RAG combines retrieval with generation."},
]


def test_parse_quiz_response():
    q = quiz.parse_quiz_response(GOOD_RESPONSE)
    assert len(q["questions"]) == 2


def test_validate_quiz_ok():
    valid, errors = quiz.validate_quiz(quiz.parse_quiz_response(GOOD_RESPONSE), 2, {c["chunk_id"] for c in CHUNKS})
    assert valid, errors


def test_validate_quiz_catches_bad_key():
    bad = quiz.parse_quiz_response(GOOD_RESPONSE)
    bad["questions"][0]["key"] = 9
    valid, errors = quiz.validate_quiz(bad, 2, {c["chunk_id"] for c in CHUNKS})
    assert not valid
    assert any("key" in e for e in errors)


def test_validate_quiz_catches_unknown_chunk_ref():
    bad = quiz.parse_quiz_response(GOOD_RESPONSE)
    bad["questions"][0]["chunk_ref"] = "ghost__c0001"
    valid, errors = quiz.validate_quiz(bad, 2, {c["chunk_id"] for c in CHUNKS})
    assert not valid


def test_key_sha_stable():
    assert quiz.key_sha([0, 1, 2]) == quiz.key_sha([0, 1, 2])
    assert quiz.key_sha([0, 1, 2]) != quiz.key_sha([0, 1, 3])


def test_generate_quiz_stub_chat():
    q = quiz.generate_quiz("Deck", CHUNKS, 2, chat_fn=lambda msgs: GOOD_RESPONSE)
    assert q["primary_key"] == [0, 0]
    assert q["n"] == 2
    assert q["key_sha"] == quiz.key_sha([0, 0])
    assert q["quiz_id"] == quiz.quiz_id("Deck", "", 2)


def test_client_view_hides_solutions():
    q = quiz.generate_quiz("Deck", CHUNKS, 2, chat_fn=lambda msgs: GOOD_RESPONSE)
    view = quiz.to_client_view(q)
    assert "primary_key" not in view
    assert "raw" not in view
    assert all("explain" not in qv and "chunk_ref" not in qv and "key" not in qv
               for qv in view["questions"])


def test_grading_against_stored_key():
    q = quiz.generate_quiz("Deck", CHUNKS, 2, chat_fn=lambda msgs: GOOD_RESPONSE)
    result = quiz.grade(q, {0: 0, 1: 1})  # Q1 right, Q2 wrong
    assert result["score"] == 1 and result["total"] == 2
    assert result["correct"] == [0]
    detail = result["details"][1]
    assert detail["correct"] is False
    assert detail["explanation"]  # explanation revealed only with the grade
