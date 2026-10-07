"""Repeatable checks for retrieval internals (RRF, candidates, keyless mode)."""
from __future__ import annotations

from src.config import PROJECT_ROOT
from src.retrieve import Candidate, compute_rrf, endpoint_ready, retrieve


def test_rrf_expected_values():
    scores = compute_rrf([["a", "b", "c"], ["b", "c", "d"]], k=60)
    # b is rank 2 in list 1 (1/62) and rank 1 in list 2 (1/61)
    assert abs(scores["b"] - (1 / 62 + 1 / 61)) < 1e-9
    assert scores["a"] == 1 / 61
    assert scores["d"] == 1 / 63
    assert scores["b"] > scores["a"]


def test_rrf_empty_ranking():
    assert compute_rrf([[], []], k=60) == {}


def test_candidate_evidence_payload():
    c = Candidate(
        chunk_id="x__p0001__c0001", doc="x", doc_title="X", kind="slide",
        page_no=1, text="hello world", image_path="outputs/pages/x__p0001.png",
    )
    ev = c.to_evidence()
    assert ev["page_no"] == 1 and ev["doc"] == "x"
    assert ev["image_path"] == "outputs/pages/x__p0001.png"
    assert ev["excerpt"].startswith("hello world")


def test_endpoint_ready_false_without_key():
    # no .env on fresh clones: every endpoint must report "not ready"
    for kind in ("chat", "text_embed", "visual_embed", "rerank"):
        assert endpoint_ready(kind) is False


def test_retrieve_keyword_only_and_filtering(pdf_file, pptx_file, tmp_path):
    """With endpoints unconfigured, retrieval degrades to keyword search and
    still returns structured evidence with the correct document/slide info."""
    from src import library

    lib_dir, out = tmp_path / "library", tmp_path / "out"
    pdf_add = library.add_document(pdf_file, lib_dir, out, render=False)
    pptx_add = library.add_document(pptx_file, lib_dir, out, render=False)

    bm25_dir = out / "indexes" / "bm25"

    hits = retrieve("Quantization", bm25_dir=bm25_dir)
    assert hits
    assert hits[0].doc == pptx_add["doc_id"]
    assert hits[0].kind == "slide"

    # material filter: restrict to the pdf doc
    hits = retrieve("Quantization", docs=[pdf_add["doc_id"]], bm25_dir=bm25_dir)
    assert hits == []

    hits = retrieve("retrieval augmented generation", docs=[pdf_add["doc_id"]],
                    bm25_dir=bm25_dir)
    assert hits and hits[0].doc == pdf_add["doc_id"]


def test_retrieve_no_match_returns_empty(pdf_file, tmp_path):
    from src import library

    lib_dir, out = tmp_path / "library", tmp_path / "out"
    library.add_document(pdf_file, lib_dir, out, render=False)
    hits = retrieve("zzzz nonexistent term qqqq", bm25_dir=out / "indexes" / "bm25")
    assert hits == []
