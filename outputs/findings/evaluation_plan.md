# Evaluation Plan (Frozen Design) — MBAX 6418 Assignment 2, Course Assistant

**Status: DESIGN FROZEN — the question set may not be changed after seeing
results.** The complete reranking comparison and final results are **still
pending** (see §11). This file is the locked evaluation design; it is not a
final report, and its results tables are blank until the controlled runs are
executed and verified.

---

## 1. Purpose of the evaluation

Evaluate whether the Course Assistant app answers questions accurately and
supports every answer with correct, verifiable evidence from a locked set of
course materials, and whether turning the class **reranker on vs. off**
changes retrieval and answer quality in a measurable, controlled way.

Specifically, the evaluation checks:

- **Retrieval quality** — does the app retrieve the right document, page, or
  slide for each question type (text, visual, hybrid)?
- **Answer correctness** — is the answer accurate and complete per the
  expected answer in §4?
- **Source support** — does every cited source exist, match the correct
  document/page/slide, and support the answer's claims (no fabricated
  citations, no invented answers)?
- **Visual evidence** — are the correct original slide/page images displayed
  alongside the answer?
- **Reranker value** — does the class reranker (port 9004) improve the
  evidence actually selected for the LLM versus keyword+vector fusion alone,
  holding every other setting fixed?
- **Honest failure behavior** — the single intentionally unanswerable
  question (Q10) must produce an honest "not in the materials" response with
  no invention.

The results determine what the README's findings section will claim. This is
**not** the final report and nothing here is a finished result.

---

## 2. Locked document set

Exactly four documents, and only these four, are in the local library
(`data/library/`, loaded via the app's own `library` CLI):

| # | File | Kind | Units | SHA-256 (recorded in manifest) |
|---|------|------|-------|--------------------------------|
| 1 | MBAX 6418 - Week 2 - LLM Fundamentals v2.pptx | slide | 42 | `1af2611e…8e62` |
| 2 | MBAX 6418 - Week 3 - Prompt Engineering v1 (1).pptx | slide | 33 | `7418bcd2…82f` |
| 3 | MBAX 6418 - Week 5 - Context Engineering and RAG v1.pptx | slide | 21 | `ea0fe406…6ff` |
| 4 | MBAX 6418 Syllabus Fall 2026.pdf | page | 7 | `0180dd94…c3dd` |

**Explicitly excluded from the evaluation corpus:** Week 4, Week 6, the
assignment instructions, and every other document. Week 4's "Serving" deck is
the only place the Gradio port (7860) appears; its exclusion is what makes
Q10 genuinely unanswerable. Document parsing stays local; port 9000 is never
used for these tasks.

---

## 3. Evaluation questions (frozen — exact wording, fixed order)

| # | Question (ask exactly this) |
|---|------------------------------|
| Q1 | If you turn in an assignment late, what is the penalty? |
| Q2 | What is quantization, and why does it matter for LLMs? |
| Q3 | What is the difference between vibe coding and agentic coding? |
| Q4 | What is the difference between zero-shot and few-shot prompting? |
| Q5 | What is RAG, and why would you use it? |
| Q6 | What chunking strategies do the materials describe? |
| Q7 | Looking at Week 2's "Popular Open Coding Models" table, which model has the most total parameters, and what total does the table report? |
| Q8 | Find the meme about Vibe Coding on "Prod" in the Week 2 slides. Which slide is it on, and what do the image and its text show? |
| Q9 | Describe the hybrid RAG pipeline diagram. What paths and stages does it show? |
| Q10 | What default port number does a locally served Gradio app use? |

**Frozen:** Q1–Q9 are answerable from the locked set (verified slide-by-slide
and page-by-page against the original files). **Q10 is the only intentionally
unanswerable question.** Q7, Q8, and Q9 are the **visual/hybrid** questions —
each requires the correct slide image to be retrieved and displayed (Q7 →
Week 2 slide 22 table image; Q8 → Week 2 slide 33 meme image; Q9 → Week 5
slide 18 diagram image).

---

## 4. Gold sources, alternates, distractors, retrieval type, and scoring criteria

Verified against the exact locked files (Week 2/3/5 decks opened slide-by-slide;
syllabus PDF page-verified with PyMuPDF; meme and diagram confirmed visually).

### Q1 — Late assignment penalty (text)
- **Question:** If you turn in an assignment late, what is the penalty?
- **Expected answer:** A 10% grade penalty per calendar day late (e.g., 80/100 →
  72/100 after one day `[.80 × .90 = .72]`, 64/100 after two days); assignments
  may not be turned in more than five days late; the lowest assignment score is
  dropped.
- **Gold source:** Syllabus **pp. 2–3**, "Assignments (20%)" — penalty formula
  on p. 2, five-day cap + dropped-lowest continuation at the top of p. 3.
- **Acceptable alternates:** either page alone (if the other half is still
  cited); syllabus p. 3 "Assignments" section header.
- **Likely distractors:** Syllabus p. 3 "Quizzes (15%)" — a *different* policy
  (no late submissions at all) that is a classic confusion trap.
- **Retrieval type:** text (keyword/text + vector).
- **Objective scoring criteria:** states 10%-per-calendar-day; example
  arithmetic correct; mentions the 5-day cap; mentions lowest-dropped; cites
  the syllabus (p. 2 and/or p. 3). Fail if it applies the quiz policy to
  assignments, states a wrong percentage, or cites no syllabus page.

### Q2 — Quantization (text)
- **Question:** What is quantization, and why does it matter for LLMs?
- **Expected answer:** Quantization scales/rounds model parameters from
  16-bit (FP16/BF16) to 8-bit (FP8) or 4-bit (INT4), making models smaller and
  potentially faster with little accuracy loss — e.g., Qwen3-Coder-30B-A3B-
  Instruct: 16-bit ~61GB → 8-bit ~31GB → 4-bit ~17GB. Formats (AWQ, GPTQ,
  GGUF, etc.) are chosen per hardware.
- **Gold source:** Week 2 **slides 15–16**.
- **Acceptable alternates:** Week 2 slide 21 (efficiency/accuracy tradeoff).
- **Likely distractors:** Week 2 slide 18 (reading a model name — contains
  "FP8"/quantization tokens), slides 22–23 (model tables that list quantized
  models).
- **Retrieval type:** text.
- **Objective scoring criteria:** names precision reduction (16→8/4-bit) AND
  the size/performance rationale; cites slide 15 or 16. Fail if the 61/31/17GB
  example is wrong, if it cites only a table slide, or if no slide is cited.

### Q3 — Vibe coding vs. agentic coding (text)
- **Question:** What is the difference between vibe coding and agentic coding?
- **Expected answer:** Vibe coding is human-in-the-loop, prompt-based,
  conversational, designed for intuitive ideation/creative exploration;
  agentic coding is autonomous, with goal-driven agents that plan, execute,
  test, and iterate, with minimal human input (Sapkota, Roumeliotis, & Karkee
  2025).
- **Gold source:** Week 2 **slide 30**, "Vibe Coding vs. Agentic Coding".
- **Acceptable alternates:** Week 2 slides 28–29 (vibe-coding framing).
- **Likely distractors:** Week 2 slide 19 ("Tool Calling/Tool Use/Agentic" —
  "agentic" appears without the comparison) and slide 36 ("AI coding agents…
  Agentic coding tools").
- **Retrieval type:** text (deliberate vocabulary collision: the word
  "agentic" appears on slides 19, 30, and 36; only 30 contains the contrast).
- **Objective scoring criteria:** contrasts BOTH columns (human-in-loop/
  prompt-based/conversational vs autonomous/goal-driven/planning-executing-
  testing-iterating); cites slide 30. Fail if it conflates the two, derives
  the answer from slide 19 or 36, or cites no slide.

### Q4 — Zero-shot vs. few-shot (text)
- **Question:** What is the difference between zero-shot and few-shot
  prompting?
- **Expected answer:** Zero-shot provides no examples; one-shot/few-shot
  provide one or many examples. The deck also recommends positive vs.
  negative examples and contrastive prompting (Gao & Das 2024).
- **Gold source:** Week 3 **slide 20**, "Prompting for Basic Tasks".
- **Acceptable alternates:** Week 3 slide 21 (few-shot example).
- **Likely distractors:** Week 3 slide 19 (a complete classification prompt
  — example-like but about prompt anatomy) and slide 23 (other prompting
  techniques).
- **Retrieval type:** text.
- **Objective scoring criteria:** distinguishes no-examples vs one/many-
  examples; cites slide 20. Fail if definitions are swapped, if it cites a
  template/anatomy slide as the source, or if no slide is cited.

### Q5 — RAG and why (text)
- **Question:** What is RAG, and why would you use it?
- **Expected answer:** RAG retrieves relevant information from documents,
  databases, and other data sources and adds it to the model's context to
  generate the response. It gives the model access beyond its training data
  (recent/private info), selects relevant material from a corpus, and grounds
  responses in sources — easier to verify, potentially reducing
  hallucinations.
- **Gold source:** Week 5 **slides 10–11**.
- **Acceptable alternates:** Week 5 slide 12 (use cases).
- **Likely distractors:** Week 5 slide 9 (section header), slide 13 (context
  optimization), slide 16 (preparing documents) — all contain the word RAG
  without the definition/why.
- **Retrieval type:** text.
- **Objective scoring criteria:** defines retrieve + add-to-context AND gives
  ≥1 why (beyond training data, grounding/verifiability, fewer
  hallucinations); cites slide 10 or 11. Fail if RAG is explained from memory
  contradicting the slides, or if only a header/distractor slide is cited.

### Q6 — Chunking strategies (text)
- **Question:** What chunking strategies do the materials describe?
- **Expected answer:** Fixed-size (set size, often with overlap); recursive
  (paragraph boundaries, then finer boundaries like sentences);
  document-based (keep related content together by structural boundaries such
  as headings); semantic (split by changing topics/meanings).
- **Gold source:** Week 5 **slide 17**, "Chunking: How Much Context Is
  Enough?".
- **Acceptable alternates:** none required (slide 17 is the only strategy
  list).
- **Likely distractors:** Week 5 slide 16 (defines chunking as a pipeline
  step but does not enumerate strategies) and slide 18 (mentions "candidate
  chunks").
- **Retrieval type:** text (the word "chunk" appears on slides 16/17/18).
- **Objective scoring criteria:** names ≥3 of the 4 strategies (fixed-size,
  recursive, document-based, semantic); cites slide 17. Fail if it answers
  with the parse/chunk/index pipeline (slide 16) or candidate-chunks pipeline
  (slide 18) as the strategy list.

### Q7 — Open coding models table (VISUAL/HYBRID)
- **Question:** Looking at Week 2's "Popular Open Coding Models" table, which
  model has the most total parameters, and what total does the table report?
- **Expected answer:** **Kimi K3** with **2,800B (2.8T) total parameters** per
  the table (1M context, MoE, 07/26). The table reports 2800 in the Params (B)
  column.
- **Gold source:** Week 2 **slide 22**, "Popular Open Coding Models (Aug
  2026)" table (read from the slide image).
- **Acceptable alternates:** none (only slide 22 contains the open-model
  table).
- **Likely distractors:** Week 2 slide 23 ("Popular Closed Coding Models" —
  params column is "?"), slide 6 (model size), slide 18 (model-name anatomy).
- **Retrieval type:** **visual/hybrid** — text key surfaces slide 22, but the
  answer must be read from the table **image**; the correct slide image must
  be displayed.
- **Objective scoring criteria:** names Kimi K3 AND reports 2,800B (or 2.8T);
  cites slide 22; slide 22 image displayed. Fail if it answers from the
  closed-model table (slide 23), reports a different model (e.g., GLM-5.2
  753B or MiniMax M3 428B), or cites a non-table slide.

### Q8 — "Vibe Coding on Prod" meme (VISUAL — REQUIRED)
- **Question:** Find the meme about Vibe Coding on "Prod" in the Week 2
  slides. Which slide is it on, and what do the image and its text show?
- **Expected answer:** The meme is on Week 2 **slide 33**, titled "Vibe Coding
  on 'Prod'". The app must display the slide image and describe the *"One does
  not simply"* (Boromir) meme: **"ONE DOES NOT SIMPLY / VIBE CODE A
  PRODUCTION-GRADE ENTERPRISE APP"** — i.e., you cannot casually vibe-code a
  production-grade enterprise app.
- **Gold source:** Week 2 **slide 33** (image on the slide; source link in
  speaker notes).
- **Acceptable alternates:** none.
- **Likely distractors:** Week 2 **slide 34** ("Security? Never heard of it…
  How it started… How it's going…" — a different two-panel meme; the known
  confusion trap).
- **Retrieval type:** **visual** (image retrieval + vision description, with
  the slide-34 trap).
- **Objective scoring criteria:** cites slide 33; displays the slide-33
  image; summary matches the meme (production vs vibe-coding contrast, "one
  does not simply"); does not describe slide 34. Fail if it cites slide 34,
  shows the wrong image, or invents meme details not visible in the image.

### Q9 — Hybrid RAG pipeline diagram (VISUAL)
- **Question:** Describe the hybrid RAG pipeline diagram. What paths and
  stages does it show?
- **Expected answer:** Question → two retrieval paths (Keyword Search;
  Embedding Model → Vector Search) → Candidate Chunks → Reranker → "Ranked
  Chunks With Source Details"; phases labeled Retrieval and Reranking.
- **Gold source:** Week 5 **slide 18**, "Hybrid RAG Pipeline with Reranking"
  (diagram on the slide).
- **Acceptable alternates:** none (the diagram is the evidence).
- **Likely distractors:** Week 5 slide 17 (chunking) and slide 16 (preparing
  documents).
- **Retrieval type:** **visual** (diagram retrieval + vision reading).
- **Objective scoring criteria:** cites slide 18; displays the slide-18
  image; describes both retrieval paths converging through the reranker to
  ranked chunks. Fail if only one path is described, the reranker stage is
  omitted, or a different slide is cited.

### Q10 — Gradio default port (ONLY unanswerable question)
- **Question:** What default port number does a locally served Gradio app
  use?
- **Expected answer:** No answer from the materials. The app must state the
  information is not in the available materials, must NOT answer "7860"
  (which appears only in Week 4 — excluded), and must not cite the syllabus's
  single mention of "Gradio" (p. 2, package list only) as evidence of a port.
- **Gold source:** none exists in the locked set.
- **Acceptable alternates:** none.
- **Likely distractors:** Syllabus p. 2 (mentions Gradio as an open-source
  package — no port number).
- **Retrieval type:** n/a (refusal test).
- **Objective scoring criteria:** explicitly declines ("not in the materials"
  or equivalent); produces no port number; produces no fabricated citation.
  Fail if it answers 7860, guesses any port, or invents a source.

**General fail conditions (Q1–Q9):** wrong doc/page; answer contradicted by
its own excerpt; missing source; structured-output validation failure; answer
stated with no citation; visual question answered without displaying the
correct image; Q8 answered from slide 34.

---

## 5. Retrieval type exercised per question

| # | Keyword/text | Visual | Notes |
|---|--------------|--------|-------|
| Q1 | ✅ | — | syllabus policy + arithmetic; quiz-policy distractor |
| Q2 | ✅ | — | deck text; distractor slides 18/22/23 |
| Q3 | ✅ | — | "agentic" vocabulary collision across s19/30/36 |
| Q4 | ✅ | — | "example"-rich neighbor slides 19/21/23 |
| Q5 | ✅ | — | RAG-term spread across s9–s18 |
| Q6 | ✅ | — | "chunk" collision on s16/17/18 |
| Q7 | ◐ (text key) | ✅ **table image (s22)** | answer read from the table image |
| Q8 | ◐ (title key) | ✅ **meme image (s33)** | required meme; s34 trap |
| Q9 | ◐ (caption key) | ✅ **diagram image (s18)** | diagram comprehension |
| Q10 | n/a | n/a | refusal test — no answer expected |

**Q7, Q8, and Q9 are the visual/hybrid questions; each requires the correct
slide image to be displayed.** Q8 is the assignment's required meme question.

---

## 6. Correctness and source-support criteria (summary)

For Q1–Q9, an answer is **correct** only if **all** of:

1. **Correctness** — the answer matches the expected answer in §4 (factually
   right; concepts/terminology match the deck).
2. **Correct document/page** — the cited source is the exact document and
   page/slide listed in §4 (Q1 → syllabus pp. 2–3; Q2 → W2 s15/16; Q3 → W2
   s30; Q4 → W3 s20; Q5 → W5 s10/11; Q6 → W5 s17; Q7 → W2 s22; Q8 → W2 s33;
   Q9 → W5 s18).
3. **Source support** — the cited excerpt actually contains the evidence; the
   app's structured-output validator passes ("✓ structured output is valid
   and sources support the answer"). No hallucinated doc, page, or excerpt is
   acceptable.
4. **Visual displayed (Q7/Q8/Q9)** — the correct slide image (22 / 33 / 18)
   is shown in the evidence gallery.

For Q10, **correct** means the app explicitly says the information is not in
the available materials and provides no fabricated answer or citation.

**Fail conditions:** wrong doc/page; answer contradicted by its own excerpt;
missing source; validator failure; answer stated with no citation; visual
question answered without displaying the correct image; Q8 answered from
slide 34; Q10 answered with "7860" or any unsourced guess.

---

## 7. Controlled reranking-on vs. reranking-off procedure

Single controlled comparison: **the only variable changed between the two
runs is the `Use reranker` checkbox (class reranker, port 9004).** Every other
setting, input, and library state stays identical (see §8).

Procedure:

1. Confirm the library is exactly the four locked documents
   (manifest = 4 doc_ids, 103 units; §2).
2. **Run A — reranking ON:** for each question Q1→Q10 in order, ask through
   the app's Q&A tab (rerank checkbox checked, slide images sent to the
   model, topic field empty, all materials selected). Record per question:
   answer, cited sources, validator status, displayed images, response time.
3. **Run B — reranking OFF:** repeat the exact same ten questions in the
   exact same order with the rerank checkbox unchecked and everything else
   identical. Record the same fields.
4. **Do not interleave** the two runs; complete Run A fully before Run B so
   the rerank state cannot drift mid-run.
5. Verify each recorded answer against §4 and §6; fill the results table (§9)
   with the pass/fail outcome per criterion.
6. Note on repeatability: the chat calls run at `temperature 0`
   (config `LLM_TEMPERATURE=0`), which reduces variation between runs, but
   exact repeatability is **not guaranteed** — the chat request does not send
   a `seed` parameter, so the serving framework may produce different outputs
   across identical requests. A second pass of one run may be used to check
   stability informally, but the reported numbers come from the single logged
   pass of each setting and are not claimed to be byte-identical on rerun.

**Expected-source rank vs. displayed-source position:** the results table
records **expected-source rank** only if the evaluation harness exposes the
actual retrieval ordering for each question. Otherwise the table records
**displayed-source position** (the order in which sources appear in the UI
evidence gallery), which is explicitly **not** raw retrieval rank.

The comparison answers: *does the reranker change which slides/pages reach the
LLM, and does that change correctness or source support in either direction?*

---

## 8. Settings that must remain identical between both runs

| Setting | Value (fixed for both runs) |
|---------|------------------------------|
| Library corpus | exactly the 4 locked files in §2 (no adds/removes between runs) |
| Question set & order | Q1→Q10 exactly as in §3 |
| Topic filter | empty (not used) |
| Course-materials selector | all available materials (empty selection = all) |
| Chat/vision model | `cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit` (9001) |
| Text embeddings | `nvidia/Nemotron-3-Embed-1B-BF16` (9002) |
| Visual embeddings | `Qwen/Qwen3-VL-Embedding-2B` (9003) |
| Reranker (Run A only) | `Qwen/Qwen3-VL-Reranker-2B` (9004); Run B: checkbox off |
| Temperature | `LLM_TEMPERATURE=0` |
| Retrieval knobs | `TOP_K_KEYWORD=8`, `TOP_K_TEXT=8`, `TOP_K_VISUAL=6`, `TOP_K_FUSED=12`, `TOP_K_FINAL=5`, `RRF_K=60` |
| Slide images to model | same checkbox state in both runs |
| Interface | same Gradio app, same library state, no code changes between runs |

Anything that would differ (e.g., adding/removing a document, changing top-k,
editing a prompt file) invalidates the comparison and must be logged as a
violation. **The only intended difference between Run A and Run B is
`use_rerank`.**

---

## 9. Results table (blank — one row per question per reranking setting)

Columns: Question · Reranking · Expected-source rank OR displayed-source
position (see §7) · Expected source present · Correct document/page ·
Irrelevant displayed sources · Source-support quality · Answer correctness ·
Visual correctness (Q7–Q9) · Structured-output validation · Response time ·
Notes.

| Q | Rerank | Rank/position | Expected source present | Correct doc/page | Irrelevant sources | Source support | Answer | Visual | Validated | Time | Notes |
|---|--------|---------------|-------------------------|------------------|--------------------|----------------|--------|--------|-----------|------|-------|
| Q1 | ON | | | | | | | | | | |
| Q1 | OFF | | | | | | | | | | |
| Q2 | ON | | | | | | | | | | |
| Q2 | OFF | | | | | | | | | | |
| Q3 | ON | | | | | | | | | | |
| Q3 | OFF | | | | | | | | | | |
| Q4 | ON | | | | | | | | | | |
| Q4 | OFF | | | | | | | | | | |
| Q5 | ON | | | | | | | | | | |
| Q5 | OFF | | | | | | | | | | |
| Q6 | ON | | | | | | | | | | |
| Q6 | OFF | | | | | | | | | | |
| Q7 | ON | | | | | | | | | | |
| Q7 | OFF | | | | | | | | | | |
| Q8 | ON | | | | | | | | | | |
| Q8 | OFF | | | | | | | | | | |
| Q9 | ON | | | | | | | | | | |
| Q9 | OFF | | | | | | | | | | |
| Q10 | ON | | | | | | | | | | |
| Q10 | OFF | | | | | | | | | | |

Each cell: ✅ / ❌ / n/a (Q10). Response time is approximate (diagnostic only,
never a headline number).

---

## 10. Smoke testing

### 10.1 Initial smoke test — FAILED at retrieval (record preserved)

The first smoke test attempted the quantization question (then Q3 of the
original 8-question set) through the Q&A tab (rerank ON, images ON). It
failed before any answer was produced: `chromadb.errors.InvalidArgumentError:
Collection expecting embedding with dimension of 384, got 2048` inside
`retrieve()` → `txt_col.query(...)` — before the reranker or LLM were
reached. The meme question (then Q4) was not attempted because the failure is
in the shared retrieval path used by every question.

**Root cause (read-only diagnosis, no code changed at the time):** the
`text_chunks` Chroma collection was built with the wrong vector dimension.
Direct probe of `outputs/indexes/chroma/chroma.sqlite3` showed `text_chunks`
expected **384** dims while the class text embedder (Nemotron, 9002) produces
**2048** dims. `src/indexes.py` passed `embeddings=vecs if len(batch) ==
len(ids) else None` — with 117 chunks in batches of 64 (64+53), the check was
false on the last batch, so Chroma embedded the documents itself with its
default 384-dim `all-MiniLM-L6-v2` function instead of the class embedder's
vectors. The query leg then sent a 2048-dim query embedding into a 384-dim
collection.

**Status — RESOLVED:** PR #13 (merged into `maddie`; commits `aae718c` +
`7c198e7`, local merge `3248e5e`) fixed the multi-batch text-vector
dimension bug in `src/indexes.py` (the full embedding array is now accumulated
and upserted explicitly). The library was rebuilt successfully with the fix,
and verified on disk: `text_chunks` and `visual_pages` are both **2048-dim**,
with 117 text vectors and 103 visual vectors. The PR's regression tests
(`tests/test_vector_indexes.py`) now pass — 4 passed — and the full
automated suite passes (103 passed, 0 failed, 4 skipped).

### 10.2 Follow-up smoke test — SUCCESS (manual interface testing)

After the fix and rebuild, the quantization question and the meme question
(original-set Q3/Q4; frozen-set Q2/Q8) were tested manually through the
running interface. Both returned answers with validated structured output and
correctly displayed source slide images; the meme question reported the
correct slide (Week 2 slide 33) and described the "One does not simply"
meme.

**UI limitations observed during manual testing (noted; not yet fixed):**
- **Unclear document names** — displayed document labels are not clearly
  identifiable.
- **Broken evidence icon** — the source-evidence icon fails to render.
- **Cropped/zoomed slide presentation** — displayed slide images appear
  cropped or zoomed rather than shown intact.
- **Raw filenames/hashes** — source captions expose raw filenames and/or
  hash-derived identifiers.
- **Extra gallery images** — additional gallery images are shown that are
  not clearly tied to the cited sources.

These are presentation/UX defects in evidence display — not retrieval or
answer-quality failures. They should be reported as limitations and re-checked
after any UI fix, but they do not change the frozen question set.

---

## 11. Status: complete comparison and final results are pending

This document is the **frozen evaluation design**, not a final report. The
controlled reranking-on/off comparison (§7), the results table (§9), and any
claims about answer quality have **not** been produced yet. The smoke test
(§10) is recorded: the initial failure was fixed by PR #13 (verified: rebuild
succeeded, 2048-dim collections, regression tests pass), and the follow-up
manual smoke test passed while exposing UI display limitations that are not
yet fixed. Final findings will be written to the README only after: (a) both
controlled runs execute and are scored against §4/§6, (b) the table in §9 is
filled and verified, and (c) this design is converted into the final
evaluation report. The question set is frozen and will not be changed after
seeing results.
