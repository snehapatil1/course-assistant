"""Render original page/slide images for visual evidence.

* PDF pages  -> rendered locally with PyMuPDF (no external tools).
* PPTX slides -> converted to PDF with LibreOffice (``soffice --headless``),
  then rendered with PyMuPDF. If LibreOffice is not installed, PPTX renders
  are skipped and reported (manual PPTX->PDF export before upload is the
  documented workaround).

Everything is generic: documents live in the app-managed library
(``data/library/``) and images go to ``outputs/pages/``.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf

from src.config import OUTPUTS_DIR, PAGES_DIR, PROJECT_ROOT

RENDER_DPI = 110

SOFFICE_CANDIDATES = [
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/opt/homebrew/bin/soffice",
    "/usr/bin/soffice",
]


def find_soffice() -> str | None:
    for cand in SOFFICE_CANDIDATES:
        if Path(cand).exists():
            return cand
    return shutil.which("soffice")


def render_pdf(path: Path, prefix: str, pages_dir: Path = PAGES_DIR) -> list[str]:
    """Render every page of a PDF to PNG. Returns newly-created page_ids."""
    pages_dir = Path(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_ids: list[str] = []
    with pymupdf.open(str(path)) as doc:
        for i in range(len(doc)):
            page_id = f"{prefix}__p{i + 1:04d}"
            out = pages_dir / f"{page_id}.png"
            if out.exists():
                continue
            pix = doc[i].get_pixmap(dpi=RENDER_DPI)
            pix.save(str(out))
            page_ids.append(page_id)
    return page_ids


def render_pptx(path: Path, prefix: str, pages_dir: Path = PAGES_DIR,
                tmp_dir: Path | None = None) -> list[str]:
    """Convert a PPTX to PDF via LibreOffice, then render each slide."""
    soffice = find_soffice()
    if soffice is None:
        return []
    tmp = Path(tmp_dir) if tmp_dir else OUTPUTS_DIR / "tmp_convert"
    tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp), str(path)],
        check=True, capture_output=True, timeout=600,
    )
    pdf = tmp / f"{Path(path).stem}.pdf"
    if not pdf.exists():
        return []
    return render_pdf(pdf, prefix, pages_dir=pages_dir)


def render_doc(source: Path, doc_id: str, pages_dir: Path = PAGES_DIR,
               tmp_dir: Path | None = None) -> list[str]:
    """Render one document's pages/slides by extension. Returns new page_ids."""
    source = Path(source)
    if source.suffix.lower() == ".pdf":
        return render_pdf(source, doc_id, pages_dir=pages_dir)
    if source.suffix.lower() == ".pptx":
        return render_pptx(source, doc_id, pages_dir=pages_dir, tmp_dir=tmp_dir)
    return []


def render_all(library_dir: Path, manifest_path: Path = OUTPUTS_DIR / "manifest.json",
               pages_dir: Path = PAGES_DIR) -> dict[str, int]:
    """Render all missing images for every document in the manifest."""
    manifest_path = Path(manifest_path)
    pages = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages_dir = Path(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)

    counts = {"slide": 0, "page": 0, "skipped_pptx": 0}
    by_doc: dict[str, list[dict]] = {}
    for p in pages:
        by_doc.setdefault(p["doc_id"], []).append(p)

    for doc_id, units in sorted(by_doc.items()):
        stored = units[0].get("stored_file") or units[0]["source_file"]
        src = library_dir / stored
        if not src.exists():
            continue
        missing = [u for u in units if not (pages_dir / (u["page_id"] + ".png")).exists()]
        if not missing:
            continue  # fully rendered already
        new_ids = render_doc(src, doc_id, pages_dir=pages_dir)
        if new_ids:
            counts[units[0]["kind"]] += len(new_ids)
        elif units[0]["kind"] == "slide":
            counts["skipped_pptx"] += len(units)
        print(f"[{doc_id}] rendered {len(new_ids)} images")

    for p in pages:
        p["image_rendered"] = (pages_dir / (p["page_id"] + ".png")).exists()
    manifest_path.write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")
    return counts


def main(argv: list[str] | None = None) -> int:
    from src.config import LIBRARY_DIR

    counts = render_all(LIBRARY_DIR)
    print(f"\nrendered: {counts}")
    if counts["skipped_pptx"]:
        print("NOTE: PPTX slides not rendered - LibreOffice not found.")
        print("Install with: brew install --cask libreoffice")
        print("Workaround: export the deck to PDF (File > Export As PDF) and upload the PDF.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
