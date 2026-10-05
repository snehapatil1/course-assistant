"""Render original page/slide images for visual evidence.

* PDF pages  -> rendered locally with PyMuPDF (no external tools).
* PPTX slides -> converted to PDF with LibreOffice (``soffice --headless``),
  then rendered with PyMuPDF. If LibreOffice is not installed, PPTX renders
  are skipped and reported (the class parsing service is the alternative).

Updates ``outputs/manifest.json`` in place, setting ``image_rendered: true``
on each unit whose image file now exists at ``image_path``.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf

from src.config import MATERIALS_DIR, OUTPUTS_DIR, PAGES_DIR, PROJECT_ROOT

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


def render_pdf(path: Path, prefix: str) -> list[str]:
    """Render every page of a PDF to PNG. Returns newly-created page_ids."""
    page_ids: list[str] = []
    with pymupdf.open(str(path)) as doc:
        for i in range(len(doc)):
            page_id = f"{prefix}__p{i + 1:04d}"
            out = PAGES_DIR / f"{page_id}.png"
            if out.exists():
                continue
            pix = doc[i].get_pixmap(dpi=RENDER_DPI)
            pix.save(str(out))
            page_ids.append(page_id)
    return page_ids


def render_pptx(path: Path, prefix: str) -> list[str]:
    """Convert a PPTX to PDF via LibreOffice, then render each slide."""
    soffice = find_soffice()
    if soffice is None:
        return []
    tmp = OUTPUTS_DIR / "tmp_convert"
    tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp), str(path)],
        check=True, capture_output=True, timeout=600,
    )
    pdf = tmp / f"{path.stem}.pdf"
    page_ids = render_pdf(pdf, prefix)
    return page_ids


def render_all() -> dict[str, int]:
    """Render all missing images; return counts {type: n_rendered}."""
    manifest_path = OUTPUTS_DIR / "manifest.json"
    pages = json.loads(manifest_path.read_text(encoding="utf-8"))
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    counts = {"slide": 0, "page": 0, "skipped_pptx": 0}
    by_doc: dict[str, list[dict]] = {}
    for p in pages:
        by_doc.setdefault(p["doc"], []).append(p)
        if p.get("image_rendered"):
            counts[p["kind"]] += 1

    for doc_id, units in sorted(by_doc.items()):
        src = MATERIALS_DIR / units[0]["source_file"]
        if not src.exists():
            continue
        missing = [u for u in units if not (PAGES_DIR / (u["page_id"] + ".png")).exists()]
        if not missing:
            continue  # fully rendered already
        if units[0]["kind"] == "page":
            new_ids = render_pdf(src, doc_id)
            counts["page"] += len(new_ids)
        else:
            new_ids = render_pptx(src, doc_id)
            if new_ids:
                counts["slide"] += len(new_ids)
            else:
                counts["skipped_pptx"] += len(units)
        print(f"[{doc_id}] rendered {len(new_ids)} images")

    for p in pages:
        p["image_rendered"] = (PAGES_DIR / (p["page_id"] + ".png")).exists()
    manifest_path.write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")
    return counts


def main(argv: list[str] | None = None) -> int:
    counts = render_all()
    print(f"\nrendered: {counts}")
    if counts["skipped_pptx"]:
        print("NOTE: PPTX slides not rendered - LibreOffice not found.")
        print("Install with: brew install --cask libreoffice  (or use the class parsing service)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
