"""Class endpoint clients: text embeddings, visual (image) embeddings,
multimodal reranking, and the vision-capable chat model.

All are OpenAI-style /v1 services configured in `.env` (see `.env.example`).
Payloads are built explicitly per service; ``VISUAL_INPUT_STYLE`` lets the
visual-embedding payload shape be pinned after probing the class endpoint
(``openai`` = ``{"model", "input":[<data-uri>]}``, ``images`` = ``{"model",
"images":[<b64>]}``). No credentials are ever printed or logged.
"""
from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import httpx
import numpy as np

from src import config

_INPUT_STYLES = ("auto", "openai", "images")


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _retryable_post(url: str, headers: dict, payload: dict, tries: int = 4) -> dict:
    """POST JSON with exponential backoff; surface non-2xx clearly."""
    last: Exception | None = None
    for attempt in range(tries):
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=120)
            if resp.status_code == 200:
                return resp.json()
            # do not echo the body (may contain leaked secrets); log status only
            last = RuntimeError(f"{url} -> HTTP {resp.status_code}")
        except httpx.HTTPError as exc:  # network-level, retry
            last = exc
        time.sleep(1.5 * (2**attempt))
    raise RuntimeError(f"endpoint call failed after {tries} tries: {last}")


# --------------------------------------------------------------------------- #
# Text embeddings
# --------------------------------------------------------------------------- #
def embed_texts(texts: list[str], model: str | None = None,
                base_url: str | None = None) -> np.ndarray:
    model = model or config.TEXT_EMBED_MODEL
    base_url = base_url or config.TEXT_EMBED_BASE_URL
    url = f"{base_url.rstrip('/')}/embeddings"
    payload = {"model": model, "input": texts}
    data = _retryable_post(url, _auth_headers(config.TEXT_EMBED_API_KEY), payload)
    rows = sorted(data["data"], key=lambda r: r["index"])
    return np.asarray([r["embedding"] for r in rows], dtype=np.float32)


def embed_query(text: str) -> np.ndarray:
    return embed_texts([text])[0]


# --------------------------------------------------------------------------- #
# Visual embeddings (image -> vector)
# --------------------------------------------------------------------------- #
def _blob_to_embedding_blob(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    return base64.b64encode(raw).decode("ascii")


def embed_images(paths: list[str]) -> np.ndarray:
    model = config.VISUAL_EMBED_MODEL
    base_url = config.VISUAL_EMBED_BASE_URL
    url = f"{base_url.rstrip('/')}/embeddings"
    style = (os.environ.get("VISUAL_INPUT_STYLE", "auto") or "auto").lower()
    if style not in _INPUT_STYLES:
        style = "auto"
    blobs = [_blob_to_embedding_blob(p) for p in paths]

    attempts = [("openai", {"model": model, "input": [f"data:image/png;base64,{b}" for b in blobs]}),
                ("images", {"model": model, "images": blobs})] if style == "auto" else [
                (style, {"model": model,
                         **({"input": [f"data:image/png;base64,{b}" for b in blobs]}
                            if style == "openai" else {"images": blobs})})]

    for name, payload in attempts:
        try:
            data = _retryable_post(url, _auth_headers(config.VISUAL_EMBED_API_KEY), payload)
            rows = sorted(data["data"], key=lambda r: r["index"])
            return np.asarray([r["embedding"] for r in rows], dtype=np.float32)
        except RuntimeError:
            if style != "auto":
                raise
    raise RuntimeError("visual embedding endpoint rejected both payload styles; "
                       "set VISUAL_INPUT_STYLE in .env after probing the endpoint")


# --------------------------------------------------------------------------- #
# Multimodal reranking (query + candidate text/images -> scores)
# --------------------------------------------------------------------------- #
def rerank(query: str, candidates: list[dict]) -> list[dict]:
    """Return candidates with a reranker score added. ``candidates`` items
    carry ``text`` and optionally ``image_path``."""
    url = f"{config.RERANK_BASE_URL.rstrip('/')}/rerank"
    docs = [
        {"text": c["text"], **({"image": c["image_path"]} if c.get("image_path") else {})}
        for c in candidates
    ]
    payload = {"model": config.RERANK_MODEL, "query": query, "documents": docs}
    data = _retryable_post(url, _auth_headers(config.RERANK_API_KEY), payload)
    for item in data.get("results", []):
        candidates[item["index"]]["rerank_score"] = float(item["score"])
    return candidates


# --------------------------------------------------------------------------- #
# Vision-capable chat (structured text)
# --------------------------------------------------------------------------- #
def chat(messages: list[dict], temperature: float | None = None,
         max_tokens: int = 1536) -> str:
    """One chat completion; returns message content. Handles reasoning models
    that may return empty content when max_tokens is small."""
    url = f"{config.CHAT_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": config.CHAT_MODEL,
        "messages": messages,
        "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": max_tokens,
    }
    data = _retryable_post(url, _auth_headers(config.CHAT_API_KEY), payload)
    content = (data["choices"][0]["message"].get("content") or "").strip()
    if not content and data["choices"][0].get("message", {}).get("reasoning_content"):
        # reasoning model burned the budget: caller should retry with more tokens
        return ""
    return content
