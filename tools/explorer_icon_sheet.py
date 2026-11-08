"""Hoja con los iconos AERO tal como los dibuja el Shell de Windows (el Explorador).

Crea tipos de archivo de prueba temporales (`.aerohoja<categoría>`, solo en HKCU) cuyo icono es el .ico AERO de
cada categoría, pide al Shell la imagen de un archivo de cada tipo (en un proceso nuevo, sin cachés) y después
borra todo. No toca ningún tipo real ni ninguna asociación.

Uso: python tools/explorer_icon_sheet.py <salida.png>
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CATS = ("folder", "video", "audio", "image", "document", "sheet", "slides", "pdf", "archive", "disc", "torrent", "app",
        "installer", "shortcut", "code", "font", "system", "unknown")
B = "\\"


def _setup(reg, classes, icon_path):
    for c in CATS:
        reg.set(classes + B + f".aerohoja{c}", None, f"AeroHoja.{c}")
        reg.set(classes + B + f"AeroHoja.{c}", None, f"Hoja {c}")
        reg.set(classes + B + f"AeroHoja.{c}" + B + "DefaultIcon", None, f'"{icon_path(c)}",0')


def _clean(reg, classes):
    for c in CATS:
        reg.delete_tree(classes + B + f".aerohoja{c}")
        reg.delete_tree(classes + B + f"AeroHoja.{c}")


def main(out: str) -> int:
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication(sys.argv[:1])  # noqa: F841
    from aero.core.associations import CLASSES, Registry, notify_shell
    from aero.ui.icon_export import ensure, icon_path

    ensure()
    reg = Registry()
    folder = Path(tempfile.mkdtemp(prefix="aero_hoja_"))
    for c in CATS:
        (folder / f"{c}.aerohoja{c}").write_bytes(b"x")
    _setup(reg, CLASSES, icon_path)
    notify_shell()
    try:
        r = subprocess.run([sys.executable, __file__, "--render", str(folder), out], capture_output=True, text=True,
                           timeout=120)
        print(r.stdout.strip() or r.stderr.strip())
        return r.returncode
    finally:
        _clean(reg, CLASSES)
        notify_shell()
        for f in folder.iterdir():
            f.unlink()
        folder.rmdir()


def render(folder: str, out: str) -> int:
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

    app = QGuiApplication(sys.argv[:1])  # noqa: F841
    from aero.core.explorer_icons import shell_icon_image
    from aero.core.filetypes import CATEGORIES

    cols, cell = 6, 150
    rows = (len(CATS) + cols - 1) // cols
    sheet = QImage(cols * cell * 2, rows * cell, QImage.Format.Format_ARGB32)
    sheet.fill(QColor("#ffffff"))
    p = QPainter(sheet)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont("Segoe UI", 9)
    p.setFont(f)
    for half, bg, fg in ((0, "#ffffff", "#222222"), (1, "#202020", "#e8e8e8")):   # Explorador claro y oscuro
        p.fillRect(QRect(half * cols * cell, 0, cols * cell, rows * cell), QColor(bg))
        for i, c in enumerate(CATS):
            x = half * cols * cell + (i % cols) * cell
            y = (i // cols) * cell
            img = shell_icon_image(os.path.join(folder, f"{c}.aerohoja{c}"), 96)
            if not img.isNull():
                p.drawImage(x + (cell - 96) // 2, y + 10, img)
            p.setPen(QColor(fg))
            p.drawText(QRect(x, y + 112, cell, 30), Qt.AlignmentFlag.AlignHCenter, CATEGORIES.get(c, c))
    p.end()
    sheet.save(out)
    print("hoja", out)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--render":
        sys.exit(render(sys.argv[2], sys.argv[3]))
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "explorer_icons.png"))
