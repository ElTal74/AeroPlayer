"""Pruebas con entrada REAL de Windows (ratón y teclado del sistema).

1. Clic real sobre la zona más transparente de la ventana principal → debe recibirlo AERO Player.
2. Quick Look real: se abre una ventana del Explorador en tests/media, se selecciona un archivo y se envía
   la tecla Espacio del sistema → debe aparecer la vista previa; Espacio de nuevo la cierra.
Mueve el ratón un instante y lo devuelve a su sitio.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AERO_DATA_DIR"] = tempfile.mkdtemp(prefix="aero_input_")
os.environ["AERO_NO_TUTORIAL"] = "1"  # el tutorial de bienvenida taparía la ventana
M = ROOT / "tests" / "media"

from PySide6.QtCore import QEvent, QObject, QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from aero.core.config import Settings  # noqa: E402
from aero.core.db import Database  # noqa: E402
from aero.ui.controller import AppController  # noqa: E402
from aero.ui.main_window import apply_theme  # noqa: E402

u32 = ctypes.windll.user32
results: dict[str, object] = {}


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


class Catch(QObject):
    def __init__(self, win):
        super().__init__()
        self.win, self.hits = win, 0

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonPress and hasattr(obj, "window") and obj.window() is self.win:
            self.hits += 1
        return False


s = Settings()
s.set("quicklook_enabled", False)
db = Database()
apply_theme(app, s)
ctl = AppController(app, s, db)
ctl.quit = lambda: None
win = ctl.show_main()
win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
win.setGeometry(200, 150, 1000, 650)
win.show()
pump(1.0)
catch = Catch(win)
app.installEventFilter(catch)

class PT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


orig = PT()
u32.GetCursorPos(ctypes.byref(orig))
for mode, tr in (("blur", 1.0), ("blur", 0.9), ("blur", 0.75), ("blur", 0.6), ("clear", 1.0)):
    s.set("glass_mode", mode)
    s.set("window_transparency", tr)
    pump(0.6)
    # Hueco entre la barra de iconos y el panel central: solo hay fondo de ventana.
    local = QPoint(win.rail.geometry().right() + 5, win.height() // 2)
    g = win.mapToGlobal(local)
    dpr = win.devicePixelRatioF()
    before = catch.hits
    u32.SetCursorPos(int(g.x() * dpr), int(g.y() * dpr))
    pump(0.15)
    u32.mouse_event(0x0002, 0, 0, 0, 0)
    u32.mouse_event(0x0004, 0, 0, 0, 0)
    pump(0.4)
    results[f"clic_en_fondo_{mode}_{tr}"] = catch.hits > before
u32.SetCursorPos(orig.x, orig.y)
win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
win.hide()

# ---------------------------------------------------------------- Quick Look real
s.set("quicklook_enabled", True)
s.set("quicklook_space_in_explorer", True)
ctl.sync_quicklook()
pump(0.8)
target = M / "foto.jpg"
subprocess.Popen(["explorer.exe", f"/select,{target}"])
import pythoncom  # noqa: E402
import win32com.client  # noqa: E402
import win32gui  # noqa: E402

pythoncom.CoInitialize()
hwnd = 0
for _ in range(60):
    pump(0.15)
    for w in win32com.client.Dispatch("Shell.Application").Windows():
        try:
            if Path(str(w.Document.Folder.Self.Path)) == M:
                hwnd = int(w.HWND)
        except Exception:  # noqa: BLE001
            continue
    if hwnd:
        break
results["explorador_abierto"] = bool(hwnd)
if hwnd:
    from aero.quicklook.window import force_foreground

    force_foreground(hwnd)
    pump(1.0)
    from aero.quicklook.winhook import explorer_file_view_focused

    results["foco_en_lista_de_archivos"] = explorer_file_view_focused()
    u32.keybd_event(0x20, 0x39, 0, 0)
    u32.keybd_event(0x20, 0x39, 2, 0)
    for _ in range(40):
        pump(0.1)
        if ctl.quicklook is not None and ctl.quicklook.isVisible():
            break
    ql = ctl.quicklook
    results["quicklook_aparece_con_espacio"] = bool(ql and ql.isVisible())
    results["quicklook_archivo"] = Path(ql.path).name if ql else None
    results["app_completa_no_abierta"] = not win.isVisible()
    pump(0.6)
    if ql:
        force_foreground(int(ql.winId()))
        pump(0.3)
        u32.keybd_event(0x20, 0x39, 0, 0)
        u32.keybd_event(0x20, 0x39, 2, 0)
        pump(0.8)
        results["quicklook_se_cierra_con_espacio"] = not ql.isVisible()
    win32gui.PostMessage(hwnd, 0x0010, 0, 0)  # cerrar la ventana del Explorador abierta para la prueba
s.set("quicklook_enabled", False)
ctl.sync_quicklook()
for k, v in results.items():
    print(f"{k}: {v}")
