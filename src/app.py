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

import gradio as gr

from src import config, library, qa, quiz, retrieve

MAX_QUESTIONS = 5
_QUIZ_STORE: dict[str, dict] = {}  # server-side only: key never leaves here


def _doc_choices() -> list[tuple[str, str]]:
    docs = library.list_documents()
    return [("All materials", "")] + [
        (f"{d['title']} ({d['units']} pages/slides, {d['images']} imgs)", d["doc_id"])
        for d in docs
    ]


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
            gr.Dropdown(choices=_doc_choices(), value=None))


def on_remove(doc_id: str, files) -> tuple[str, gr.Dropdown]:
    if not doc_id:
        return "Select a document to remove first.", gr.Dropdown(choices=_doc_choices(), value=None)
    return (library.remove_document(doc_id)["message"],
            gr.Dropdown(choices=_doc_choices(), value=None))


def refresh_docs() -> gr.Dropdown:
    return gr.Dropdown(choices=_doc_choices(), value=None)


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
    candidates = retrieve.retrieve(
        query, docs=[doc_id] if doc_id else None, use_rerank=rerank
    )
    if not candidates:
        return ("No matching material found in the library for this question. "
                "Try a different question or add more documents in the Materials tab."), [], gr.update()

    result = qa.answer_question(question, candidates, include_images=images_on)

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
        return _endpoint_status_md(), *radios, ""
    if n_questions < 1 or n_questions > MAX_QUESTIONS:
        return f"Choose between 1 and {MAX_QUESTIONS} questions.", *radios, ""

    chunks = json.loads((config.PROJECT_ROOT / "outputs" / "chunks.json").read_text(encoding="utf-8"))
    if material:
        chunks = [c for c in chunks if c["doc"] == material]
    if not chunks:
        return ("No chunks found for the selected material - add documents in the "
                "Materials tab first."), *radios, ""

    doc_title = next((d["title"] for d in library.list_documents() if d["doc_id"] == material),
                     material or "All materials")
    qz = quiz.generate_quiz(doc_title, chunks, n_questions, topic=topic)
    _QUIZ_STORE[qz["quiz_id"]] = qz
    view = quiz.to_client_view(qz)

    md = [f"### Quiz {view['quiz_id']} — {view['material_title']}"]
    if view["topic"]:
        md.append(f"*topic: {view['topic']}*")
    for i, qview in enumerate(view["questions"], start=1):
        md.append(f"**Q{i}.** {qview['question']}")
    md.append("")
    md.append("Answer below, then press **Grade quiz**. Solutions are shown only after grading.")

    upd = [
        gr.update(visible=True, choices=qview["options"], label=f"Q{i + 1}")
        for i, qview in enumerate(view["questions"])
    ]
    upd += [gr.update(visible=False, choices=[]) for _ in range(MAX_QUESTIONS - len(upd))]
    return "\n\n".join(md), *upd, view["quiz_id"]


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
                  f"Your answer: {r['your_answer']} · correct option: "
                  f"{qz['questions'][r['id']]['options'][qz['questions'][r['id']]['key']]}  \n"
                  f"*Why:* {r['explanation']}  \n"
                  f"Source: `{r['chunk_ref']}`")
    return "\n\n".join(md)


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
def build_app() -> gr.Blocks:
    with gr.Blocks(title="Course Assistant") as demo:
        gr.Markdown("# Course Assistant\n"
                    "Answers questions and generates practice quizzes from **your** uploaded course materials.")

        with gr.Tab("Materials"):
            with gr.Row():
                upload = gr.Files(label="Upload PDF or PPTX (same file twice is a no-op)",
                                  file_types=[".pdf", ".pptx"], file_count="multiple")
            status = gr.Textbox(label="Status", lines=4)
            with gr.Row():
                doc_dropdown = gr.Dropdown(choices=_doc_choices(), label="Documents in library",
                                           interactive=True, scale=3)
                remove_btn = gr.Button("Remove selected document", scale=1)
            gr.Markdown("**Supported formats:** PDF (text layer) and PPTX. PPTX slides are converted "
                        "to PDF with LibreOffice (`soffice`) and rendered as images; if LibreOffice is "
                        "missing, export the deck to PDF manually and upload that. Removing a document "
                        "deletes its text, images, and index entries.")
            upload.change(on_upload, inputs=[upload], outputs=[status, doc_dropdown])
            remove_btn.click(on_remove, inputs=[doc_dropdown, upload], outputs=[status, doc_dropdown])

        with gr.Tab("Q&A"):
            with gr.Row():
                qa_material = gr.Dropdown(choices=_doc_choices(), label="Material filter", scale=2)
                qa_topic = gr.Textbox(label="Topic filter (optional)", placeholder="e.g. quantization", scale=2)
                qa_rerank = gr.Checkbox(label="Use reranker", value=True)
                qa_images = gr.Checkbox(label="Send slide images to the model", value=True)
            qa_question = gr.Textbox(label="Your question", lines=2,
                                     placeholder="e.g. What does the diagram on slide 12 show?")
            qa_btn = gr.Button("Answer")
            qa_answer = gr.Markdown()
            qa_gallery = gr.Gallery(label="Original slide/page images (document + slide number)",
                                    columns=2, height="auto")
            qa_btn.click(answer_qa,
                         inputs=[qa_question, qa_material, qa_topic, qa_rerank, qa_images],
                         outputs=[qa_answer, qa_gallery, qa_material])

        with gr.Tab("Quiz"):
            with gr.Row():
                quiz_material = gr.Dropdown(choices=_doc_choices(), label="Material (choose one)", scale=2)
                quiz_topic = gr.Textbox(label="Topic (optional)", scale=2)
                quiz_n = gr.Slider(1, MAX_QUESTIONS, value=3, step=1, label="Number of questions", scale=1)
            quiz_btn = gr.Button("Generate quiz from my materials")
            quiz_view = gr.Markdown()
            quiz_radios = [gr.Radio(label=f"Q{i + 1}", visible=False) for i in range(MAX_QUESTIONS)]
            quiz_id_box = gr.Textbox(label="Quiz id", visible=False)
            grade_btn = gr.Button("Grade quiz", visible=True)
            quiz_result = gr.Markdown()
            quiz_btn.click(generate_quiz_ui,
                           inputs=[quiz_material, quiz_topic, quiz_n],
                           outputs=[quiz_view, *quiz_radios, quiz_id_box])
            grade_btn.click(grade_quiz, inputs=[quiz_id_box, *quiz_radios], outputs=[quiz_result])

    return demo


if __name__ == "__main__":
    build_app().launch()
