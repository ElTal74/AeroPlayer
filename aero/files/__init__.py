"""Biblioteca de archivos y carpetas: listado, estadísticas, filtros y orden (sin Qt).

Las carpetas de la biblioteca son referencias: AERO Player nunca mueve, copia ni modifica su contenido.
"""

from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass

from aero.core import filetypes
from aero.core.formats import kind_of

FILTERS: dict[str, tuple[str, set[str]]] = {
    "all": ("Todos", set()),
    "image": ("Imágenes", {"image"}),
    "audio": ("Música y audio", {"audio"}),
    "video": ("Vídeos", {"video"}),
    "docs": ("Documentos", {"document", "pdf", "text"}),
    "sheet": ("Hojas de cálculo", {"sheet"}),
    "slides": ("Presentaciones", {"slides"}),
    "archive": ("Comprimidos", {"archive"}),
    "other": ("Otros", {"unknown"}),
}
PLURALS = {
    "image": ("imagen", "imágenes"), "video": ("vídeo", "vídeos"), "audio": ("audio", "audios"),
    "document": ("documento", "documentos"), "pdf": ("PDF", "PDF"), "sheet": ("hoja de cálculo", "hojas de cálculo"),
    "slides": ("presentación", "presentaciones"), "text": ("texto", "textos"),
    "archive": ("comprimido", "comprimidos"), "unknown": ("otro", "otros"), "folder": ("carpeta", "carpetas"),
    "file": ("archivo", "archivos"),
}


def count(n: int, kind: str) -> str:
    """«1 carpeta», «3 carpetas», «1.250 imágenes»."""
    from aero.i18n import ntr

    one, many = PLURALS.get(kind, ("elemento", "elementos"))
    text = ntr("{n} " + one, "{n} " + many, n)        # claves del catálogo: «{n} archivo», «{n} carpeta»…
    return text.replace(str(n), f"{n:,}".replace(",", "."), 1) if n >= 1000 else text


SORTS = {"name": "Nombre", "kind": "Tipo", "size": "Tamaño", "date": "Fecha"}


@dataclass(slots=True)        # sin __dict__: crear miles de entradas cuesta menos memoria y tiempo
class FileEntry:
    name: str
    path: str               # ruta real, o la ruta del comprimido si `inner` no está vacío
    is_dir: bool = False
    size: int = 0
    mtime: float = 0.0
    kind: str = "unknown"
    inner: str = ""         # nombre dentro del comprimido
    locked: bool = False    # cifrado o bloqueado por seguridad
    category: str = ""      # categoría visual (aero.core.filetypes); vacía = se deduce de la extensión

    @property
    def ext(self) -> str:
        return os.path.splitext(self.name)[1].lower()


def _hidden(e: os.DirEntry) -> bool:
    if e.name.startswith(("$", "~$")) or e.name in ("desktop.ini", "thumbs.db", "Thumbs.db"):
        return True
    try:
        attrs = getattr(e.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM)) if attrs else e.name.startswith(".")


def list_dir(path: str) -> list[FileEntry]:
    """Contenido inmediato de una carpeta (sin ocultos ni de sistema). Lanza PermissionError si no se puede leer.

    Con el núcleo nativo (Rust) el recorrido y la clasificación se hacen sin el GIL; si no está, en Python."""
    from aero.core import native

    nc = native.core()
    if nc is not None:
        join = os.path.join
        return [FileEntry(name, join(path, name), is_dir, size, mt, "folder" if is_dir else kind_of(name),
                          category=cat) for name, is_dir, size, mt, cat in nc.scan_dir(path)]
    return list_dir_py(path)


def list_dir_py(path: str) -> list[FileEntry]:
    """Versión Python de `list_dir` (respaldo y referencia de las pruebas de equivalencia)."""
    out: list[FileEntry] = []
    with os.scandir(path) as it:
        for e in it:
            if _hidden(e):
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            size = 0 if is_dir else st.st_size
            cat = filetypes.by_extension(e.name, is_dir)
            if cat == "unknown" and size:
                cat = filetypes.sniff(e.path, size)   # sin extensión conocida: 64 bytes, en este hilo de trabajo
            out.append(FileEntry(e.name, e.path, is_dir, size, st.st_mtime,
                                 "folder" if is_dir else kind_of(e.name), category=cat))
    return out


def archive_entries(info, prefix: str) -> list[FileEntry]:
    out = []
    for e in info.children(prefix):
        ts = e.mtime.timestamp() if e.mtime else 0.0
        out.append(FileEntry(e.base, info.path, e.is_dir, e.size, ts, "folder" if e.is_dir else kind_of(e.base),
                             inner=e.name, locked=e.encrypted or e.unsafe,
                             category=filetypes.by_extension(e.base, e.is_dir)))
    return out


@dataclass
class FolderStats:
    files: int = 0
    dirs: int = 0
    size: int = 0
    complete: bool = True
    kinds: dict | None = None


def folder_stats(path: str, max_items: int = 200_000, max_seconds: float = 4.0) -> FolderStats:
    """Recorre la carpeta (en segundo plano) con límites de elementos y tiempo; nunca sigue enlaces."""
    from aero.core import native

    nc = native.core()
    if nc is not None:
        files, dirs, size, complete = nc.folder_stats(path, max_items, max_seconds)
        return FolderStats(files, dirs, size, complete, {})
    return folder_stats_py(path, max_items, max_seconds)


def folder_stats_py(path: str, max_items: int = 200_000, max_seconds: float = 4.0) -> FolderStats:
    s = FolderStats(kinds={})
    end = time.monotonic() + max_seconds
    stack = [path]
    n = 0
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                n += 1
                if n > max_items or (n % 512 == 0 and time.monotonic() > end):
                    s.complete = False
                    return s
                try:
                    if e.is_dir(follow_symlinks=False):
                        if d == path:
                            s.dirs += 1
                        stack.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        s.size += e.stat(follow_symlinks=False).st_size
                        if d == path:
                            s.files += 1
                except OSError:
                    continue
    return s


def immediate_stats(entries: list[FileEntry]) -> FolderStats:
    s = FolderStats(kinds={})
    for e in entries:
        if e.is_dir:
            s.dirs += 1
        else:
            s.files += 1
            s.size += e.size
            cat = e.category or e.kind     # categoría AERO (la misma que el icono)
            s.kinds[cat] = s.kinds.get(cat, 0) + 1
    return s


def apply_view(entries: list[FileEntry], text: str = "", filt: str = "all", sort: str = "name",
               descending: bool = False) -> list[FileEntry]:
    """Filtra y ordena. Las carpetas siempre van primero y el filtro de tipo no las oculta (se sigue navegando)."""
    kinds = FILTERS.get(filt, FILTERS["all"])[1]
    t = text.strip().lower()
    rows = [e for e in entries if (not t or t in e.name.lower()) and (not kinds or e.is_dir or e.kind in kinds)]
    keys = {
        "name": lambda e: e.name.lower(),
        "kind": lambda e: (e.kind, e.ext, e.name.lower()),
        "size": lambda e: (e.size, e.name.lower()),
        "date": lambda e: (e.mtime, e.name.lower()),
    }
    rows.sort(key=keys.get(sort, keys["name"]), reverse=descending)
    rows.sort(key=lambda e: not e.is_dir)  # estable: carpetas primero conservando el orden
    return rows
