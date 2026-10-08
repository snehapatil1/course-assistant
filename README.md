# course-assistant

MBAX 6418: Business Generative AI and LLM Course Assistant

A generic, app-managed hybrid multimodal RAG app: students upload **their
own** course materials (PDF/PPTX), ask grounded questions with visual
evidence, and generate practice quizzes — built with Python (bm25s, ChromaDB,
Gradio) and the class services on `dobolyi.com:9001+`. No course file is
hardcoded anywhere; the corpus is whatever the user adds in the app.

> Detailed setup, usage, findings, and limitations follow below (in progress).
> See `PROGRESS.md` for the step-by-step build log.

## Default interface: Mountain Master

**Mountain Master is the main interface on the Meaghan branch**, combining the mountain dashboard design with the course backend. It includes **Q&A**, **Practice Quiz**, **Course Materials**, and a persistent **Light / Dark** appearance control. The interface displays the design label **Mountain v2**.

### Open on Windows

Download `Start Course Assistant.bat` from this page, place it in the `course-assistant` folder, then double-click it. It installs dependencies and opens the dashboard in your browser. Keep the window open while using the app.

For detailed dashboard instructions, see [README-DASHBOARD.md](README-DASHBOARD.md).

### Preview

**Light mode**

![Mountain Master — light](outputs/screenshots/mountain-master-qa-light.png)

**Dark mode**

![Mountain Master — dark](outputs/screenshots/mountain-master-qa-dark.png)

### Manual setup (macOS/Linux)

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-dashboard.txt
cp .env.example .env          # only if .env does not already exist; configure locally
.venv/bin/python -m src.app   # opens the default Mountain interface
```

On Windows, use `.venv\Scripts\python.exe` instead of `.venv/bin/python`. All launch methods use `src.app`; the older standalone dashboard modules are not alternate entry points.

**Materials management (works with zero configuration):** in the app's
Materials tab, upload PDF/PPTX files. The same file uploaded twice is a no-op
(content-hash dedupe); removing a document purges its text, images, and index
entries. PPTX files are converted with LibreOffice (install:
`brew install --cask libreoffice`; without it, export the deck to PDF and
upload that). See `data/library/README.md` for formats and conversion steps.

**Q&A and Quiz tabs activate once `.env` has the class endpoints** (vision
chat LLM, text/visual embeddings, multimodal reranker — `dobolyi.com:9001+`).
Until then the app clearly reports which services are missing.

## Architecture

![Product architecture](outputs/screenshots/architecture.png)

The app runs locally: the **Materials** tab ingests uploaded PDF/PPTX (dedupe
→ parse → render page/slide images → chunk → BM25 + text-vector +
visual-vector indexes), the **Q&A** tab retrieves evidence across the three
indexes (keyword always; vectors when configured), fuses with RRF, optionally
reranks, and answers with a vision LLM as structured `{answer, sources}`
(schema- and support-validated), showing the original slide images with
document + slide number; the **Quiz** tab generates MCQs from the selected
uploaded material with a fixed server-side answer key, scores, and
source-cited explanations. Interactive diagram: `docs/architecture.html`.

## Credentials

Real keys live only in the local, gitignored `.env` (dummy values in
`.env.example`). They are never shown in the UI, logs, errors, screenshots,
docs, or on GitHub.
