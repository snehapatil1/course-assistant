"""Repeatable checks for the ingestion pipeline (no API key required).

Run with:  .venv/bin/python -m pytest
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingest import _split_long_text, build_chunks

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_DOCS = {
    "hermes_configuration_guide",
    "hermes_installation_guide",
    "quiz1",
    "quiz1_answer_key",
    "syllabus",
    "week02_llm_fundamentals",
    "week03_prompt_engineering",
    "week04_serving_debugging",
    "week05_context_rag",
    "week06_multimodal",
}


@pytest.fixture(scope="module")
def manifest() -> list[dict]:
    return json.loads((PROJECT_ROOT / "outputs" / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def chunks() -> list[dict]:
    return json.loads((PROJECT_ROOT / "outputs" / "chunks.json").read_text(encoding="utf-8"))


def test_manifest_covers_all_materials(manifest):
    docs = {p["doc"] for p in manifest}
    assert docs == EXPECTED_DOCS, f"missing/extra docs: {docs ^ EXPECTED_DOCS}"


def test_every_unit_has_metadata(manifest):
    for p in manifest:
        assert p["page_id"]
        assert p["kind"] in ("slide", "page")
        assert isinstance(p["page_no"], int) and p["page_no"] >= 1
        assert p["doc"] and p["source_file"]
        assert p["image_path"].endswith(".png")


def test_page_ids_unique(manifest):
    ids = [p["page_id"] for p in manifest]
    assert len(ids) == len(set(ids))


def test_slides_have_reasonable_text(manifest):
    slides = [p for p in manifest if p["kind"] == "slide"]
    assert len(slides) >= 100
    # title/slide 1 of week 2 should carry the course name
    w2 = next(p for p in manifest if p["doc"] == "week02_llm_fundamentals" and p["page_no"] == 1)
    assert "MBAX 6418" in w2["text"] or "LLM Fundamentals" in w2["text"]


def test_chunks_have_all_fields(chunks):
    for c in chunks:
        assert c["chunk_id"]
        assert c["text"].strip()
        assert c["doc"] in EXPECTED_DOCS
        assert isinstance(c["page_no"], int)
        assert c["image_path"].endswith(".png")


def test_chunk_ids_unique(chunks):
    ids = [c["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))


def test_slide_is_one_atomic_chunk(chunks, manifest):
    slide_pages = {p["page_id"] for p in manifest if p["kind"] == "slide"}
    for c in chunks:
        if c["kind"] == "slide":
            assert c["chunk_of"] in slide_pages
    slide_chunk_pages = {c["chunk_of"] for c in chunks if c["kind"] == "slide"}
    assert len(slide_chunk_pages) <= len(slide_pages)


def test_long_pdf_page_split_preserves_text(chunks):
    # syllabus page 5 is the longest page; its chunks must jointly cover it
    syllabus_chunks = sorted(
        (c for c in chunks if c["doc"] == "syllabus" and c["page_no"] == 5),
        key=lambda c: c["chunk_id"],
    )
    assert len(syllabus_chunks) > 1, "expect the long syllabus page to be split"
    joined = "".join(c["text"] for c in syllabus_chunks)
    # overlap may duplicate a little text, but nothing may be lost entirely
    assert len(joined) >= 2000


def test_split_long_text_basics():
    text = "word " * 2000
    parts = _split_long_text(text, 1100, 120)
    assert len(parts) > 1
    assert all(len(p) <= 1100 * 1.5 for p in parts)
    assert "".join(parts).replace("word " * 120, "")  # overlap present, not destructive


def test_quiz1_answer_key_ground_truth(manifest):
    key_text = "\n".join(
        p["text"].lower()
        for p in manifest
        if p["doc"] == "quiz1_answer_key"
        if (p["text"] or "").strip()
    )
    for needle in ("quantization", "few-shot", "embeddings"):
        assert needle in key_text, f"missing {needle!r} in answer key"


def test_empty_text_unit_is_intentional(manifest):
    empties = [p for p in manifest if not (p["text"] or p["notes"]).strip()]
    # exactly one: an image-only page of the Hermes configuration guide
    assert [p["page_id"] for p in empties] == ["hermes_configuration_guide__p0009"]
