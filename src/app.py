"""Gradio interface: Materials · Q&A · Quiz.

Guidelines implemented:
* Users manage course materials in-app: add and remove documents; loading the
  same file twice is a no-op (content-hash dedupe); removing a document purges
  its searchable content, images, and index rows.
* Q&A retrieves evidence (keyword + vector legs when configured) and shows the
  original page/slide images with the document name and slide number; users can
  ask the app to explain slide content (pictures, diagrams, charts) - the
  slide image is sent to the vision LLM.
* Quiz generates from the student's uploaded materials; the answer key is
  fixed server-side and solutions are hidden until answered.

Local features always work; vector search, vision Q&A, and quiz generation
activate when the class endpoints are configured in ``.env`` (run
``cp .env.example .env`` and fill in real values).
"""
from __future__ import annotations

import json
import base64
from html import escape
from pathlib import Path
import os
import sys
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
from src.dashboard import Source

import gradio as gr

from src import config, library, qa, quiz, retrieve

MAX_QUESTIONS = 5
_QUIZ_STORE: dict[str, dict] = {}  # server-side only: key never leaves here

# A single, self-contained "Generating Quiz..." indicator rendered INSIDE the
# quiz workspace. Gradio's own progress bars accumulate duplicates on repeat
# clicks, so this flow avoids gr.Progress entirely.
_QUIZ_LOADING_HTML = """
<style>
@keyframes quizProgress {
  from { transform: translateX(-10%); }
  to   { transform: translateX(200%); }
}
</style>
<div style="width:100%; text-align:center; padding:18px 0;">
  <div style="font-size:15px; color:#94a3b8;">Generating Quiz...</div>
  <div style="width:min(360px, 80%); margin:12px auto 0; height:8px; border-radius:999px;
              background:rgba(148,163,184,0.18); overflow:hidden;">
    <div style="width:36%; height:100%; border-radius:999px;
                background:linear-gradient(90deg,#22d3ee,#34d399);
                animation:quizProgress 1.1s ease-in-out infinite alternate;">
    </div>
  </div>
</div>
"""

# Quiz layout rules, delivered INSIDE every quiz workspace update. Gradio's
# Markdown sanitizer strips <style> tags and page-head CSS only applies to
# tabs loaded after the last restart, so the workspace uses gr.HTML and these
# rules travel with each generation - a stale tab always renders the same
# compact layout. Scoped to #quiz-workspace so nothing leaks to other tabs.
_QUIZ_LAYOUT_CSS = """
#quiz-workspace {gap:10px!important;}
#quiz-workspace > .block.panel-title {padding:0!important;}
#quiz-workspace > .block:nth-child(2) {margin-top:-10px!important;} /* title flush under the heading */
#quiz-workspace > .block.panel-title :is(h1,h2,h3,h4) {margin:2px 0!important;}
#quiz-workspace .quiz-headline {margin:0 0 2px 0!important;font-size:17px;line-height:1.35;}
#quiz-workspace .quiz-sub {margin:0 0 2px 0!important;font-size:13px;color:#64748b;}
#quiz-workspace .prose {margin:0!important;}
#quiz-workspace .block {margin:0!important;padding-top:4px!important;}
#quiz-workspace .form fieldset {padding:2px 0!important;}
#quiz-workspace .block [data-testid="block-info"] {margin:0!important;padding:2px 0!important;line-height:1.35!important;}
#quiz-workspace .form .wrap {padding-top:0!important;gap:2px!important;}
#quiz-workspace label {margin:0!important;padding:3px 2px!important;min-height:0!important;line-height:1.35!important;}
#quiz-workspace label span {display:inline!important;}
#quiz-workspace [data-testid="status-tracker"],
#quiz-workspace .progress-text {display:none!important;}
#quiz-workspace input[type=radio] {flex-shrink:0;margin-top:4px;}
#quiz-workspace .wrap {overflow:visible!important;white-space:normal!important;}
"""


def _doc_choices() -> list[tuple[str, str]]:
    docs = library.list_documents()
    return [
        (f"{d['title']} ({d['units']} pages/slides, {d['images']} imgs)", d["doc_id"])
        for d in docs
    ]


def _inventory_choices() -> list[tuple[str, str]]:
    return [(f"{d['title']} — {d['status']} [{d['doc_id']}]", d['doc_id'])
            for d in library.list_inventory()]


def _qa_quiz_choices() -> list[tuple[str, str]]:
    return [(f"{d['title']} — {d['status']} [{d['doc_id']}]", d['doc_id'])
            for d in library.list_inventory()]


def _endpoint_status_md() -> str:
    lines = [
        "## Class endpoints status",
        f"- Chat (vision LLM): {'✓ configured' if retrieve.endpoint_ready('chat') else '✗ not configured'}",
        f"- Text embeddings: {'✓ configured' if retrieve.endpoint_ready('text_embed') else '✗ not configured'}",
        f"- Visual embeddings: {'✓ configured' if retrieve.endpoint_ready('visual_embed') else '✗ not configured'}",
        f"- Reranker: {'✓ configured' if retrieve.endpoint_ready('rerank') else '✗ not configured'}",
        "",
        "Copy `.env.example` to `.env` and set the real class endpoint values, then restart the app.",
        "Materials upload/remove and keyword search work without any endpoints.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Materials tab
# --------------------------------------------------------------------------- #
def on_upload(files) -> tuple[str, gr.Dropdown]:
    messages = []
    for f in files or []:
        try:
            messages.append(library.add_document(f.name)["message"])
        except ValueError as exc:
            messages.append(f"skipped {f.name}: {exc}")
    return ("\n".join(messages) if messages else "no files to add",
            gr.Dropdown(choices=_inventory_choices(), value=None))


def on_remove(doc_id: str, files) -> tuple[str, gr.Dropdown]:
    if not doc_id:
        return "Select a document to remove first.", gr.Dropdown(choices=_inventory_choices(), value=None)
    return (library.remove_document(doc_id)["message"],
            gr.Dropdown(choices=_inventory_choices(), value=None))


def refresh_docs() -> gr.Dropdown:
    return gr.Dropdown(choices=_inventory_choices(), value=None)


# --------------------------------------------------------------------------- #
# Q&A tab
# --------------------------------------------------------------------------- #
def answer_qa(question: str, doc_id: str, topic: str, rerank: bool,
              images_on: bool) -> tuple[str, list, gr.Dropdown]:
    if not question.strip():
        return "Ask a question first.", [], gr.update()
    if not retrieve.endpoint_ready("chat"):
        return _endpoint_status_md(), [], gr.update()

    query = f"{topic}: {question}" if topic.strip() else question
    try:
        candidates = retrieve.retrieve(
            query, docs=([doc_id] if isinstance(doc_id, str) else doc_id) or None, use_rerank=rerank
        )
    except Exception as exc:  # noqa: BLE001 - surface honest, readable errors
        import traceback

        traceback.print_exc()
        return (f"Something went wrong while searching the library: {exc} "
                f"(details in outputs/app.log). If the library is empty, add "
                f"materials in the Materials tab first."), [], gr.update()
    if not candidates:
        return ("No matching material found in the library for this question. "
                "Try a different question or add more documents in the Materials tab."), [], gr.update()

    try:
        result = qa.answer_question(question, candidates, include_images=images_on)
    except Exception as exc:  # noqa: BLE001 - surface honest, readable errors
        import traceback

        traceback.print_exc()
        return (f"Something went wrong while generating the answer: {exc} "
                f"(details in outputs/app.log)."), [], gr.update()

    md = ["## Answer", result["answer"] or "_(empty response)_", ""]
    md.append("**Validation:** " + (
        "✓ structured output is valid and sources support the answer"
        if result["valid"] else "✗ " + "; ".join(result["validation_errors"])
    ))
    md.append("")
    md.append("## Sources")
    for s in result["sources"]:
        md.append(f"- **{s.get('doc_title') or s.get('doc')}** — "
                  f"{'slide' if s.get('kind') == 'slide' else 'page'} {s.get('page_no')}: "
                  f"> {s.get('excerpt', '')}")
    md.append("")
    md.append("## Retrieved slide images")
    gallery = []
    for c in candidates:
        img = config.PROJECT_ROOT / c.image_path
        if img.exists():
            gallery.append((str(img), f"{c.doc_title} — slide/page {c.page_no}"))
    return "\n\n".join(md) if md else "", gallery, gr.update()


# --------------------------------------------------------------------------- #
# Quiz tab
# --------------------------------------------------------------------------- #
def generate_quiz_ui(material: str, topic: str, n_questions: int):
    radios = [gr.update(visible=False, choices=[]) for _ in range(MAX_QUESTIONS)]
    if not retrieve.endpoint_ready("chat"):
        return _endpoint_status_md(), *radios, "", gr.update(interactive=True)
    if n_questions < 1 or n_questions > MAX_QUESTIONS:
        return f"Choose between 1 and {MAX_QUESTIONS} questions.", *radios, "", gr.update(interactive=True)

    chunks_path = config.PROJECT_ROOT / "outputs" / "chunks.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.exists() else []
    if material:
        selected = [material] if isinstance(material, str) else material
        chunks = [c for c in chunks if c["doc"] in selected]
    if not chunks:
        return (f"No chunks found for the selected material - add documents in the "
                "Materials tab first."), *radios, "", gr.update(interactive=True)

    selected = ([material] if isinstance(material, str) else material) or []
    doc_title = ", ".join(d["title"] for d in library.list_documents() if d["doc_id"] in selected) if selected else "All available materials"

    try:
        qz = quiz.generate_quiz(doc_title, chunks, n_questions, topic=topic)
    except Exception as exc:  # noqa: BLE001 - surface honest, readable errors
        import traceback

        traceback.print_exc()
        return (f"Something went wrong while generating the quiz: {exc} "
                f"(details in outputs/app.log)."), *radios, "", gr.update(interactive=True)
    _QUIZ_STORE[qz["quiz_id"]] = qz
    view = quiz.to_client_view(qz)

    parts = [f"<style>{_QUIZ_LAYOUT_CSS}</style>",
             f"<h3 class='quiz-headline'>Quiz {view['quiz_id']} — {view['material_title']}</h3>"]
    if view["topic"]:
        parts.append(f"<p class='quiz-sub'>topic: {escape(view['topic'])}</p>")
    parts.append("<p class='quiz-sub'>(Answer below, then press <strong>Grade quiz</strong>. "
                 "Solutions are shown only after grading.)</p>")
    if qz.get("topic_note"):
        parts.append(f"<p class='quiz-note' style='margin:4px 0 0;font-size:12.5px;"
                     f"color:#b45309;line-height:1.4;'>{escape(qz['topic_note'])}</p>")

    upd = [
        gr.update(visible=True, choices=qview["options"], label=f"Q{i + 1}. {qview['question']}")
        for i, qview in enumerate(view["questions"])
    ]
    upd += [gr.update(visible=False, choices=[]) for _ in range(MAX_QUESTIONS - len(upd))]
    return "".join(parts), *upd, view["quiz_id"], gr.update(interactive=True)


def grade_quiz(quiz_id: str, *radio_values):
    if not quiz_id or quiz_id not in _QUIZ_STORE:
        return "Generate a quiz first."
    qz = _QUIZ_STORE[quiz_id]
    answers: dict[int, int] = {}
    for i in range(qz["n"]):
        chosen = radio_values[i] if i < len(radio_values) else None
        if chosen is not None:
            answers[i] = qz["questions"][i]["options"].index(chosen)
    if len(answers) < qz["n"]:
        missing = sorted(set(range(qz["n"])) - set(answers))
        return (f"⚠ Not all questions answered (missing Q{', Q'.join(map(str, [m + 1 for m in missing]))}). "
                "Unanswered questions count as incorrect.")

    result = quiz.grade(qz, answers)
    md = [f"### Score: {result['score']} / {result['total']}"]
    for r in result["details"]:
        mark = "✅" if r["correct"] else "❌"
        md.append(f"{mark} **{r['question']}**  \n"
                  f"Your answer: {r['your_answer'] + 1 if r['your_answer'] is not None else '—'} · "
                  f"correct option: "
                  f"{qz['questions'][r['id']]['options'][qz['questions'][r['id']]['key']]}  \n"
                  f"*Why:* {r['explanation']}  \n"
                  f"Source: `{r['chunk_ref']}`")
    return "\n\n".join(md)


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[1]
CSS = """
.gradio-container {max-width:1240px!important; margin:auto!important;}
.course-header {display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border-color-primary);padding:18px 0 24px;margin-bottom:14px;gap:16px;}
.course-header h1 {font-size:34px;font-weight:600;margin:5px 0;color:var(--body-text-color);line-height:1.2;}
.eyebrow {font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--body-text-color-subdued);}
.course-header p {margin:8px 0 0;color:var(--body-text-color-subdued);font-size:15px;}
.pill {border:1px solid var(--border-color-primary);background:var(--background-fill-secondary);padding:9px 14px;border-radius:24px;font-size:13px;white-space:nowrap;}
.overview {font-size:14px;color:var(--body-text-color-subdued);margin:4px 0 22px;}
.overview strong {color:var(--body-text-color);}
.workspace {padding-top:20px!important;gap:28px!important;}
.sidebar {background:var(--background-fill-secondary)!important;border:1px solid var(--border-color-primary)!important;padding:20px!important;border-radius:12px!important;}
.panel-title {font-size:21px!important;color:var(--body-text-color)!important;}
.answer-box,.evidence-empty {background:var(--block-background-fill);border:1px solid var(--border-color-primary);border-radius:12px;padding:24px;color:var(--body-text-color-subdued);min-height:115px;}
.answer-box {white-space:pre-wrap;line-height:1.7;color:var(--body-text-color);}
.empty-heading {font-size:19px;color:var(--body-text-color);margin-bottom:8px;font-weight:600;}
.source-card {border:1px solid var(--border-color-primary);border-radius:12px;background:var(--block-background-fill);padding:22px;margin:14px 0;}
.source-card h3 {margin:0 0 6px;font-size:18px;color:var(--body-text-color);}
.source-location {font-size:13px;color:var(--body-text-color-subdued);margin-bottom:14px;}
.source-excerpt {white-space:pre-wrap;line-height:1.65;background:var(--background-fill-secondary);padding:16px;border-radius:7px;}
.source-card img {max-width:100%;max-height:720px;object-fit:contain;display:block;margin:16px auto;}
.hint {color:var(--body-text-color-subdued);font-size:13px;line-height:1.6;}
button {min-height:44px!important;}
footer {display:none!important;}
@media(max-width:650px) {.course-header {align-items:flex-start;flex-direction:column;}.course-header h1{font-size:28px;}.workspace{gap:16px!important;}}
"""
# Embed only this trusted decorative asset. No directory is exposed by Gradio.
_mountain = base64.b64encode((ROOT / 'src/assets/rocky-mountains.jpg').read_bytes()).decode('ascii')
CSS += ':root {--ca-mountain-photo:url("data:image/jpeg;base64,' + _mountain + '");}'
CSS += (ROOT / 'src/dashboard.css').read_text(encoding='utf-8')
THEME_JS = """(mode) => {
    let saved = null;
    try { saved = localStorage.getItem('course-assistant-theme'); } catch (_) {}
    const selected = mode || (saved === 'Dark' ? 'Dark' : 'Light');
    document.documentElement.classList.toggle('dark', selected === 'Dark');
    document.body.classList.toggle('dark', selected === 'Dark');
    document.documentElement.dataset.courseTheme = selected.toLowerCase();
    try { localStorage.setItem('course-assistant-theme', selected); } catch (_) {}
    return selected;
}"""
EMPTY_ANSWER = '<div class="answer-box"><div class="empty-heading">Start with a question</div>Choose your materials and ask about a concept, a reading, or a course requirement.</div>'
EMPTY_SOURCES = '<div class="evidence-empty"><div class="empty-heading">Evidence, not guesswork</div>Supporting passages and original page or slide images will appear here, separately from the answer.</div>'


def text_html(text: str) -> str:
    return f'<div class="answer-box">{escape(text)}</div>' if text else EMPTY_ANSWER


def source_html(sources: list[Source]) -> str:
    if not sources:
        return EMPTY_SOURCES
    cards = []
    for s in sources:
        image = '<p class="hint">Original image unavailable. The excerpt above is from the course material.</p>'
        if s.image:
            try:
                data = base64.b64encode(Path(s.image).read_bytes()).decode('ascii')
                mime = 'image/png' if Path(s.image).suffix.lower() == '.png' else 'image/jpeg'
                image = f'<img src="data:{mime};base64,{data}" alt="Original source: {escape(s.title)} — {escape(s.location)}">'
            except OSError:
                pass
        cards.append(f'<article class="source-card"><h3>{escape(s.title)}</h3><div class="source-location">{escape(s.location)}</div><div class="source-excerpt">{escape(s.excerpt)}</div>{image}</article>')
    return ''.join(cards)


def answer_dashboard(question, doc_id, topic, rerank, images_on):
    """Adapt the master answer callback to separate answer/evidence cards."""
    text, images, _ = answer_qa(question or '', doc_id or '', topic or '', rerank, images_on)
    answer, separator, sources = text.partition('\n\n## Sources')
    sources = sources.removesuffix('\n\n## Retrieved slide images').strip()
    return answer, sources if separator else 'Supporting passages appear here after a grounded answer.', images


def library_overview():
    docs = library.list_documents()
    return '<div class="overview"><strong>{}</strong> materials &nbsp; / &nbsp; <strong>{}</strong> pages &amp; slides &nbsp; / &nbsp; <strong>{}</strong> original images</div>'.format(len(docs), sum(d['units'] for d in docs), sum(d['images'] for d in docs))


def library_inventory_html():
    records = library.list_inventory()
    rows = ''.join(
        f'<tr data-doc-id="{escape(d["doc_id"], quote=True)}"><td>{escape(d["title"])}'
        f'<small>{escape(d["doc_id"])}</small></td><td>{d["units"]}</td>'
        f'<td>{escape(d["status"])}</td></tr>' for d in records)
    available = sum(d['original_available'] for d in records)
    return (f'<p class="hint">{len(records)} inventory records · {available} originals stored locally. '
            'Study selectors include active processed documents only. Removal uses one explicit target and is guarded when historical metadata exists. Index-only records '
            'are not ready materials; re-upload the original to process them. Different document IDs '
            'are shown separately, even when titles refer to the same lecture.</p>'
            '<table><thead><tr><th>Material / document ID</th><th>Pages / slides</th><th>Status</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>')


def refresh_library_ui():
    return (gr.update(choices=_inventory_choices(), value=None),
            *[gr.update(choices=_qa_quiz_choices(), value=[], multiselect=True) for _ in range(2)],
            library_overview(), library_inventory_html())


def upload_dashboard(files):
    message, _ = on_upload(files)
    return message, *refresh_library_ui()


def remove_dashboard(doc_id):
    message, _ = on_remove(doc_id, None)
    return message, *refresh_library_ui()


def build_app() -> gr.Blocks:
    with gr.Blocks(title='Course Assistant', analytics_enabled=False) as demo:
        with gr.Row(elem_id='topbar'):
            gr.HTML('<div class="brand"><span class="brand-mark" aria-hidden="true">⌁</span><div>Course Assistant<small>MBAX 6418 · STUDY WORKSPACE</small></div></div>')
            theme_mode = gr.Radio(['Light', 'Dark'], value='Light', label='Appearance', elem_id='theme-mode', scale=0, min_width=210)
        demo.load(fn=None, outputs=theme_mode, js=THEME_JS)
        theme_mode.change(fn=None, inputs=theme_mode, js=THEME_JS)
        gr.HTML('<header class="course-header"><div><div class="eyebrow">A clearer path to understanding</div><h1>Your course. In focus.</h1><p>Ask with context. Study with evidence. Practice at your pace.</p></div></header>')
        overview = gr.HTML(library_overview())
        with gr.Tab('Q&A'):
            with gr.Row(elem_classes='workspace'):
                with gr.Column(scale=1, min_width=220, elem_classes='sidebar', elem_id='qa-filters'):
                    gr.Markdown('### Study focus', elem_classes='panel-title')
                    qa_material = gr.Dropdown(choices=_qa_quiz_choices(), value=[], multiselect=True, info='Empty selection = All available materials. Select multiple to narrow scope.', label='Course materials', interactive=True)
                    qa_topic = gr.Textbox(label='Topic (optional)', placeholder='e.g. quantization')
                    qa_rerank = gr.Checkbox(label='Use reranker', value=True)
                    qa_images = gr.Checkbox(label='Send slide images to the model', value=True)
                    gr.HTML('<div class="study-note"><span class="note-icon">↗</span><strong>A more focused question.<br>A more useful answer.</strong><p>Select a reading or topic to narrow your study session.</p></div>')
                    with gr.Accordion('Class endpoint configuration', open=False):
                        gr.Markdown(_endpoint_status_md())
                        gr.Markdown('Configured means settings are present, not a network health check.', elem_classes='hint')
                with gr.Column(scale=2, min_width=360, elem_classes='dashboard-card', elem_id='qa-workspace'):
                    gr.Markdown('### Ask a question', elem_classes='panel-title')
                    question = gr.Textbox(label='Your question', lines=4, placeholder='What does the diagram on slide 12 show?')
                    with gr.Row():
                        ask = gr.Button('Ask question', variant='primary', scale=2)
                        clear = gr.Button('Clear', scale=1)
                    gr.Markdown('### Answer', elem_classes='panel-title')
                    answer = gr.Markdown('Choose your materials and ask about a concept, a reading, or a course requirement.', elem_classes='answer-box')
                with gr.Column(scale=1, min_width=260, elem_classes='dashboard-card', elem_id='qa-evidence'):
                    gr.Markdown('### Source evidence', elem_classes='panel-title')
                    evidence = gr.Markdown('Supporting passages appear here after a grounded answer.', elem_classes='evidence-empty')
                    gallery = gr.Gallery(label='Original slide/page images (document + slide number)', columns=1, height='auto')
        with gr.Tab('Practice Quiz'):
            with gr.Row(elem_classes='workspace'):
                with gr.Column(scale=1, min_width=220, elem_classes='sidebar', elem_id='quiz-filters'):
                    gr.Markdown('### Set your practice focus', elem_classes='panel-title')
                    quiz_material = gr.Dropdown(choices=_qa_quiz_choices(), value=[], multiselect=True, info='Empty selection = All available materials. Select multiple to narrow scope.', label='Quiz materials', interactive=True)
                    quiz_topic = gr.Textbox(label='Quiz topic (optional)')
                    quiz_n = gr.Slider(1, MAX_QUESTIONS, value=3, step=1, label='Number of questions')
                    create = gr.Button('Create practice quiz', variant='primary')
                    gr.Markdown('Choose one answer per question. Solutions stay server-side until grading.', elem_classes='hint')
                with gr.Column(scale=3, min_width=360, elem_classes='dashboard-card', elem_id='quiz-workspace'):
                    gr.Markdown('### Practice workspace', elem_classes='panel-title')
                    quiz_view = gr.HTML('A little practice goes a long way. Choose your focus, then create a quiz.')
                    radios = [gr.Radio(label=f'Q{i + 1}', visible=False, interactive=True) for i in range(MAX_QUESTIONS)]
                    quiz_id = gr.State('')
                    grade = gr.Button('Grade quiz', variant='primary')
                with gr.Column(scale=1, min_width=220, elem_classes='dashboard-card', elem_id='quiz-evidence'):
                    gr.Markdown('### Review & evidence', elem_classes='panel-title')
                    result = gr.Markdown('Your score, explanations, and source references appear after you answer and grade your quiz.')
        with gr.Tab('Course Materials'):
            with gr.Row(elem_classes='workspace'):
                with gr.Column(scale=1, min_width=260, elem_classes='sidebar'):
                    gr.Markdown('### Add materials', elem_classes='panel-title')
                    upload = gr.Files(label='Upload PDF or PPTX', file_types=['.pdf', '.pptx'], file_count='multiple')
                    save = gr.Button('Save materials', variant='primary')
                    refresh = gr.Button('Refresh library')
                with gr.Column(scale=3, min_width=360, elem_classes='dashboard-card'):
                    gr.Markdown('### Your course library', elem_classes='panel-title')
                    inventory = gr.HTML(library_inventory_html(), elem_id='library-inventory')
                    doc_dropdown = gr.Dropdown(choices=_inventory_choices(), label='Documents in library (single removal target)', interactive=True)
                    remove = gr.Button('Remove selected document')
                    status = gr.Textbox(label='Library status', lines=4, interactive=False)
                    gr.Markdown('PDF text and PPTX are parsed, rendered and indexed by the course backend. Identical content is added only once. PPTX rendering requires LibreOffice; otherwise export to PDF first. Removing a document deletes its stored original, text, images and index entries.', elem_classes='hint')
        gr.Markdown('Course Assistant · Check supporting evidence. Practice is not a graded assessment.', elem_classes='hint', elem_id='app-footnote')
        qa_inputs = [question, qa_material, qa_topic, qa_rerank, qa_images]
        ask.click(answer_dashboard, qa_inputs, [answer, evidence, gallery], api_name='ask')
        question.submit(answer_dashboard, qa_inputs, [answer, evidence, gallery], api_name=False)
        clear.click(lambda: ('', 'Ready for a new question.', 'Supporting passages appear here after a grounded answer.', []), outputs=[question, answer, evidence, gallery], api_name=False)
        # single click chain: first event blanks the workspace (markdown AND
        # any previous quiz's radio options) and shows ONE custom
        # "Generating Quiz..." bar; the second generates. gr.Progress is
        # deliberately not used - it stacked duplicate bars on repeat clicks.
        # The button is disabled while a generation is in flight so repeated
        # clicks can never interleave two generations.
        create.click(
            lambda: (_QUIZ_LOADING_HTML,
                     *[gr.update(visible=False, choices=[]) for _ in range(MAX_QUESTIONS)],
                     gr.update(interactive=False)),
            outputs=[quiz_view, *radios, create],
            show_progress='hidden', api_name=None).then(
            generate_quiz_ui, [quiz_material, quiz_topic, quiz_n],
            [quiz_view, *radios, quiz_id, create], api_name='create_quiz',
            show_progress='hidden')
        grade.click(grade_quiz, [quiz_id, *radios], result, api_name='grade_quiz')
        library_outputs = [doc_dropdown, qa_material, quiz_material, overview, inventory]
        save.click(upload_dashboard, upload, [status, *library_outputs], api_name='save_materials')
        remove.click(remove_dashboard, doc_dropdown, [status, *library_outputs], api_name='remove_material')
        refresh.click(refresh_library_ui, outputs=library_outputs, api_name='refresh_library')
    return demo


def main() -> None:
    build_app().queue(default_concurrency_limit=1).launch(
        server_name='127.0.0.1', server_port=None, share=False,
        inbrowser='--no-browser' not in sys.argv, show_error=False,
        head=f'<style>{CSS}</style>', theme=gr.themes.Soft(primary_hue='blue'),
        footer_links=[], blocked_paths=[str(ROOT / '.env'), str(ROOT / '.git')])


if __name__ == '__main__':
    main()
