"""Ubicaciones de datos, caché y recursos de la aplicación."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from aero import APP_ID


def _platform_dirs() -> tuple[Path, Path]:
    """(datos, caché) según el sistema: Windows %APPDATA% / %LOCALAPPDATA%; macOS ~/Library/Application Support y
    ~/Library/Caches; Linux XDG (~/.local/share y ~/.cache)."""
    home = Path.home()
    if sys.platform == "win32":
        data = Path(os.environ.get("APPDATA") or home)
        cache = Path(os.environ.get("LOCALAPPDATA") or home) / APP_ID / "cache"
        return data / APP_ID, cache
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_ID, home / "Library" / "Caches" / APP_ID
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    cache = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    return data / APP_ID, cache / APP_ID


def data_dir() -> Path:
    """Carpeta de datos del usuario (ver `_platform_dirs`). AERO_DATA_DIR la redefine (pruebas)."""
    base = os.environ.get("AERO_DATA_DIR")
    p = Path(base) if base else _platform_dirs()[0]
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    base = os.environ.get("AERO_DATA_DIR")
    p = Path(base) / "cache" if base else _platform_dirs()[1]
    p.mkdir(parents=True, exist_ok=True)
    return p


def resource_dir() -> Path:
    """Recursos empaquetados (funciona también dentro de un ejecutable de PyInstaller)."""
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen) / "aero" / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


def app_root() -> Path:
    """Carpeta del ejecutable (o del repositorio en desarrollo); allí se buscan binarios incluidos."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def default_output_dir() -> Path:
    docs = Path.home() / "Documents"
    if not docs.exists():
        docs = Path.home()
    return docs / "AERO Player" / "Conversiones"
