# Fresh-copy setup verification — findings (2026-10-11)

Verification of a fresh clone of `master` (`77f5661`, pre-fix state) against
the README setup instructions, plus manual browser confirmation. This file
records what was found *before* the fixes on `maddie/fresh-copy-fixes`; it is
kept so the evidence trail matches the fix rationale.

Status labels used below:

- **CONFIRMED (browser)** — reproduced manually in the real UI by a human.
- **CONFIRMED (automated)** — reproduced via script/automation (library API
  paths, service probes, or the automated suite).
- **automation-only observation** — observed via scripts; not exercised in
  the real browser at the time of testing.

## Status summary

| Item | Status |
|---|---|
| Fresh-copy setup | **Partially successful** — env/install/launch/upload/quiz/Q&A-with-selection work; two README gaps (endpoint source + `/v1`) and two app bugs below |
| Phantom library records (4 docs listed, only Week 5 uploaded) | **CONFIRMED (browser)** |
| Empty-selection Q&A ("all materials") | **CONFIRMED (browser)** — error, no answer |
| Explicit Week 5 selection + grounded Q&A | **CONFIRMED (browser)** — detailed grounded answer + "Validation: ✓ structured output is valid and sources support the answer." |
| Quiz generation and grading | **CONFIRMED (automated)** |
| Automated tests from a clean clone | **CONFIRMED (automated)** — 108 passed, 4 skipped |

## Setup result

- `uv venv --python 3.11 .venv` — **worked exactly as documented.**
- `uv pip install --python .venv/bin/python -r requirements-dashboard.txt` — **worked.**
- `.env` — the README says `cp .env.example .env` + "configure locally" but
  never says where the real values come from (the class endpoints file),
  which ports map to which variable, or that 9002/9004 need a `/v1` suffix
  (the endpoints file omits it; without it, upload fails with HTTP 404 on
  `/embeddings`; probing showed `/models` answers 200 only WITH `/v1`).
  Automation-only observation; undocumented knowledge was required.
- `.venv/bin/python -m src.app` — **worked** (when the default port was in
  use, Gradio bound the next free port; the documented port worked once
  freed).

## Materials + formats + LibreOffice

- Upload PDF/PPTX via Materials tab — **CONFIRMED (automated)** (21 slides
  rendered for the uploaded deck).
- Dedupe: re-upload → "already in the library (same content hash)" — **CONFIRMED (automated)**.
- PPTX→PDF conversion via an installed LibreOffice — **CONFIRMED (automated)** (21 images).
- README references `data/library/README.md` for formats/conversion steps —
  **file does not exist on master** (data/ is gitignored; nothing committed).
  Broken reference; now replaced by inline README documentation.

## Q&A (grounded, rerank ON, images ON)

- With the uploaded document selected — **CONFIRMED (browser)**: correct
  answer, "✓ structured output is valid and sources support the answer",
  5 gallery images returned.
- With NO document selected (documented default "empty selection = all
  materials") — **CONFIRMED (browser)**: the wire path sends an empty-string
  doc filter → zero candidates → the reranker rejects with HTTP 400
  ("At least one text_pair element must be given") → the UI shows "Something
  went wrong while searching the library…". Root cause: `answer_qa` turns `""`
  into `[""]` and filters everything out; the empty-default selection was not
  covered by the team's integration test (it always passes a concrete doc_id).
- Phantom documents — **CONFIRMED (browser)**: `master` tracks
  `outputs/manifest.json` and `outputs/chunks.json` (app-generated library
  state), so a fresh clone *starts* with 4 listed documents (from earlier
  team runs) that do not exist on disk. Selecting any phantom causes the same
  rerank 400; the remove dropdown even defaults to a phantom doc.

## Quiz

- Generate (1 Q, week5) — **CONFIRMED (automated)** (4 MCQ options rendered).
- Grade — **CONFIRMED (automated)**: "### Score: 0 / 1" with explanation and
  a cited source ("Week 5 deck · slide 7") plus excerpt.

## Tests

- The README contained **no command to run the automated tests** — only the
  passing claim "Test suite: 94 passed, 4 skipped" with no reproduction
  steps. (pytest is pinned in requirements-dashboard.txt.)
- Suite run from a clean clone: **108 passed, 4 skipped** — the README count
  was stale; now replaced with a dated baseline + "Running the tests"
  section.

## Fixes implemented on `maddie/fresh-copy-fixes` (summary, see PR diff)

1. **Phantom documents:** `.gitignore` now excludes `outputs/manifest.json`
   and `outputs/chunks.json`; both were removed from Git tracking; fresh
   clones start empty and the app recreates the files on first add (covered
   by `test_clean_library_starts_empty_and_creates_state_files`).
2. **Empty-selection Q&A:** `answer_qa` now normalizes `None` / `[]` / `""` /
   `[""]` to "all available materials"; the reranker is no longer called with
   zero candidates; genuine no-evidence cases return the normal honest
   message. Covered by new regression tests in `test_retrieval.py` and
   `test_mountain_integration.py`.
3. **README:** added "Running the tests" (`.venv/bin/python -m pytest -q`),
   endpoint→`.env` mapping table with an explicit `/v1` requirement on all
   base URLs (including 9002/9004), documented PDF/PPTX formats + LibreOffice
   conversion, replaced the broken `data/library/README.md` reference, and
   updated the stale test-count claim to a dated snapshot.

## Verification of isolation

- The existing repository, `maddie` branch, and PR #16 were not touched.
- No credentials appear anywhere in this file; only dummy values and public
  paths are referenced. Local work was performed in throwaway clones.
