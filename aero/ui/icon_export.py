"""Exporta la familia de iconos AERO a archivos .ico para el Explorador de Windows.

Cada .ico lleva 10 tamaños (16–256 px) en PNG, como los iconos de Windows desde Vista; se dibujan con el mismo
código que dentro de la aplicación (`aero.ui.file_icons`), así que el Explorador y AERO Player muestran lo mismo.

* Paquete instalado: los .ico van dentro de la instalación (`_internal\\icons`), una ruta estable.
* Ejecución desde el código: se generan en `packaging/icons` (los mismos archivos que se incluyen al compilar).

Uso: `python -m aero.ui.icon_export [carpeta]` regenera los archivos.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
ROOT = Path(__file__).resolve().parents[2]


def icons_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "icons"
    return ROOT / "packaging" / "icons"


def icon_path(category: str) -> Path:
    return icons_dir() / f"{category}.ico"


def _png(category: str, size: int) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    from aero.ui import file_icons

    pm = file_icons.pixmap(category, size, 1.0, dark=False)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.toImage().save(buf, "PNG")
    buf.close()
    return bytes(data)


def ico_bytes(category: str) -> bytes:
    images = [(s, _png(category, s)) for s in SIZES]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, png in images:
        dim = 0 if s >= 256 else s                       # 0 = 256 en el formato ICO
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    return head + entries + blobs


def export(folder: Path | None = None) -> dict[str, Path]:
    """Escribe un .ico por categoría (solo si cambió, para no tocar la fecha sin motivo)."""
    from aero.ui.file_icons import PALETTE

    folder = Path(folder or icons_dir())
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for cat in PALETTE:
        path = folder / f"{cat}.ico"
        data = ico_bytes(cat)
        try:
            same = path.read_bytes() == data
        except OSError:
            same = False
        if not same:
            path.write_bytes(data)
        out[cat] = path
    return out


def ensure() -> Path:
    """Garantiza que los .ico existen (desde el código se generan si faltan). Devuelve la carpeta."""
    from aero.ui.file_icons import PALETTE

    folder = icons_dir()
    if not all((folder / f"{c}.ico").exists() for c in PALETTE):
        import threading

        if threading.current_thread() is not threading.main_thread():
            return folder          # QPixmap solo en el hilo de la interfaz: quien llame verá que falta el archivo
        if getattr(sys, "frozen", False):
            raise FileNotFoundError(f"Faltan los iconos de la instalación en {folder}")
        export(folder)
    return folder


if __name__ == "__main__":
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication(sys.argv[:1])
    for c, p in export(Path(sys.argv[1]) if len(sys.argv) > 1 else None).items():
        print(c, p, p.stat().st_size)
