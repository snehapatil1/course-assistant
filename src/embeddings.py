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

_INPUT_STYLES = ("openai", "images")  # reserved: payload shapes per endpoint probe


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
def _blob_to_embedding_blob(path: str | Path, max_side: int | None = None,
                            quality: int = 85) -> str:
    """base64 of the image, downscaled/re-encoded for the embedder's budget.

    The class visual-embedding endpoint rejects inputs above its context
    limit (8192 tokens), and the budget tracks the encoded image size: dense
    slides at JPEG q85/192px can still overflow (~9.7KB max observed). The
    caller ``embed_images`` falls back to smaller/lower-quality encodings;
    see ``VISUAL_MAX_SIDE`` / ``VISUAL_IMAGE_FORMAT`` overrides.
    """
    raw = Path(path).read_bytes()
    if max_side is None:
        max_side = int(os.environ.get("VISUAL_MAX_SIDE", "192") or "192")
    fmt = (os.environ.get("VISUAL_IMAGE_FORMAT", "JPEG") or "JPEG").upper()
    if max_side > 0:
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(raw)).convert("RGB")
            if max(img.size) > max_side:
                img.thumbnail((max_side, max_side))
                buf = io.BytesIO()
                img.save(buf, format=fmt, quality=quality, optimize=True)
                raw = buf.getvalue()
        except Exception:
            pass  # fall back to the original bytes
    return base64.b64encode(raw).decode("ascii")


def _image_data_uri(path: str | Path, max_side: int | None = None,
                    quality: int = 85) -> str:
    """Data URI for the visual embedder; the mime must match the encoding."""
    fmt = (os.environ.get("VISUAL_IMAGE_FORMAT", "JPEG") or "JPEG").upper()
    return (f"data:image/{fmt.lower()};base64,"
            f"{_blob_to_embedding_blob(path, max_side=max_side, quality=quality)}")


def embed_images(paths: list[str]) -> np.ndarray:
    model = config.VISUAL_EMBED_MODEL
    base_url = config.VISUAL_EMBED_BASE_URL
    url = f"{base_url.rstrip('/')}/embeddings"
    headers = _auth_headers(config.VISUAL_EMBED_API_KEY)

    vectors: list[np.ndarray] = []
    for path in paths:
        uri = _embed_one_image(url, headers, model, path)
        data = _retryable_post(url, headers, {"model": model, "input": [uri]})
        rows = sorted(data["data"], key=lambda r: r["index"])
        vectors.append(np.asarray(rows[0]["embedding"], dtype=np.float32))
    return np.stack(vectors)


def _embed_one_image(url: str, headers: dict, model: str, path: str) -> str:
    """Find an encoding of ``path`` that fits the endpoint's token budget.

    Dense slides can overflow at the default size (HTTP 400); the ladder
    shrinks the side and drops quality until the request succeeds.
    """
    import httpx as _httpx

    for side, quality in ((192, 85), (160, 80), (128, 75), (96, 70)):
        uri = _image_data_uri(path, max_side=side, quality=quality)
        resp = _httpx.post(url, headers=headers,
                           json={"model": model, "input": [uri]}, timeout=120)
        if resp.status_code == 200:
            return uri
        if resp.status_code != 400:  # not a size rejection; surface the real error
            raise RuntimeError(f"visual embedding {url} -> HTTP {resp.status_code}")
    raise RuntimeError(
        f"visual embedding endpoint still rejected {path} at the smallest encoding"
    )


# --------------------------------------------------------------------------- #
# Multimodal reranking (query + candidate text/images -> scores)
# --------------------------------------------------------------------------- #
def rerank(query: str, candidates: list[dict]) -> list[dict]:
    """Return candidates with a reranker score added.

    Class endpoint schema (probed): POST /v1/rerank with ``documents`` as a
    list of plain strings; scores come back as ``relevance_score`` per index.
    """
    url = f"{config.RERANK_BASE_URL.rstrip('/')}/rerank"
    docs = [c["text"][:1500] for c in candidates]
    payload = {"model": config.RERANK_MODEL, "query": query, "documents": docs}
    data = _retryable_post(url, _auth_headers(config.RERANK_API_KEY), payload)
    for item in data.get("results", []):
        candidates[item["index"]]["rerank_score"] = float(
            item.get("relevance_score", item.get("score", 0.0))
        )
    return candidates


# --------------------------------------------------------------------------- #
# Vision-capable chat (structured text)
# --------------------------------------------------------------------------- #
def chat(messages: list[dict], temperature: float | None = None,
         max_tokens: int = 4096) -> str:
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
