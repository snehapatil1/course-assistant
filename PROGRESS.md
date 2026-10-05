# PROGRESS.md — step log (MBAX 6418 Assignment 2: course-assistant)

Every step is logged here as it is built, tested, and verified. Findings and
limitations are honest: what was actually executed (with saved artifacts) vs.
what remains unchecked.

---

## Step 1 — Discovery & project setup (2026-10-05)

**Done:**
- Cloned `snehapatil1/course-assistant` (public repo, branch `master`) into
  `/Users/snehapatil1/Documents/MSBA/Fall/Business AI LLM/Assignment/Assignment2`.
- Verified `gh` CLI is authenticated (snehapatil1, scopes: gist, read:org, repo, workflow).
- Created 7 GitHub issues with completion checks (issues #1–#7), left
  unassigned so the team chooses ownership.
- Probed class endpoints: ports 9001–9006 + 9010 return 401 (auth required);
  9007 = ACE-Step music model (open), 9009 = Whisper ASR (open). Ports
  9011–9030 not reachable. Service mapping for 9001–9006/9010 pending the
  class key (user/team providing connection details).
- Materials inventory (10 files, copied into `data/materials/`):
  5 PowerPoint decks (Weeks 2–6) + 5 PDFs (Syllabus, Quiz 1, Quiz 1 Answer
  Key, Hermes Installation Guide, Hermes Configuration Guide).
- Confirmed local toolchain: Python 3.11.16 via `uv` (same as Assignment 1);
  no LibreOffice/poppler initially, so slide rendering uses LibreOffice
  (installed via `brew install --cask libreoffice`, background job) or the
  class parsing service as an alternative.
- Bootstrap: `.gitignore`, `.env.example` (dummy values only), `requirements.txt`,
  venv created, packages installed via uv (49s).
- Read the full text of Syllabus, Quiz 1 and Quiz 1 Answer Key (12 questions)
  for ground truth.

**Verified by:** file listings, HTTP status probes, `gh issue list` output.

---

## Step 2 — Ingestion: parse, chunk, render (2026-10-05)

**Done:**
- `src/ingest.py` — PDF pages via PyMuPDF; PPTX slides via python-pptx
  (shapes, tables, grouped shapes, speaker notes), one record per slide/page,
  all metadata preserved (`doc`, `page_no`, `kind`, `source_file`, `image_path`).
- `src/render.py` — PDF pages rendered locally with PyMuPDF at 110 dpi;
  PPTX slides via LibreOffice headless conversion (pending install).
- Ran ingestion: **173 page units** (142 slides + 31 PDF pages), **192 chunks**
  (slides atomic; long PDF pages split at 1100 chars with 120 overlap).
- Rendered **31 PDF page images** to `outputs/pages/` (syllabus p1, quiz1 p1
  visually verified readable). PPTX renders pending LibreOffice.
- Known empty-text unit: `hermes_configuration_guide__p0009` (image-only page)
  — kept intentionally for the visual index.
- Tests: `tests/test_ingest.py` — **11 pass** (manifest coverage, metadata,
  unique ids, chunk invariants, slide atomicity, long-page split, answer-key
  ground truth, intentional empty unit).
- Git: branch `feat/1-ingestion`, PR opened for review.

**Verified by:** `python -m src.ingest`, `python -m src.render`,
`python -m pytest -q` (11 passed), PIL size check + vision check of renders.
**Not yet done:** PPTX slide images (LibreOffice still installing), any
endpoint-dependent work (embeddings/indexes/LLM) awaiting class key.

---

## Step 3 — Local retrieval core: BM25 + hybrid fusion (2026-10-05)

**Done:**
- LibreOffice installed (`brew install --cask libreoffice`) — **all 173 page
  images now rendered**: 142 slides + 31 PDF pages (110 dpi). Re-run is
  idempotent (0 new renders on 2nd run). Slide renders visually verified
  (week05 p3 / week02 p15: tidy, readable, CU Boulder branding intact).
- `src/indexes.py` — BM25 index built via bm25s (192 chunks; save + load
  round-trip). Hit the bm25s 0.3.12 API drift: `load()` is a classmethod
  returning the instance, needs `load_scores(num_docs=...)` to restore
  retrieval state, and no longer round-trips a corpus attribute (kept our own
  `corpus_meta.json`). `bm25_search` maps integer doc-rows back to chunks.
- `src/embeddings.py` — class endpoint clients for text embedding, visual
  embedding (two payload styles, `VISUAL_INPUT_STYLE`), multimodal rerank,
  and chat; exponential-backoff retries; no secrets printed. Not yet exercised
  (awaiting key).
- `src/retrieve.py` — hybrid retrieval: BM25 top-k + text-vector top-k +
  visual-vector top-k → RRF fusion (`compute_rrf`) → optional class reranker →
  top-k `Candidate`s carrying full evidence (doc, page, excerpt, image path).
- `src/indexes.py --bm25-only` builds the keyword index with zero endpoints.
- **Keyword search verified end-to-end** (temperature-free, deterministic):
  - "What is quantization?" → week02 slides 15/16 (exact) + quiz1_answer_key p1
  - "context window and RAG" → week05 slides 2/5 + week02 p8
  - "gradio launch share" → week04 slide 7
  - "what is fine-tuning?" → quiz1 p2 (Q10 region) + week05 p13
- Tests: `tests/test_retrieval.py` added — RRF fusion math, BM25 round-trip,
  semantic sanity (quantization → week02, gradio → week04), Candidate evidence
  payload. Full suite: **17 pass**.
- Git: commits pushed to `feat/1-ingestion`; PR #8 scope updated to
  "ingestion + local retrieval core".

**Verified by:** `python -m pytest -q` (17 passed), direct BM25 query output
(above), vision checks of renders.
**Not yet done:** text/visual vector indexes, reranker, Q&A, quiz, UI — all
depend on the class endpoint key (user/team supplying connection details).

## Step 4 — (next) — Vector indexes + hybrid retrieval end-to-end (key)

