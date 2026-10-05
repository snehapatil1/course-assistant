"""Repeatable checks for retrieval internals (no API key required)."""
from __future__ import annotations

from src.indexes import bm25_search, load_bm25
from src.retrieve import compute_rrf


def test_rrf_expected_values():
    scores = compute_rrf([["a", "b", "c"], ["b", "c", "d"]], k=60)
    # b is rank 2 in list 1 (1/62) and rank 1 in list 2 (1/61)
    assert abs(scores["b"] - (1 / 62 + 1 / 61)) < 1e-9
    assert scores["a"] == 1 / 61
    assert scores["d"] == 1 / 63
    # b (two lists) must outrank a (one list)
    assert scores["b"] > scores["a"]


def test_rrf_empty_ranking():
    assert compute_rrf([[], []], k=60) == {}


def test_bm25_index_roundtrip():
    index, corpus = load_bm25()
    assert len(corpus) == 192
    assert all("chunk_id" in c and "text" in c for c in corpus[:5])


def test_bm25_semantic_sanity():
    """A textbook-style keyword query must hit the right week's slides."""
    index, corpus = load_bm25()
    hits = bm25_search("What is quantization?", index, corpus, k=3)
    assert hits, "expected at least one hit"
    assert hits[0]["chunk_id"].startswith("week02_llm_fundamentals")
    assert "quantization" in hits[0]["text"].lower()


def test_bm25_gradio_query_targets_week4():
    index, corpus = load_bm25()
    hits = bm25_search("gradio launch share", index, corpus, k=3)
    assert hits[0]["doc"] == "week04_serving_debugging"


def test_candidate_evidence_payload():
    from src.retrieve import Candidate

    c = Candidate(
        chunk_id="x__p0001__c0001", doc="x", doc_title="X", kind="slide",
        page_no=1, text="hello world", image_path="outputs/pages/x__p0001.png",
    )
    ev = c.to_evidence()
    assert ev["page_no"] == 1 and ev["doc"] == "x"
    assert ev["image_path"] == "outputs/pages/x__p0001.png"
    assert ev["excerpt"].startswith("hello world")
