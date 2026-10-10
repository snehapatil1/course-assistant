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


def test_parse_repaired_unclosed_braces():
    # model cut off before the final closing brace
    raw = '{"answer": "x", "sources": [{"doc": "a", "page_no": 1, "excerpt": "e"}'
    obj = qa.parse_json_response(raw)
    assert obj["answer"] == "x"
    assert obj["sources"][0]["doc"] == "a"


def test_parse_repaired_truncated_mid_string():
    # model cut off inside a string value; repair returns a parseable object
    raw = '{"answer": "Based on the provided materials, a **c'
    obj = qa.parse_json_response(raw)
    assert "answer" in obj
    assert obj["answer"] == ""  # truncated value -> empty, caught by schema


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


# --------------------------------------------------------------------------- #
# Strict JSON schema (acceptance criterion 1)
# --------------------------------------------------------------------------- #
def test_validate_rejects_unknown_source_field():
    obj = {"answer": "x", "sources": [{"doc": "doc_a", "page_no": 1,
                                       "excerpt": "Quantization reduces model size",
                                       "made_up_field": 1}]}
    valid, errors = qa.validate_answer(obj, _candidates())
    assert not valid
    assert any("made_up_field" in e or "Extra inputs" in e for e in errors)


def test_validate_rejects_non_integer_page():
    obj = {"answer": "x", "sources": [{"doc": "doc_a", "page_no": "1",
                                       "excerpt": "Quantization reduces model size"}]}
    valid, errors = qa.validate_answer(obj, _candidates())
    assert not valid
    assert any("page_no" in e for e in errors)


def test_validate_rejects_missing_sources_key():
    valid, errors = qa.validate_answer({"answer": "x"}, _candidates())
    assert not valid
    assert any("sources" in e for e in errors)


def test_validate_rejects_empty_excerpt():
    # a source without an actual excerpt is not a source (criterion 2)
    obj = {"answer": "x", "sources": [{"doc": "doc_a", "page_no": 1, "excerpt": ""}]}
    valid, errors = qa.validate_answer(obj, _candidates())
    assert not valid
    assert any("excerpt" in e for e in errors)


def test_validate_requires_sources_for_grounded_answer():
    # grounded answers must cite evidence - never invent without citation
    obj = {"answer": "Quantization reduces precision.", "sources": []}
    valid, errors = qa.validate_answer(obj, _candidates())
    assert not valid
    assert any("cite at least one source" in e for e in errors)


def test_validate_accepts_honest_not_found():
    obj = {"answer": qa.NOT_FOUND_MARKER, "sources": []}
    valid, errors = qa.validate_answer(obj, _candidates())
    assert valid, errors


def test_validate_rejects_not_found_with_sources():
    obj = {"answer": qa.NOT_FOUND_MARKER, "sources": [
        {"doc": "doc_a", "page_no": 1, "excerpt": "Quantization reduces model size"}]}
    valid, errors = qa.validate_answer(obj, _candidates())
    assert not valid


def test_is_not_found_tolerant_variants():
    assert qa.is_not_found("Not found in the provided materials.")
    assert qa.is_not_found(" not found in the PROVIDED materials ")
    assert not qa.is_not_found("Not sure, maybe page 3?")


# --------------------------------------------------------------------------- #
# Temperature control (criterion 5: eval at temperature 0)
# --------------------------------------------------------------------------- #
def _valid_stub_payload(answer="Quantization reduces precision."):
    return json.dumps({"answer": answer, "sources": [
        {"doc": "doc_a", "page_no": 1, "excerpt": "Quantization reduces model size"}]})


def test_answer_question_passes_temperature():
    seen = {}
    def stub_chat(messages, **kwargs):
        seen.update(kwargs)
        return _valid_stub_payload()
    qa.answer_question("What is quantization?", _candidates(), chat_fn=stub_chat,
                       include_images=False, temperature=0.0)
    assert seen.get("temperature") == 0.0


def test_answer_question_default_sends_no_temperature_kwarg():
    # a plain chat_fn without **kwargs must still work (backward compatible)
    def stub_chat(messages):
        return _valid_stub_payload()
    result = qa.answer_question("What is quantization?", _candidates(),
                                chat_fn=stub_chat, include_images=False)
    assert result["valid"] is True


# --------------------------------------------------------------------------- #
# Empty-response fallback ladder (criterion 5)
# --------------------------------------------------------------------------- #
def test_ladder_rescues_with_larger_budget():
    calls = []
    def stub_chat(messages, **kwargs):
        calls.append(kwargs.get("max_tokens"))
        if kwargs.get("max_tokens") == 8192:
            return _valid_stub_payload()
        return ""
    result = qa.answer_question("What is quantization?", _candidates(),
                                chat_fn=stub_chat, include_images=False)
    assert result["valid"] is True
    assert calls == [None, 8192]
    assert result["ladder"] == {"rungs_used": 2, "retried": True,
                                "images_stripped": False}


def test_ladder_vision_rung_gets_headroom_budget(tmp_path):
    # image-bearing prompts send 8192 tokens from rung 1 (fewer truncations)
    from PIL import Image
    cands = _candidates()
    for c in cands:
        img = tmp_path / f"{c.chunk_id}.png"
        Image.new("RGB", (32, 32), "white").save(img)
        c.image_path = str(img)
    seen = []
    def stub_chat(messages, **kwargs):
        seen.append(kwargs.get("max_tokens"))
        return _valid_stub_payload()
    result = qa.answer_question("What is quantization?", cands, chat_fn=stub_chat,
                                include_images=True)
    assert result["valid"] is True
    assert seen == [8192]
    assert result["ladder"]["rungs_used"] == 1 and not result["ladder"]["retried"]


def test_ladder_strips_images_on_final_rung(tmp_path):
    from PIL import Image
    cands = _candidates()
    for c in cands:
        img = tmp_path / f"{c.chunk_id}.png"
        Image.new("RGB", (32, 32), "white").save(img)
        c.image_path = str(img)

    def stub_chat(messages, **kwargs):
        parts = messages[1]["content"]
        has_images = any(
            isinstance(p, dict) and p.get("type") == "image_url" for p in parts
        )
        if kwargs.get("max_tokens") == 8192 and not has_images:
            return _valid_stub_payload()
        return ""
    result = qa.answer_question("What is quantization?", cands, chat_fn=stub_chat,
                                include_images=True)
    assert result["valid"] is True
    assert result["ladder"] == {"rungs_used": 3, "retried": True,
                                "images_stripped": True}
    assert result["images_sent"] == 0  # the successful rung had no images


def test_ladder_exhausted_raises():
    def stub_chat(messages, **kwargs):
        return ""
    import pytest
    with pytest.raises(ValueError):
        qa.answer_question("What is quantization?", _candidates(),
                           chat_fn=stub_chat, include_images=False)


# --------------------------------------------------------------------------- #
# Vision path (criterion 4) + server-side source enrichment (criterion 2)
# --------------------------------------------------------------------------- #
def test_build_messages_attaches_images_when_files_exist(tmp_path):
    from PIL import Image
    cands = _candidates()
    for c in cands:
        img = tmp_path / f"{c.chunk_id}.png"
        Image.new("RGB", (32, 32), "white").save(img)
        c.image_path = str(img)
    messages = qa.build_messages("Q", cands, include_images=True)
    assert qa.count_images(messages) == len(cands)
    assert any("Deck A" in str(m) for m in messages)
    messages_off = qa.build_messages("Q", cands, include_images=False)
    assert qa.count_images(messages_off) == 0


def test_images_sent_recorded_on_plain_success(tmp_path):
    from PIL import Image
    cands = _candidates()
    for c in cands:
        img = tmp_path / f"{c.chunk_id}.png"
        Image.new("RGB", (32, 32), "white").save(img)
        c.image_path = str(img)
    def stub_chat(messages, **kwargs):
        return _valid_stub_payload()
    result = qa.answer_question("What is quantization?", cands, chat_fn=stub_chat,
                                include_images=True)
    assert result["valid"] is True
    assert result["images_sent"] == len(cands)
    assert result["ladder"]["rungs_used"] == 1


def test_answer_question_enriches_sources_from_evidence():
    def stub_chat(messages):
        return _valid_stub_payload()
    result = qa.answer_question("What is quantization?", _candidates(),
                                chat_fn=stub_chat, include_images=False)
    src = result["sources"][0]
    assert src["doc"] == "doc_a" and src["page_no"] == 1
    assert src["doc_title"] == "Deck A"
    assert src["kind"] == "slide"
    assert src["image_path"] == "outputs/pages/doc_a__p0001.png"
    assert src["chunk_id"].startswith("doc_a")
