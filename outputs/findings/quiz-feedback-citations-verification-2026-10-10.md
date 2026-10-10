# Quiz feedback citations — manual + automated verification (2026-10-10)

Branch: `katherine/quiz-improvements` (uncommitted changes; HEAD == origin/master)
Scope: quiz grading feedback cites stored source metadata; workspace reset on new quiz.

## Observed results (manual GUI test)

Manual quiz test in the running app (local Gradio `127.0.0.1:7860`), material
= Week 2 "LLM Fundamentals" deck, topic = quantization:

- Three quantization questions were generated and graded **3/3**.
- Each graded question's feedback showed a **Source** citation with the real
  document title, slide number, and a supporting excerpt of the stored chunk
  text (e.g. `MBAX 6418 - Week 2 - LLM Fundamentals v2.pptx · slide 15`).
- Requesting a **new quiz cleared the previous quiz's feedback** (score,
  explanations, source references, and radio selections all reset).

Screenshot evidence (saved to `outputs/screenshots/`, contents confirmed via
local OCR — model has no vision):

| File | Content (OCR-confirmed) |
|---|---|
| `quiz-graded-3of3-quantization-score-evidence.png` | "Review & evidence · Score: 3 / 3"; Q1: 16→8→4-bit precision effect on storage; your answer 1 ✓; why + source: Week 2 deck, slide 15; excerpt: "Quantization is a process for scaling and rounding model parameters…" |
| `quiz-feedback-quantization-formats-gguf-slide16.png` | Q2: quantization format recommended for CPU+GPU incl. Apple M chips; correct: GGUF; source: slide 16; excerpt: "Quantization Formats — Various quantization formats exist…" |
| `quiz-feedback-reading-model-name-fp8-slide18.png` | Q3: meaning of `-FP8` suffix in `Qwen3-Coder-30B-A3B-Instruct-FP8`; correct: quantization precision; source: slide 18; excerpt: "Reading a Model Name…" |

The three questions match the topic-driven chunk selection path (quantization
blocks from slides 15/16/18 ranked first).

## Automated test verification (this session)

- `python -m pytest tests/test_quiz.py tests/test_dashboard.py -v`
  → **34 passed, 2 skipped** (5.47s). Skipped = pre-existing gradio-client
  integration tests (skip condition unchanged).
- `python -m pytest tests/ -q` (full suite, endpoints hermetic via conftest)
  → **108 passed, 4 skipped** in 11.77s. Warnings are pre-existing pandas
  deprecations from gradio's queueing layer.
- New/updated tests covering this change:
  - `test_generate_quiz_stores_source_metadata` — chunk_map carries stored
    doc_title / page_no / kind / excerpt.
  - `test_grading_cites_stored_metadata_never_model_text` — citations come
    from the stored chunk, never the model's explanation string.
  - `test_grading_unknown_ref_degrades_without_crashing` — unresolvable
    `chunk_ref` → `{"resolved": False}`, UI renders honest fallback.
  - `test_generate_quiz_ids_do_not_collide_for_identical_inputs` — unique
    per-generation `quiz_id` so identical inputs never overwrite a stored
    answer key.
  - `test_new_quiz_clears_previous_quiz_state` — `_QUIZ_STORE` cleared and
    workspace/review column reset the instant a new quiz is requested.
  - Updated: `test_generate_quiz_stub_chat`, `test_client_view_hides_solutions`
    (canonical_id; `chunk_map`/`primary_key`/`raw` never reach the client).

## Completed vs. not yet completed

**Completed / verified:**
- [x] Manual: 3/3 graded quiz with title + slide + excerpt citations (3 screenshots).
- [x] Manual: generating a new quiz clears the previous quiz's feedback.
- [x] Automated: quiz + dashboard suites green; full suite green (108 passed).
- [x] Credential discipline: `.env` gitignored/untracked; no keys in any file
      or output; screenshots contain UI/course material only.

**Not yet completed (honest gaps):**
- [ ] PR not opened; branch not pushed; no teammate review or CI run yet.
- [ ] "Failed generation must not leave the previous quiz gradable" is covered
      by unit test only — not exercised live with an induced generation failure.
- [ ] The "cleared feedback" moment itself was observed by eye but not captured
      as a screenshot (the 3 saved shots show graded states).
- [ ] 2 gradio-client tests remain skipped (pre-existing); manual re-check of
      the Library/QA tabs was not repeated this session (unit-level coverage
      is green via the full suite).
