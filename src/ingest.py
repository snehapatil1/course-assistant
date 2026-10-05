"""Ingestion: parse PDFs and PPTX into per-page records, chunk text, and
(in a later step) render original page/slide images for visual evidence.

Outputs
-------
* ``outputs/manifest.json`` - one record per page/slide with the full text,
  metadata, and the image path (image itself rendered by a renderer step).
* ``outputs/chunks.json`` - retrieval chunks derived from the manifest
  (a slide is one chunk; long PDF pages are split with overlap).

Accepted formats
----------------
* PDF (text layer)
* PPTX (shapes, tables, grouped shapes, speaker notes)

No key is required for text extraction; rendering images is a separate,
pluggable step (class parsing service or LibreOffice).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf  # PyMuPDF
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from src.config import MATERIALS_DIR, PAGES_DIR, PROJECT_ROOT, TEXT_DIR

PAGE_IMAGE_PATTERN = r"(?i)\.(pdf|pptx?)$"


# --------------------------------------------------------------------------- #
# PPTX extraction
# --------------------------------------------------------------------------- #
def _shape_text(shape, seen=None) -> str:
    """Recursively collect text from a shape (text frame, table, group)."""
    if seen is None:
        seen = set()
    if shape.shape_id in seen:
        return ""
    seen.add(shape.shape_id)
    parts: list[str] = []

    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        for sub in shape.shapes:
            parts.append(_shape_text(sub, seen))
        return "\n".join(p for p in parts if p.strip())

    if shape.has_text_frame:
        for para in shape.text_frame.paragraphs:
            line = "".join(run.text for run in para.runs)
            if line.strip() or para.text.strip():
                parts.append(para.text.strip())

    if shape.has_table:
        rows = []
        for row in shape.table.rows:
            cells = [c.text.strip() for c in row.cells]
            rows.append(" | ".join(cells))
        parts.append("\n".join(rows))

    return "\n".join(p for p in parts if p)


def extract_pptx(path: Path) -> list[dict]:
    """Return one record per slide: {page_no, text, notes, kind='slide'}."""
    prs = Presentation(str(path))
    records: list[dict] = []
    for idx, slide in enumerate(prs.slides, start=1):
        texts: list[str] = [_shape_text(sh) for sh in slide.shapes]
        body = "\n".join(t for t in texts if t.strip()).strip()
        notes = ""
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        records.append({"page_no": idx, "kind": "slide", "text": body, "notes": notes})
    return records


# --------------------------------------------------------------------------- #
# PDF extraction
# --------------------------------------------------------------------------- #
def extract_pdf(path: Path) -> list[dict]:
    """Return one record per page: {page_no, text, notes='', kind='page'}."""
    records: list[dict] = []
    with pymupdf.open(str(path)) as doc:
        for idx in range(len(doc)):
            page = doc[idx]
            text = str(page.get_text("text") or "").strip()
            records.append({"page_no": idx + 1, "kind": "page", "text": text, "notes": ""})
    return records


EXTRACTORS = {".pptx": extract_pptx, ".pdf": extract_pdf}


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return s or "doc"


def ingest_all() -> list[dict]:
    """Parse every file in data/materials into a manifest of page records."""
    files = sorted(MATERIALS_DIR.iterdir())
    if not files:
        raise FileNotFoundError(f"no materials found in {MATERIALS_DIR}")

    pages: list[dict] = []
    for f in files:
        if not f.is_file() or not re.search(PAGE_IMAGE_PATTERN, f.name):
            print(f"[skip ] {f.name} (unsupported format)")
            continue
        extractor = EXTRACTORS.get(f.suffix.lower())
        if extractor is None:
            print(f"[skip ] {f.name} (no extractor)")
            continue
        doc_id = f.stem
        records = extractor(f)
        for rec in records:
            page_id = f"{doc_id}__p{rec['page_no']:04d}"
            image_rel = f"outputs/pages/{page_id}.png"
            pages.append(
                {
                    "page_id": page_id,
                    "doc": doc_id,
                    "doc_title": f.name,
                    "source_file": f.name,
                    "kind": rec["kind"],
                    "page_no": rec["page_no"],
                    "text": rec["text"],
                    "notes": rec["notes"],
                    "image_path": image_rel,
                }
            )
        kind = records[-1]["kind"] if records else "?"
        print(f"[ok   ] {f.name}: {len(records)} {'slides' if kind=='slide' else 'pages'}")
    return pages


def write_manifest(pages: list[dict], manifest_path: Path) -> Path:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest_path


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #
@dataclass
class Chunk:
    chunk_id: str
    doc: str
    doc_title: str
    source_file: str
    kind: str
    page_no: int
    text: str
    image_path: str
    section: str = ""
    chunk_of: str = ""  # page_id this chunk belongs to (for PDF sub-chunks)
    extra: dict = field(default_factory=dict)


PDF_CHUNK_CHARS = 1100
PDF_CHUNK_OVERLAP = 120


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Small recursive splitter (no external dep needed for PDF pages)."""
    text = text.strip()
    if len(text) <= chunk_size:
        return [text] if text else []
    # split on paragraph boundaries first for cleaner breaks
    for sep in ("\n\n", "\n", ". ", " "):
        idx = text.rfind(sep, 0, chunk_size)
        if idx > chunk_size // 2:
            head, tail = text[: idx + len(sep)], text[idx + len(sep):]
            tail = (head[-overlap:] + tail) if overlap else tail
            return [head] + _split_long_text(tail, chunk_size, overlap)
    return [text[:chunk_size]] + _split_long_text(text[chunk_size:], chunk_size, overlap)


def build_chunks(pages: list[dict]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in pages:
        text = (page["text"] + "\n\n" + page["notes"]).strip()
        if not text:
            continue
        base = {
            "doc": page["doc"],
            "doc_title": page["doc_title"],
            "source_file": page["source_file"],
            "kind": page["kind"],
            "page_no": page["page_no"],
            "image_path": page["image_path"],
        }
        if page["kind"] == "slide" or len(text) <= PDF_CHUNK_CHARS:
            cid = f"{page['doc']}__p{page['page_no']:04d}__c0001"
            chunks.append(Chunk(chunk_id=cid, text=text, chunk_of=page["page_id"], **base))
        else:
            parts = _split_long_text(text, PDF_CHUNK_CHARS, PDF_CHUNK_OVERLAP)
            for i, part in enumerate(parts, start=1):
                cid = f"{page['doc']}__p{page['page_no']:04d}__c{i:04d}"
                chunks.append(
                    Chunk(chunk_id=cid, text=part, chunk_of=page["page_id"], **base)
                )
    return chunks


def write_chunks(chunks: list[Chunk], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(c) for c in chunks], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parse course materials into manifest + chunks.")
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "outputs")
    args = ap.parse_args(argv)

    manifest_path = args.out / "manifest.json"
    chunks_path = args.out / "chunks.json"

    pages = ingest_all()
    write_manifest(pages, manifest_path)
    chunks = build_chunks(pages)
    write_chunks(chunks, chunks_path)

    n_slides = sum(1 for p in pages if p["kind"] == "slide")
    n_pages = sum(1 for p in pages if p["kind"] == "page")
    n_empty = sum(1 for p in pages if not (p["text"] or p["notes"]).strip())
    print(f"\nmanifest.json: {len(pages)} units ({n_slides} slides, {n_pages} pdf pages, {n_empty} empty text)")
    print(f"chunks.json  : {len(chunks)} chunks")
    print(f"  -> {manifest_path}")
    print(f"  -> {chunks_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
