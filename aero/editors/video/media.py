"""Servicios de medios del editor de vídeo (todos en hilos de trabajo, con caché).

* Miniatura de un clip (un fotograma con FFmpeg).
* Forma de onda (picos por intervalo) a partir de audio mono a baja frecuencia.
* Proxies: copias a 360 px de alto y codificación rápida para editar con fluidez en equipos modestos; la
  exportación usa siempre los originales.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from aero.core import tools

WAVE_RATE = 50  # picos por segundo


def _ff() -> str:
    return tools.find_tool("ffmpeg") or "ffmpeg"


def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def thumbnail_png(path: str, t: float, height: int = 72) -> bytes:
    r = subprocess.run([_ff(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}",
                        "-i", path, "-frames:v", "1", "-vf", f"scale=-2:{height}", "-f", "image2pipe", "-c:v", "png",
                        "-"], capture_output=True, timeout=30, creationflags=_flags())
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("Sin fotograma")
    return r.stdout


def waveform(path: str) -> list[float]:
    """Picos normalizados (0–1), WAVE_RATE por segundo de archivo."""
    import numpy as np

    rate = 4000
    r = subprocess.run([_ff(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", path, "-vn", "-ac", "1",
                        "-ar", str(rate), "-f", "s16le", "-"], capture_output=True, timeout=120,
                       creationflags=_flags())
    data = np.frombuffer(r.stdout, dtype=np.int16)
    if data.size == 0:
        return []
    step = rate // WAVE_RATE
    n = data.size // step
    peaks = np.abs(data[: n * step].reshape(n, step).astype(np.int32)).max(axis=1) / 32768.0
    return [float(x) for x in np.clip(peaks * 1.4, 0, 1)]


def proxy_path(path: str) -> Path:
    from aero.core.paths import cache_dir

    st = os.stat(path)
    key = hashlib.sha1(f"{os.path.abspath(path)}|{st.st_mtime}|{st.st_size}".encode()).hexdigest()[:20]
    d = cache_dir() / "video-proxies"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.mp4"


def make_proxy(path: str) -> str:
    out = proxy_path(path)
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    tmp = out.with_suffix(".part.mp4")
    r = subprocess.run([_ff(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", path, "-vf",
                        "scale=-2:360", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-g", "15",
                        "-c:a", "aac", "-b:a", "96k", str(tmp)], capture_output=True, timeout=3600,
                       creationflags=_flags())
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("No se pudo crear el proxy.")
    os.replace(tmp, out)
    return str(out)
