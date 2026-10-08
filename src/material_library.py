"""Local originals only. Saving does not imply ingestion or search readiness."""
from __future__ import annotations
from pathlib import Path
import hashlib
import re
import threading
import zipfile
from collections.abc import Callable
from src.dashboard import Catalog, material_title


class MaterialLibrary:
    def __init__(self, root: Path, max_bytes: int = 25 * 1024 * 1024,
                 ingestion_hook: Callable[[Path], None] | None = None):
        self.root = root.resolve()
        self.folder = self.root / 'data/materials'
        self.max_bytes = max_bytes
        self.ingestion_hook = ingestion_hook
        self._lock = threading.Lock()

    @staticmethod
    def safe_name(name: str) -> str:
        name = name.replace('\\', '/').rsplit('/', 1)[-1]
        stem = re.sub(r'[^\w .-]', '_', Path(name).stem).strip(' .')[:100] or 'material'
        if stem.upper() in {'CON','PRN','AUX','NUL', *[f'COM{i}' for i in range(10)], *[f'LPT{i}' for i in range(10)]}:
            stem = 'material_' + stem
        return stem + Path(name).suffix.lower()

    def upload(self, paths: list[str] | None) -> str:
        if not paths:
            return 'Choose PDF or PowerPoint (.pptx) files first.'
        if len(paths) > 20:
            return 'Please add up to 20 files at a time.'
        added = duplicate = 0
        rejected = []
        with self._lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            for raw in paths:
                try:
                    source = Path(raw)
                    if source.suffix.lower() not in ('.pdf', '.pptx') or not source.is_file():
                        rejected.append('A file was not accepted. Use PDF or PPTX.')
                        continue
                    if source.stat().st_size > self.max_bytes:
                        rejected.append('A file was too large. Limit: 25 MB per file.')
                        continue
                    data = source.read_bytes()
                    if len(data) > self.max_bytes:
                        rejected.append('A file was too large. Limit: 25 MB per file.')
                        continue
                    if source.suffix.lower() == '.pdf':
                        valid = data.startswith(b'%PDF-')
                    else:
                        try:
                            with zipfile.ZipFile(source) as z:
                                names = set(z.namelist())
                                valid = '[Content_Types].xml' in names and 'ppt/presentation.xml' in names
                        except (OSError, zipfile.BadZipFile):
                            valid = False
                    if not valid:
                        rejected.append('A file was not accepted: its contents do not match PDF or PPTX.')
                        continue
                    digest = hashlib.sha256(data).hexdigest()
                    same = next((p for p in self.folder.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in ('.pdf','.pptx') and p.stat().st_size == len(data) and hashlib.sha256(p.read_bytes()).hexdigest() == digest), None)
                    if same:
                        duplicate += 1
                        continue
                    target = self.folder / self.safe_name(source.name)
                    if target.exists():
                        target = target.with_name(f'{target.stem}-{digest[:10]}{target.suffix}')
                    counter = 1
                    candidate = target
                    while candidate.exists():
                        candidate = target.with_name(f'{target.stem}-{counter}{target.suffix}')
                        counter += 1
                    # Exclusive creation protects originals even if another process races.
                    with candidate.open('xb') as f:
                        f.write(data)
                    added += 1
                    if self.ingestion_hook:
                        try:
                            self.ingestion_hook(candidate)
                        except Exception:
                            rejected.append('Saved locally; processing could not be requested. Ask your course team for help.')
                except (OSError, ValueError):
                    rejected.append('A file could not be saved. Please try again.')
        message = f'{added} added · {duplicate} already saved. Originals stay on this computer. New uploads await processing before they appear in study selectors.'
        return message + (' ' + ' '.join(dict.fromkeys(rejected)) if rejected else '')

    def rows(self, catalog: Catalog) -> list[list[str]]:
        prepared = {str(c.get('source_file') or c.get('doc_title') or c['doc']): c for c in catalog.chunks}
        seen = set()
        rows = []
        for p in sorted(self.folder.glob('*')) if self.folder.exists() else []:
            if not p.is_file() or p.is_symlink() or p.suffix.lower() not in ('.pdf','.pptx'):
                continue
            seen.add(p.name)
            status = 'Text prepared · generation service separate' if p.name in prepared else 'Uploaded · Awaiting processing'
            size = f'{p.stat().st_size / 1024:,.1f} KB'
            rows.append([material_title(p.name), p.suffix[1:].upper(), size, status, p.name])
        for name, c in sorted(prepared.items()):
            if name not in seen:
                rows.append([material_title(c.get('doc_title') or name), Path(name).suffix[1:].upper() or '—', 'Original not stored', 'Text prepared · original file unavailable', name])
        return rows
