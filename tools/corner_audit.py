"""Auditoría de esquinas: abre todas las ventanas de AERO Player y dice cuáles no quedan redondeadas.

Uso: python tools/devrun.py run esquinas -- .venv/Scripts/python.exe tools/corner_audit.py
Para cada ventana de primer nivel visible muestra la preferencia de esquinas de Windows 11 (DWM, atributo 33)
y si es «layered» (WS_EX_LAYERED: ahí DWM no redondea y hay que hacerlo con una región o pintándolo).
"""

from __future__ import annotations

import ctypes
import os
os.environ.setdefault("AERO_NO_UPDATES", "1")   # sin consultar GitHub durante las comprobaciones
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AERO_DATA_DIR"] = tempfile.mkdtemp(prefix="aero_corner_")
os.environ["AERO_NO_TUTORIAL"] = "1"
M = ROOT / "tests" / "media"

from PySide6.QtCore import QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox  # noqa: E402

app = QApplication([])
from aero.core.config import Settings  # noqa: E402
from aero.core.db import Database  # noqa: E402
from aero.ui.controller import AppController  # noqa: E402
from aero.ui.main_window import apply_theme  # noqa: E402

s = Settings()
s.set("tutorial_done", True)
s.set("quicklook_enabled", False)
apply_theme(app, s)
ctl = AppController(app, s, Database())
opened = []


def safe(name, fn):
    try:
        w = fn()
        if w is not None:
            opened.append((name, w))
    except Exception:  # noqa: BLE001
        print("NO SE PUDO ABRIR", name)
        traceback.print_exc()


def pump(ms=400):
    end = __import__("time").time() + ms / 1000
    while __import__("time").time() < end:
        app.processEvents()


def report():
    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    rows = []
    for w in QApplication.topLevelWidgets():
        if not w.isVisible():
            continue
        hwnd = int(w.winId())
        v = ctypes.c_int(-1)
        dwm.DwmGetWindowAttribute(hwnd, 33, ctypes.byref(v), ctypes.sizeof(v))
        ex = user32.GetWindowLongW(hwnd, -20)
        layered = bool(ex & 0x80000)
        name = next((n for n, o in opened if o is w), "")
        img = w.grab().toImage()
        corners = [img.pixelColor(x, y).alpha() for x, y in ((0, 0), (img.width() - 1, 0), (0, img.height() - 1),
                                                                (img.width() - 1, img.height() - 1))]             if not img.isNull() else [255] * 4
        painted_round = max(corners) < 40          # la propia ventana deja transparentes sus esquinas
        ok = (v.value in (2, 3) and not layered) or (layered and painted_round)
        rows.append((ok, type(w).__name__, name, v.value, layered, w.width(), w.height(), corners))
    rows.sort(key=lambda r: (r[0], r[1]))
    for ok, cls, name, pref, layered, ww, hh, corners in rows:
        print(f"{'OK ' if ok else 'MAL'} {cls:28} {name:22} pref={pref} layered={layered} alfa_esquinas={corners} {ww}x{hh}")
    print("TOTAL", len(rows), "MAL", sum(1 for r in rows if not r[0]))


def run():
    main = ctl.show_main()
    pump()
    safe("principal", lambda: main)
    safe("visor_imagen", lambda: ctl.open_media_window(str(M / "foto.jpg")))
    safe("visor_video", lambda: ctl.open_media_window(str(M / "clip.mkv")))
    safe("vista_rapida", lambda: (ctl.show_quicklook(str(M / "foto.jpg")), ctl.quicklook)[1])
    safe("editor_video", lambda: ctl.open_video_editor())
    safe("editor_imagen", lambda: ctl.open_image_editor(str(M / "foto.jpg")))
    safe("paint", lambda: ctl.open_paint(""))
    safe("documento", lambda: ctl.open_document_editor())
    safe("hoja", lambda: ctl.open_sheet_editor())
    safe("presentacion", lambda: ctl.open_slides_editor())
    safe("pdf_editable", lambda: ctl.open_pdf_convert())
    from aero.archive import ui as aui

    safe("extraer", lambda: (lambda d: (d.show(), d)[1])(aui.ExtractDialog(str(M / "foto.jpg"))))
    safe("comprimir", lambda: (lambda d: (d.show(), d)[1])(aui.CompressDialog([str(M / "foto.jpg")])))
    from aero.torrent import metainfo
    from aero.torrent.ui import TorrentDialog, show_downloads

    t = metainfo.parse(metainfo.make([("a.bin", b"x" * 100)], "a.bin", 16384))
    safe("torrent", lambda: (lambda d: (d.show(), d)[1])(TorrentDialog(t)))
    safe("descargas", show_downloads)
    from aero.ui.batch_tools import BatchRename, BatchResize

    safe("renombrar", lambda: (lambda d: (d.show(), d)[1])(BatchRename([str(M / "foto.jpg")])))
    safe("redimensionar", lambda: (lambda d: (d.show(), d)[1])(BatchResize([str(M / "foto.jpg")])))
    box = QMessageBox(QMessageBox.Icon.Question, "Mensaje", "¿Prueba?", parent=main)
    box.setModal(False)
    box.show()
    opened.append(("mensaje", box))
    m = QMenu(main)
    m.addAction("Uno")
    m.popup(QPoint(300, 300))
    opened.append(("menu", m))
    try:
        main.open_palette() if hasattr(main, "open_palette") else None
    except Exception:  # noqa: BLE001
        pass
    try:
        main.tasks_btn.show_popup()
    except Exception:  # noqa: BLE001
        pass
    pump(1500)
    report()
    sys.stdout.flush()
    os._exit(0)          # sin esperar a que se cierren vídeos y editores


QTimer.singleShot(500, run)
app.exec()
