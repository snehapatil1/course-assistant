"""App-managed document library: students upload their own course materials.

Generic by design - no course file is hardcoded anywhere. The app adds and
removes documents through here:

* ``add_document`` - SHA-256 dedupe (same file twice is a no-op), copy into
  ``data/library/``, parse -> render page/slide images -> chunk -> update the
  manifest, chunks, BM25 index, and (when class endpoints are configured) the
  ChromaDB text + visual indexes.
* ``remove_document`` - deletes the document's pages from the manifest, its
  chunks, its rendered images, its library file, and its rows from every
  index, so later answers never rely on removed content.
* ``list_documents`` / ``rebuild_all`` - inventory and crash-recovery.

Local (keyless) parts always run; text/visual vector indexes are
synchronized only when the class endpoints are configured in ``.env``
(otherwise a clear status message is returned).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from src import config
from src.ingest import (build_chunks, build_page_records, ingest_library,
                        sha256_file, slugify, write_chunks, write_manifest)
from src.render import render_all, render_doc

SUPPORTED_SUFFIXES = {".pdf", ".pptx"}


# --------------------------------------------------------------------------- #
# Manifest I/O
# --------------------------------------------------------------------------- #
def load_manifest(out_dir: Path = config.OUTPUTS_DIR) -> list[dict]:
    path = Path(out_dir) / "manifest.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(pages: list[dict], out_dir: Path) -> Path:
    return write_manifest(pages, Path(out_dir) / "manifest.json")


def _refresh_chunks_and_bm25(pages: list[dict], out_dir: Path) -> dict:
    """Rebuild chunks.json + BM25 index (local, no key needed).

    An empty library is a valid state: the BM25 index dir keeps an empty
    corpus marker so loaders do not fail on a fresh install.
    """
    out_dir = Path(out_dir)
    from dataclasses import asdict

    import shutil as _shutil

    chunks = build_chunks(pages)
    write_chunks(chunks, out_dir / "chunks.json")

    from src.indexes import build_bm25

    index_dir = out_dir / "indexes" / "bm25"
    if chunks:
        build_bm25([asdict(c) for c in chunks], out_dir=index_dir)
    else:
        _shutil.rmtree(index_dir, ignore_errors=True)
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / "corpus_meta.json").write_text("[]", encoding="utf-8")
    return {"chunks": len(chunks)}


def _sync_vector_indexes(chunks: list[dict], pages: list[dict], out_dir: Path) -> dict:
    """Synchronize ChromaDB text + visual indexes (requires class endpoints)."""
    out_dir = Path(out_dir)
    try:
        config.require_endpoint("text_embed")
        config.require_endpoint("visual_embed")
    except RuntimeError as exc:
        return {"status": "skipped", "reason": str(exc)}

    import numpy as np

    from src.embeddings import embed_images, embed_texts
    from src.indexes import (build_vector_indexes, get_chroma,
                             get_text_collection, get_visual_collection)

    client = get_chroma()
    # full rebuild: drop + recreate both collections (delete(where={}) is invalid)
    for name in ("text_chunks", "visual_pages"):
        try:
            client.delete_collection(name)
        except Exception:
            pass  # collection did not exist yet
    get_text_collection(client)
    get_visual_collection(client)

    embed_text = lambda texts: embed_texts(texts).astype(np.float32)
    embed_image = lambda paths: embed_images(paths).astype(np.float32)
    counts = build_vector_indexes(chunks, pages, embed_text, embed_image)
    return {"status": "ok", **counts}


# --------------------------------------------------------------------------- #
# Library operations
# --------------------------------------------------------------------------- #
def add_document(
    path: str | Path,
    library_dir: Path = config.LIBRARY_DIR,
    out_dir: Path = config.OUTPUTS_DIR,
    render: bool = True,
) -> dict:
    """Add one document to the library. Dedupes by content hash."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported format {ext!r}; supported: {sorted(SUPPORTED_SUFFIXES)}")

    library_dir = Path(library_dir)
    out_dir = Path(out_dir)
    library_dir.mkdir(parents=True, exist_ok=True)

    file_hash = sha256_file(path)
    pages = load_manifest(out_dir)
    for p in pages:  # dedupe by content hash
        if p.get("file_hash") == file_hash:
            return {
                "status": "duplicate",
                "doc_id": p["doc_id"],
                "title": p["doc_title"],
                "message": f"'{p['doc_title']}' is already in the library (same content hash)",
            }

    doc_id = f"{slugify(path.stem)}__{file_hash[:8]}"
    stored_name = f"{doc_id}{ext}"
    stored = library_dir / stored_name
    shutil.copy2(path, stored)

    new_pages = build_page_records(stored, doc_id, path.name, file_hash)
    for p in new_pages:
        p["stored_file"] = stored_name

    rendered = []
    if render:
        rendered = render_doc(stored, doc_id,
                              pages_dir=out_dir / "pages",
                              tmp_dir=out_dir / "tmp_convert")

    pages.extend(new_pages)
    _save_manifest(pages, out_dir)
    stats = _refresh_chunks_and_bm25(pages, out_dir)
    vector = _sync_vector_indexes(
        json.loads((out_dir / "chunks.json").read_text(encoding="utf-8")),
        pages, out_dir,
    )

    n_images = sum(1 for p in new_pages if (out_dir / "pages" / (p["page_id"] + ".png")).exists())
    return {
        "status": "added",
        "doc_id": doc_id,
        "title": path.name,
        "units": len(new_pages),
        "images": n_images,
        "vector_indexes": vector.get("status", "skipped"),
        "message": f"added '{path.name}': {len(new_pages)} pages/slides, "
                   f"{n_images} image(s) rendered; vector indexes {vector.get('status')}",
    }


def remove_document(
    doc_id: str,
    library_dir: Path = config.LIBRARY_DIR,
    out_dir: Path = config.OUTPUTS_DIR,
) -> dict:
    """Remove a document and ALL of its searchable content."""
    library_dir = Path(library_dir)
    out_dir = Path(out_dir)

    pages = load_manifest(out_dir)
    doc_pages = [p for p in pages if p["doc_id"] == doc_id]
    if not doc_pages:
        return {"status": "not_found", "doc_id": doc_id}

    # remove rendered images
    for p in doc_pages:
        img = out_dir / "pages" / (p["page_id"] + ".png")
        if img.exists():
            img.unlink()

    # remove the stored library file (doc_id + extension)
    for p in doc_pages:
        stored = library_dir / p["stored_file"]
        if stored.exists():
            stored.unlink()

    remaining = [p for p in pages if p["doc_id"] != doc_id]
    _save_manifest(remaining, out_dir)
    stats = _refresh_chunks_and_bm25(remaining, out_dir)

    # drop the document from the vector indexes when configured
    try:
        config.require_endpoint("text_embed")
        from src.indexes import get_chroma, get_text_collection, get_visual_collection

        client = get_chroma()
        for col in (get_text_collection(client), get_visual_collection(client)):
            col.delete(where={"doc": doc_id})
        vector = "ok"
    except RuntimeError:
        vector = "skipped"

    return {
        "status": "removed",
        "doc_id": doc_id,
        "removed_units": len(doc_pages),
        "chunks_remaining": stats["chunks"],
        "vector_indexes": vector,
        "message": f"removed '{doc_pages[0]['doc_title']}': {len(doc_pages)} page(s) "
                   f"purged from manifest, chunks, images, and indexes",
    }


def list_documents(out_dir: Path = config.OUTPUTS_DIR) -> list[dict]:
    """Inventory of the library: one entry per document, in add order."""
    pages = load_manifest(out_dir)
    docs: dict[str, dict] = {}
    for p in pages:
        entry = docs.setdefault(
            p["doc_id"],
            {
                "doc_id": p["doc_id"],
                "title": p["doc_title"],
                "kind": p["kind"],
                "units": 0,
                "images": 0,
                "file_hash": p["file_hash"],
            },
        )
        entry["units"] += 1
        if (Path(out_dir) / "pages" / (p["page_id"] + ".png")).exists():
            entry["images"] += 1
    return list(docs.values())


def rebuild_all(library_dir: Path = config.LIBRARY_DIR,
                out_dir: Path = config.OUTPUTS_DIR,
                render: bool = True) -> dict:
    """Rebuild manifest/chunks/BM25/vectors from whatever is in the library."""
    library_dir = Path(library_dir)
    out_dir = Path(out_dir)
    pages = ingest_library(library_dir)
    for p in pages:
        p["stored_file"] = p["source_file"]
    _save_manifest(pages, out_dir)
    stats = _refresh_chunks_and_bm25(pages, out_dir)
    if render:
        render_counts = render_all(library_dir, out_dir / "manifest.json",
                                   pages_dir=out_dir / "pages")
    else:
        render_counts = {}
    vector = _sync_vector_indexes(
        json.loads((out_dir / "chunks.json").read_text(encoding="utf-8")), pages, out_dir)
    return {
        "documents": len(set(p["doc_id"] for p in pages)),
        "units": len(pages),
        **stats,
        "rendered": render_counts,
        "vector_indexes": vector.get("status", "skipped"),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Manage the app document library.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="add one or more PDF/PPTX files")
    p_add.add_argument("files", nargs="+", type=Path)

    p_rm = sub.add_parser("remove", help="remove a document by doc_id")
    p_rm.add_argument("doc_id")

    sub.add_parser("list", help="list documents")
    sub.add_parser("rebuild", help="rebuild manifest + indexes from the library folder")

    args = ap.parse_args(argv)

    if args.cmd == "add":
        for f in args.files:
            print(add_document(f)["message"])
    elif args.cmd == "remove":
        print(remove_document(args.doc_id)["message"])
    elif args.cmd == "list":
        for d in list_documents():
            print(f"{d['doc_id']:45s} {d['units']:3d} units  {d['title']}")
        if not list_documents():
            print("(library is empty)")
    elif args.cmd == "rebuild":
        print(rebuild_all())
    return 0


if __name__ == "__main__":
    sys.exit(main())
