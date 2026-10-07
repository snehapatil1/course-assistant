"""Repeatable checks for parsing + chunking (fixture documents, keyless)."""
from __future__ import annotations

from dataclasses import asdict

import pytest

from src.ingest import (_split_long_text, build_chunks, build_page_records,
                        extract_pdf, extract_pptx, sha256_file)


def test_extract_pdf_counts_and_text(pdf_file):
    records = extract_pdf(pdf_file)
    assert len(records) == 2
    assert records[1]["kind"] == "page"
    assert "retrieval augmented" in records[1]["text"].lower()


def test_extract_pptx_counts_and_text(pptx_file):
    records = extract_pptx(pptx_file)
    assert len(records) == 3
    assert all(r["kind"] == "slide" for r in records)
    assert "Quantization" in " ".join(r["text"] for r in records)


def test_build_page_records_metadata(pdf_file):
    h = sha256_file(pdf_file)
    pages = build_page_records(pdf_file, "my_doc", "my_lecture_notes.pdf", h)
    assert len(pages) == 2
    p0 = pages[0]
    assert p0["page_id"] == "my_doc__p0001"
    assert p0["doc_id"] == "my_doc"
    assert p0["doc_title"] == "my_lecture_notes.pdf"
    assert p0["file_hash"] == h
    assert p0["image_path"] == "outputs/pages/my_doc__p0001.png"
    assert p0["kind"] == "page" and p0["page_no"] == 1


def test_unsupported_format_rejected(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    with pytest.raises(ValueError, match="unsupported format"):
        build_page_records(bad, "bad", "notes.txt", "x" * 64)


def test_slides_are_atomic_chunks(pptx_file):
    pages = build_page_records(pptx_file, "deck", "my_deck.pptx", "h" * 64)
    chunks = [asdict(c) for c in build_chunks(pages)]
    assert len(chunks) == 3  # one chunk per slide, no splitting
    assert all(c["kind"] == "slide" for c in chunks)
    assert all(c["chunk_id"].endswith("__c0001") for c in chunks)


def test_long_pdf_page_splits_with_overlap():
    text = ("word " * 3000).strip()
    parts = _split_long_text(text, 1100, 120)
    assert len(parts) > 1
    assert all(len(p) <= 1100 * 1.5 for p in parts)
    joined = "".join(parts)
    assert "word " * 1100 in joined  # nothing dropped, overlap allowed


def test_short_pdf_page_single_chunk(pdf_file):
    pages = build_page_records(pdf_file, "notes", "my_lecture_notes.pdf", "h" * 64)
    chunks = [asdict(c) for c in build_chunks(pages)]
    assert len(chunks) == 2  # both pages short -> one chunk each
    assert all(c["chunk_id"].endswith("__c0001") for c in chunks)
