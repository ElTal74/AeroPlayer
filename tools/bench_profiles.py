"""Mediciones por perfil de calidad (requisito 18.12).

Uso:  python tools/bench_profiles.py [salida.json]

Cada perfil (Ultra ligero, Equilibrado, Alta calidad) se mide en un proceso nuevo, dos veces:
* «equipo»: tal cual, en este ordenador.
* «limitado»: SIMULACIÓN de un equipo modesto dentro de un objeto de trabajo de Windows con 2 núcleos y
  1,5 GB de memoria como máximo para el proceso. No reduce la velocidad de cada núcleo ni simula una
  gráfica integrada: se documenta como simulación, no como prueba en un equipo real.

Mide: arranque, memoria, CPU en reposo, CPU con un tema animado, CPU con música y visualizador, CPU con
vídeo, apertura de una imagen de 4000×3000 en el visor, abrir una carpeta de 5 000 archivos y el bloqueo
máximo de la interfaz durante esas operaciones (ningún bloqueo debería superar ~50 ms).
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "tests" / "media"
PROFILES = ("ultra", "balanced", "high")


# --------------------------------------------------------------------------- entorno limitado (simulado)
class _JOBLIMIT(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _IOCOUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]


class _EXTLIMIT(ctypes.Structure):
    _fields_ = [("Basic", _JOBLIMIT), ("Io", _IOCOUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def limit_self(cores: int = 2, mem_bytes: int = 1536 * 2 ** 20) -> None:
    k = ctypes.windll.kernel32
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k.CreateJobObjectW(None, None)
    info = _EXTLIMIT()
    info.Basic.LimitFlags = 0x100 | 0x10  # PROCESS_MEMORY | AFFINITY
    info.Basic.Affinity = (1 << cores) - 1
    info.ProcessMemoryLimit = mem_bytes
    k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    k.AssignProcessToJobObject(job, k.GetCurrentProcess())


# --------------------------------------------------------------------------- proceso hijo
def child(profile: str, limited: bool) -> dict:
    if limited:
        limit_self()
    os.environ["AERO_DATA_DIR"] = tempfile.mkdtemp(prefix="aero_bp_")
    os.environ["AERO_NO_TUTORIAL"] = "1"
    sys.path.insert(0, str(ROOT))
    t0 = time.perf_counter()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    sys.path.insert(0, str(ROOT / "tools"))
    app = QApplication([])
    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.ui import main_window as mw
    from aero.ui.controller import AppController

    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.c_void_p] * 4
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
            [(n, ctypes.c_size_t) for n in ("Peak", "WS", "a", "b", "c", "d", "PF", "PPF", "Private")]

    def mem_mb() -> float:
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return round(c.Private / 2 ** 20, 1)

    def cpu_s() -> float:
        ft = [wintypes.FILETIME() for _ in range(4)]
        k32.GetProcessTimes(k32.GetCurrentProcess(), *(ctypes.byref(f) for f in ft))
        return sum((f.dwHighDateTime << 32 | f.dwLowDateTime) / 1e7 for f in ft[2:])

    # Bloqueo máximo del hilo de la interfaz: un temporizador de 5 ms anota el mayor hueco.
    gap = {"last": time.perf_counter(), "max": 0.0}

    def beat():
        now = time.perf_counter()
        gap["max"] = max(gap["max"], now - gap["last"])
        gap["last"] = now

    hb = QTimer()
    hb.setInterval(5)
    hb.timeout.connect(beat)

    from PySide6.QtCore import QEventLoop

    def pump(sec: float):
        # Espera real con el bucle de eventos de Qt (bloqueado hasta que hay trabajo): no consume CPU propia.
        loop = QEventLoop()
        QTimer.singleShot(int(sec * 1000), loop.quit)
        loop.exec()

    def block_during(fn, settle: float) -> float:
        pump(0.2)
        hb.start()
        gap["max"], gap["last"] = 0.0, time.perf_counter()
        fn()
        pump(settle)
        hb.stop()
        return round(gap["max"] * 1000, 1)

    def cpu_during(sec: float) -> float:
        c0 = cpu_s()
        pump(sec)
        return round((cpu_s() - c0) / sec * 100, 2)

    R: dict = {"profile": profile, "limited": limited}
    s = Settings()
    s.set("quality_profile", profile)
    s.set("quicklook_enabled", False)
    mw.apply_theme(app, s)
    ctl = AppController(app, s, Database())
    ctl.quit = lambda: None
    win = ctl.show_main()
    win.resize(1400, 860)
    app.processEvents()
    R["startup_ms"] = round((time.perf_counter() - t0) * 1000)
    pump(9)  # precalentamiento de páginas en reposo
    R["mem_idle_mb"] = mem_mb()
    R["cpu_idle_pct"] = cpu_during(8)

    from aero.ui.theme import PRESETS

    spec = json.loads(json.dumps(PRESETS["aqua"]))
    spec["motion"]["speed"] = 0.5
    for key in ("bubbles", "particles", "clouds"):
        spec["deco"].setdefault(key, {})["on"] = True
    s.set("user_themes", {"bench": spec})
    s.set("theme", "user:bench")
    win.navigate("home")
    win.activateWindow()
    pump(1.5)
    R["cpu_motion_theme_pct"] = cpu_during(6)
    s.set("theme", "burbuja")
    pump(0.5)

    win.play([str(M / "pulso.flac")], 0)
    win.navigate("player")
    pump(1)
    R["cpu_music_visualizer_pct"] = cpu_during(5)
    win.engine.stop()
    pump(0.3)
    win.play([str(M / "clip.mkv")], 0)
    pump(0.8)
    R["cpu_video_pct"] = cpu_during(3)
    win.engine.stop()

    t = time.perf_counter()
    ctl.show_quicklook(str(M / "grande.jpg"))
    ql = ctl.quicklook
    while "image" not in ql._views or ql._views["image"].item.pixmap().isNull():
        app.processEvents()
        time.sleep(0.001)
    R["quicklook_image_ms"] = round((time.perf_counter() - t) * 1000)
    ql.close_preview()

    big = Path(tempfile.mkdtemp(prefix="aero_bp_dir_"))
    for i in range(5000):
        (big / f"documento_{i:05d}.txt").write_bytes(b"x")
    page = win.page("files")
    win.navigate("files")
    t = time.perf_counter()
    R["folder_5000_block_ms"] = block_during(lambda: page.browse(str(big)), 1.5)
    R["folder_5000_rows"] = page.browser.model.rowCount()
    R["mem_after_use_mb"] = mem_mb()
    R["ui_max_block_ms_idle"] = block_during(lambda: None, 2)
    return R


# --------------------------------------------------------------------------- proceso principal
def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        res = child(sys.argv[2], "--limited" in sys.argv)
        print("RESULT " + json.dumps(res))
        sys.stdout.flush()
        os._exit(0)
    out = []
    for limited in (False, True):
        for prof in PROFILES:
            args = [sys.executable, __file__, "--child", prof] + (["--limited"] if limited else [])
            r = subprocess.run(args, capture_output=True, text=True, timeout=240, cwd=ROOT)
            line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")), "")
            if not line:
                print("fallo", prof, limited, r.stderr[-800:])
                continue
            res = json.loads(line[7:])
            out.append(res)
            print(json.dumps(res))
    data = {"fecha": time.strftime("%Y-%m-%d %H:%M"), "nota": "«limited» es una simulación (2 núcleos y 1,5 GB por "
            "proceso en un objeto de trabajo de Windows) en este mismo equipo, no un equipo modesto real.",
            "resultados": out}
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
