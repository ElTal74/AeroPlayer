"""Capturas de ventanas tal como se ven en Windows (para la web y las revisiones).

`grab()` devuelve la ventana con su transparencia: sobre un visor de imágenes blanco, el cristal oscuro de los
temas se ve lavado. Aquí se compone sobre el tinte del tema (lo mismo que hace el cristal acrílico de Windows
sobre el escritorio) y se recortan las esquinas redondeadas, así que la imagen se parece a la pantalla real.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath


def window_image(w, radius: float = 8.0) -> QImage:
    from aero.ui.glass import tm

    src = w.grab().toImage()
    dpr = src.devicePixelRatio()
    out = QImage(src.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    size = QRectF(0, 0, src.width() / dpr, src.height() / dpr)
    clip = QPainterPath()
    clip.addRoundedRect(size, radius, radius)
    p.setClipPath(clip)
    t = tm().theme
    g = QLinearGradient(QPointF(0, 0), QPointF(size.width(), size.height()))
    stops = list(t.bg) or [(0.0, "#2c2542"), (1.0, "#1f3b47")]
    for pos, col in stops:
        c = QColor(col)
        c.setAlpha(255)
        g.setColorAt(pos, c)
    p.fillRect(size, g)
    p.drawImage(QPointF(0, 0), src)
    p.end()
    return out


def save(w, path: str) -> None:
    """Guarda la captura; con extensión .webp, comprimida para la web (unas 4 veces menos que PNG)."""
    img = window_image(w)
    if path.lower().endswith(".webp"):
        img.save(path, "WEBP", 86)
    else:
        img.save(path)
