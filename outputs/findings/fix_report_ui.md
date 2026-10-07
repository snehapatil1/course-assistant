## Step 7 — UI bug fixes (Q&A error + quiz progress) (2026-10-07)

User-reported issues and their root causes (both found in logs, both fixed):

1. **Q&A "Answer" button error.**
   `chromadb.errors.InvalidArgumentError: Collection expecting embedding with
   dimension of 2048, got 384`. The text collection holds 2048-dim Nemotron
   vectors, but `retrieve()` queried it with `query_texts=...`, which makes
   Chroma embed the query with its default 384-dim MiniLM function -> crash.
   Fix: query the text collection with `query_embeddings` produced by the
   class embedder (same as the visual leg already did); embed once and reuse
   for both legs; short-circuit when the library is empty. Also wrapped both
   app handlers in try/except so any future failure renders a readable
   message in the UI (with traceback in outputs/app.log) instead of a red
   error banner.

2. **Quiz generation "super slow, no progress".** The LLM call takes 30-120s
   (reasoning model) with zero feedback. Fix: `gr.Progress` stages in the
   quiz handler ("Selecting chunks…", "Calling the class LLM to write the
   questions… (this can take a minute or two)", "Quiz ready"); exceptions
   surface as readable messages. Verified mid-flight: the progress bar showed
   "Calling the class LLM… - 30.0%".

**Also investigated:** the week-2 deck reappeared in the library after the
cleanup. Timestamps prove it was re-uploaded THROUGH the app's upload
handler at 13:07-13:08 (file copied 13:07:30, manifest written 13:08:03) -
no CLI add ran in that window, so it came from the UI (a browser re-upload
while testing). Removed it again; the library is empty.

**Verified live (browser, after fixes):**
- Q&A on a synthetic 1-page doc: "Hybrid search combines keyword and vector
  retrieval." + "✓ structured output is valid" + source (doc + page +
  excerpt) - no error banner.
- Quiz: progress indicator visible during generation; 1 question generated
  with 4 options; grading rendered "Score: 0/1" with explanation + cited
  chunk for a deliberately wrong pick.
- Cleanup after verification: test doc removed -> manifest 0, chunks 0,
  pages 0, chroma text/visual 0, library empty; app restarted fresh.
- `python -m pytest -q` still 37 passed (hermetic suite).

**Commits:** pushed to `sneha`.
