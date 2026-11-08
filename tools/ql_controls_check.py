"""Verificación REAL de los controles del Quick Look de vídeo: mueve el puntero del sistema.

Uso: python tools/ql_controls_check.py [vídeo]
Para cada tamaño de ventana (y pantalla completa) repite: esperar a que los controles se oculten, mover el
puntero sobre el vídeo y comprobar que reaparecen al momento. Al terminar devuelve el puntero a su sitio.
Mueve el ratón real durante unos segundos: no usar mientras se trabaja con el equipo.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AERO_DATA_DIR"] = tempfile.mkdtemp(prefix="aero_qlc_")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from aero.core.config import Settings  # noqa: E402
from aero.core.db import Database  # noqa: E402
from aero.ui.controller import AppController  # noqa: E402
from aero.ui.main_window import apply_theme  # noqa: E402


WAKES: list = []
T0 = time.monotonic()


def pump(t: float) -> None:
    end = time.monotonic() + t
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


def main() -> int:
    clip = sys.argv[1] if len(sys.argv) > 1 else ""
    if not clip:
        clip = os.path.join(tempfile.mkdtemp(), "c.mp4")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=size=1280x720:rate=25:duration=60", "-c:v", "libx264", "-pix_fmt", "yuv420p", clip],
                       check=True)
    s = Settings()
    s.set("quicklook_enabled", False)
    apply_theme(app, s)
    ctl = AppController(app, s, Database())
    ctl.quit = lambda: None
    ctl.show_quicklook(clip)
    ql = ctl.quicklook
    orig = ql.wake

    def traced():
        WAKES.append(round(time.monotonic() - T0, 2))
        orig()
    ql.wake = traced
    pump(1.5)
    old = QCursor.pos()
    fails = 0
    try:
        for size in ((480, 270), (900, 506), (1400, 788), "full"):
            if size == "full":
                ql.toggle_fullscreen()
            else:
                ql._apply_size(*size)
            pump(0.4)
            for rep in range(2):
                c = ql.geometry().center() + QPoint(40 * rep, -30)
                QCursor.setPos(c)
                pump(ql.IDLE_MS / 1000 + 0.8)
                hidden = not ql._controls_visible
                QCursor.setPos(c + QPoint(12, 8))
                t0 = time.monotonic()
                pump(0.05)
                while not ql._controls_visible and time.monotonic() - t0 < 0.5:
                    pump(0.01)
                shown = ql._controls_visible
                dt = (time.monotonic() - t0) * 1000
                ok = hidden and shown
                if not ok:
                    u = ctypes.windll.user32
                    u.WindowFromPoint.restype = ctypes.c_void_p
                    cp = QCursor.pos()
                    under = u.WindowFromPoint(ctypes.wintypes.POINT(cp.x(), cp.y()))
                    ours = {int(ql.winId()): "ventana", int(ql.overlay.winId()): "capa"}
                    buf = ctypes.create_unicode_buffer(128)
                    u.GetClassNameW(ctypes.c_void_p(under), buf, 128)
                    pid = ctypes.c_ulong()
                    u.GetWindowThreadProcessId(ctypes.c_void_p(under), ctypes.byref(pid))
                    u.GetAncestor.restype = ctypes.c_void_p
                    root = u.GetAncestor(ctypes.c_void_p(under), 2)
                    print("   bajo el puntero:", ours.get(under, under), buf.value, "raíz:", ours.get(root, root),
                          "proceso propio:", pid.value == os.getpid(), "en uso:", ql.controls_in_use(),
                          "geo:", ql.geometry().getRect(), "puntero:", (cp.x(), cp.y()), "wakes:", WAKES[-3:])
                fails += not ok
                print(f"t={time.monotonic() - T0:.2f}", end=" ")
                print(f"{size!s:>12} ciclo {rep + 1}: ocultos={hidden} reaparecen={shown} ({dt:.0f} ms)"
                      f" {'OK' if ok else 'FALLO'}")
        if ql.isFullScreen():
            ql.toggle_fullscreen()
    finally:
        QCursor.setPos(old)
        ql.close_preview()
    print("RESULTADO:", "todo correcto" if not fails else f"{fails} fallos")
    return 1 if fails else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)  # el motor multimedia puede retener el cierre normal del intérprete
