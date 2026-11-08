"""Lienzo de AERO Paint: zoom, desplazamiento, herramientas de dibujo, selección y vista previa de formas."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QInputDialog, QWidget

from aero.editors.paint.document import PaintDocument
from aero.i18n import tr

SHAPES = ("line", "rect", "ellipse", "triangle", "star")
BRUSHES = {"round": "Redondo", "square": "Cuadrado", "marker": "Rotulador", "spray": "Aerógrafo"}


def _checker(p: QPainter, r: QRectF) -> None:
    p.fillRect(r, QColor("#ffffff"))
    s = 10
    p.save()
    p.setClipRect(r)
    c = QColor("#e3e6ea")
    y = r.top()
    row = 0
    while y < r.bottom():
        x = r.left() + (s if row % 2 else 0)
        while x < r.right():
            p.fillRect(QRectF(x, y, s, s), c)
            x += 2 * s
        y += s
        row += 1
    p.restore()


class PaintCanvas(QWidget):
    changed = Signal()
    zoom_changed = Signal(float)
    color_picked = Signal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        from aero.ui.glass import mark_opaque

        mark_opaque(self)  # pinta toda su área: el cristal de debajo no se repinta en cada trazo
        self.doc: PaintDocument | None = None
        self.zoom = 1.0
        self.offset = QPointF(0, 0)
        self.tool = "brush"
        self.brush = "round"
        self.width_px = 8
        self.opacity = 1.0
        self.primary = QColor("#1f6feb")
        self.secondary = QColor("#ffffff")
        self.fill_shapes = False
        self.tolerance = 24
        self.font_size = 36
        self.grid = False
        self.selection: QPainterPath | None = None   # en coordenadas de la imagen
        self.auto_fit = True
        self._drag = None
        self._last: QPointF | None = None
        self._color = self.primary
        self._lasso: list[QPointF] = []
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(False)
        self.setMinimumSize(320, 240)

    # ------------------------------------------------------------------ geometría
    def set_document(self, doc: PaintDocument) -> None:
        self.doc = doc
        self.selection = None
        self.fit()

    def image_rect(self) -> QRectF:
        s = self.doc.size
        return QRectF(self.offset.x(), self.offset.y(), s.width() * self.zoom, s.height() * self.zoom)

    def to_image(self, p: QPointF) -> QPointF:
        return QPointF((p.x() - self.offset.x()) / self.zoom, (p.y() - self.offset.y()) / self.zoom)

    def fit(self) -> None:
        self.auto_fit = True
        if self.doc is None:
            return
        s = self.doc.size
        z = min((self.width() - 40) / max(1, s.width()), (self.height() - 40) / max(1, s.height()), 4.0)
        self.set_zoom(max(0.02, z), center=True)

    def set_zoom(self, z: float, anchor: QPointF | None = None, center: bool = False) -> None:
        if self.doc is None:
            return
        z = max(0.02, min(32.0, z))
        if center:
            s = self.doc.size
            self.offset = QPointF((self.width() - s.width() * z) / 2, (self.height() - s.height() * z) / 2)
        else:
            a = anchor or QPointF(self.width() / 2, self.height() / 2)
            img = self.to_image(a)
            self.offset = QPointF(a.x() - img.x() * z, a.y() - img.y() * z)
        self.zoom = z
        self.zoom_changed.emit(z)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.doc is not None and self.auto_fit:
            self.fit()  # mientras no se haga zoom a mano, el lienzo se ajusta a la ventana

    # ------------------------------------------------------------------ dibujo en pantalla
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(18, 21, 28))
        if self.doc is None:
            return
        r = self.image_rect()
        _checker(p, r)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 2)
        p.drawImage(r, self.doc.render())
        if self.grid and self.zoom >= 2:
            p.setPen(QPen(QColor(0, 0, 0, 40), 1))
            step = self.zoom
            x = r.left()
            while x <= r.right():
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                x += step
            y = r.top()
            while y <= r.bottom():
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
                y += step
        elif self.grid:
            step = 32 * self.zoom
            p.setPen(QPen(QColor(0, 0, 0, 45), 1))
            x = r.left()
            while x <= r.right():
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                x += step
            y = r.top()
            while y <= r.bottom():
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
                y += step
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.offset)
        p.scale(self.zoom, self.zoom)
        if self._drag and self._drag[0] in SHAPES:
            self._draw_shape(p, self._drag[0], self._drag[1], self._drag[2])
        if self._drag and self._drag[0] == "select":
            path = QPainterPath()
            path.addRect(QRectF(self._drag[1], self._drag[2]).normalized())
            self._ants(p, path)
        if self._lasso:
            path = QPainterPath()
            path.addPolygon(QPolygonF(self._lasso))
            self._ants(p, path)
        if self.selection is not None:
            self._ants(p, self.selection)

    def _ants(self, p: QPainter, path: QPainterPath) -> None:
        w = 1.2 / self.zoom
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("white"), w))
        p.drawPath(path)
        pen = QPen(QColor("black"), w, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawPath(path)

    # ------------------------------------------------------------------ trazos
    def _pen(self, color: QColor) -> QPen:
        c = QColor(color)
        c.setAlphaF(c.alphaF() * (0.45 if self.brush == "marker" else 1.0) * self.opacity)
        cap = Qt.PenCapStyle.SquareCap if self.brush == "square" or self.tool == "pencil" else Qt.PenCapStyle.RoundCap
        width = 1 if self.tool == "pencil" and self.width_px <= 1 else self.width_px
        return QPen(c, width, Qt.PenStyle.SolidLine, cap, Qt.PenJoinStyle.RoundJoin)

    def _layer_painter(self) -> QPainter | None:
        if self.doc is None or not self.doc.current.visible:
            return None
        p = QPainter(self.doc.current.image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, self.tool != "pencil")
        if self.selection is not None:
            p.setClipPath(self.selection)  # solo se pinta dentro de la selección
        return p

    def _stroke(self, a: QPointF, b: QPointF) -> None:
        p = self._layer_painter()
        if p is None:
            return
        if self.tool == "eraser":
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.setPen(QPen(QColor(0, 0, 0, 255), self.width_px, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(a, b)
        elif self.tool == "brush" and self.brush == "spray":
            rnd = random.Random(int(a.x() * 31 + a.y() * 17))
            c = QColor(self._color)
            c.setAlphaF(0.5 * self.opacity)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            r = self.width_px
            for _ in range(int(6 + r)):
                ang, dist = rnd.uniform(0, math.tau), r * math.sqrt(rnd.random())
                p.drawEllipse(QPointF(b.x() + math.cos(ang) * dist, b.y() + math.sin(ang) * dist), 0.7, 0.7)
        else:
            p.setPen(self._pen(self._color))
            p.drawLine(a, b)
        p.end()
        self.update()

    def _shape_path(self, kind: str, a: QPointF, b: QPointF) -> QPainterPath:
        r = QRectF(a, b).normalized()
        path = QPainterPath()
        if kind == "line":
            path.moveTo(a)
            path.lineTo(b)
        elif kind == "rect":
            path.addRect(r)
        elif kind == "ellipse":
            path.addEllipse(r)
        elif kind == "triangle":
            path.addPolygon(QPolygonF([QPointF(r.center().x(), r.top()), r.bottomRight(), r.bottomLeft()]))
            path.closeSubpath()
        else:  # estrella de cinco puntas
            c, ro = r.center(), min(r.width(), r.height()) / 2
            pts = []
            for i in range(10):
                rr = ro if i % 2 == 0 else ro * 0.45
                ang = -math.pi / 2 + i * math.pi / 5
                pts.append(QPointF(c.x() + math.cos(ang) * rr, c.y() + math.sin(ang) * rr))
            path.addPolygon(QPolygonF(pts))
            path.closeSubpath()
        return path

    def _draw_shape(self, p: QPainter, kind: str, a: QPointF, b: QPointF) -> None:
        path = self._shape_path(kind, a, b)
        if self.fill_shapes and kind != "line":
            c = QColor(self.secondary)
            c.setAlphaF(c.alphaF() * self.opacity)
            p.fillPath(path, c)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(self._pen(self._color))
        p.drawPath(path)

    def _constrain(self, a: QPointF, b: QPointF, shift: bool) -> QPointF:
        if not shift:
            return b
        d = b - a
        m = max(abs(d.x()), abs(d.y()))
        return QPointF(a.x() + math.copysign(m, d.x() or 1), a.y() + math.copysign(m, d.y() or 1))

    # ------------------------------------------------------------------ ratón
    def mousePressEvent(self, e):
        if self.doc is None:
            return
        pos = e.position()
        ip = self.to_image(pos)
        self.setFocus()
        if e.button() == Qt.MouseButton.MiddleButton or self.tool == "hand":
            self._drag = ("pan", pos, QPointF(self.offset))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            return
        self._color = self.primary if e.button() == Qt.MouseButton.LeftButton else self.secondary
        t = self.tool
        if t == "picker":
            c = self.doc.pick(int(ip.x()), int(ip.y()))
            self.color_picked.emit(c)
            return
        if t == "fill":
            mask = None
            if self.selection is not None:
                mask = self._selection_mask()
            self.doc.flood_fill(int(ip.x()), int(ip.y()), self._color, self.tolerance, mask)
            self.update()
            self.changed.emit()
            return
        if t == "text":
            text, ok = QInputDialog.getText(self, tr("Texto"), tr("Escribe el texto:"))
            if ok and text:
                self.doc.checkpoint("Texto")
                p = self._layer_painter()
                if p is not None:
                    f = QFont("Segoe UI")
                    f.setPixelSize(self.font_size)
                    f.setBold(True)
                    p.setFont(f)
                    p.setPen(self._color)
                    p.drawText(ip, text)
                    p.end()
                self.update()
                self.changed.emit()
            return
        if t in ("select", "crop"):
            self._drag = ("select", ip, ip)
            self.selection = None
            return
        if t == "lasso":
            self._lasso = [ip]
            self.selection = None
            return
        if t in SHAPES:
            self._drag = (t, ip, ip)
            return
        if t in ("pencil", "brush", "eraser"):
            if not self.doc.current.visible:
                return
            self.doc.checkpoint({"pencil": "Lápiz", "brush": "Pincel", "eraser": "Borrador"}[t])
            self._last = ip
            self._stroke(ip, ip)
            self._drag = ("stroke",)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is None and not self._lasso:
            return
        ip = self.to_image(pos)
        if self._drag and self._drag[0] == "pan":
            self.offset = self._drag[2] + (pos - self._drag[1])
            self.update()
        elif self._drag and self._drag[0] == "stroke" and self._last is not None:
            self._stroke(self._last, ip)
            self._last = ip
        elif self._drag and self._drag[0] in SHAPES + ("select",):
            b = self._constrain(self._drag[1], ip, bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            self._drag = (self._drag[0], self._drag[1], b)
            self.update()
        elif self._lasso:
            self._lasso.append(ip)
            self.update()

    def mouseReleaseEvent(self, e):
        d, self._drag = self._drag, None
        self.unsetCursor()
        if self._lasso:
            if len(self._lasso) > 2:
                path = QPainterPath()
                path.addPolygon(QPolygonF(self._lasso))
                path.closeSubpath()
                self.selection = path
            self._lasso = []
            self.update()
            return
        if d is None:
            return
        if d[0] == "stroke":
            self._last = None
            self.changed.emit()
        elif d[0] == "select":
            r = QRectF(d[1], d[2]).normalized()
            if r.width() >= 2 and r.height() >= 2:
                path = QPainterPath()
                path.addRect(r)
                self.selection = path
                if self.tool == "crop":
                    self.crop_to_selection()
            self.update()
        elif d[0] in SHAPES:
            if (d[2] - d[1]).manhattanLength() < 1:
                return
            self.doc.checkpoint("Forma")
            p = self._layer_painter()
            if p is not None:
                self._draw_shape(p, d[0], d[1], d[2])
                p.end()
            self.update()
            self.changed.emit()

    def wheelEvent(self, e):
        self.auto_fit = False
        self.set_zoom(self.zoom * 1.15 ** (e.angleDelta().y() / 120), e.position())

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selection is not None:
            self.clear_selection_area()
        elif e.key() == Qt.Key.Key_Escape:
            self.selection = None
            self.update()
        else:
            super().keyPressEvent(e)

    # ------------------------------------------------------------------ selección
    def _selection_mask(self):
        import numpy as np
        from PySide6.QtGui import QImage

        s = self.doc.size
        m = QImage(s, QImage.Format.Format_Grayscale8)
        m.fill(0)
        p = QPainter(m)
        p.fillPath(self.selection, QColor(255, 255, 255))
        p.end()
        arr = np.frombuffer(m.constBits(), dtype=np.uint8).reshape(s.height(), m.bytesPerLine())[:, : s.width()]
        return arr > 127

    def clear_selection_area(self) -> None:
        if self.doc is None or self.selection is None:
            return
        self.doc.checkpoint("Borrar selección")
        p = QPainter(self.doc.current.image)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillPath(self.selection, QBrush(QColor(0, 0, 0, 255)))
        p.end()
        self.update()
        self.changed.emit()

    def crop_to_selection(self) -> bool:
        if self.doc is None or self.selection is None:
            return False
        r = self.selection.boundingRect().toAlignedRect()
        self.doc.crop(QRect(QPoint(max(0, r.x()), max(0, r.y())), r.size()))
        self.selection = None
        self.fit()
        self.changed.emit()
        return True
