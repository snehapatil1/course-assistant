# PROGRESS.md — step log (MBAX 6418 Assignment 2: course-assistant)

Every step is logged here as it is built, tested, and verified. Findings and
limitations are honest: what was actually executed (with saved artifacts) vs.
what remains unchecked.

**Git workflow:** `master` is the integrated line; all development happens on
branch `sneha` (personal working branch) and lands on `master` via pull
requests. Never commit directly to `master`.

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
- High-level architecture diagram: `docs/architecture.html` (dark-theme SVG,
  covers student → Gradio UI → backend (ingestion / hybrid retrieval / Q&A /
  quiz) → local indexes + evidence → class services + .env security),
  screenshot saved to `outputs/screenshots/architecture.png` (verified
  full-page, no clipping/overlaps).
- Git: commits pushed to `feat/1-ingestion`; PR #8 scope updated to
  "ingestion + local retrieval core". Team rule: all development now on
  branch `sneha` (master via PRs only).

**Verified by:** `python -m pytest -q` (17 passed), direct BM25 query output
(above), vision checks of renders.
**Not yet done:** text/visual vector indexes, reranker, Q&A, quiz, UI — all
depend on the class endpoint key (user/team supplying connection details).

## Step 4 — (next) — Vector indexes + hybrid retrieval end-to-end (key)

---

## Step 5 — Generic, app-managed library (made the app format-agnostic) (2026-10-05)

Per the revised guidelines, the app no longer knows about any specific course
file: students upload their own materials and everything (Q&A, quizzes)
operates on that library.

**Done:**
- `src/library.py` (new) — app-managed document library:
  - `add_document`: SHA-256 **dedupe** (same file twice -> no duplicate),
    copy into `data/library/`, parse, render page/slide images, rebuild
    manifest + chunks + BM25, sync ChromaDB text/visual indexes when the
    class endpoints are configured (`vector indexes skipped` message
    otherwise).
  - `remove_document`: purges the stored file, text, images, chunk rows, BM25
    corpus, and vector rows — later answers never rely on removed content.
  - `list_documents` / `rebuild_all` / CLI (`python -m src.library
    add|remove|list|rebuild`).
- `src/ingest.py` — rewritten generic: `build_page_records(path, doc_id,
  title, hash)` per document; no fixed corpus, no `data/materials`.
- `src/render.py` — generic `render_doc` by extension (PDF direct;
  PPTX via LibreOffice headless); renders everything in the manifest.
- `src/retrieve.py` — graceful degradation: BM25 always; text/visual vector
  legs + reranker only when endpoints configured (`endpoint_ready`).
- `src/qa.py` (new) — vision prompt from evidence (text + slide images),
  structured `{answer, sources}` parsing, schema + **support validation**
  (fabricated doc/page/excerpt rejected; "not in materials" is an honest
  answer).
- `src/quiz.py` (new) — MCQs from selected uploaded material; fixed key
  server-side (`primary_key` never leaves the server; `to_client_view`
  strips key/explain/raw; `key_sha` stability), grading + explanations.
- `src/app.py` (new) — Gradio app: **Materials** tab (upload/remove/dedupe
  status; works with zero configuration), **Q&A** tab (material/topic
  filters, rerank + vision toggles, answer + validated sources + original
  slide images with document/slide captions), **Quiz** tab (material/topic/
  count, radios, grade vs stored key, solutions revealed only after
  grading). Unconfigured endpoints produce an honest status panel.
- Fixed two real edge cases found by the new tests: bm25s crashes on an
  empty corpus (removing the last document) -> empty-library guards in
  build/load/search; bm25s returns zero-score noise rows when a query
  matches nothing -> filtered out.
- Removed ALL references to the earlier uploaded corpus: `data/materials/`
  deleted, `EXPECTED_DOCS`/week*/quiz1/syllabus tests replaced with
  synthetic fixture documents (see `tests/conftest.py`), `outputs/`
  reset to an empty library (manifest/chunks = []). Verified with grep:
  zero hits for week0|quiz1|syllabus|MATERIALS_DIR in src/ and tests/.
- Docs: `data/library/README.md` (supported formats, LibreOffice conversion
  steps, manual PPTX→PDF workaround, render verification spot-check),
  README.md quick-start + credentials section.
- Tests: **36 pass** (parsing, chunking, library add/dedupe/remove/purge,
  BM25 follows add+remove, RRF, candidate evidence, endpoint-ready guards,
  Q&A parsing + fabricated-source rejection, quiz key stability/grading/
  solution-hiding).
- Smoke check: `build_app()` constructs the Gradio Blocks without error.

**Verified by:** `python -m pytest -q` (36 passed), CLI round trip
(add -> list -> remove -> empty), grep for stale references (0 hits),
`build_app()` smoke test.
**Not yet done:** real-endpoint paths (vectors, vision Q&A, quiz
generation) still await the class key; UI screenshots pending a live run.

## Step 6 — (next) — Class endpoints (key) -> full end-to-end + UI screenshots

---

## Step 6 — LIVE: class endpoints configured, full end-to-end verified (2026-10-07)

**Configured (local `.env` only — gitignored, never on GitHub):**
chat `dobolyi.com:9001/v1` (cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit), text embed
`9002/v1` (Nemotron-3-Embed-1B-BF16), visual embed `9003/v1`
(Qwen3-VL-Embedding-2B), reranker `9004/v1` (Qwen3-VL-Reranker-2B). Probed
each port's `/v1/models` and payload schemas before wiring.

**Done:**
- Library built with the app's generic pipeline: 4 user documents (weeks 2/3/5
  decks + syllabus PDF; week03 came in via an earlier partial add) = 103
  page units, 103 rendered images, 103 text vectors + 103 visual vectors in
  ChromaDB, BM25 over 103 chunks.
- Probed service quirks and fixed them in code:
  - visual embed endpoint rejects inputs over its 8192-token context limit;
    the budget tracks the ENCODED image size (110-dpi PNG slide ~860KB fails;
    JPEG q85 ≤192px ~5-8KB fits; dense slides up to 9.7KB still fail) ->
    adaptive resize ladder (192/160/128/96px, q85->70) + one image per
    request + correct JPEG mime in data URIs.
  - reranker accepts `documents` as plain strings only (no image objects) ->
    text-only reranking, `relevance_score` field.
  - reasoning chat model intermittently returns empty completions for quiz
    generation -> retry with max_tokens=8192; chat default raised to 2048.
- Verified live (temperature 0, results in `outputs/findings/e2e_live.json`,
  `e2e_quiz.json`):
  - Hybrid retrieval: "What is quantization?" -> week02 slides 15/16 first
    (rerank scores 0.70/0.44); diagram query -> week05 RAG slides 18/9/10
    (visual leg working).
  - Vision Q&A: answered quantization with 3 validated sources (doc+page+
    excerpt); described the RAG pipeline diagram FROM the slide image with
    valid output.
  - Quiz: 3 MCQs generated from week02 with chunk citations, fixed key,
    grading 2/3 on a deliberately wrong answer.
  - UI E2E via browser: asked the question in the Gradio app, got answer +
    "✓ structured output is valid" + sources + slide image gallery with
    document/slide captions; screenshot saved
    (`outputs/screenshots/qa_answered.png`).
- Tests: suite stays hermetic (conftest forces endpoints off; endpoint-ready
  logic now reads live module state) — **37 pass**.
- Committed on `sneha` (26b5980, 880126d/4c4515d); `.env` never staged
  (verified in `git status`).

**Verified by:** curl probes of all four ports (200 + models confirmed), live
embedding/chat calls, E2E results saved under `outputs/findings/`, browser UI
run with screenshot, `python -m pytest -q` (37 passed).
**Not yet done / limitations (honest):**
- Reranking is text-only (endpoint schema; image objects rejected).
- Visual embeddings operate on ≤192px JPEGs (endpoint budget); display
  renders stay full-res.
- The required **design comparison** (rerank on/off, or hybrid vs single
  index) and README findings writeup are the next planned step.
- The running app (proc 6bdc3e609481) serves at http://127.0.0.1:7860.

## Step 7 — (next) — Design comparison + README findings/limitations

---

## Step 8 — Grounded QA deliverable: strict schema, source audit, eval harness (2026-10-08)

Task branch `4-grounded-qa-answer-sources-as-validated-structured-output-vision-capable-no-invented-citations` (Savannah). Closed the gaps between the existing QA engine and the acceptance criteria, and added the reproducibility harness that was missing. All offline behavior verified by the suite; the live run needs `.env` (see the end of this step).

**Done:**
- `src/qa.py` — validation hardened:
  - **Formal JSON schema** (`ANSWER_JSON_SCHEMA`, draft-07, via `jsonschema`): model payload must be exactly `{answer, sources[]}` with each source exactly `{doc, page_no, excerpt}` — unknown fields, non-integer pages, missing keys, and **empty excerpts are rejected** (previously an empty excerpt passed the support check — the "actual excerpt" requirement).
  - **Grounded answers must cite ≥1 source**; `sources: []` on a real answer is now invalid (the "invented answer" failure mode). The honest refusal is pinned to the agreed marker `Not found in the provided materials.` (`qa.is_not_found` is whitespace/case tolerant) and must have `sources == []`.
  - Support check retained + factored (`qa.excerpt_overlaps`): every source must pin to a retrieved candidate and its excerpt must overlap retrieved text.
  - **Display metadata is resolved server-side** (`qa._enrich_sources`: doc_title/kind/image_path/chunk_id from the pinned candidate) — the model never supplies display fields, so the strict schema stays strict while the UI keeps its labels.
  - **Explicit `temperature=` passthrough** on `answer_question` (eval runs at 0).
  - **Empty-response fallback ladder made explicit + recorded**: rung 1 normal → rung 2 same messages with `max_tokens=8192` → rung 3 images stripped + larger budget → `qa.EmptyResponseError` (subclass of ValueError, carries the ladder information; UI surfaces it honestly).
  - Vision path unchanged in spirit: `include_images=True` attaches each candidate's page/slide image (`qa.count_images` reports how many were sent, recorded per question).
- `src/eval_qa.py` (new) — the evaluation harness the task required:
  - Default 12-question eval set (text-grounded, multi-source, **diagram/vision**, **out-of-materials honesty probes**, thin-evidence probes), overridable via CLI (`--questions`, `--list-defaults`).
  - Runs retrieve → vision messages → chat at **temperature 0** → strict schema + support validation; catches ladder exhaustion and retrieval errors per question (never fatal).
  - **Per-source audit** (AC2): doc + page/slide + non-empty excerpt + pinned-to-evidence + excerpt-overlaps-evidence + page/slide screenshot availability.
  - Writes `outputs/findings/grounded_qa_eval_<ts>.json` (+ `grounded_qa_eval_latest.json`) with per-question records, raw model output, ladder usage, `images_sent`, latency, and a summary (valid ratio, honest refusals, vision path used, ladder stats, failures).
  - Hermetic by design: `retrieve_fn`/`chat_fn` injectable; CLI refuses cleanly (exit 2) when endpoints aren't configured.
- `requirements.txt`: +`jsonschema>=4`.
- Tests: `tests/test_qa.py` +17 (schema strictness, grounded-no-sources, empty-excerpt, temperature passthrough, ladder rescue/strip/exhaust, vision image parts, source enrichment); `tests/test_eval_qa.py` +10 (file output, honest refusal, no-candidates, ladder-exhausted recording, vision on/off, retrieval-error path, latest copy, CLI offline guard). Full suite: **84 passed, 4 skipped** (was 58).

**Verified by:** `python -m pytest -q` (84 passed, 4 skipped), CLI smoke (`--list-defaults`; offline run exits 2 with a readable message).
**Not yet done (honest):** the LIVE eval against the class endpoints (chat/embeddings/rerank) — `.env` with the class key is required; this machine has none. Once `.env` + course documents are in the library, run `python -m src.eval_qa` and commit the results file.

---

## Step 9 — Eval set aligned to assignment spec + rerank comparison harness (2026-10-08)

Read the full assignment text (MBAX 6418 Assignment 2) and aligned the harness to its explicit requirements.

**Done:**
- `DEFAULT_EVAL_SET` trimmed to **10 questions** (assignment says 5–10): text-grounded (quantization, fine-tuning, context window, Gradio), multi-source (optimization comparison, RAG components), **≥2 visual questions incl. the Week 2 "Vibe Coding on 'Prod'" meme** (the assignment's explicit "try it" check), **1 unanswerable honesty probe** (capital of France), 1 thin-evidence probe. Eval-set spec enforced by a test.
- **Design comparison: `compare_rerank()` + `--compare-rerank`** — runs the SAME eval set twice (reranker ON vs OFF), records per question whether the answer is schema+support valid, how many sources it cited, and latency (assignment: "record whether each answer is correct, whether its sources support it, and how long it takes"); answer correctness is flagged as a manual judgment (README). Combined output saved to `outputs/findings/grounded_qa_compare_rerank_{ts}.json` (+ `_latest.json`) with side-by-side rows and per-side summaries. This gives the team the instrument for the required "compare two approaches" report (rerank on/off is the planned step 7 comparison).
- `run_eval(..., write_results=False)` internal switch so the comparison run writes one combined file.
- Tests +3 (eval-set spec, comparison hermetic with rerank toggling observed, per-side failure recording). Full suite: **87 passed, 4 skipped**.

**Verified by:** `python -m pytest -q` (87 passed, 4 skipped), `--list-defaults` shows the 10-question set.
**Not yet done (honest):** live run of the eval set and the rerank comparison (needs `.env` endpoint keys + library documents); then the README question-set/comparison/findings report.

---

## Step 10 — LIVE evaluation: real endpoints, real library (2026-10-08)

Full live run on Savannah's machine with the class endpoints configured (chat 9001, text embed 9002, reranker 9004; visual embed 9003 down during the run — visual-vector leg skipped honestly).

**Done:**
- Wired `.env` with the class config (gitignored; keys never committed/printed).
- **Fixed a fresh-machine bug found live:** `build_vector_indexes` upserted only the LAST embedding batch (`embeddings=vecs if len(batch)==len(ids) else None`), so multi-batch corpora silently created Chroma collections with the built-in 384-dim embedder → every vector query crashed ("expecting 384, got 2048") on a fresh machine (Sneha's single-batch library never hit it). Now upserts the full vector set; regression-tested (`tests/test_vector_indexes.py`).
- **Graceful degradation:** `_sync_vector_indexes` no longer requires BOTH endpoints to sync either; a down/unreachable visual-embedding service (9003 was resetting connections) is probed (status-only, 3s) and the visual leg is skipped with a recorded status instead of crashing adds. Same for the `python -m src.indexes` CLI (`--visual skipped` message).
- **Real library rebuilt:** purged stale manifest/chunks entries that shipped in git (team's index-only records — the app's remove CLI intentionally blocks removing them) after backing up; re-added the 3 real files: Week 2 deck (42 slides), Week 6 deck (20), Syllabus (7) → **69 rendered page/slide images** via the now-installed LibreOffice 26.8.1 (installed from official dmg; no Homebrew on this Mac).
- **Truncation robustness:** reasoning+vision outputs can be cut mid-JSON → `parse_json_response` gained a repair ladder (clip to last complete value / append closers) and rung 1 of the empty-response ladder now sends `max_tokens=8192` whenever the prompt carries images.
- **Live eval (10 questions, temperature 0, TOP_K_FINAL=8):** `outputs/findings/grounded_qa_eval_live_k8_20261008.json` → **9/10 schema+support valid**. Answers: quantization (week 2 p15, 5.4s), quant-vs-finetuning comparison (grounded week 2 p15, 20s), **Vibe Coding meme answered FROM the slide image** (Boromir meme cited week 2 p33; direct image-only check: model identified the meme + Agentic Coding contrast on the retrieved slide — the assignment's "try it" case), 6 honest refusals (5 legitimately absent from the honest 3-doc corpus: gradio/RAG components/diagram/assignment-built/France + 1 fine-tuning false negative), 1 flaky truncation (passed on rerun). Vision path used on 9/10 questions (8 images sent each). Fallback ladder fired once (retry + headroom) with no total failures on rerun.
- **Design comparison (assignment A/B requirement):** `TOP_K_FINAL=8 python -m src.eval_qa --compare-rerank` → **10/10 valid with rerank ON and 10/10 OFF**; rerank adds ~1–7s/question (ON avg 8.9s vs OFF 7.0s) but did not change validity on this corpus → keep rerank for robustness on larger libraries, documented for the README report. Saved: `outputs/findings/grounded_qa_compare_rerank_latest.json`.
- Full suite: **94 passed, 4 skipped** (was 87; +7: vector-index regression ×4, truncation repair ×2, vision-budget ladder ×1).

**Verified by:** live endpoint probes (status codes only), live eval + comparison JSONs with per-question source audits, `find outputs/pages | wc -l` = 69, `python -m pytest -q` (94 passed).
**Limitations (honest):** visual-embedding endpoint (9003) was down during the run → no visual-vector retrieval leg (diagram question answered from week-5-style content only where present; honest refusal otherwise); fine-tuning false-negative; comparison corpus is small (3 docs) so rerank ON/OFF differences are subtle; router-metrics: one question needed the fallback ladder.


## Step (2026-10-08) — Quiz UI layout hardening (sneha, uncommitted)
- Radio option text now sits BESIDE the circle: quiz option `<span>` forced `display:inline`
  (was `block` from PR #12's wrap fix, which put text on the line below the circle).
- Workspace blanking on "Create practice quiz" covered the stale question radios too:
  click chain's first event now hides markdown AND all 5 radio groups; Gradio queue
  chrome ("processing | N/Ns") hidden via CSS; single custom "Generating Quiz..." bar.
- Create button is single-flight (disabled while generating, re-enabled in every
  return path of generate_quiz_ui) so repeated clicks cannot interleave generations.
- Compact quiz layout: column gap 10px, fieldset padding 2px, option rows 28px,
  question groups 138px apart (was 199-218px), heading→Q1 78px (was ~115px).
- Verified in-browser across repeated + rapid runs: identical geometry every run,
  radios 0 during generation, 12 after; full-page screenshot compact_run2.png.
- Stale-tab root cause: CSS in the page <head> only applies to tabs loaded AFTER a
  restart; Gradio Markdown strips <style> tags (verified: styles:0 mid-loading).
  The user's long-lived tab kept the old airy layout no matter the server fixes.
- FINAL FIX: quiz_view switched gr.Markdown -> gr.HTML (no sanitization); every quiz
  generation ships _QUIZ_LAYOUT_CSS inside the update (scoped to #quiz-workspace:
  gap 10px, title margin 0, fieldset 2px, option rows 28px, span inline, queue chrome
  hidden). Stale tabs get the compact layout on the next click - no reload needed.
- Loading indicator also gr.HTML -> its @keyframes now actually run (was stripped).
- Verified 3 consecutive generations: headBottom->title 16px, title->Q1 39px,
  Q1..Q3 separations 139/138 (uniform), text beside circle; identical run-to-run.
- Companion test updated for new return shape (test_mountain_integration.py);
  17 passed in quiz+mountain suites.
## Step (2026-10-08) — Quiz topic now drives chunk selection (sneha, uncommitted)
- Bug: topic was only a prompt hint; chunks fed to the model were the first
  max(8, n*3) in page order -> PPT5 + topic=quantization produced an unrelated
  LITM question (week-5 content, no quantization anywhere in the window).
- Fix (src/quiz.py): select_topic_chunks() ranks material-filtered chunks by
  keyword relevance (words + 2-grams, stopword-filtered, phrase x2 bonus),
  deterministic/endpoint-free (reproducibility: temp 0 + same inputs -> same
  quiz). Top-k window leads with topic hits; chunk_ref mapping + validation
  still use the ranked list; full chunk-id set unchanged.
- Honesty: when the topic has no hits in the selected material, the quiz
  carries topic_note ("not covered ... closest available blocks") shown in
  amber in the quiz header; the prompt also says questions MUST concern the
  topic. Prompt now names the topic explicitly.
- Tests: 5 new (ranking, phrase bonus, no-hits, empty-topic order, prompt
  focus); suite 22 passed quiz+mountain. Live E2E: All materials + topic
  quantization -> Q1-Q3 all quantization (purpose, Qwen file size, M-chip
  format). UI shows "topic: quantization" line.
