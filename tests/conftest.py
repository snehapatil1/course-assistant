"""Shared fixtures: synthetic student documents (no course files involved)."""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from pptx import Presentation


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    """A tiny 2-page PDF about RAG (a stand-in for a student's notes)."""
    path = tmp_path / "my_lecture_notes.pdf"
    doc = pymupdf.open()
    for text in (
        "Introduction to retrieval augmented generation.",
        "Retrieval augmented generation combines search with generation for accurate answers.",
    ):
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def pptx_file(tmp_path: Path) -> Path:
    """A tiny 3-slide deck (a stand-in for a student's slides)."""
    path = tmp_path / "my_deck.pptx"
    prs = Presentation()
    blank = prs.slide_layouts[6]
    for text in ("Slide one: course overview", "Quantization reduces model size",
                 "Few-shot prompting examples"):
        slide = prs.slides.add_slide(blank)
        box = slide.shapes.add_textbox(914400, 914400, 5000000, 1100000)
        box.text_frame.text = text
    prs.save(str(path))
    return path
