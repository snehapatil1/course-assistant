"""Configuration for the course assistant.

All real credentials live in the local, gitignored ``.env`` file
(see ``.env.example`` for dummy values). Everything here is read from
environment variables - values are never hardcoded and never printed.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = PROJECT_ROOT / "data" / "library"  # app-managed: students' uploaded materials
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PAGES_DIR = OUTPUTS_DIR / "pages"
TEXT_DIR = OUTPUTS_DIR / "text"
INDEXES_DIR = OUTPUTS_DIR / "indexes"
FINDINGS_DIR = OUTPUTS_DIR / "findings"
SCREENSHOTS_DIR = OUTPUTS_DIR / "screenshots"

load_dotenv(PROJECT_ROOT / ".env")

_DUMMY_MARKERS = ("dummy", "placeholder", "your-key", "changeme", "example")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def is_dummy(value: str) -> bool:
    return any(m in value.lower() for m in _DUMMY_MARKERS)


# --- class services (OpenAI-compatible /v1 where noted) --------------------
CHAT_BASE_URL = env("CHAT_BASE_URL")
CHAT_API_KEY = env("CHAT_API_KEY")
CHAT_MODEL = env("CHAT_MODEL")

TEXT_EMBED_BASE_URL = env("TEXT_EMBED_BASE_URL")
TEXT_EMBED_API_KEY = env("TEXT_EMBED_API_KEY")
TEXT_EMBED_MODEL = env("TEXT_EMBED_MODEL")

VISUAL_EMBED_BASE_URL = env("VISUAL_EMBED_BASE_URL")
VISUAL_EMBED_API_KEY = env("VISUAL_EMBED_API_KEY")
VISUAL_EMBED_MODEL = env("VISUAL_EMBED_MODEL")

RERANK_BASE_URL = env("RERANK_BASE_URL")
RERANK_API_KEY = env("RERANK_API_KEY")
RERANK_MODEL = env("RERANK_MODEL")

PARSE_BASE_URL = env("PARSE_BASE_URL")
PARSE_API_KEY = env("PARSE_API_KEY")
PARSE_MODEL = env("PARSE_MODEL")

# --- reproducibility ---------------------------------------------------------
LLM_TEMPERATURE = float(env("LLM_TEMPERATURE", "0"))
RANDOM_SEED = int(env("RANDOM_SEED", "123"))

# --- retrieval knobs (tunable; the rerank-on/off comparison uses these) -------
TOP_K_KEYWORD = int(env("TOP_K_KEYWORD", "8"))
TOP_K_TEXT = int(env("TOP_K_TEXT", "8"))
TOP_K_VISUAL = int(env("TOP_K_VISUAL", "6"))
TOP_K_FUSED = int(env("TOP_K_FUSED", "12"))
TOP_K_FINAL = int(env("TOP_K_FINAL", "5"))
RRF_K = int(env("RRF_K", "60"))

_KIND_ATTRS = {
    "chat": ("CHAT_BASE_URL", "CHAT_API_KEY", "CHAT_MODEL"),
    "text_embed": ("TEXT_EMBED_BASE_URL", "TEXT_EMBED_API_KEY", "TEXT_EMBED_MODEL"),
    "visual_embed": ("VISUAL_EMBED_BASE_URL", "VISUAL_EMBED_API_KEY", "VISUAL_EMBED_MODEL"),
    "rerank": ("RERANK_BASE_URL", "RERANK_API_KEY", "RERANK_MODEL"),
    "parse": ("PARSE_BASE_URL", "PARSE_API_KEY", "PARSE_MODEL"),
}


def require_endpoint(kind: str) -> None:
    """Raise a clear error unless the endpoint is configured with a real key.

    Reads the current module state live, so tests can toggle endpoints off by
    patching the attributes (e.g. ``config.CHAT_API_KEY = ""``).
    """
    attrs = _KIND_ATTRS.get(kind)
    if attrs is None:
        raise ValueError(f"unknown endpoint kind: {kind!r}")
    url, key, model = (globals().get(a, "") for a in attrs)
    missing = [name for name, v in (("URL", url), ("key", key), ("model", model)) if not v]
    if missing:
        raise RuntimeError(
            f"endpoint '{kind}' not configured ({', '.join(missing)} missing). "
            f"Copy .env.example to .env and set real values."
        )
    if is_dummy(key):
        raise RuntimeError(
            f"endpoint '{kind}' has a DUMMY key - set the real class key in .env."
        )
