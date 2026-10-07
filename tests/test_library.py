"""Repeatable checks for the app-managed library (add/dedupe/remove/purge).

All tests run against temporary library + output directories with synthetic
documents - no course files, no endpoints required.
"""
from __future__ import annotations

import json

from src import library
from src.indexes import bm25_search, load_bm25


def _dirs(tmp_path):
    return tmp_path / "library", tmp_path / "out"


def _manifest(out):
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def test_add_pdf(pdf_file, tmp_path):
    lib_dir, out = _dirs(tmp_path)
    r = library.add_document(pdf_file, lib_dir, out, render=False)
    assert r["status"] == "added"
    assert r["units"] == 2
    assert len(_manifest(out)) == 2
    chunks = json.loads((out / "chunks.json").read_text(encoding="utf-8"))
    assert len(chunks) == 2
    assert len(list(lib_dir.iterdir())) == 1


def test_add_pptx(pptx_file, tmp_path):
    lib_dir, out = _dirs(tmp_path)
    r = library.add_document(pptx_file, lib_dir, out, render=False)
    assert r["status"] == "added"
    assert r["units"] == 3
    assert all(p["kind"] == "slide" for p in _manifest(out))


def test_same_file_twice_is_a_noop(pdf_file, tmp_path):
    lib_dir, out = _dirs(tmp_path)
    r1 = library.add_document(pdf_file, lib_dir, out, render=False)
    r2 = library.add_document(pdf_file, lib_dir, out, render=False)
    assert r1["status"] == "added" and r2["status"] == "duplicate"
    assert len(_manifest(out)) == 2  # unchanged
    assert len(list(lib_dir.iterdir())) == 1  # one stored copy


def test_remove_purges_everything(pdf_file, pptx_file, tmp_path):
    lib_dir, out = _dirs(tmp_path)
    a = library.add_document(pdf_file, lib_dir, out, render=False)
    b = library.add_document(pptx_file, lib_dir, out, render=False)

    r = library.remove_document(a["doc_id"], lib_dir, out)
    assert r["status"] == "removed"
    assert r["removed_units"] == 2

    remaining = _manifest(out)
    assert all(p["doc_id"] != a["doc_id"] for p in remaining)
    assert len(remaining) == 3  # only the pptx slides remain

    chunks = json.loads((out / "chunks.json").read_text(encoding="utf-8"))
    assert all(c["doc"] != a["doc_id"] for c in chunks)

    assert len(list(lib_dir.iterdir())) == 1  # only the pptx file remains

    docs = library.list_documents(out)
    assert [d["doc_id"] for d in docs] == [b["doc_id"]]


def test_remove_missing_document(tmp_path):
    lib_dir, out = _dirs(tmp_path)
    r = library.remove_document("no_such_doc", lib_dir, out)
    assert r["status"] == "not_found"


def test_bm25_follows_the_library(pdf_file, pptx_file, tmp_path):
    """Keyword search must reflect add AND remove: dropped docs leave no hits."""
    lib_dir, out = _dirs(tmp_path)
    pdf_add = library.add_document(pdf_file, lib_dir, out, render=False)
    pptx_add = library.add_document(pptx_file, lib_dir, out, render=False)

    index, corpus = load_bm25(out / "indexes" / "bm25")
    hits = bm25_search("Quantization", index, corpus, k=3)
    assert hits and hits[0]["doc"] == pptx_add["doc_id"]

    library.remove_document(pptx_add["doc_id"], lib_dir, out)
    index, corpus = load_bm25(out / "indexes" / "bm25")
    hits = bm25_search("Quantization", index, corpus, k=3)
    assert hits == []  # removed content is no longer searchable


def test_bm25_text_queries(pdf_file, tmp_path):
    lib_dir, out = _dirs(tmp_path)
    add = library.add_document(pdf_file, lib_dir, out, render=False)
    index, corpus = load_bm25(out / "indexes" / "bm25")
    hits = bm25_search("retrieval augmented generation", index, corpus, k=3)
    assert hits and hits[0]["doc"] == add["doc_id"]


def test_list_documents_metadata(pdf_file, pptx_file, tmp_path):
    lib_dir, out = _dirs(tmp_path)
    library.add_document(pdf_file, lib_dir, out, render=False)
    library.add_document(pptx_file, lib_dir, out, render=False)
    docs = library.list_documents(out)
    assert len(docs) == 2
    assert {d["kind"] for d in docs} == {"page", "slide"}
    assert all(d["units"] >= 1 for d in docs)
