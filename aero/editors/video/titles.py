"""Títulos como imagen transparente: los dibuja Qt igual en el visor y en la exportación.

Al exportar, cada título se renderiza a PNG y se superpone como una imagen más; así se mueve, escala, gira y
recorta exactamente como en el visor (antes `drawtext` solo admitía la posición arriba / centro / abajo).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

FAMILY = "Segoe UI"
PAD = 6


def title_font(size_px: float) -> QFont:
    f = QFont(FAMILY)
    f.setPixelSize(max(4, int(round(size_px))))
    f.setBold(True)
    return f


_APP = None


def _ensure_gui() -> None:
    """Las fuentes de Qt necesitan una QGuiApplication: sin ella Qt aborta el proceso (exportar desde un guion o
    una prueba sin ventana). En AERO Player siempre existe; aquí se crea solo si falta."""
    global _APP
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        from PySide6.QtWidgets import QApplication

        _APP = QApplication([])   # completa (también sirve si después se abren ventanas)


def render_title(clip, unit: float = 1.0) -> QImage:
    """Imagen ARGB del texto del clip (`unit`: píxeles del lienzo de salida por píxel del proyecto)."""
    _ensure_gui()
    lines = (clip.text or " ").splitlines() or [" "]
    f = title_font(max(8, clip.text_size) * unit)
    fm = QFontMetricsF(f)
    border = max(1.0, 2.0 * unit)
    w = max(fm.horizontalAdvance(ln) for ln in lines) + 2 * (PAD + border)
    lh = fm.lineSpacing()
    h = lh * len(lines) + 2 * (PAD + border)
    img = QImage(max(2, int(w + 0.5)), max(2, int(h + 0.5)), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    path = QPainterPath()
    for i, ln in enumerate(lines):
        x = (w - fm.horizontalAdvance(ln)) / 2
        y = PAD + border + i * lh + fm.ascent()
        path.addText(QPointF(x, y), f, ln)
    # Borde suave (como el de los títulos exportados) y relleno del color elegido
    p.setPen(QPen(QColor(0, 0, 0, 115), border * 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(clip.text_color) if QColor(clip.text_color).isValid() else QColor("#ffffff"))
    p.drawPath(path)
    p.end()
    return img


def bounds(clip) -> QRectF:
    img = render_title(clip)
    return QRectF(0, 0, img.width(), img.height())
