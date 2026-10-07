"""Repeatable checks for grounded Q&A (schema parse, support validation)."""
from __future__ import annotations

import json

from src import qa
from src.retrieve import Candidate


def _candidates() -> list[Candidate]:
    return [
        Candidate(
            chunk_id="doc_a__p0001__c0001", doc="doc_a", doc_title="Deck A",
            kind="slide", page_no=1,
            text="Quantization reduces model size from 16-bit to 4-bit precision.",
            image_path="outputs/pages/doc_a__p0001.png",
        ),
        Candidate(
            chunk_id="doc_b__p0002__c0001", doc="doc_b", doc_title="Notes B",
            kind="page", page_no=2,
            text="RAG combines retrieval with generation for grounded answers.",
            image_path="outputs/pages/doc_b__p0002.png",
        ),
    ]


def test_parse_json_plain_and_fenced():
    obj = qa.parse_json_response('{"answer": "x", "sources": []}')
    assert obj["answer"] == "x"
    fenced = qa.parse_json_response('```json\n{"answer": "y", "sources": []}\n```')
    assert fenced["answer"] == "y"


def test_parse_json_rejects_non_json():
    import pytest

    with pytest.raises(ValueError):
        qa.parse_json_response("sorry, no json here")


def test_validate_accepts_supported_source():
    obj = {
        "answer": "Quantization reduces precision.",
        "sources": [{"doc": "doc_a", "page_no": 1, "excerpt": "Quantization reduces model size"}],
    }
    valid, errors = qa.validate_answer(obj, _candidates())
    assert valid, errors


def test_validate_rejects_fabricated_source():
    obj = {
        "answer": "Quantum computing is covered on slide 42.",
        "sources": [{"doc": "doc_z", "page_no": 42, "excerpt": "quantum entanglement speeds up"}],
    }
    valid, errors = qa.validate_answer(obj, _candidates())
    assert not valid
    assert any("not in evidence" in e or "fabricated" in e for e in errors)


def test_validate_rejects_fabricated_excerpt_on_real_doc():
    obj = {
        "answer": "x",
        "sources": [{"doc": "doc_a", "page_no": 1, "excerpt": "totally unrelated invented phrase"}],
    }
    valid, errors = qa.validate_answer(obj, _candidates())
    assert not valid


def test_answer_question_with_stub_chat():
    def stub_chat(messages):
        assert any("Quantization" in str(m) for m in messages)
        return json.dumps({
            "answer": "Quantization reduces precision.",
            "sources": [{"doc": "doc_a", "page_no": 1,
                         "excerpt": "Quantization reduces model size"}],
        })

    result = qa.answer_question("What is quantization?", _candidates(), chat_fn=stub_chat,
                                include_images=False)
    assert result["answer"].startswith("Quantization")
    assert result["valid"] is True, result["validation_errors"]
    assert result["sources"][0]["doc"] == "doc_a"


def test_missing_info_is_honest():
    def stub_chat(messages):
        return json.dumps({"answer": "Not found in the provided materials.", "sources": []})

    result = qa.answer_question("What is LoRA?", _candidates(), chat_fn=stub_chat,
                                include_images=False)
    assert "Not found" in result["answer"]
    assert result["valid"] is True
