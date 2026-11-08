"""Lienzo del editor: muestra el documento y traduce el ratón en herramientas.

Rendimiento: la vista previa de los ajustes de color se calcula sobre una copia reducida del fondo (como
mucho `PROXY` píxeles de lado, en segundo plano y agrupando cambios seguidos), y la composición final se
guarda en caché a la escala de pantalla. Durante un trazo solo se pinta el trazo en curso encima.
Con zoom por encima de la vista previa y sin ajustes, se dibuja directamente a resolución completa.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QInputDialog, QWidget

from aero.editors.image import adjust
from aero.editors.image.document import ImageDocument

PROXY = 2048
ASPECTS = {"Libre": None, "Original": "orig", "1:1": 1.0, "4:3": 4 / 3, "3:2": 3 / 2, "16:9": 16 / 9,
           "9:16": 9 / 16, "4:5": 4 / 5}
SHAPES = ("brush", "highlight", "line", "arrow", "rect", "ellipse")


def _proxy_job(img, a: dict, side: int):
    """Hilo de trabajo (sin objetos Qt vivos de la interfaz): reduce y ajusta el fondo."""
    from PySide6.QtCore import Qt as _Qt

    w, h = img.width(), img.height()
    k = min(1.0, side / max(w, h))
    small = img if k >= 1.0 else img.scaled(max(1, int(w * k)), max(1, int(h * k)),
                                            _Qt.AspectRatioMode.IgnoreAspectRatio,
                                            _Qt.TransformationMode.SmoothTransformation)
    return adjust.apply(small, a, scale=k), k


class ImageCanvas(QWidget):
    zoom_changed = Signal(float)
    changed = Signal()            # el documento cambió (historial, título…)
    selection_changed = Signal()
    crop_changed = Signal()
    layer_moved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(320, 240)
        self.doc: ImageDocument | None = None
        self.zoom = 1.0
        self.offset = QPointF(0, 0)
        self.tool = "hand"
        self.color = QColor("#ff3b30")
        self.width_px = 6
        self.opacity = 1.0
        self.fill = False
        self.font_size = 48
        self.bold = True
        self.aspect = None
        self.selection: QRectF | None = None
        self.crop_rect: QRectF | None = None
        self._drag = None          # (tipo, punto de inicio en imagen, datos)
        self._stroke: list[QPointF] = []
        self._pan_from = None
        self._space = False
        self._adj_base = None      # fondo ajustado (reducido) y su escala
        self._adj_scale = 1.0
        self._adj_key = None
        self._adj_pending = False
        self._adj_timer = QTimer(self)
        self._adj_timer.setSingleShot(True)
        self._adj_timer.setInterval(40)
        self._adj_timer.timeout.connect(self._compute_adjust)
        self._comp: QPixmap | None = None
        self._comp_key = None
        self._fit_on_show = True

    # ------------------------------------------------------------------ documento y vista
    def set_document(self, doc: ImageDocument):
        self.doc = doc
        self.selection = self.crop_rect = None
        self._adj_key = self._comp_key = None
        self._adj_base = None
        self.refresh()
        self.fit()

    def refresh(self):
        """Algo cambió en el documento: vista previa de ajustes (si hace falta) y repintado."""
        if self.doc is None:
            return
        key = (id(self.doc.background.image), self.doc.background.image.cacheKey(),
               tuple(sorted(self.doc.adjust.items())))
        if key != self._adj_key:
            self._adj_key = key
            if adjust.is_neutral(self.doc.adjust):
                self._adj_base, self._adj_scale = None, 1.0
            else:
                self._adj_timer.start()
        self._comp_key = None
        self.update()
        self.changed.emit()

    def _compute_adjust(self):
        from aero.core.tasks import tasks

        if self._adj_pending:
            self._adj_timer.start()  # se recalcula al terminar el anterior con los valores nuevos
            return
        self._adj_pending = True
        img, a, key = self.doc.background.image, dict(self.doc.adjust), self._adj_key

        def done(res):
            self._adj_pending = False
            if key == self._adj_key:
                self._adj_base, self._adj_scale = res
                self._comp_key = None
                self.update()

        def fail(_e):
            self._adj_pending = False

        tasks().submit(lambda: _proxy_job(img, a, PROXY), "interactive", done, fail, self)

    def image_rect(self) -> QRectF:
        s = self.doc.size
        return QRectF(self.offset.x(), self.offset.y(), s.width() * self.zoom, s.height() * self.zoom)

    def to_image(self, p: QPointF) -> QPointF:
        return QPointF((p.x() - self.offset.x()) / self.zoom, (p.y() - self.offset.y()) / self.zoom)

    def to_view(self, p: QPointF) -> QPointF:
        return QPointF(p.x() * self.zoom + self.offset.x(), p.y() * self.zoom + self.offset.y())

    def fit(self):
        if self.doc is None or self.width() < 10:
            return
        s = self.doc.size
        z = min((self.width() - 48) / s.width(), (self.height() - 48) / s.height())
        self.set_zoom(max(0.02, z), center=True)

    def set_zoom(self, z: float, anchor: QPointF | None = None, center: bool = False):
        if self.doc is None:
            return
        z = max(0.02, min(32.0, z))
        if center:
            s = self.doc.size
            self.offset = QPointF((self.width() - s.width() * z) / 2, (self.height() - s.height() * z) / 2)
        else:
            a = anchor if anchor is not None else QPointF(self.width() / 2, self.height() / 2)
            ip = self.to_image(a)
            self.offset = QPointF(a.x() - ip.x() * z, a.y() - ip.y() * z)
        self.zoom = z
        self._comp_key = None
        self.update()
        self.zoom_changed.emit(z)

    def showEvent(self, e):
        super().showEvent(e)
        if self._fit_on_show:
            self._fit_on_show = False
            QTimer.singleShot(0, self.fit)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._comp_key = None

    # ------------------------------------------------------------------ pintado
    def _composite(self) -> tuple[QPixmap, float]:
        dpr = self.devicePixelRatioF()
        scale = min(1.0, self.zoom * dpr)
        if self._adj_base is not None:
            scale = min(scale, self._adj_scale)
        key = (self.doc.version, self._adj_key, round(scale, 4), id(self._adj_base))
        if key != self._comp_key or self._comp is None:
            base = self._adj_base if self._adj_base is not None else None
            if base is None and not adjust.is_neutral(self.doc.adjust):
                base = self.doc.background.image  # mientras llega la vista previa ajustada
            img = self.doc.render(scale, base=base if base is not None else self.doc.background.image)
            self._comp = QPixmap.fromImage(img)
            self._comp_key = key
        return self._comp, scale

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(18, 22, 30))
        if self.doc is None:
            return
        r = self.image_rect()
        # Damero para la transparencia
        p.save()
        p.setClipRect(r)
        c1, c2 = QColor(52, 58, 68), QColor(40, 45, 54)
        p.fillRect(r, c1)
        step = 10
        x0, y0 = int(r.left()), int(r.top())
        for yy in range(max(0, int(r.top())), min(self.height(), int(r.bottom()) + 1), step):
            for xx in range(max(0, x0 + ((yy - y0) // step % 2) * step), min(self.width(), int(r.right()) + 1),
                            step * 2):
                p.fillRect(xx, yy, step, step, c2)
        p.restore()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 2.0)
        dpr = self.devicePixelRatioF()
        if self.zoom * dpr > 1.05 and adjust.is_neutral(self.doc.adjust):
            # Ampliado: resolución completa, solo la zona visible
            p.save()
            p.setClipRect(QRectF(self.rect()).intersected(r))
            p.translate(self.offset)
            p.scale(self.zoom, self.zoom)
            if self.doc.background.visible:
                p.drawImage(QPointF(0, 0), self.doc.background.image)
            for ly in self.doc.layers[1:]:
                if ly.visible:
                    p.save()
                    p.setOpacity(ly.opacity)
                    p.setTransform(ly.transform(), True)
                    p.drawImage(QPointF(0, 0), ly.image)
                    p.restore()
            p.restore()
        else:
            pm, _scale = self._composite()
            p.drawPixmap(r, pm, QRectF(pm.rect()))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Borde fino del lienzo
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawRect(r.adjusted(-0.5, -0.5, 0.5, 0.5))
        self._paint_overlay(p)

    def _view_rect(self, rr: QRectF) -> QRectF:
        a, b = self.to_view(rr.topLeft()), self.to_view(rr.bottomRight())
        return QRectF(a, b)

    def _paint_overlay(self, p: QPainter):
        doc = self.doc
        # Capa activa (no fondo): marco de selección
        if self.tool == "move" and not doc.current.background:
            b = self._view_rect(doc.current.bounds())
            p.setPen(QPen(QColor(120, 200, 255, 220), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(b)
        if self.selection is not None:
            v = self._view_rect(self.selection)
            p.setPen(QPen(QColor(255, 255, 255, 230), 1, Qt.PenStyle.DashLine))
            p.setBrush(QColor(120, 200, 255, 40))
            p.drawRect(v)
        if self.crop_rect is not None:
            v = self._view_rect(self.crop_rect)
            shade = QPainterPath()
            shade.addRect(QRectF(self.rect()))
            hole = QPainterPath()
            hole.addRect(v)
            p.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 140))
            p.setPen(QPen(QColor(255, 255, 255, 230), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(v)
            p.setPen(QPen(QColor(255, 255, 255, 80), 1))
            for i in (1, 2):
                x = v.left() + v.width() * i / 3
                y = v.top() + v.height() * i / 3
                p.drawLine(QPointF(x, v.top()), QPointF(x, v.bottom()))
                p.drawLine(QPointF(v.left(), y), QPointF(v.right(), y))
            p.setBrush(QColor("white"))
            for c in (v.topLeft(), v.topRight(), v.bottomLeft(), v.bottomRight()):
                p.drawEllipse(c, 4.5, 4.5)
        # Trazo en curso
        if self._drag and self._drag[0] == "shape":
            p.save()
            p.translate(self.offset)
            p.scale(self.zoom, self.zoom)
            self._draw_shape(p, self._drag[1], self._drag[2], self._stroke)
            p.restore()

    # ------------------------------------------------------------------ formas
    def _pen(self) -> QPen:
        c = QColor(self.color)
        if self.tool == "highlight":
            c.setAlphaF(0.38 * self.opacity)
            pen = QPen(c, self.width_px * 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin)
        else:
            c.setAlphaF(self.opacity)
            pen = QPen(c, self.width_px, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        return pen

    def _draw_shape(self, p: QPainter, a: QPointF, b: QPointF, pts: list[QPointF]):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = self._pen()
        p.setPen(pen)
        fill = QColor(pen.color())
        p.setBrush(fill if (self.fill and self.tool in ("rect", "ellipse")) else Qt.BrushStyle.NoBrush)
        t = self.tool
        if t in ("brush", "highlight"):
            if len(pts) > 1:
                path = QPainterPath(pts[0])
                for q in pts[1:]:
                    path.lineTo(q)
                p.drawPath(path)
            elif pts:
                p.drawPoint(pts[0])
        elif t in ("line", "arrow"):
            p.drawLine(a, b)
            if t == "arrow" and (b - a).manhattanLength() > 2:
                ang = math.atan2(b.y() - a.y(), b.x() - a.x())
                L = max(12.0, self.width_px * 4.0)
                head = QPolygonF([b, QPointF(b.x() - L * math.cos(ang - 0.45), b.y() - L * math.sin(ang - 0.45)),
                                  QPointF(b.x() - L * math.cos(ang + 0.45), b.y() - L * math.sin(ang + 0.45))])
                p.setBrush(QBrush(pen.color()))
                p.drawPolygon(head)
        elif t == "rect":
            p.drawRect(QRectF(a, b).normalized())
        elif t == "ellipse":
            p.drawEllipse(QRectF(a, b).normalized())

    def _constrain(self, a: QPointF, b: QPointF, shift: bool) -> QPointF:
        if not shift:
            return b
        d = b - a
        if self.tool in ("rect", "ellipse"):
            s = max(abs(d.x()), abs(d.y()))
            return QPointF(a.x() + math.copysign(s, d.x() or 1), a.y() + math.copysign(s, d.y() or 1))
        ang = round(math.atan2(d.y(), d.x()) / (math.pi / 4)) * (math.pi / 4)
        L = math.hypot(d.x(), d.y())
        return QPointF(a.x() + L * math.cos(ang), a.y() + L * math.sin(ang))

    def _commit_shape(self, a: QPointF, b: QPointF):
        doc = self.doc
        label = {"brush": "Pincel", "highlight": "Resaltar", "line": "Línea", "arrow": "Flecha", "rect": "Rectángulo",
                 "ellipse": "Elipse"}[self.tool]
        doc.checkpoint(label)
        ly = doc.drawing_layer()
        img = ly.image.copy()
        p = QPainter(img)
        self._draw_shape(p, a, b, self._stroke)
        p.end()
        ly.image = img
        doc.changed()
        self.refresh()

    def place_text(self, at: QPointF, text: str):
        if not text.strip():
            return
        doc = self.doc
        doc.checkpoint("Texto")
        ly = doc.drawing_layer()
        img = ly.image.copy()
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        f = QFont("Segoe UI")
        f.setPixelSize(max(6, int(self.font_size)))
        f.setBold(self.bold)
        p.setFont(f)
        c = QColor(self.color)
        c.setAlphaF(self.opacity)
        # Contorno suave para que el texto se lea sobre cualquier foto
        path = QPainterPath()
        fm = p.fontMetrics()
        for i, line in enumerate(text.splitlines()):
            path.addText(at.x(), at.y() + fm.ascent() + i * fm.lineSpacing(), f, line)
        p.setPen(QPen(QColor(0, 0, 0, int(110 * self.opacity)), max(1.0, self.font_size / 18)))
        p.setBrush(c)
        p.drawPath(path)
        p.end()
        ly.image = img
        doc.changed()
        self.refresh()

    # ------------------------------------------------------------------ recorte
    def start_crop(self, aspect):
        self.aspect = aspect
        s = self.doc.size
        r = QRectF(0, 0, s.width(), s.height())
        self.crop_rect = self._fit_aspect(r.adjusted(s.width() * 0.05, s.height() * 0.05,
                                                     -s.width() * 0.05, -s.height() * 0.05))
        self.update()
        self.crop_changed.emit()

    def _aspect_value(self):
        if self.aspect == "orig":
            return self.doc.size.width() / self.doc.size.height()
        return self.aspect

    def _fit_aspect(self, r: QRectF) -> QRectF:
        a = self._aspect_value()
        if not a:
            return r
        w, h = r.width(), r.height()
        if w / max(h, 1e-6) > a:
            w = h * a
        else:
            h = w / a
        c = r.center()
        return QRectF(c.x() - w / 2, c.y() - h / 2, w, h)

    def apply_crop(self):
        if self.crop_rect is None:
            return
        self.doc.crop(self.crop_rect.toAlignedRect())
        self.crop_rect = None
        self.refresh()
        self.fit()

    # ------------------------------------------------------------------ ratón
    def _hit_crop_corner(self, pos: QPointF):
        if self.crop_rect is None:
            return None
        v = self._view_rect(self.crop_rect)
        for name, c in (("tl", v.topLeft()), ("tr", v.topRight()), ("bl", v.bottomLeft()), ("br", v.bottomRight())):
            if (pos - c).manhattanLength() < 14:
                return name
        return "inside" if v.contains(pos) else None

    def mousePressEvent(self, e):
        if self.doc is None:
            return
        pos = e.position()
        ip = self.to_image(pos)
        if e.button() == Qt.MouseButton.MiddleButton or (e.button() == Qt.MouseButton.LeftButton and
                                                          (self.tool == "hand" or self._space)):
            self._pan_from = (pos, QPointF(self.offset))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        t = self.tool
        if t == "crop" and self.crop_rect is not None:
            hit = self._hit_crop_corner(pos)
            if hit:
                self._drag = ("crop", ip, (hit, QRectF(self.crop_rect)))
                return
            self._drag = ("crop", ip, ("new", None))
        elif t == "select":
            self._drag = ("select", ip, None)
            self.selection = QRectF(ip, ip)
        elif t == "move" and not self.doc.current.background:
            self.doc.checkpoint("Mover capa")
            ly = self.doc.current
            self._drag = ("move", ip, (ly.x, ly.y))
        elif t in SHAPES:
            self._stroke = [ip]
            self._drag = ("shape", ip, ip)
        elif t == "text":
            text, ok = QInputDialog.getMultiLineText(self, "Insertar texto", "Texto:")
            if ok:
                self.place_text(ip, text)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._pan_from is not None:
            start, off = self._pan_from
            self.offset = off + (pos - start)
            self._comp_key = self._comp_key  # la composición no cambia al desplazar
            self.update()
            return
        if self._drag is None:
            if self.tool == "crop":
                hit = self._hit_crop_corner(pos)
                self.setCursor(Qt.CursorShape.SizeFDiagCursor if hit in ("tl", "br") else
                               Qt.CursorShape.SizeBDiagCursor if hit in ("tr", "bl") else
                               Qt.CursorShape.SizeAllCursor if hit == "inside" else Qt.CursorShape.CrossCursor)
            else:
                self.setCursor({"hand": Qt.CursorShape.OpenHandCursor, "move": Qt.CursorShape.SizeAllCursor,
                                "text": Qt.CursorShape.IBeamCursor}.get(self.tool, Qt.CursorShape.CrossCursor))
            return
        kind, start, data = self._drag
        ip = self.to_image(pos)
        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if kind == "select":
            self.selection = QRectF(start, ip).normalized()
            self.selection_changed.emit()
        elif kind == "move":
            ly = self.doc.current
            ly.x, ly.y = data[0] + ip.x() - start.x(), data[1] + ip.y() - start.y()
            self.doc.version += 1
            self.layer_moved.emit()
        elif kind == "crop":
            mode, orig = data
            s = self.doc.size
            bound = QRectF(0, 0, s.width(), s.height())
            if mode == "new":
                r = QRectF(start, ip).normalized()
            elif mode == "inside":
                d = ip - start
                r = orig.translated(d)
                r.moveLeft(max(0, min(r.left(), s.width() - r.width())))
                r.moveTop(max(0, min(r.top(), s.height() - r.height())))
            else:
                r = QRectF(orig)
                if "l" in mode:
                    r.setLeft(ip.x())
                if "r" in mode:
                    r.setRight(ip.x())
                if "t" in mode:
                    r.setTop(ip.y())
                if "b" in mode:
                    r.setBottom(ip.y())
                r = r.normalized()
            r = r.intersected(bound)
            a = self._aspect_value()
            if a and mode != "inside" and r.height() > 0:
                anchor = {"tl": r.bottomRight(), "tr": r.bottomLeft(), "bl": r.topRight(),
                          "br": r.topLeft(), "new": start}.get(mode, r.topLeft())
                w = min(r.width(), r.height() * a)
                h = w / a
                sx = -1 if ip.x() < anchor.x() else 1
                sy = -1 if ip.y() < anchor.y() else 1
                r = QRectF(anchor, QPointF(anchor.x() + sx * w, anchor.y() + sy * h)).normalized().intersected(bound)
            self.crop_rect = r
            self.crop_changed.emit()
        elif kind == "shape":
            if self.tool in ("brush", "highlight"):
                self._stroke.append(ip)
            else:
                self._drag = ("shape", start, self._constrain(start, ip, shift))
        self.update()

    def mouseReleaseEvent(self, e):
        if self._pan_from is not None:
            self._pan_from = None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.tool == "hand" else Qt.CursorShape.CrossCursor)
            return
        if self._drag is None:
            return
        kind, start, data = self._drag
        self._drag = None
        if kind == "shape":
            self._commit_shape(start, data)
            self._stroke = []
        elif kind == "move":
            self.doc.changed()
            self.refresh()
        elif kind == "select" and self.selection is not None and self.selection.width() < 2:
            self.selection = None
            self.selection_changed.emit()
        self.update()

    def wheelEvent(self, e):
        if self.doc is None:
            return
        steps = e.angleDelta().y() / 120
        self.set_zoom(self.zoom * (1.15 ** steps), anchor=e.position())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self._space = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.crop_rect is not None:
            self.apply_crop()
        elif e.key() == Qt.Key.Key_Escape:
            self.selection = self.crop_rect = None
            self.selection_changed.emit()
            self.update()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self._space = False
        super().keyReleaseEvent(e)

    def selection_rect(self) -> QRect | None:
        return None if self.selection is None else self.selection.toAlignedRect()

    def sizeHint(self):
        return QSize(900, 640)
