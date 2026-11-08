"""Ubicaciones de datos, caché y recursos de la aplicación."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from aero import APP_ID


def data_dir() -> Path:
    """Carpeta de datos del usuario (%APPDATA%\\AeroPlayer). AERO_DATA_DIR la redefine (pruebas)."""
    base = os.environ.get("AERO_DATA_DIR") or os.path.join(os.environ.get("APPDATA") or str(Path.home()), APP_ID)
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    base = os.environ.get("AERO_DATA_DIR")
    if base:
        p = Path(base) / "cache"
    else:
        p = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / APP_ID / "cache"
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
