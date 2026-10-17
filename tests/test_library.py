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


def test_clean_library_starts_empty_and_creates_state_files(pdf_file, tmp_path):
    """A fresh clone (no manifest/chunks committed) must start empty and
    create its state files normally on first add."""
    lib_dir, out = _dirs(tmp_path)
    # no generated-library state exists yet
    assert not (out / "manifest.json").exists()
    assert not (out / "chunks.json").exists()
    assert library.list_documents(out) == []

    # adding a document creates manifest.json + chunks.json automatically
    r = library.add_document(pdf_file, lib_dir, out, render=False)
    assert r["status"] == "added"
    assert (out / "manifest.json").is_file()
    assert (out / "chunks.json").is_file()
    assert len(_manifest(out)) == 2
    assert len(library.list_documents(out)) == 1


def test_list_documents_metadata(pdf_file, pptx_file, tmp_path):
    lib_dir, out = _dirs(tmp_path)
    library.add_document(pdf_file, lib_dir, out, render=False)
    library.add_document(pptx_file, lib_dir, out, render=False)
    docs = library.list_documents(out)
    assert len(docs) == 2
    assert {d["kind"] for d in docs} == {"page", "slide"}
    assert all(d["units"] >= 1 for d in docs)


# --- Targeted removal: never blocks on manifest/index drift -------------------

def test_remove_succeeds_with_orphan_index_records(tmp_path, monkeypatch):
    """The historical guard blocked removal when the BM25 corpus contained
    doc_ids absent from the manifest (git-tracked manifests drifted from the
    runtime library). Removal must purge only the target and PRESERVE the
    unrelated index records."""
    import json

    from src.indexes import build_bm25

    out = tmp_path / "outputs"
    lib = tmp_path / "library"
    (out / "indexes" / "bm25").mkdir(parents=True)
    (out / "pages").mkdir()
    lib.mkdir()
    manifest = [
        {"doc_id": "doc_a__11111111", "doc_title": "A",
         "page_id": "doc_a__11111111__p0001", "page_no": 1,
         "stored_file": "doc_a__11111111.pdf", "kind": "page"},
    ]
    (out / "manifest.json").write_text(json.dumps(manifest))
    (lib / "doc_a__11111111.pdf").write_bytes(b"%PDF-fake")
    corpus = [
        # orphan: indexed but NOT in the manifest - must survive removal of A
        {"doc": "doc_b__22222222", "doc_title": "B", "page_no": 2,
         "kind": "slide", "chunk_id": "b1", "text": "orphan chunk"},
        {"doc": "doc_a__11111111", "doc_title": "A", "page_no": 1,
         "kind": "page", "chunk_id": "a1", "text": "a chunk"},
    ]
    (out / "indexes" / "bm25" / "corpus_meta.json").write_text(json.dumps(corpus))
    build_bm25(corpus, out_dir=out / "indexes" / "bm25")
    (out / "chunks.json").write_text(json.dumps(corpus))

    from src import library
    monkeypatch.setattr(library.config, "require_endpoint",
                        lambda kind: (_ for _ in ()).throw(RuntimeError("off")))

    result = library.remove_document("doc_a__11111111",
                                     library_dir=lib, out_dir=out)
    assert result["status"] == "removed"
    assert not (lib / "doc_a__11111111.pdf").exists()
    assert json.loads((out / "manifest.json").read_text()) == []
    from src.indexes import load_bm25
    meta = json.loads((out / "indexes" / "bm25" / "corpus_meta.json").read_text())
    assert [c["doc"] for c in meta] == ["doc_b__22222222"], \
        "unrelated index records must survive a targeted removal"
    chunks = json.loads((out / "chunks.json").read_text())
    assert [c["doc"] for c in chunks] == ["doc_b__22222222"]
