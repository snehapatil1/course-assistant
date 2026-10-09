# Evaluation Plan (Draft) — MBAX 6418 Assignment 2, Course Assistant

**Status: DRAFT — for review, not a final report.**
The complete reranking comparison and final results are **still pending** (see §11).
No part of this document is committed, and the results tables are blank until
the controlled runs below are executed and verified.

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
  expected answer defined in §4?
- **Source support** — does every cited source exist, match the correct
  document/page/slide, and support the answer's claims (no fabricated
  citations, no invented answers)?
- **Visual evidence** — are the correct original slide/page images displayed
  alongside the answer?
- **Reranker value** — does the class reranker (port 9004) improve the
  top-k evidence actually supplied to the LLM versus keyword+vector fusion
  alone, holding every other setting fixed?
- **Honest failure behavior** — the one intentionally unanswerable question
  must produce an honest "not in the materials" response with no invention.

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
Q8 genuinely unanswerable. Document parsing stays local; port 9000 is never
used for these tasks.

---

## 3. Evaluation questions (exact wording, fixed order)

| # | Question (ask exactly this) |
|---|------------------------------|
| Q1 | What percentage of the final grade is the Final Project? |
| Q2 | Are late quiz submissions accepted, and what happens to your lowest quiz score? |
| Q3 | What is quantization, and why does it matter for LLMs? |
| Q4 | Find the meme about Vibe Coding on "Prod" in the Week 2 slides. Which slide is it on, and what does the image and its text show? |
| Q5 | What is the difference between zero-shot and few-shot prompting? |
| Q6 | What is RAG, and why would you use it? |
| Q7 | Describe the diagram on the slide: the hybrid RAG pipeline with reranking. What are the paths and stages shown? |
| Q8 | What default port number does a locally served Gradio app use? |

---

## 4. Expected answers and correct source page/slide

Verified against the exact locked files (Week 2/3/5 decks opened slide-by-slide;
syllabus PDF page-verified with PyMuPDF; meme and diagram confirmed visually).

| # | Expected answer | Correct source |
|---|-----------------|----------------|
| Q1 | 45% | Syllabus **p. 2** (grading table: Assignments 20% / Quizzes 15% / Final Project 45% / Final Exam 15% / Attendance & Participation 5% = 100%); matching "Final Project (45%)" section on **p. 3** |
| Q2 | No — late quiz submissions are not accepted for any reason; the lowest quiz score is dropped from the final grade | Syllabus **p. 3**, "Quizzes (15%)" |
| Q3 | Quantization scales/rounds model parameters from 16-bit (FP16/BF16) to 8-bit (FP8) or 4-bit (INT4), making models smaller and faster with little accuracy loss — e.g., Qwen3-Coder-30B-A3B-Instruct: 16-bit ~61GB → 8-bit ~31GB → 4-bit ~17GB | Week 2 **slides 15–16** (slide 21 for the efficiency/accuracy tradeoff) |
| Q4 | The meme is on Week 2 **slide 33**, titled "Vibe Coding on 'Prod'". The app must display the slide image and describe the *"One does not simply"* (Boromir) meme: **"ONE DOES NOT SIMPLY / VIBE CODE A PRODUCTION-GRADE ENTERPRISE APP"** — i.e., you cannot casually vibe-code a production-grade enterprise app | Week 2 **slide 33** (image on the slide; source link in speaker notes). Slide **34** ("Security? Never heard of it… How it started… How it's going…") is a different meme and is the known confusion trap |
| Q5 | Zero-shot provides no examples; one-shot/few-shot provide one or many examples. Deck also mentions positive vs. negative examples and contrastive prompting (Gao & Das 2024) | Week 3 **slide 20**, "Prompting for Basic Tasks" (33-slide deck) |
| Q6 | RAG retrieves relevant information from documents/databases/other sources and adds it to the model's context; it gives access beyond training data (recent/private info), grounds responses in sources, making answers verifiable and potentially reducing hallucinations | Week 5 **slides 10–11** |
| Q7 | Diagram shows: **Question → (Keyword Search / Embedding Model → Vector Search) → Candidate Chunks → Reranker → "Ranked Chunks With Source Details"**; phases labeled **Retrieval** and **Reranking**. The app must describe the two retrieval paths converging through the reranker | Week 5 **slide 18**, "Hybrid RAG Pipeline with Reranking" (diagram on the slide) |
| Q8 | (Unanswerable) App must state the materials don't cover it; must NOT answer "7860" and must not fabricate a citation. The syllabus (p. 2) only lists Gradio as an available package — no port number | No valid source exists in the locked set (only Week 4 — excluded — states 7860) |

---

## 5. Retrieval type exercised per question

| # | Keyword/text retrieval | Visual retrieval | Notes |
|---|------------------------|------------------|-------|
| Q1 | ✅ text | — | syllabus-only fact |
| Q2 | ✅ text | — | syllabus policy |
| Q3 | ✅ text | — | deck text (also the live E2E regression query) |
| Q4 | ◐ text (title) | ✅ **image (meme)** | must retrieve + display slide 33 image; vision must describe it |
| Q5 | ✅ text | — | deck text |
| Q6 | ✅ text | — | deck text |
| Q7 | ◐ text (caption) | ✅ **image (diagram)** | must retrieve + display slide 18; vision must read the diagram |
| Q8 | n/a | n/a | refusal test — no answer expected at all |

**Q4 and Q7 are the two required visual questions.** Q4 is the assignment's
required "Vibe Coding on Prod" meme question.

---

## 6. Correctness and source-support criteria

For every answerable question (Q1–Q7), the answer is judged **correct** only if
**all** of:

1. **Correctness** — the answer matches the expected answer in §4 (factually
   right; for Q5/Q6, the concept and terminology match the deck).
2. **Correct document/page** — the cited source is the exact document and
   page/slide listed in §4 (Q1/Q2 → syllabus p. 2/3; Q3 → W2 s15/16; Q4 → W2
   s33; Q5 → W3 s20; Q6 → W5 s10/11; Q7 → W5 s18).
3. **Source support** — the cited excerpt actually contains the evidence for
   the claim; the app's structured-output validator passes (`"✓ structured
   output is valid and sources support the answer"`). No hallucinated doc,
   page, or excerpt is acceptable.
4. **Visual displayed (Q4/Q7)** — the correct slide image (33 / 18) is shown
   in the evidence gallery.

For Q8, **correct** means the app explicitly says the information is not in
the available materials and provides no fabricated answer or citation.

**Fail conditions:** wrong doc/page; answer contradicted by its own excerpt;
missing source; validator failure; answer stated with no citation; visual
question answered without displaying the correct image; Q4 answered from
slide 34; Q8 answered with "7860" or any unsourced guess.

---

## 7. Controlled reranking-on vs. reranking-off procedure

Single controlled comparison: **the only variable changed between the two
runs is the `Use reranker` checkbox (class reranker, port 9004).** Every other
setting, input, and library state stays identical (see §8).

Procedure:

1. Confirm the library is exactly the four locked documents
   (manifest = 4 doc_ids, 103 units; §2).
2. **Run A — reranking ON:** for each question Q1→Q8 in order, ask through
   the app's Q&A tab (rerank checkbox checked, slide images sent to the
   model, topic field empty, all materials selected). Record per question:
   answer, cited sources, validator status, displayed images, response time.
3. **Run B — reranking OFF:** repeat the exact same eight questions in the
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

The comparison answers: *does the reranker change which slides/pages reach the
LLM, and does that change correctness or source support in either direction?*

---

## 8. Settings that must remain identical between both runs

| Setting | Value (fixed for both runs) |
|---------|------------------------------|
| Library corpus | exactly the 4 locked files in §2 (no adds/removes between runs) |
| Question set & order | Q1→Q8 exactly as in §3 |
| Topic filter | empty (not used) |
| Course-materials selector | all available materials (empty selection = all) |
| Chat/vision model | `cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit` (9001) |
| Text embeddings | `nvidia/Nemotron-3-Embed-1B-BF16` (9002) |
| Visual embeddings | `Qwen/Qwen3-VL-Embedding-2B` (9003) |
| Reranker (Run A only) | `Qwen/Qwen3-VL-Reranker-2B` (9004); Run B: checkbox off |
| Temperature | `LLM_TEMPERATURE=0` |
| Seed | `RANDOM_SEED=123` |
| Retrieval knobs | `TOP_K_KEYWORD=8`, `TOP_K_TEXT=8`, `TOP_K_VISUAL=6`, `TOP_K_FUSED=12`, `TOP_K_FINAL=5`, `RRF_K=60` |
| Slide images to model | same checkbox state in both runs |
| Interface | same Gradio app, same library state, no code changes between runs |

Anything that would differ (e.g., adding/removing a document, changing top-k,
editing a prompt file) invalidates the comparison and must be logged as a
violation. **The only intended difference between Run A and Run B is
`use_rerank`.**

---

## 9. Results table (blank — to be filled after the controlled runs)

| Question | Reranking setting | Correctness | Source support | Correct document/page | Visual displayed | Response time | Notes |
|----------|-------------------|-------------|----------------|------------------------|------------------|---------------|-------|
| Q1 | ON | | | | | | |
| Q1 | OFF | | | | | | |
| Q2 | ON | | | | | | |
| Q2 | OFF | | | | | | |
| Q3 | ON | | | | | | |
| Q3 | OFF | | | | | | |
| Q4 | ON | | | | | | |
| Q4 | OFF | | | | | | |
| Q5 | ON | | | | | | |
| Q5 | OFF | | | | | | |
| Q6 | ON | | | | | | |
| Q6 | OFF | | | | | | |
| Q7 | ON | | | | | | |
| Q7 | OFF | | | | | | |
| Q8 | ON | | | | | | |
| Q8 | OFF | | | | | | |

Each cell: ✅ / ❌ / n/a (Q8) — plus a note when a failure occurs. Response
time is approximate (diagnostic only, never a headline number).

---

## 10. Preliminary Smoke Testing

**Status: FAILED at retrieval — not a valid run, no results recorded.**

Two questions were attempted through the running app's Q&A tab (rerank ON,
images ON) as a pre-evaluation smoke test. The first question failed before
any answer was produced:

1. **Q3 (quantization) — FAILED at retrieval.** The app raised
   `chromadb.errors.InvalidArgumentError: Collection expecting embedding with
   dimension of 384, got 2048` inside `retrieve()` → `txt_col.query(...)`
   (before the reranker or LLM were reached). The UI surfaced the app's
   readable error message; no answer, sources, or validation were produced.
2. **Q4 (meme) — NOT attempted.** The failure is in the shared retrieval path
   used by every question (the text-collection query crashes on any query
   embedding), so Q4 would reproduce the identical error; per the "stop on
   failure" rule, no duplicate run was made.

**Root cause (read-only diagnosis, no code changed):** the `text_chunks`
Chroma collection was built with the wrong vector dimension. Direct probe of
`outputs/indexes/chroma/chroma.sqlite3` shows `text_chunks` expects **384**
dims while the class text embedder (Nemotron, 9002) produces **2048** dims.
`src/indexes.py:152` passes `embeddings=vecs if len(batch) == len(ids) else
None` — with 117 chunks in batches of 64 (64+53), the check is false on the
last batch, so Chroma embedded the documents itself with its default
384-dim `all-MiniLM-L6-v2` function instead of the class embedder's vectors.
The query leg then sends a 2048-dim query embedding into a 384-dim collection.

**Result: the smoke test could not validate any question.** No correctness,
source-support, or timing data was recorded (the request never reached the
LLM). The response-time measurement is therefore not applicable.

**Next action (pending approval):** fix `src/indexes.py` so the text index is
built with the class embedder's actual vectors (2048-dim, and align collection
creation accordingly), rebuild the vector indexes via the app's normal
`library rebuild`, then re-run this smoke test before any official runs.

---

## 11. Status: complete comparison and final results are pending

This document is a **draft plan only**. The controlled reranking-on/off
comparison (§7), the results table (§9), and any claims about answer quality
have **not** been produced yet. The smoke test (§10) failed at retrieval and
contributes **no** results. Final findings will be written to the README only
after: (a) the index fix is approved and applied, (b) the smoke test passes,
(c) both controlled runs execute and are verified against §4/§6, and
(d) this plan is converted into the final evaluation report.
