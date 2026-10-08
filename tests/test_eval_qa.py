"""Hermetic tests for the grounded-QA evaluation harness (no endpoints)."""
from __future__ import annotations

import json

import pytest
from PIL import Image

from src import eval_qa, qa
from src.retrieve import Candidate

Q1 = "What is quantization?"
Q2 = "What is the capital of France?"


def _candidates(tmp_path) -> list[Candidate]:
    """Two evidence items with REAL page screenshots on disk."""
    pairs = [
        ("doc_a", 1, "slide",
         "Quantization reduces model size from 16-bit to 4-bit precision."),
        ("doc_b", 2, "page",
         "RAG combines retrieval with generation for grounded answers."),
    ]
    out = []
    for doc, page, kind, text in pairs:
        img = tmp_path / f"{doc}_p{page:04d}.png"
        Image.new("RGB", (32, 32), "white").save(img)
        out.append(Candidate(
            chunk_id=f"{doc}__p{page:04d}__c0001", doc=doc, doc_title=f"Title {doc}",
            kind=kind, page_no=page, text=text, image_path=str(img)))
    return out


def _valid_payload():
    return json.dumps({"answer": "Quantization reduces precision.", "sources": [
        {"doc": "doc_a", "page_no": 1, "excerpt": "Quantization reduces model size"}]})


@pytest.fixture
def retrieve_all(tmp_path):
    def _fn(query, use_rerank=True):
        return _candidates(tmp_path)
    return _fn


def test_run_eval_writes_results_file(tmp_path, retrieve_all):
    out = tmp_path / "eval.json"
    payload = eval_qa.run_eval(
        questions=[Q1, Q2], retrieve_fn=retrieve_all,
        chat_fn=lambda messages, **kw: _valid_payload(), out_path=out)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["n_questions"] == 2
    assert data["summary"]["schema_valid"] == 2
    assert all(r["valid"] for r in data["results"])
    assert all(r["conducted"] for r in data["results"])
    # every source audited: doc + page + non-empty excerpt + pinned + screenshot
    for r in data["results"]:
        assert r["sources"], r
        s = r["sources"][0]
        assert s["doc"] and s["page_no"] == 1
        assert s["excerpt_nonempty"] is True
        assert s["pinned_to_evidence"] is True
        assert s["page_screenshot_available"] is True
        assert s["excerpt_overlaps_evidence"] is True
    assert payload["temperature"] == 0.0


def test_run_eval_honest_refusal_out_of_materials(tmp_path, retrieve_all):
    def chat(messages, **kw):
        return json.dumps({"answer": qa.NOT_FOUND_MARKER, "sources": []})
    payload = eval_qa.run_eval(questions=[Q2], retrieve_fn=retrieve_all,
                               chat_fn=chat, out_path=tmp_path / "e.json")
    r = payload["results"][0]
    assert r["valid"] is True
    assert qa.is_not_found(r["answer"])
    assert payload["summary"]["honest_refusals"] == 1
    assert payload["summary"]["with_sources"] == 0


def test_run_eval_no_candidates_is_conducted_false(tmp_path):
    payload = eval_qa.run_eval(
        questions=[Q1],
        retrieve_fn=lambda query, use_rerank=True: [],
        chat_fn=None, out_path=tmp_path / "e.json")
    r = payload["results"][0]
    assert r["conducted"] is False
    assert "no candidates" in r["reason"]
    assert payload["summary"]["not_conducted"] == 1


def test_run_eval_ladder_exhausted_recorded_not_fatal(tmp_path, retrieve_all):
    def chat(messages, **kw):
        return ""
    payload = eval_qa.run_eval(questions=[Q1], retrieve_fn=retrieve_all,
                               chat_fn=chat, out_path=tmp_path / "e.json")
    r = payload["results"][0]
    assert r["conducted"] is True
    assert r["valid"] is False
    assert any("ladder exhausted" in e for e in r["validation_errors"])
    assert payload["summary"]["ladder_exhausted"] == 1
    assert payload["summary"]["schema_valid"] == 0


def test_run_eval_vision_sends_images(tmp_path, retrieve_all):
    seen = {}
    def chat(messages, **kw):
        parts = messages[1]["content"]
        seen["images"] = sum(1 for p in parts
                             if isinstance(p, dict) and p.get("type") == "image_url")
        return _valid_payload()
    payload = eval_qa.run_eval(questions=[Q1], retrieve_fn=retrieve_all,
                               chat_fn=chat, include_images=True,
                               out_path=tmp_path / "e.json")
    assert seen["images"] == 2  # both candidates carry a real page screenshot
    assert payload["summary"]["vision_path_used"] == 1
    assert payload["results"][0]["images_sent"] == 2


def test_run_eval_no_vision_sends_no_images(tmp_path, retrieve_all):
    seen = {}
    def chat(messages, **kw):
        parts = messages[1]["content"]
        seen["images"] = sum(1 for p in parts
                             if isinstance(p, dict) and p.get("type") == "image_url")
        return _valid_payload()
    payload = eval_qa.run_eval(questions=[Q1], retrieve_fn=retrieve_all,
                               chat_fn=chat, include_images=False,
                               out_path=tmp_path / "e.json")
    assert seen["images"] == 0
    assert payload["summary"]["vision_path_used"] == 0


def test_run_eval_retrieval_error_recorded(tmp_path):
    def broken(query, use_rerank=True):
        raise RuntimeError("index exploded")
    payload = eval_qa.run_eval(questions=[Q1], retrieve_fn=broken, chat_fn=None,
                               out_path=tmp_path / "e.json")
    r = payload["results"][0]
    assert r["conducted"] is False
    assert "retrieval error" in r["reason"]


def test_run_eval_defaults_and_latest_copy(tmp_path, retrieve_all):
    payload = eval_qa.run_eval(questions=[Q1], retrieve_fn=retrieve_all,
                               chat_fn=lambda messages, **kw: _valid_payload(),
                               out_path=tmp_path / "custom.json")
    latest = tmp_path / eval_qa.LATEST_NAME
    assert (tmp_path / "custom.json").exists()
    assert latest.exists()
    assert json.loads(latest.read_text(encoding="utf-8"))["summary"]["n_questions"] == 1
    assert payload["task"].startswith("4-grounded-qa")


def test_main_guard_offline(capsys):
    # CLI refuses to run when the chat endpoint is not configured
    import src.eval_qa as m
    rc = m.main(["--questions", Q1])
    assert rc == 2
    assert "not configured" in capsys.readouterr().err


def test_main_list_defaults(capsys):
    import src.eval_qa as m
    assert m.main(["--list-defaults"]) == 0
    out = capsys.readouterr().out
    assert "What is quantization?" in out
    assert "capital of France" in out
