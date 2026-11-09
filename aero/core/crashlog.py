"""Registro local de errores: excepciones no capturadas, cierres nativos y avisos graves de Qt.

Todo se queda en el equipo (carpeta de datos › «registro»), nunca se envía. Sirve para adjuntarlo a una
incidencia en GitHub. Cada archivo se limita a 512 KB: al pasarse se guarda como `.1` y se empieza otro.
"""

from __future__ import annotations

import datetime as _dt
import faulthandler
import os
import sys
import threading
import traceback
from pathlib import Path

MAX_BYTES = 512 * 1024
_installed = False
_native = None          # archivo abierto para faulthandler (debe seguir abierto mientras dure el proceso)


def folder() -> Path:
    from aero.core.paths import data_dir

    d = data_dir() / "registro"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_file() -> Path:
    return folder() / "errores.log"


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            old = path.with_suffix(path.suffix + ".1")
            old.unlink(missing_ok=True)
            path.rename(old)
    except OSError:
        pass


def write(title: str, text: str = "") -> None:
    """Añade una entrada al registro. Nunca lanza: un fallo al registrar no debe provocar otro."""
    try:
        from aero import __version__

        path = log_file()
        _rotate(path)
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(f"[{stamp}] AERO Player {__version__} · {sys.platform} · {title}\n")
            if text:
                fh.write(text.rstrip() + "\n")
            fh.write("\n")
    except Exception:  # noqa: BLE001
        pass


def _excepthook(kind, value, tb):
    write(f"Error no capturado: {kind.__name__}", "".join(traceback.format_exception(kind, value, tb)))
    if sys.__stderr__ is not None:
        traceback.print_exception(kind, value, tb)


def _thread_hook(args):
    if args.exc_type is SystemExit:
        return
    name = getattr(args.thread, "name", "?")
    write(f"Error en el hilo «{name}»: {args.exc_type.__name__}",
          "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))


def _qt_messages(mode, _ctx, message) -> None:
    from PySide6.QtCore import QtMsgType

    text = str(message)
    # FFmpeg avisa como «crítico» al sondear codificadores por hardware (MFT): es normal, no es un error
    benign = mode == QtMsgType.QtCriticalMsg and text.startswith("FFmpeg log:")
    if mode == QtMsgType.QtFatalMsg or (mode == QtMsgType.QtCriticalMsg and not benign):
        write(f"Qt: {mode.name}", text)
    if sys.__stderr__ is not None:
        try:
            sys.__stderr__.write(f"{message}\n")
        except (OSError, ValueError):
            pass


def install(qt: bool = True) -> None:
    """Una vez por proceso, al arrancar la aplicación (no en las pruebas)."""
    global _installed, _native
    if _installed or os.environ.get("AERO_NO_CRASHLOG"):
        return
    _installed = True
    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
    try:
        native = folder() / "cierres.log"
        _rotate(native)
        _native = open(native, "a", encoding="utf-8")   # noqa: SIM115 - abierto toda la vida del proceso
        faulthandler.enable(file=_native, all_threads=True)
    except OSError:
        pass
    if qt:
        try:
            from PySide6.QtCore import qInstallMessageHandler

            qInstallMessageHandler(_qt_messages)
        except ImportError:  # pragma: no cover
            pass


def recent(limit: int = 20000) -> str:
    """Final del registro (para mostrarlo o copiarlo)."""
    try:
        return log_file().read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""
