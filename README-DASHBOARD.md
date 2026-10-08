# Course Assistant — Meaghan dashboard

Mountain v2 combines the custom mountain interface and Light/Dark appearance with the backend from master.

## Launch on Windows

Double-click **Start Course Assistant.bat**. Keep its window open while using the app. First setup requires internet and Python 3.11+ or uv and installs dashboard plus backend dependencies. Use the browser window that opens or the local address printed in the launcher. A free port is selected when older copies are running.

## Use

- **Q&A:** choose material and an optional topic; ask a question. Answers and evidence are separate, with original images when available.
- **Practice Quiz:** choose material, topic and question count, generate questions, answer every question, then select **Grade quiz**. Keys remain server-side during generation; feedback includes score, explanations and source references.
- **Course Materials:** upload PDFs/PPTX, refresh or remove materials. Master’s backend processes text, renders images and builds indexes. Identical content is deduplicated. Removing a material removes its stored original, text, images and index entries. PPTX rendering requires LibreOffice; export to PDF as an alternative.
- **Appearance:** Light/Dark selection persists for the same browser address and port. Mountains are decoration, not evidence.

Class services require server-side configuration. Follow README.md and .env.example. Keep real credentials only in ignored local .env or server environment; never publish them. Configured status does not prove service connectivity.

## Development

src/app.py uses master’s library, retrieval, Q&A and quiz modules. Styling is in src/dashboard.css; decorative image attribution is in src/assets/ATTRIBUTION.md.

```bat
.venv\Scripts\python.exe -m src.app
.venv\Scripts\python.exe -m pytest -q
```

For Git Bash use .venv/Scripts/python.exe.

Verification: 58 tests passed, 4 skipped, with upstream pandas warnings. Live AI requests were not verified by this run. Browser checks covered all tabs, Light/Dark persistence, three-column layout, empty questions and mobile overflow.

Current previews in outputs/screenshots use the mountain-master- prefix: qa-light, qa-dark, quiz-light, quiz-dark, library-light, library-dark and mobile-dark PNG files. Earlier dashboard-* screenshots and standalone dashboard modules are retained as development history. The launch entry point is src.app.
