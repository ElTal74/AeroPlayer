"""Visor del editor de vídeo con manipulación directa (mover, escalar, estirar, girar, recortar y anclaje).

* Cada elemento (vídeo superior, imágenes y títulos) va dentro de un «marco» que recorta y transforma con la
  geometría común (`geometry.py`): lo que se ve aquí es lo que se exporta.
* Con un clip seleccionado aparecen sus controles: arrastrar dentro lo mueve (con guías e imán al centro y a
  los bordes; Mayús limita a un eje), las esquinas escalan manteniendo la proporción (Mayús: libre), los lados
  estiran en X o en Y, Alt + esquina o lado recorta, el tirador superior gira (Mayús: pasos de 15°) y la cruz
  es el punto de anclaje. Las flechas mueven 1 px (Mayús: 10 px).
* Las pistas bloqueadas muestran el marco discontinuo y no se pueden transformar.
* El visor solo cambia el clip y avisa (`transform_*`); el editor guarda el deshacer y refresca el resto.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsPixmapItem, QGraphicsRectItem, \
    QGraphicsScene, QGraphicsView

from aero.editors.video import geometry
from aero.editors.video.project import Clip
from aero.i18n import tr
from aero.ui.glass import label

HANDLE_PX = 9          # lado de los tiradores en píxeles de pantalla
ROT_PX = 30            # distancia del tirador de giro al borde superior
SNAP_PX = 8            # distancia del imán (pantalla)
ACCENT = QColor("#4fb3ff")
GUIDE = QColor("#ff4fd8")

CORNERS = {"tl": (-1, -1), "tr": (1, -1), "br": (1, 1), "bl": (-1, 1)}
EDGES = {"t": (0, -1), "r": (1, 0), "b": (0, 1), "l": (-1, 0)}


class Gizmo(QGraphicsObject):
    """Marco, tiradores, anclaje y guías del clip seleccionado (no se exporta)."""

    def __init__(self, view: "Preview"):
        super().__init__()
        self.view = view
        self.setZValue(1_000_000)
        self.guides: list[tuple[QPointF, QPointF]] = []

    def boundingRect(self) -> QRectF:
        p = self.view.ed.project
        return QRectF(-4000, -4000, p.width + 8000, p.height + 8000)

    def refresh(self):
        self.prepareGeometryChange()
        self.update()

    def paint(self, p: QPainter, _opt, _w=None):
        v = self.view
        pl, locked = v.selected_placement()
        k = v.scale_k()
        if self.guides:
            p.setPen(QPen(GUIDE, 1.2 / k, Qt.PenStyle.DashLine))
            for a, b in self.guides:
                p.drawLine(a, b)
        if pl is None:
            return
        poly = geometry.corners(pl)
        p.setPen(QPen(ACCENT, 1.6 / k, Qt.PenStyle.DashLine if locked else Qt.PenStyle.SolidLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(poly)
        if locked:
            return
        hs = HANDLE_PX / k
        for name, pt in v.handle_points(pl).items():
            if name == "rot":
                top = v.local_to_scene(pl, QPointF(0, -pl.h / 2))
                p.setPen(QPen(ACCENT, 1.2 / k))
                p.drawLine(top, pt)
                p.setBrush(QColor("#ffffff"))
                p.drawEllipse(pt, hs * 0.7, hs * 0.7)
            elif name == "anchor":
                p.setPen(QPen(QColor("#ffffff"), 1.4 / k))
                p.drawLine(pt + QPointF(-hs, 0), pt + QPointF(hs, 0))
                p.drawLine(pt + QPointF(0, -hs), pt + QPointF(0, hs))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(pt, hs * 0.45, hs * 0.45)
            else:
                p.setPen(QPen(ACCENT, 1.2 / k))
                p.setBrush(QColor("#ffffff"))
                p.drawRect(QRectF(pt.x() - hs / 2, pt.y() - hs / 2, hs, hs))


class Preview(QGraphicsView):
    transform_started = Signal()
    transform_changed = Signal()
    transform_finished = Signal()
    clip_clicked = Signal(str)          # id del clip pulsado en el visor ("" = hueco: quitar selección)

    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setStyleSheet("background: #000; border: none;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.video = QGraphicsVideoItem()
        self.video.setAspectRatioMode(Qt.AspectRatioMode.IgnoreAspectRatio)
        self._holder(self.video)
        self.image = QGraphicsPixmapItem()     # compatibilidad: ya no se usa para componer
        self.texts: list[QGraphicsPixmapItem] = []
        self.layers: dict[str, QGraphicsPixmapItem] = {}   # imágenes y títulos (id de clip → elemento)
        self.still = QGraphicsPixmapItem()
        self.still.setZValue(5000)
        self.still.hide()
        self.scene_.addItem(self.still)
        self.gizmo = Gizmo(self)
        self.scene_.addItem(self.gizmo)
        self.busy_lbl = label(tr("Aplicando efectos…"), "caption")
        self.busy_lbl.setParent(self)
        self.busy_lbl.setStyleSheet("color: white; background: rgba(0,0,0,140); padding: 3px 8px; border-radius: 6px;")
        self.busy_lbl.move(10, 10)
        self.busy_lbl.hide()
        self._pix: dict[str, QPixmap] = {}
        self._titles: dict[tuple, QPixmap] = {}
        # id de clip → (elemento, marco, colocación, z, ancho original, alto original)
        self.placed: dict[str, tuple] = {}
        self._video_clip = ""
        self._drag = None
        self.resize_scene()

    # ------------------------------------------------------------------ colocación
    def _holder(self, item) -> QGraphicsRectItem:
        h = item.parentItem()
        if h is None:
            h = QGraphicsRectItem()
            h.setPen(QPen(Qt.PenStyle.NoPen))
            h.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
            self.scene_.addItem(h)
            item.setParentItem(h)
        return h

    def place(self, item, c: Clip, src_w: float, src_h: float, z: float, item_scale=(1.0, 1.0)) -> None:
        """Recorta, escala, gira y coloca el elemento igual que la exportación. `item_scale`: si la imagen del
        elemento está reducida respecto al original (vista previa), factor para llevarla a su tamaño."""
        p = self.ed.project
        h = self._holder(item)
        pl = geometry.place(p.width, p.height, src_w, src_h, c)
        if pl is None:
            h.hide()
            self.placed.pop(c.id, None)
            return
        l, t, _r, _b = geometry.crop_of(c)
        h.setRect(QRectF(0, 0, pl.crop_w, pl.crop_h))
        item.setPos(-l * src_w, -t * src_h)
        item.setTransform(QTransform.fromScale(*item_scale))
        h.setTransform(geometry.element_transform(pl))
        h.setOpacity(max(0.0, min(1.0, c.opacity)))
        h.setZValue(z)
        item.setZValue(z)   # también en el elemento: el orden de capas se puede consultar en él directamente
        h.show()
        self.placed[c.id] = (item, h, pl, z, src_w, src_h, item_scale)
        self.gizmo.refresh()

    def set_video(self, c: Clip | None, src_w: float = 0, src_h: float = 0, z: float = 0) -> None:
        h = self._holder(self.video)
        if c is None:
            h.hide()
            if self._video_clip:
                self.placed.pop(self._video_clip, None)
            self._video_clip = ""
            self.gizmo.refresh()
            return
        if self._video_clip and self._video_clip != c.id:
            self.placed.pop(self._video_clip, None)
        self._video_clip = c.id
        self.video.setSize(QSizeF(src_w, src_h))
        self.place(self.video, c, src_w, src_h, z)

    def show_still(self, img: QImage | None) -> None:
        """Fotograma renderizado con efectos (encima de todo salvo los controles); None lo quita."""
        if img is None:
            self.still.hide()
            return
        p = self.ed.project
        self.still.setPixmap(QPixmap.fromImage(img).scaled(p.width, p.height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                           Qt.TransformationMode.SmoothTransformation))
        self.still.show()

    def busy(self, on: bool) -> None:
        self.busy_lbl.setVisible(on)

    def _drop_missing(self, want: set[str], kinds: set[str]) -> None:
        for cid in list(self.layers):
            it = self.layers[cid]
            if cid not in want and it.data(0) in kinds:
                self.scene_.removeItem(it.parentItem())
                self.layers.pop(cid)
                self.placed.pop(cid, None)

    def show_images(self, clips: list[tuple[Clip, float]]) -> None:
        self._drop_missing({c.id for c, _z in clips}, {"image"})
        p = self.ed.project
        for c, z in clips:
            pm = self._pix.get(c.src)
            if pm is None:
                pm = QPixmap(c.src)
                if pm.width() > p.width * 2 or pm.height() > p.height * 2:  # vista previa: no hace falta más
                    pm = pm.scaled(p.width * 2, p.height * 2, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                self._pix[c.src] = pm
            it = self._layer_item(c.id, "image", pm)
            # La geometría usa el tamaño original (la copia reducida se estira a ese tamaño)
            sw, sh = (c.src_w, c.src_h) if c.src_w and c.src_h else (pm.width(), pm.height())
            self.place(it, c, sw, sh, z, (sw / max(1, pm.width()), sh / max(1, pm.height())))

    def _layer_item(self, cid: str, kind: str, pm: QPixmap) -> QGraphicsPixmapItem:
        it = self.layers.get(cid)
        if it is None:
            it = QGraphicsPixmapItem(pm)
            it.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            it.setData(0, kind)
            self._holder(it)
            self.layers[cid] = it
        elif it.pixmap().cacheKey() != pm.cacheKey():
            it.setPixmap(pm)
        return it

    def show_texts(self, clips: list[Clip]):
        from aero.editors.video.titles import render_title

        self._drop_missing({c.id for c in clips}, {"text"})
        self.texts = []
        for i, c in enumerate(clips):
            if not c.text.strip():
                continue
            key = (c.text, c.text_size, c.text_color)
            pm = self._titles.get(key)
            if pm is None:
                if len(self._titles) > 64:
                    self._titles.clear()
                pm = QPixmap.fromImage(render_title(c))
                self._titles[key] = pm
            it = self._layer_item(c.id, "text", pm)
            self.place(it, c, pm.width(), pm.height(), 1000 + i)
            self.texts.append(it)

    def resize_scene(self):
        p = self.ed.project
        self.scene_.setSceneRect(QRectF(0, 0, p.width, p.height))
        self.fitInView(self.scene_.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.gizmo.refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fitInView(self.scene_.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # ------------------------------------------------------------------ selección y tiradores
    def scale_k(self) -> float:
        return max(1e-3, abs(self.transform().m11()))

    def selected_placement(self):
        c = self.ed.selected_clip()
        if c is None or c.id not in self.placed:
            return None, False
        return self.placed[c.id][2], self.ed.clip_locked(c)

    @staticmethod
    def local_to_scene(pl, pt: QPointF) -> QPointF:
        return geometry.frame_transform(pl).map(pt)

    @staticmethod
    def scene_to_local(pl, pt: QPointF) -> QPointF:
        inv, _ok = geometry.frame_transform(pl).inverted()
        return inv.map(pt)

    def handle_points(self, pl) -> dict[str, QPointF]:
        out = {}
        for name, (sx, sy) in {**CORNERS, **EDGES}.items():
            out[name] = self.local_to_scene(pl, QPointF(sx * pl.w / 2, sy * pl.h / 2))
        out["rot"] = self.local_to_scene(pl, QPointF(0, -pl.h / 2 - ROT_PX / self.scale_k()))
        c = self.ed.selected_clip()
        out["anchor"] = self.local_to_scene(pl, QPointF(c.anchor_x * pl.w / 2, c.anchor_y * pl.h / 2))
        return out

    def _hit_handle(self, pl, sp: QPointF) -> str:
        tol = (HANDLE_PX + 4) / self.scale_k()
        pts = self.handle_points(pl)
        for name in ("anchor", "rot", *CORNERS, *EDGES):
            d = pts[name] - sp
            if math.hypot(d.x(), d.y()) <= tol:
                return name
        return ""

    def _clip_at(self, sp: QPointF) -> str:
        best, best_z = "", -1e18
        for cid, (_it, h, pl, z, *_rest) in self.placed.items():
            if h.isVisible() and geometry.corners(pl).containsPoint(sp, Qt.FillRule.OddEvenFill) and z > best_z:
                best, best_z = cid, z
        return best

    # ------------------------------------------------------------------ ratón
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        self.setFocus()
        sp = self.mapToScene(e.position().toPoint())
        pl, locked = self.selected_placement()
        op = ""
        if pl is not None and not locked:
            op = self._hit_handle(pl, sp)
            if not op and geometry.corners(pl).containsPoint(sp, Qt.FillRule.OddEvenFill):
                op = "move"
        if not op:
            cid = self._clip_at(sp)
            cur = self.ed.selected_clip()
            if cid != (cur.id if cur else ""):
                self.clip_clicked.emit(cid)
            pl, locked = self.selected_placement()
            if not cid or pl is None or locked:
                return
            op = "move"
        if op in EDGES or op in CORNERS:
            if e.modifiers() & Qt.KeyboardModifier.AltModifier:
                op = "crop_" + op
        c = self.ed.selected_clip()
        self._drag = {"op": op, "start": sp, "clip": c, "pl": pl, "vals": _snapshot(c), "began": False}
        self.setCursor(Qt.CursorShape.ClosedHandCursor if op == "move" else Qt.CursorShape.CrossCursor)

    def mouseMoveEvent(self, e):
        sp = self.mapToScene(e.position().toPoint())
        d = self._drag
        if d is None:
            self._hover(sp)
            return
        if not d["began"]:
            if (e.position() - self.mapFromScene(d["start"]).toPointF()).manhattanLength() < 2:
                return
            d["began"] = True
            self.transform_started.emit()
        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._apply(d, sp, shift)
        self._replace(d["clip"])
        self.transform_changed.emit()

    def mouseReleaseEvent(self, e):
        d, self._drag = self._drag, None
        self.gizmo.guides = []
        self.gizmo.refresh()
        self.unsetCursor()
        if d is not None and d["began"]:
            self.transform_finished.emit()

    def _hover(self, sp: QPointF):
        pl, locked = self.selected_placement()
        shape = Qt.CursorShape.ArrowCursor
        if pl is not None and not locked:
            h = self._hit_handle(pl, sp)
            if h == "rot":
                shape = Qt.CursorShape.CrossCursor
            elif h == "anchor":
                shape = Qt.CursorShape.SizeAllCursor
            elif h in CORNERS:
                shape = Qt.CursorShape.SizeFDiagCursor if h in ("tl", "br") else Qt.CursorShape.SizeBDiagCursor
            elif h in EDGES:
                shape = Qt.CursorShape.SizeHorCursor if h in ("l", "r") else Qt.CursorShape.SizeVerCursor
            elif geometry.corners(pl).containsPoint(sp, Qt.FillRule.OddEvenFill):
                shape = Qt.CursorShape.OpenHandCursor
        if self.viewport().cursor().shape() != shape:
            self.viewport().setCursor(shape)

    def event(self, e):
        # Con un elemento seleccionado, las flechas lo mueven aquí (no avanzan el cabezal de la ventana)
        from PySide6.QtCore import QEvent

        if e.type() == QEvent.Type.ShortcutOverride and e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right,
                                                                     Qt.Key.Key_Up, Qt.Key.Key_Down):
            c = self.ed.selected_clip()
            if c is not None and c.id in self.placed and not self.ed.clip_locked(c):
                e.accept()
                return True
        return super().event(e)

    def keyPressEvent(self, e):
        c = self.ed.selected_clip()
        steps = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if c is None or e.key() not in steps or self.ed.clip_locked(c) or c.id not in self.placed:
            return super().keyPressEvent(e)
        dx, dy = steps[e.key()]
        k = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        p = self.ed.project
        self.transform_started.emit()
        c.pos_x += dx * k / (p.width / 2)
        c.pos_y += dy * k / (p.height / 2)
        self._replace(c)
        self.transform_changed.emit()
        self.transform_finished.emit()

    # ------------------------------------------------------------------ operaciones
    def _replace(self, c: Clip):
        entry = self.placed.get(c.id)
        if entry is None:
            return
        it, _h, _pl, z, sw, sh, ks = entry
        self.place(it, c, sw, sh, z, ks)
        self.still.hide()   # el fotograma con efectos ya no coincide: se vuelve a calcular al soltar

    def _apply(self, d: dict, sp: QPointF, shift: bool) -> None:
        c, pl0, v0, op = d["clip"], d["pl"], d["vals"], d["op"]
        p = self.ed.project
        W, H = p.width, p.height
        if op == "move":
            delta = sp - d["start"]
            if shift:
                delta = QPointF(delta.x(), 0) if abs(delta.x()) >= abs(delta.y()) else QPointF(0, delta.y())
            delta = self._snap_move(pl0, delta)
            anchor = pl0.anchor + delta
            base_y = pl0.anchor.y() - v0["pos_y"] * H / 2
            c.pos_x = (anchor.x() - W / 2) / (W / 2)
            c.pos_y = (anchor.y() - base_y) / (H / 2)
            return
        self.gizmo.guides = []
        if op == "rot":
            a0 = math.atan2(d["start"].y() - pl0.anchor.y(), d["start"].x() - pl0.anchor.x())
            a1 = math.atan2(sp.y() - pl0.anchor.y(), sp.x() - pl0.anchor.x())
            ang = v0["angle"] + math.degrees(a1 - a0)
            if shift:
                ang = round(ang / 15) * 15
            c.angle = ((ang + 180) % 360) - 180
            return
        m = self.scene_to_local(pl0, sp)
        if op == "anchor":
            ax = max(-1.5, min(1.5, m.x() / (pl0.w / 2)))
            ay = max(-1.5, min(1.5, m.y() / (pl0.h / 2)))
            c.anchor_x, c.anchor_y = ax, ay
            # El elemento no se mueve: el anclaje pasa a estar bajo el ratón
            new_anchor = self.local_to_scene(pl0, QPointF(ax * pl0.w / 2, ay * pl0.h / 2))
            base_y = pl0.anchor.y() - v0["pos_y"] * H / 2
            c.pos_x = (new_anchor.x() - W / 2) / (W / 2)
            c.pos_y = (new_anchor.y() - base_y) / (H / 2)
            return
        if op.startswith("crop_"):
            self._crop(d, op[5:], m)
            return
        a = QPointF(v0["anchor_x"] * pl0.w / 2, v0["anchor_y"] * pl0.h / 2)
        hx, hy = (CORNERS.get(op) or EDGES[op])
        h0 = QPointF(hx * pl0.w / 2, hy * pl0.h / 2)

        def factor(mv, av, hv):
            return (mv - av) / (hv - av) if abs(hv - av) > 1e-6 else 1.0

        if op in CORNERS and not shift:
            dv = h0 - a
            f = ((m.x() - a.x()) * dv.x() + (m.y() - a.y()) * dv.y()) / max(1e-6, dv.x() ** 2 + dv.y() ** 2)
            c.scale = max(0.02, min(20.0, v0["scale"] * f))
            return
        if op in CORNERS or op in ("l", "r"):
            c.sx = max(0.02, min(20.0, v0["sx"] * factor(m.x(), a.x(), h0.x())))
        if op in CORNERS or op in ("t", "b"):
            c.sy = max(0.02, min(20.0, v0["sy"] * factor(m.y(), a.y(), h0.y())))

    def _crop(self, d: dict, side: str, m: QPointF) -> None:
        """Alt + tirador: recorta ese lado; el lado opuesto se queda donde estaba."""
        c, pl0, v0 = d["clip"], d["pl"], d["vals"]
        if pl0.rot90 not in (0,):
            self.ed.info.setText(tr("Para recortar con el ratón, quita antes el giro de 90°; usa el inspector."))
            return
        l0, t0, r0, b0 = v0["crop"]
        crop = [l0, t0, r0, b0]
        fx, fy = (1 - l0 - r0) / max(1e-6, pl0.w), (1 - t0 - b0) / max(1e-6, pl0.h)
        sx, sy = (CORNERS.get(side) or EDGES[side])
        if sx < 0:
            crop[0] = max(0.0, min(0.9 - r0, l0 + (m.x() + pl0.w / 2) * fx))
        elif sx > 0:
            crop[2] = max(0.0, min(0.9 - l0, r0 + (pl0.w / 2 - m.x()) * fx))
        if sy < 0:
            crop[1] = max(0.0, min(0.9 - b0, t0 + (m.y() + pl0.h / 2) * fy))
        elif sy > 0:
            crop[3] = max(0.0, min(0.9 - t0, b0 + (pl0.h / 2 - m.y()) * fy))
        # Punto fijo: la esquina o el lado opuesto al tirador
        opp = QPointF(-sx * pl0.w / 2, -sy * pl0.h / 2)
        before = self.local_to_scene(pl0, opp)
        c.crop = crop
        c.pos_x, c.pos_y = v0["pos_x"], v0["pos_y"]
        entry = self.placed[c.id]
        p = self.ed.project
        pl1 = geometry.place(p.width, p.height, entry[4], entry[5], c)
        if pl1 is None:
            return
        after = self.local_to_scene(pl1, QPointF(-sx * pl1.w / 2, -sy * pl1.h / 2))
        c.pos_x += (before.x() - after.x()) / (p.width / 2)
        c.pos_y += (before.y() - after.y()) / (p.height / 2)

    def _snap_move(self, pl0, delta: QPointF) -> QPointF:
        """Imán al centro y a los bordes del lienzo, con guías visibles."""
        p = self.ed.project
        W, H = p.width, p.height
        thr = SNAP_PX / self.scale_k()
        poly = geometry.corners(pl0)
        xs = [poly[i].x() for i in range(4)]
        ys = [poly[i].y() for i in range(4)]
        cx, cy = pl0.center.x(), pl0.center.y()
        guides = []
        best_x = None
        for cur, target in ((cx, W / 2), (min(xs), 0.0), (max(xs), float(W))):
            diff = target - (cur + delta.x())
            if abs(diff) < thr and (best_x is None or abs(diff) < abs(best_x[0])):
                best_x = (diff, target)
        if best_x is not None:
            delta = QPointF(delta.x() + best_x[0], delta.y())
            guides.append((QPointF(best_x[1], 0), QPointF(best_x[1], H)))
        best_y = None
        for cur, target in ((cy, H / 2), (min(ys), 0.0), (max(ys), float(H))):
            diff = target - (cur + delta.y())
            if abs(diff) < thr and (best_y is None or abs(diff) < abs(best_y[0])):
                best_y = (diff, target)
        if best_y is not None:
            delta = QPointF(delta.x(), delta.y() + best_y[0])
            guides.append((QPointF(0, best_y[1]), QPointF(W, best_y[1])))
        self.gizmo.guides = guides
        return delta


def _snapshot(c: Clip) -> dict:
    return {"pos_x": c.pos_x, "pos_y": c.pos_y, "scale": c.scale, "sx": c.sx, "sy": c.sy, "angle": c.angle,
            "anchor_x": c.anchor_x, "anchor_y": c.anchor_y, "crop": list(geometry.crop_of(c))}

