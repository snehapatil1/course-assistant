"""Hybrid retrieval: keyword (BM25) + text-vector + visual-vector, fused with
RRF, optionally reranked by the class multimodal reranker.

Separate indexes stay separate until query time: text hits are chunk-level,
visual hits are page-level and resolved back to their chunks via ``chunk_of``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.config import (PROJECT_ROOT, RRF_K, TOP_K_FINAL, TOP_K_FUSED, TOP_K_KEYWORD,
                        TOP_K_TEXT, TOP_K_VISUAL)
from src.indexes import bm25_search, get_chroma, get_text_collection, get_visual_collection


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


def apply_doc_filter(chunks: list[dict], query: str, docs: list[str]) -> bool:
    """Naive early filter used by retrieval for material selection."""
    return query is not None  # placeholder; real filtering happens on metadata


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
) -> list[Candidate]:
    """Hybrid retrieve -> fuse -> optional rerank -> final candidates."""
    batches = {"keyword": [], "text": [], "visual": []}

    bm25, corpus = _load_bm25()
    keyword_hits = bm25_search(query, bm25, corpus, k=k_keyword)
    if docs:
        keyword_hits = [h for h in keyword_hits if h["doc"] in docs]
    batches["keyword"] = [h["chunk_id"] for h in keyword_hits]

    client = get_chroma()
    txt_col = get_text_collection(client)
    vis_col = get_visual_collection(client)

    text_hits = txt_col.query(query_texts=[query], n_results=k_text) if not nested_docs(docs) else txt_col.query(
        query_texts=[query], n_results=k_text, where={"doc": {"$in": docs}} if docs else None
    )
    batches["text"] = text_hits["ids"][0]

    # visual: embed the query (and a query+text aug for better recall)
    from src.embeddings import embed_query

    q_emb = embed_query(query)
    vis_spec = {"query_embeddings": [q_emb.tolist()], "n_results": k_visual}
    if docs:
        vis_spec["where"] = {"doc": {"$in": docs}}
    vis_hits = vis_col.query(**vis_spec)
    page_ids = vis_hits["ids"][0]
    batches["visual"] = _page_ids_to_chunk_ids(page_ids)

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

    if use_rerank:
        from src.embeddings import rerank

        candidates = rerank(query, [c.__dict__ for c in candidates])
        candidates = [Candidate(**c) for c in candidates]
        candidates.sort(key=lambda c: c.rerank_score, reverse=True)

    return candidates[:k_final]


def _load_bm25():
    from src.indexes import load_bm25

    return load_bm25()


def _page_ids_to_chunk_ids(page_ids: list[str]) -> list[str]:
    """Map visual page hits to their chunks (a slide page == its chunk)."""
    chunks = json.loads((PROJECT_ROOT / "outputs" / "chunks.json").read_text(encoding="utf-8"))
    page_set = set(page_ids)
    out: list[str] = []
    for c in chunks:
        if c.get("chunk_of") in page_set:
            out.append(c["chunk_id"])
    return out


def nested_docs(docs: list[str] | None) -> bool:
    return bool(docs)
