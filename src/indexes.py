"""Indexes: BM25 keyword index (local) and ChromaDB vector collections
(text and visual, kept separate).

Text embeddings / visual embeddings are supplied as callables so the whole
pipeline can be built and unit-tested without the class key; the real
endpoint embedders live in ``src/embeddings.py``.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import bm25s
import numpy as np

from src.config import INDEXES_DIR, PROJECT_ROOT, RANDOM_SEED

BM25_DIR = INDEXES_DIR / "bm25"
CHROMA_DIR = INDEXES_DIR / "chroma"


# --------------------------------------------------------------------------- #
# BM25 keyword index
# --------------------------------------------------------------------------- #
def build_bm25(chunks: list[dict], out_dir: Path = BM25_DIR) -> Path:
    """Build a BM25 index over chunk texts; save index + chunk metadata."""
    corpus = [c["text"] for c in chunks]
    tokenized = bm25s.tokenize(corpus, stopwords="en")
    index = bm25s.BM25()
    index.index(tokenized)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index.save(str(out_dir))
    # bm25s >= 0.3 no longer round-trips a corpus attribute; keep our own copy
    (out_dir / "corpus_meta.json").write_text(
        json.dumps(chunks, ensure_ascii=False), encoding="utf-8"
    )
    return out_dir


def load_bm25(in_dir: Path = BM25_DIR) -> tuple[bm25s.BM25, list[dict]]:
    # BM25.load is a classmethod returning the loaded instance
    index = bm25s.BM25.load(str(in_dir))
    params = json.loads((in_dir / "params.index.json").read_text(encoding="utf-8"))
    index.load_scores(str(in_dir), num_docs=int(params["num_docs"]))
    corpus = json.loads((in_dir / "corpus_meta.json").read_text(encoding="utf-8"))
    return index, corpus


def bm25_search(query: str, index: bm25s.BM25, corpus: list[dict], k: int = 8) -> list[dict]:
    """Return top-k chunks as [{chunk_id, text, score, meta...}] (desc score).

    ``retrieve`` returns 0-based integer row ids into the indexed corpus
    (padded with -1); we map them back to chunk metadata via ``corpus``.
    """
    tokenized = bm25s.tokenize(query, stopwords="en")
    results, scores = index.retrieve(tokenized, k=k)
    hits: list[dict] = []
    for row_idx in range(results.shape[0]):
        for col_idx in range(results.shape[1]):
            doc_row = int(results[row_idx, col_idx])
            if doc_row < 0:
                continue
            meta = corpus[doc_row]
            hits.append(
                {
                    "chunk_id": meta["chunk_id"],
                    "score": float(scores[row_idx, col_idx]),
                    **meta,
                }
            )
    return hits


def _find_chunk(corpus: list[dict], chunk_id: str) -> dict:
    for c in corpus:
        if c["chunk_id"] == chunk_id:
            return c
    raise KeyError(chunk_id)


# --------------------------------------------------------------------------- #
# ChromaDB collections (text + visual, separate)
# --------------------------------------------------------------------------- #
def get_chroma():  # noqa: ANN201 - typeless to keep chromadb import lazy
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client


def get_text_collection(client) -> "chromadb.Collection":  # noqa: ANN001
    return client.get_or_create_collection(
        name="text_chunks",
        metadata={"hnsw:space": "cosine"},
    )


def get_visual_collection(client) -> "chromadb.Collection":  # noqa: ANN001
    return client.get_or_create_collection(
        name="visual_pages",
        metadata={"hnsw:space": "cosine"},
    )


def build_vector_indexes(
    chunks: list[dict],
    pages: list[dict],
    embed_text: callable,
    embed_image: callable,
    text_batch_size: int = 64,
    image_batch_size: int = 16,
) -> dict[str, int]:
    """Embed chunks (text) and page images (visual) into two separate
    collections. ``embed_text(texts)->np.ndarray (n,d)`` and
    ``embed_image(paths)->np.ndarray (n,d)`` are injected callables."""
    client = get_chroma()
    txt_col = get_text_collection(client)
    vis_col = get_visual_collection(client)
    rng = np.random.default_rng(RANDOM_SEED)

    # --- text collection: one vector per chunk --------------------------------
    ids, docs, metas = [], [], []
    for b_start in range(0, len(chunks), text_batch_size):
        batch = chunks[b_start : b_start + text_batch_size]
        vecs = embed_text([c["text"] for c in batch])
        for c, v in zip(batch, vecs):
            ids.append(c["chunk_id"])
            docs.append(c["text"])
            metas.append(
                {
                    "doc": c["doc"],
                    "doc_title": c["doc_title"],
                    "kind": c["kind"],
                    "page_no": c["page_no"],
                    "image_path": c["image_path"],
                    "chunk_of": c.get("chunk_of", ""),
                }
            )
    txt_col.upsert(ids=ids, embeddings=vecs if len(batch) == len(ids) else None, documents=docs, metadatas=metas)

    # --- visual collection: one vector per page image -------------------------
    v_ids, v_paths = [], []
    for p in pages:
        img = PROJECT_ROOT / p["image_path"]
        if not img.exists():
            continue
        v_ids.append(p["page_id"])
        v_paths.append(str(img))
    for b_start in range(0, len(v_paths), image_batch_size):
        batch_paths = v_paths[b_start : b_start + image_batch_size]
        vecs = embed_image(batch_paths)
        if b_start == 0:
            all_vecs = vecs
        else:
            all_vecs = np.concatenate([all_vecs, vecs], axis=0)
    v_metas = [
        {
            "page_id": pid,
            "doc": next(p2["doc"] for p2 in pages if p2["page_id"] == pid),
            "image_path": next(p2["image_path"] for p2 in pages if p2["page_id"] == pid),
        }
        for pid in v_ids
    ]
    vis_col.upsert(ids=v_ids, embeddings=all_vecs.tolist(), metadatas=v_metas)

    return {"text_vectors": len(ids), "visual_vectors": len(v_ids)}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--bm25-only", action="store_true", help="build only the BM25 index (no endpoints needed)")
    args = ap.parse_args(argv)

    t0 = time.time()
    chunks = json.loads((PROJECT_ROOT / "outputs" / "chunks.json").read_text(encoding="utf-8"))
    pages = json.loads((PROJECT_ROOT / "outputs" / "manifest.json").read_text(encoding="utf-8"))

    build_bm25(chunks)
    print(f"bm25 index: {len(chunks)} chunks -> {BM25_DIR} ({time.time() - t0:.1f}s)")
    if args.bm25_only:
        return 0

    from src.embeddings import embed_images, embed_texts  # requires class endpoints

    embed_text = lambda texts: embed_texts(texts).astype(np.float32)
    embed_image = lambda paths: embed_images(paths).astype(np.float32)
    counts = build_vector_indexes(chunks, pages, embed_text, embed_image)
    print(f"vector indexes: {counts} -> {CHROMA_DIR}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
