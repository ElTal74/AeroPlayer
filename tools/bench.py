"""Mediciones de rendimiento reproducibles de AERO Player.

Uso:  python tools/bench.py [salida.json]
Mide: importación, construcción de la ventana, primer pintado, memoria, CPU en reposo, cambio de sección,
regeneración del fondo, apertura de imagen y PDF, y modo visor (si existe).
"""

from __future__ import annotations

import ctypes
import json
import os
os.environ.setdefault("AERO_NO_UPDATES", "1")   # sin consultar GitHub durante las comprobaciones
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AERO_DATA_DIR", tempfile.mkdtemp(prefix="aero_bench_"))
M = ROOT / "tests" / "media"
T0 = time.perf_counter()
R: dict = {}


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]


K32 = ctypes.windll.kernel32
K32.GetCurrentProcess.restype = wintypes.HANDLE
K32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
K32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.c_void_p] * 4


def mem_mb() -> float:
    c = PMC()
    c.cb = ctypes.sizeof(PMC)
    K32.K32GetProcessMemoryInfo(K32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return round(c.PrivateUsage / 2 ** 20, 1)


def cpu_s() -> float:
    k, u, c, e = (wintypes.FILETIME() for _ in range(4))
    K32.GetProcessTimes(K32.GetCurrentProcess(), ctypes.byref(c),
                                           ctypes.byref(e), ctypes.byref(k), ctypes.byref(u))
    f = lambda t: (t.dwHighDateTime << 32 | t.dwLowDateTime) / 1e7  # noqa: E731
    return f(k) + f(u)


def ms(t: float) -> float:
    return round((time.perf_counter() - t) * 1000, 1)


from PySide6.QtWidgets import QApplication  # noqa: E402

R["import_qt_ms"] = ms(T0)
app = QApplication([])
app.setStyle("Fusion")


def pump(sec: float):
    end = time.perf_counter() + sec
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


t = time.perf_counter()
from aero.core.config import Settings  # noqa: E402
from aero.core.db import Database  # noqa: E402
from aero.ui import main_window as mw  # noqa: E402

R["import_app_ms"] = ms(t)
settings, db = Settings(), Database()
t = time.perf_counter()
mw.apply_theme(app, settings)
win = mw.MainWindow(settings, db)
R["build_window_ms"] = ms(t)
win.resize(1600, 950)
t = time.perf_counter()
win.show()
app.processEvents()
win.repaint()
R["first_paint_ms"] = ms(t)
R["startup_total_ms"] = ms(T0)
pump(1.5)
R["mem_after_start_mb"] = mem_mb()
c0 = cpu_s()
pump(5)
R["cpu_idle_pct"] = round((cpu_s() - c0) / 5 * 100, 2)
# Las páginas se precalientan en reposo durante los primeros segundos; esto mide el reposo real después.
pump(4)
c0 = cpu_s()
pump(5)
R["cpu_idle_after_warm_pct"] = round((cpu_s() - c0) / 5 * 100, 2)

keys = [k for k in ("library", "player", "viewer", "converter", "playlists", "settings", "home")]
times = []
for k in keys:
    t = time.perf_counter()
    win.navigate(k)
    app.processEvents()
    win.repaint()
    times.append(ms(t))
    pump(0.3)
R["page_first_visit_ms_avg"] = round(sum(times) / len(times), 1)
R["page_first_visit_ms_max"] = max(times)
times = []
for k in keys:
    t = time.perf_counter()
    win.navigate(k)
    app.processEvents()
    win.repaint()
    times.append(ms(t))
    pump(0.3)
R["page_switch_ms_avg"] = round(sum(times) / len(times), 1)
R["page_switch_ms_max"] = max(times)

from aero.ui.glass import render_background, tm  # noqa: E402

for w_, h_ in ((1600, 950), (2560, 1440)):
    t = time.perf_counter()
    try:  # v1.1: el fondo se genera a media resolución (es suave) y con la opacidad incorporada
        render_background(tm().theme, w_ // 2, h_ // 2, 0.5)
    except TypeError:
        render_background(tm().theme, w_, h_)
    R[f"render_bg_{w_}x{h_}_ms"] = ms(t)

t = time.perf_counter()
win.resize(1700, 1000)
pump(0.3)
win.repaint()
R["resize_ms"] = ms(t) - 300

viewer = win.page("viewer") if hasattr(win, "page") else win.viewer
t = time.perf_counter()
viewer.open(str(M / "foto.jpg"))
while viewer.stack.currentWidget() is viewer.loading:
    app.processEvents()
R["open_image_ms"] = ms(t)
t = time.perf_counter()
viewer.open(str(M / "doc.pdf"))
app.processEvents()
R["open_pdf_ms"] = ms(t)

# v1.2: deslizador de transparencia (camino rápido) y fondo con movimiento
if hasattr(mw, "apply_levels"):
    win.navigate("settings")
    sp = win.page("settings")
    pump(0.5)
    times = []
    for v in range(20, 50):
        t = time.perf_counter()
        sp.transp.slider.setValue(v)
        sp.transp._flush()
        win.repaint()
        app.processEvents()
        times.append(ms(t))
    times.sort()
    R["slider_step_ms_median"] = times[len(times) // 2]
    R["slider_step_ms_max"] = times[-1]
    win.navigate("home")
    from aero.ui.theme import PRESETS

    spec = json.loads(json.dumps(PRESETS["aqua"]))
    spec["motion"]["speed"] = 0.5
    spec["deco"]["particles"]["on"] = True
    settings.set("user_themes", {"bench": spec})
    settings.set("theme", "user:bench")
    mw.apply_theme(app, settings)
    win.activateWindow()
    pump(1)
    c0 = cpu_s()
    pump(5)
    R["cpu_idle_motion_theme_pct"] = round((cpu_s() - c0) / 5 * 100, 2)
    settings.set("theme", "burbuja")
    mw.apply_theme(app, settings)
    pump(0.5)

c0 = cpu_s()
win.navigate("player")
win.play([str(M / "pulso.flac")], 0)
pump(1)
c0 = cpu_s()
pump(4)
R["cpu_playing_visualizer_pct"] = round((cpu_s() - c0) / 4 * 100, 1)
try:
    from aero.ui.visualizer import SCENE_KEYS

    per = {}
    for key in SCENE_KEYS:
        settings.set("visualizer_key", key)
        pump(0.6)
        c0 = cpu_s()
        pump(2)
        per[key] = round((cpu_s() - c0) / 2 * 100, 1)
    R["cpu_visualizer_by_scene_pct"] = per
except ImportError:
    pass
win.engine.stop()
pump(0.5)
c0 = cpu_s()
win.play([str(M / "clip.mkv")], 0)
pump(3)
R["cpu_playing_video_pct"] = round((cpu_s() - c0) / 3 * 100, 1)
R["mem_after_use_mb"] = mem_mb()
win.engine.stop()
if hasattr(win, "page"):
    from aero.ui.media_window import MediaWindow

    t = time.perf_counter()
    mwin = MediaWindow(settings, db)
    mwin.open(str(M / "grande.jpg"))
    iv = None
    while iv is None or iv.item.pixmap().isNull():
        app.processEvents()
        iv = mwin._views.get("image")
    R["viewer_window_image_4000x3000_ms"] = ms(t)
    mwin.close()
win.quitting = True
win.close()
print(json.dumps(R, indent=1))
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(json.dumps(R, indent=1), encoding="utf-8")
