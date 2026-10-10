"""Regression tests for `build_vector_indexes` (fresh-machine path).

Guards the multi-batch dimension bug: when the corpus spans several
embedding batches, the collection must be created with the REAL embedder
dimension (2048 for the class model), not Chroma's built-in 384 - the old
code upserted only the last batch's vectors and silently fell back to 384,
breaking every later vector query on a fresh machine.
"""
from __future__ import annotations

from PIL import Image

from src import indexes


def _chunks(n: int = 100, doc: str = "doc_a") -> list[dict]:
    return [
        {"chunk_id": f"{doc}__p{i + 1:04d}__c0001", "doc": doc,
         "doc_title": f"Deck {doc}", "kind": "slide", "page_no": i + 1,
         "text": f"Evidence chunk number {i} about retrieval.",
         "image_path": f"outputs/pages/{doc}__p{i + 1:04d}.png"}
        for i in range(n)
    ]


def _pages(doc: str = "doc_a", n: int = 3) -> list[dict]:
    return [
        {"page_id": f"{doc}__p{i + 1:04d}", "doc_id": doc,
         "image_path": f"outputs/pages/{doc}__p{i + 1:04d}.png"}
        for i in range(n)
    ]


def _zero_embedder(dim: int):
    import numpy as np

    def _embed(texts):
        return np.zeros((len(texts), dim), dtype=np.float32)

    return _embed


def test_multibatch_corpus_keeps_real_dimension(tmp_path, monkeypatch):
    # 100 chunks > text_batch_size 64 -> must NOT fall back to 384-dim
    monkeypatch.setattr(indexes, "CHROMA_DIR", tmp_path / "chroma")
    chunks = _chunks(100)
    counts = indexes.build_vector_indexes(chunks, [], _zero_embedder(2048),
                                          None, text_batch_size=64)
    assert counts == {"text_vectors": 100, "visual_vectors": 0}
    col = indexes.get_text_collection(indexes.get_chroma())
    got = col.get(include=["embeddings"])
    assert len(got["ids"]) == 100
    assert len(got["embeddings"][0]) == 2048


def test_single_batch_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(indexes, "CHROMA_DIR", tmp_path / "chroma")
    chunks = _chunks(10)
    counts = indexes.build_vector_indexes(chunks, [], _zero_embedder(12))
    assert counts["text_vectors"] == 10
    col = indexes.get_text_collection(indexes.get_chroma())
    got = col.get(include=["embeddings"])
    assert len(got["embeddings"][0]) == 12


def test_visual_leg_uses_existing_images_only(tmp_path, monkeypatch):
    monkeypatch.setattr(indexes, "CHROMA_DIR", tmp_path / "chroma")
    pages = _pages()
    for p in pages[:2]:  # only 2 of 3 images actually exist
        img = tmp_path / p["image_path"].split("/")[-1]
        Image.new("RGB", (16, 16), "white").save(img)
        p["image_path"] = str(img)  # absolute path (overrides PROJECT_ROOT join)
    counts = indexes.build_vector_indexes(_chunks(10), pages, _zero_embedder(8),
                                          _zero_embedder(4), image_batch_size=1)
    assert counts == {"text_vectors": 10, "visual_vectors": 2}
    col = indexes.get_visual_collection(indexes.get_chroma())
    got = col.get(include=["embeddings"])
    assert len(got["ids"]) == 2
    assert len(got["embeddings"][0]) == 4


def test_visual_leg_skipped_when_embed_image_none(tmp_path, monkeypatch):
    monkeypatch.setattr(indexes, "CHROMA_DIR", tmp_path / "chroma")
    counts = indexes.build_vector_indexes(_chunks(5), _pages(), _zero_embedder(8),
                                          None)
    assert counts["visual_vectors"] == 0
