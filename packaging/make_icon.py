"""Genera packaging/aero.ico a partir del icono vectorial de la aplicación (sin recursos de terceros)."""

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication

    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    from aero.ui.glass import make_app_icon

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    make_app_icon(256).save(buf, "PNG")
    img = Image.open(io.BytesIO(bytes(buf.data())))
    out = ROOT / "packaging" / "aero.ico"
    img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)
    # Icono de los archivos .aeroarchive: caja de archivo con cremallera y el sello de AERO Player
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    archive_icon(256).save(buf, "PNG")
    img = Image.open(io.BytesIO(bytes(buf.data())))
    out = ROOT / "packaging" / "aeroarchive.ico"
    img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)


def archive_icon(size: int):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen

    from aero.ui.glass import make_app_icon

    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    s = size / 256
    body = QRectF(28 * s, 46 * s, 200 * s, 182 * s)
    path = QPainterPath()
    path.addRoundedRect(body, 26 * s, 26 * s)
    g = QLinearGradient(body.topLeft(), body.bottomLeft())
    g.setColorAt(0, QColor("#7fd8ff"))
    g.setColorAt(0.5, QColor("#2a8fe0"))
    g.setColorAt(1, QColor("#1257a8"))
    p.fillPath(path, g)
    gloss = QPainterPath()
    gloss.addRoundedRect(QRectF(body.left() + 8 * s, body.top() + 6 * s, body.width() - 16 * s, body.height() * 0.42),
                         20 * s, 20 * s)
    gg = QLinearGradient(0, body.top(), 0, body.top() + body.height() * 0.42)
    gg.setColorAt(0, QColor(255, 255, 255, 150))
    gg.setColorAt(1, QColor(255, 255, 255, 10))
    p.fillPath(gloss, gg)
    p.setPen(QPen(QColor(255, 255, 255, 200), 3 * s))
    p.drawPath(path)
    # cremallera
    zx = body.center().x()
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(7):
        y = body.top() + 10 * s + i * 14 * s
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawRoundedRect(QRectF(zx - (12 if i % 2 else 2) * s, y, 10 * s, 7 * s), 2 * s, 2 * s)
    p.setBrush(QColor("#ffe680"))
    p.drawRoundedRect(QRectF(zx - 9 * s, body.top() + 108 * s, 18 * s, 26 * s), 5 * s, 5 * s)
    # sello de la aplicación
    badge = make_app_icon(256).toImage()
    p.drawImage(QRectF(132 * s, 128 * s, 112 * s, 112 * s), badge)
    p.setPen(QPen(QColor(255, 255, 255, 220), 2 * s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(188 * s, 184 * s), 54 * s, 54 * s)
    p.end()
    return img


if __name__ == "__main__":
    main()
