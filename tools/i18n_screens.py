"""Recorre las pantallas reales en cada idioma y busca textos que se hayan quedado en español.

Abre la ventana principal con todos sus apartados (y todas las secciones de Ajustes), los editores (vídeo,
imágenes, AERO Paint, documentos, hojas, presentaciones, PDF editable) y los lotes, y mira cada texto
visible: etiquetas, botones, ayudas, campos, listas, pestañas, títulos de ventana y nombres accesibles.

Un texto cuenta como «sin traducir» si es un texto de origen (español) que el idioma sí traduce, o si contiene
rasgos que solo tiene el español (¿ ¡ ñ, «del», «los»…). Los nombres de archivo y los datos del usuario no
aparecen en estas pantallas vacías.

Uso:
    python tools/i18n_screens.py [idioma …]      # por defecto, todos menos el español
    python tools/i18n_screens.py --strict        # código 1 si hay algún texto sin traducir (publicar)
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AERO_DATA_DIR", tempfile.mkdtemp(prefix="aero_i18n_"))

import aero  # noqa: E402,F401 - límites de hilos antes de NumPy

SPANISH_ONLY = re.compile(r"[¿¡ñÑ]|\b(del|los|las|para|una|archivo|archivos|carpeta|guardar|abrir|añadir|"
                          r"vídeo|canciones|también|aquí|está|ningún|ninguna|búsqueda|después|página)\b", re.I)


# Palabras que también son correctas en otros idiomas (no delatan un texto en español)
SHARED = {"pt-BR": {"para", "una", "vídeo", "página", "está"}, "it": {"del", "una", "para"}}


def texts_of(root) -> list[tuple[str, str]]:
    """(texto, de dónde) de todos los widgets descendientes, visibles u ocultos (pestañas no abiertas)."""
    from PySide6.QtWidgets import (QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit, QListWidget,
                                   QTabBar, QTabWidget, QTreeWidget, QWidget)

    out = []

    def add(t, where):
        if t and isinstance(t, str):
            out.append((t, where))

    for w in [root, *root.findChildren(QWidget)]:
        name = type(w).__name__
        add(w.toolTip(), f"{name}.toolTip")
        add(w.accessibleName(), f"{name}.accessibleName")
        if w.isWindow():
            add(w.windowTitle(), f"{name}.windowTitle")
        if isinstance(w, QLabel):
            add(w.text(), "QLabel")
        elif isinstance(w, QAbstractButton):
            add(w.text(), name)
        elif isinstance(w, QLineEdit):
            add(w.placeholderText(), "QLineEdit.placeholder")
        elif isinstance(w, QComboBox):
            for i in range(w.count()):
                add(w.itemText(i), "QComboBox")
        elif isinstance(w, QTabBar):
            for i in range(w.count()):
                add(w.tabText(i), "QTabBar")
                add(w.tabToolTip(i), "QTabBar.tip")
        elif isinstance(w, QTabWidget):
            for i in range(w.count()):
                add(w.tabText(i), "QTabWidget")
        elif isinstance(w, QGroupBox):
            add(w.title(), "QGroupBox")
        elif isinstance(w, QListWidget):
            for i in range(min(w.count(), 200)):
                add(w.item(i).text(), "QListWidget")
                add(w.item(i).toolTip(), "QListWidget.tip")
        elif isinstance(w, QTreeWidget):
            h = w.headerItem()
            for i in range(h.columnCount()):
                add(h.text(i), "QTreeWidget.header")
        for act in w.actions():
            add(act.text(), f"{name}.action")
            add(act.toolTip(), f"{name}.action.tip")
    return out


def leftovers(code: str, texts) -> list[tuple[str, str]]:
    from aero.i18n import LANGUAGES, catalog

    cat = catalog(code)
    sources = set(cat)
    values = {str(v).strip() for v in cat.values() if isinstance(v, str)}
    bad = []
    for t, where in texts:
        s = t.strip()
        if len(s) < 2 or not any(c.isalpha() for c in s):
            continue
        if s in LANGUAGES.values() or s.startswith("OCR: "):
            continue   # nombres de idioma: cada uno en su propio idioma (como en cualquier selector de idioma)
        if s in sources and cat.get(s) not in (None, s):
            bad.append((s, where))               # texto de origen que este idioma traduce: falta tr()
            continue
        # Rasgos del español en cada línea que no sea ya una traducción conocida (p. ej. ayudas de 3 líneas)
        lines = [ln for ln in s.splitlines() if ln.strip() and ln.strip() not in values]
        shared = SHARED.get(code, set())
        for ln in lines:
            hits = {m.group(0).lower() for m in SPANISH_ONLY.finditer(ln)} - shared
            if hits:
                bad.append((s, where))
                break
    return sorted(set(bad))


def screens(app):
    """Crea cada pantalla y devuelve [(nombre, widget)]. Se cierran después."""
    from PySide6.QtGui import QColor, QImage

    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.ui.controller import AppController
    from aero.ui.main_window import PAGE_KEYS, apply_theme

    s = Settings()
    s.set("tutorial_done", True)
    s.set("quicklook_enabled", False)
    apply_theme(app, s)
    ctl = AppController(app, s, Database())
    win = ctl.show_main()
    out = [("main", win)]
    for k in PAGE_KEYS:
        win.navigate(k)
        app.processEvents()
    tmp = Path(tempfile.mkdtemp())
    img = QImage(64, 48, QImage.Format.Format_RGB32)
    img.fill(QColor("#336699"))
    png = tmp / "img.png"
    img.save(str(png))
    out.append(("paint", ctl.open_paint("")))
    out.append(("video", ctl.open_video_editor()))
    ie = ctl.open_image_editor(str(png))
    end = time.time() + 5
    while time.time() < end and getattr(ie, "doc", None) is None:
        app.processEvents()
        time.sleep(0.02)
    out.append(("image", ie))
    for name, fn in (("doc", "open_document_editor"), ("sheet", "open_sheet_editor"), ("slides", "open_slides_editor"),
                     ("pdfconv", "open_pdf_convert")):
        try:
            out.append((name, getattr(ctl, fn)()))
        except TypeError:
            pass
    from aero.ui.batch_tools import BatchRename, BatchResize

    out.append(("rename", BatchRename([str(png)])))
    out.append(("resize", BatchResize([str(png)])))
    from aero.torrent import metainfo
    from aero.torrent.ui import DownloadsWindow, TorrentDialog, TorrentManager

    t = metainfo.parse(metainfo.make([("Carpeta/video.mkv", b"v" * 40_000), ("setup.exe", b"e" * 100)], "Pack", 16384))
    td = TorrentDialog(t)
    td.show()
    out.append(("torrent", td))
    out.append(("downloads", DownloadsWindow(TorrentManager())))
    import io
    import zipfile

    import pycdlib

    from aero.files.browser import FolderBrowser

    iso_path = tmp / "disco.iso"
    iso = pycdlib.PyCdlib()
    iso.new(joliet=3, vol_ident="AERO")
    iso.add_fp(io.BytesIO(b"hola"), 4, "/A.TXT;1", joliet_path="/a.txt")
    iso.write(str(iso_path))
    iso.close()
    with zipfile.ZipFile(tmp / "caja.zip", "w") as z:
        z.writestr("dentro/foto.png", b"x")
    for name, src in (("zip", tmp / "caja.zip"), ("iso", iso_path)):
        fb = FolderBrowser()
        fb.resize(700, 400)
        fb.show()
        fb.set_root(str(src))
        end = time.time() + 5
        while time.time() < end and fb.archive is None:
            app.processEvents()
            time.sleep(0.02)
        out.append((f"archivo_{name}", fb))
    app.processEvents()
    return ctl, out


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from aero.i18n import LANGUAGES, set_language

    strict = "--strict" in sys.argv
    args = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and sys.argv[i - 1] != "--json"]
    codes = [a for a in args if a in LANGUAGES] or [c for c in LANGUAGES if not c.startswith("es")]
    app = QApplication.instance() or QApplication([])
    total = 0
    report = {}
    for code in codes:
        set_language(code)
        from aero.core.config import Settings

        Settings().set("language", code)
        ctl, scr = screens(app)
        bad = []
        for name, w in scr:
            bad += [(t, f"{name}:{where}") for t, where in leftovers(code, texts_of(w))]
        bad = sorted(set(bad))
        report[code] = bad
        total += len(bad)
        print(f"{code}: {len(bad)} textos sin traducir")
        for t, where in bad[:400]:
            print(f"   [{where}] {t!r}")
        for _n, w in scr:
            try:
                if hasattr(w, "doc") and getattr(w, "doc", None) is not None and hasattr(w.doc, "dirty"):
                    w.doc.dirty = False
                if hasattr(w, "dirty"):
                    w.dirty = False
                w.hide()
                w.deleteLater()
            except RuntimeError:
                pass
        app.processEvents()
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                                                encoding="utf-8")
    if strict and total:
        print("Hay textos sin traducir: no se puede publicar esta versión.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
