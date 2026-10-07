"""Hybrid retrieval for the course assistant.

Generic: retrieves over whatever the student has uploaded. Keyword (BM25)
runs locally with zero endpoints; text-vector and visual-vector legs run via
ChromaDB only when the class embedding endpoints are configured in ``.env``.
Rankings are fused with RRF and (optionally) reranked by the class
multimodal reranker. Every candidate carries doc + page/slide + excerpt +
original image path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src import config
from src.config import (PROJECT_ROOT, RRF_K, TOP_K_FINAL, TOP_K_FUSED, TOP_K_KEYWORD,
                        TOP_K_TEXT, TOP_K_VISUAL)
from src.indexes import bm25_search, get_chroma, get_text_collection, get_visual_collection


def endpoint_ready(kind: str) -> bool:
    try:
        config.require_endpoint(kind)
        return True
    except RuntimeError:
        return False


@dataclass
class Candidate:
    chunk_id: str
    doc: str
    doc_title: str
    kind: str
    page_no: int
    text: str
    image_path: str
    scores: dict[str, float] = field(default_factory=dict)
    rerank_score: float = 0.0

    def to_evidence(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc": self.doc,
            "doc_title": self.doc_title,
            "page_no": self.page_no,
            "kind": self.kind,
            "excerpt": _excerpt(self.text),
            "image_path": self.image_path,
        }


def _excerpt(text: str, limit: int = 900) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + " …"


# --------------------------------------------------------------------------- #
# Pure fusion (unit-testable without any endpoint)
# --------------------------------------------------------------------------- #
def compute_rrf(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal-rank fusion: score = sum(1 / (k + rank)) across rankings."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
def retrieve(
    query: str,
    docs: list[str] | None = None,
    k_keyword: int = TOP_K_KEYWORD,
    k_text: int = TOP_K_TEXT,
    k_visual: int = TOP_K_VISUAL,
    k_fused: int = TOP_K_FUSED,
    k_final: int = TOP_K_FINAL,
    use_rerank: bool = True,
    bm25_dir: Path | None = None,
) -> list[Candidate]:
    """Hybrid retrieve -> fuse -> optional rerank -> final candidates.

    Keyword-only when the class embedding endpoints are not configured
    (the app still answers, honestly, with what it has).
    """
    from src.indexes import load_bm25

    index, corpus = load_bm25(bm25_dir or PROJECT_ROOT / "outputs" / "indexes" / "bm25")
    keyword_hits = bm25_search(query, index, corpus, k=k_keyword)
    if docs:
        keyword_hits = [h for h in keyword_hits if h["doc"] in docs]
    batches = {"keyword": [h["chunk_id"] for h in keyword_hits]}
    if not corpus:
        return []  # empty library: nothing to retrieve

    text_ready = endpoint_ready("text_embed")
    visual_ready = endpoint_ready("visual_embed")

    # embed the query with OUR embedder and query both collections with
    # vectors - query_texts would use Chroma's default 384-dim function and
    # crash against our 2048-dim vectors
    q_emb = None
    if text_ready or visual_ready:
        from src.embeddings import embed_query

        q_emb = embed_query(query)

    if text_ready:
        assert q_emb is not None  # embedded above when text_ready
        txt_col = get_text_collection(get_chroma())
        where = {"doc": {"$in": docs}} if docs else None
        text_hits = txt_col.query(
            query_embeddings=[q_emb.tolist()], n_results=k_text, where=where
        )
        batches["text"] = text_hits["ids"][0]

    if visual_ready:
        assert q_emb is not None  # embedded above when visual_ready
        vis_col = get_visual_collection(get_chroma())
        spec: dict = {"query_embeddings": [q_emb.tolist()], "n_results": k_visual}
        if docs:
            spec["where"] = {"doc": {"$in": docs}}
        vis_hits = vis_col.query(**spec)
        batches["visual"] = _page_ids_to_chunk_ids(vis_hits["ids"][0])

    fused = compute_rrf(list(batches.values()), k=RRF_K)
    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k_fused]
    chunks_by_id = {c["chunk_id"]: c for c in corpus}
    candidates = [
        Candidate(
            chunk_id=cid,
            doc=chunks_by_id[cid]["doc"],
            doc_title=chunks_by_id[cid]["doc_title"],
            kind=chunks_by_id[cid]["kind"],
            page_no=chunks_by_id[cid]["page_no"],
            text=chunks_by_id[cid]["text"],
            image_path=chunks_by_id[cid]["image_path"],
            scores={"rrf": score},
        )
        for cid, score in ordered
        if cid in chunks_by_id
    ]

    if use_rerank and endpoint_ready("rerank"):
        from src.embeddings import rerank

        candidates = rerank(query, [c.__dict__ for c in candidates])
        candidates = [Candidate(**c) for c in candidates]
        candidates.sort(key=lambda c: c.rerank_score, reverse=True)

    return candidates[:k_final]


def _page_ids_to_chunk_ids(page_ids: list[str]) -> list[str]:
    """Map visual page hits to their chunks (a slide page == its chunk)."""
    chunks = json.loads((PROJECT_ROOT / "outputs" / "chunks.json").read_text(encoding="utf-8"))
    page_set = set(page_ids)
    out: list[str] = []
    for c in chunks:
        if c.get("chunk_of") in page_set:
            out.append(c["chunk_id"])
    return out
