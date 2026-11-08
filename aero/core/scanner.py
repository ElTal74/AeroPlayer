"""Escáner de biblioteca en segundo plano: incremental, pausable y cancelable."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from aero.core.db import Database
from aero.core.formats import AUDIO, VIDEO
from aero.core.metadata import read_tags_many

BATCH = 150


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def is_excluded(path: str, excludes: list[str]) -> bool:
    n = _norm(path)
    for ex in excludes:
        e = _norm(ex)
        if n == e or n.startswith(e.rstrip("\\/") + os.sep):
            return True
    return False


def iter_media(root: str, excludes: list[str], stop: threading.Event, resume: threading.Event):
    """Recorre `root` sin seguir enlaces simbólicos ni entrar en carpetas ocultas/del sistema."""
    stack = [root]
    while stack:
        if stop.is_set():
            return
        resume.wait()
        d = stack.pop()
        if is_excluded(d, excludes):
            continue
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if not e.name.startswith((".", "$")):
                        stack.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    ext = os.path.splitext(e.name)[1].lower()
                    if ext in AUDIO or ext in VIDEO:
                        st = e.stat()
                        yield e.path, ext, st.st_size, st.st_mtime
            except OSError:
                continue


class LibraryScanner(QThread):
    progress = Signal(int, str)        # archivos procesados, ruta actual
    finished_scan = Signal(int, int)   # añadidos/actualizados, eliminados
    failed = Signal(str)

    def __init__(self, folders: list[str], excludes: list[str], db_path=None, parent=None):
        super().__init__(parent)
        self.folders = [f for f in folders if f]
        self.excludes = list(excludes)
        self.db_path = db_path
        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume.set()

    def pause(self) -> None:
        self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    def cancel(self) -> None:
        self._stop.set()
        self._resume.set()

    @staticmethod
    def _save(db, batch: list[dict]) -> None:
        """Lee las etiquetas del lote de una vez (en paralelo con el núcleo nativo) y lo guarda."""
        if not batch:
            return
        for row, tags in zip(batch, read_tags_many([r["path"] for r in batch])):
            row.update(tags)
        db.upsert_media(batch)

    def run(self) -> None:
        try:
            db = Database(self.db_path)
        except Exception as e:  # pragma: no cover
            self.failed.emit(f"No se pudo abrir la base de datos: {e}")
            return
        changed = removed = processed = 0
        try:
            for root in self.folders:
                if self._stop.is_set():
                    break
                if not os.path.isdir(root):
                    continue
                known = db.known_files(root)
                hidden = db.hidden_paths()
                seen: set[str] = set()
                batch: list[dict] = []
                for path, ext, size, mtime in iter_media(root, self.excludes, self._stop, self._resume):
                    seen.add(path)
                    processed += 1
                    if path in hidden:
                        continue
                    if processed % 25 == 0:
                        self.progress.emit(processed, path)
                    old = known.get(path)
                    if old and abs((old[0] or 0) - mtime) < 1 and old[1] == size:
                        continue
                    p = Path(path)
                    row = {
                        "path": path, "root": root, "folder": str(p.parent), "name": p.stem, "ext": ext,
                        "kind": "audio" if ext in AUDIO else "video", "size": size, "mtime": mtime,
                    }
                    batch.append(row)
                    if len(batch) >= BATCH:
                        self._save(db, batch)
                        changed += len(batch)
                        batch.clear()
                self._save(db, batch)
                changed += len(batch)
                if not self._stop.is_set():
                    gone = [p for p in known if p not in seen]
                    db.remove_paths(gone)
                    removed += len(gone)
        except Exception as e:  # pragma: no cover - defensivo
            self.failed.emit(str(e))
        finally:
            db.close()
        self.progress.emit(processed, "")
        self.finished_scan.emit(changed, removed)
