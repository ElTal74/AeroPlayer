"""Mide el núcleo nativo (Rust) frente a la versión Python en un árbol sintético grande.

Uso: python tools/bench_native.py [salida.json]
Crea 50 000 archivos en 500 carpetas en una carpeta temporal (y la borra al terminar).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def best(fn, n=3):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return round(min(times) * 1000, 1)


def main(out: str | None) -> dict:
    from aero import files
    from aero.core import native
    from aero.ui.command_palette import search_files, search_files_py

    if not native.available():
        raise SystemExit("Núcleo nativo no disponible: python tools/build_native.py")
    tmp = Path(tempfile.mkdtemp(prefix="aero_bench_native_"))
    exts = [".mp4", ".mkv", ".mp3", ".flac", ".jpg", ".png", ".docx", ".pdf", ".zip", ".iso", ".py", ".txt", ""]
    try:
        for d in range(500):
            sub = tmp / f"carpeta {d:03d}" / ("más hondo" if d % 3 else "")
            sub.mkdir(parents=True, exist_ok=True)
            for i in range(100):
                (sub / f"archivo {d:03d}-{i:03d} canción{exts[i % len(exts)]}").write_bytes(b"x" * (i % 5))
        big = tmp / "carpeta 000"
        for i in range(5000):
            (big / f"extra {i:05d}{exts[i % len(exts)]}").write_bytes(b"x")
        stop = threading.Event()
        r = {
            "listar_5100_rust_ms": best(lambda: files.list_dir(str(big))),
            "listar_5100_python_ms": best(lambda: files.list_dir_py(str(big))),
            "estadisticas_50k_rust_ms": best(lambda: files.folder_stats(str(tmp))),
            "estadisticas_50k_python_ms": best(lambda: files.folder_stats_py(str(tmp))),
            "buscar_50k_rust_ms": best(lambda: search_files([str(tmp)], "cancion 499", stop, 400)),
            "buscar_50k_python_ms": best(lambda: search_files_py([str(tmp)], "cancion 499", stop, 400)),
        }
        # ¿Libera el GIL? Mientras Rust recorre, otro hilo de Python debe poder trabajar.
        ticks = [0]
        done = threading.Event()

        def busy():
            while not done.is_set():
                ticks[0] += 1
                time.sleep(0.001)

        t = threading.Thread(target=busy)
        t.start()
        t0 = time.perf_counter()
        files.folder_stats(str(tmp))
        el = time.perf_counter() - t0
        done.set()
        t.join()
        r["hilo_python_activo_durante_rust_pct"] = round(min(100.0, ticks[0] / max(1, el * 1000) * 100), 1)
        for k, v in r.items():
            print(f"{k:42} {v}")
        if out:
            Path(out).write_text(json.dumps(r, indent=1), encoding="utf-8")
        return r
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
