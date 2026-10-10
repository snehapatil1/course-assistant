"""Repeatable checks for the quiz engine (fixed key, hidden solutions, grading)."""
from __future__ import annotations

import json

import pytest

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


def test_generate_quiz_resolves_block_labels():
    """Model-referenced block numbers must map back to canonical chunk ids."""
    response = json.dumps({
        "questions": [
            {"question": "Q1?", "options": ["a", "b", "c", "d"], "key": 0,
             "explain": "see block 1", "chunk_ref": "1"},
            {"question": "Q2?", "options": ["a", "b", "c", "d"], "key": 2,
             "explain": "see block 2", "chunk_ref": "2"},
        ]
    })
    q = quiz.generate_quiz("Deck", CHUNKS, 2, chat_fn=lambda msgs: response)
    refs = [q["questions"][i]["chunk_ref"] for i in range(2)]
    assert refs == ["deck__p0015__c0001", "notes__p0002__c0001"]


def test_generate_quiz_resolves_unique_prefix():
    """A truncated chunk id that is a unique prefix must still resolve."""
    response = json.dumps({
        "questions": [
            {"question": "Q1?", "options": ["a", "b", "c", "d"], "key": 0,
             "explain": "x", "chunk_ref": "deck__p0015"},
        ]
    })
    q = quiz.generate_quiz("Deck", CHUNKS, 1, chat_fn=lambda msgs: response)
    assert q["questions"][0]["chunk_ref"] == "deck__p0015__c0001"


def test_generate_quiz_retries_once_on_bad_refs():
    """Invalid chunk_ref on the first pass must trigger one regeneration."""
    calls = {"n": 0}

    def flaky_chat(msgs):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({
                "questions": [
                    {"question": "Q1?", "options": ["a", "b", "c", "d"], "key": 0,
                     "explain": "x", "chunk_ref": "ghost_ref_xyz"},
                ]
            })
        return GOOD_RESPONSE  # valid on the retry

    q = quiz.generate_quiz("Deck", CHUNKS, 2, chat_fn=flaky_chat)
    assert calls["n"] == 2
    assert all(x["chunk_ref"] in {c["chunk_id"] for c in CHUNKS}
               for x in q["questions"])


def test_generate_quiz_fails_honestly_after_retry():
    calls = {"n": 0}

    def always_bad(msgs):
        calls["n"] += 1
        return json.dumps({
            "questions": [
                {"question": "Q1?", "options": ["a", "b", "c", "d"], "key": 0,
                 "explain": "x", "chunk_ref": "ghost_ref_xyz"},
            ]
        })

    with pytest.raises(ValueError, match="failed validation after retry"):
        quiz.generate_quiz("Deck", CHUNKS, 1, chat_fn=always_bad)
    assert calls["n"] == 2


def test_grading_against_stored_key():
    q = quiz.generate_quiz("Deck", CHUNKS, 2, chat_fn=lambda msgs: GOOD_RESPONSE)
    result = quiz.grade(q, {0: 0, 1: 1})  # Q1 right, Q2 wrong
    assert result["score"] == 1 and result["total"] == 2
    assert result["correct"] == [0]
    detail = result["details"][1]
    assert detail["correct"] is False
    assert detail["explanation"]  # explanation revealed only with the grade


# --- Topic-aware chunk ranking (issue: material selected + topic given, but
# questions came from unrelated first-in-page-order chunks) -----------------

TOPIC_CHUNKS = [
    {"chunk_id": "w5__p0001__c0001", "doc_title": "Week 5", "page_no": 1,
     "text": "Retrieval-augmented generation combines a retriever with a generator."},
    {"chunk_id": "w5__p0002__c0001", "doc_title": "Week 5", "page_no": 2,
     "text": "Least-to-most prompting (LITM) decomposes a hard task into steps."},
    {"chunk_id": "w5__p0003__c0001", "doc_title": "Week 5", "page_no": 3,
     "text": "Quantization converts weights to lower precision to shrink the model."},
    {"chunk_id": "w5__p0004__c0001", "doc_title": "Week 5", "page_no": 4,
     "text": "Context windows bound how many tokens a model can attend to."},
]


def test_select_topic_chunks_ranks_mentions_first():
    top, hits = quiz.select_topic_chunks(TOPIC_CHUNKS, "quantization", k=2)
    assert hits is True
    assert top[0]["chunk_id"] == "w5__p0003__c0001"
    assert "quantization" in top[0]["text"].lower()


def test_select_topic_chunks_phrase_bonus():
    top, _ = quiz.select_topic_chunks(TOPIC_CHUNKS, "context windows", k=1)
    assert top[0]["chunk_id"] == "w5__p0004__c0001"


def test_select_topic_chunks_no_hits_reports_false():
    top, hits = quiz.select_topic_chunks(TOPIC_CHUNKS, "matrices", k=3)
    assert hits is False
    assert len(top) == 3


def test_select_topic_chunks_empty_topic_keeps_order():
    top, hits = quiz.select_topic_chunks(TOPIC_CHUNKS, "", k=10)
    assert hits is True
    assert [c["chunk_id"] for c in top] == [c["chunk_id"] for c in TOPIC_CHUNKS]


def test_build_quiz_messages_includes_focus_topic():
    msgs = quiz._build_quiz_messages("Week 5", TOPIC_CHUNKS, 2, topic="quantization")
    user = msgs[-1]["content"]
    assert "Topic: quantization" in user
    assert "MUST concern this topic" in user
