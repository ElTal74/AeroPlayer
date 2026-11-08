"""Localización de herramientas externas (FFmpeg, ffprobe, LibreOffice) y sondeo de medios."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from aero.core.paths import app_root

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_overrides: dict[str, str] = {}


def set_override(name: str, path: str) -> None:
    if path:
        _overrides[name] = path
    else:
        _overrides.pop(name, None)
    find_tool.cache_clear()
    encoders.cache_clear()
    hw_encoder_works.cache_clear()


@lru_cache(maxsize=None)
def find_tool(name: str) -> str | None:
    """Busca el binario: ruta configurada → carpeta bin incluida → PATH → ubicaciones típicas."""
    exe = name + (".exe" if os.name == "nt" else "")
    ov = _overrides.get(name)
    if ov and Path(ov).is_file():
        return ov
    for cand in (app_root() / "bin" / exe, app_root() / "bin" / name / exe):
        if cand.is_file():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    if name == "soffice":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            cand = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if cand.is_file():
                return str(cand)
    return None


def run_quiet(args: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
                          stdin=subprocess.DEVNULL)


@lru_cache(maxsize=None)
def encoders() -> frozenset[str]:
    ff = find_tool("ffmpeg")
    if not ff:
        return frozenset()
    try:
        out = run_quiet([ff, "-hide_banner", "-encoders"], 15).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
            names.add(parts[1])
    return frozenset(names)


@lru_cache(maxsize=None)
def hw_encoder_works(name: str) -> bool:
    """Prueba real de un codificador por hardware (NVENC/QSV/AMF) con un fotograma sintético."""
    ff = find_tool("ffmpeg")
    if not ff or name not in encoders():
        return False
    try:
        r = run_quiet([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.1",
                       "-frames:v", "2", "-c:v", name, "-f", "null", "-"], 20)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def probe(path: str) -> dict | None:
    """Información técnica con ffprobe (JSON) o None si no está disponible / falla."""
    fp = find_tool("ffprobe")
    if not fp:
        return None
    try:
        r = run_quiet([fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path], 30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except ValueError:
        return None


def reveal_in_explorer(path: str) -> None:
    p = Path(path)
    if os.name == "nt":
        if p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)], creationflags=CREATE_NO_WINDOW)
        else:
            os.startfile(str(p if p.exists() else p.parent))  # noqa: S606 - ruta validada
    else:  # pragma: no cover
        subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])


def open_with_default(path: str) -> None:
    if os.name == "nt":
        os.startfile(path)  # noqa: S606
    else:  # pragma: no cover
        subprocess.Popen(["xdg-open", path])
