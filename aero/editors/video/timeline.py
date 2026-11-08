"""Línea de tiempo del editor de vídeo (widget dibujado a mano, solo repinta lo necesario)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from aero.editors.video.project import Project, Track
from aero.i18n import tr

RULER = 26
TRACK_H = 56
HEAD_W = 92
EDGE = 7
SNAP_PX = 8
COLORS = {"video": "#3b7dd8", "audio": "#2f9e6e", "image": "#8a63d2", "text": "#d9962b"}


def fmt_time(t: float, frames: bool = False, fps: float = 30) -> str:
    t = max(0.0, t)
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    base = f"{h}:{m:02d}:{int(s):02d}" if h else f"{m}:{int(s):02d}"
    return base + (f",{int((s % 1) * fps):02d}" if frames else "")


class Timeline(QWidget):
    changed = Signal()                 # el proyecto cambió (para deshacer y títulos)
    playhead_moved = Signal(float)
    selection_changed = Signal()
    drop_media = Signal(str, object, float)   # ruta, pista, segundo
    request = Signal(str, object)             # acción del menú contextual (split, delete, layer_up…), objetivo

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.pps = 60.0            # píxeles por segundo
        self.offset = 0.0          # segundos a la izquierda
        self.playhead = 0.0
        self.selected: set[str] = set()
        self.thumbs: dict[str, object] = {}     # ruta → QImage
        self.waves: dict[str, list[float]] = {}  # ruta → picos
        self._drag = None
        self.selected_transition: str | None = None   # id del clip cuya transición de entrada está elegida
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(RULER + TRACK_H * 4 + 4)

    # ------------------------------------------------------------------ geometría
    def x_of(self, t: float) -> float:
        return HEAD_W + (t - self.offset) * self.pps

    def t_of(self, x: float) -> float:
        return max(0.0, self.offset + (x - HEAD_W) / self.pps)

    def track_at(self, y: float) -> Track | None:
        i = int((y - RULER) // TRACK_H)
        return self.project.tracks[i] if 0 <= i < len(self.project.tracks) and y >= RULER else None

    def clip_rect(self, ti: int, c) -> QRectF:
        return QRectF(self.x_of(c.start), RULER + ti * TRACK_H + 4, max(4.0, c.duration * self.pps), TRACK_H - 8)

    def transition_rect(self, c, r: QRectF | None = None) -> QRectF:
        """Zona de la transición de entrada del clip (dentro de su borde izquierdo)."""
        if r is None:
            ti = next(i for i, t in enumerate(self.project.tracks) if c in t.clips)
            r = self.clip_rect(ti, c)
        w = max(10.0, min(r.width() / 2, c.transition_d * self.pps))
        return QRectF(r.left(), r.bottom() - 16, w, 14)

    def hit_transition(self, pos: QPointF):
        """(clip, borde) si el punto cae en una transición: «edge» = extremo derecho (duración), «body»."""
        for ti, t in enumerate(self.project.tracks):
            for c in t.clips:
                if c.transition == "none":
                    continue
                tr_r = self.transition_rect(c, self.clip_rect(ti, c))
                if tr_r.adjusted(0, -2, 3, 2).contains(pos):
                    return c, ("edge" if tr_r.right() - pos.x() < 5 else "body")
        return None, None

    def hit(self, pos: QPointF):
        for ti, t in enumerate(self.project.tracks):
            for c in reversed(t.clips):
                r = self.clip_rect(ti, c)
                if r.contains(pos):
                    # En clips cortos (o con poco zoom) el borde no puede ocupar todo el clip
                    e = min(EDGE, r.width() / 4)
                    edge = "in" if pos.x() - r.left() < e else "out" if r.right() - pos.x() < e else "body"
                    return t, c, edge
        return None, None, None

    def set_zoom(self, pps: float, anchor_x: float | None = None):
        anchor_x = anchor_x if anchor_x is not None else self.x_of(self.playhead)
        t = self.t_of(anchor_x)
        self.pps = max(4.0, min(800.0, pps))
        self.offset = max(0.0, t - (anchor_x - HEAD_W) / self.pps)
        self.update()

    def ensure_visible(self, t: float):
        w = (self.width() - HEAD_W) / self.pps
        if t < self.offset or t > self.offset + w * 0.95:
            self.offset = max(0.0, t - w * 0.3)

    def sizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(900, RULER + TRACK_H * len(self.project.tracks) + 6)

    # ------------------------------------------------------------------ dibujo
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W = self.width()
        p.fillRect(self.rect(), QColor(20, 24, 32))
        # Regla
        p.fillRect(QRectF(0, 0, W, RULER), QColor(28, 33, 44))
        step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if s * self.pps >= 70)
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        t = (self.offset // step) * step
        while self.x_of(t) < W:
            x = self.x_of(t)
            if x >= HEAD_W:
                p.setPen(QColor(110, 120, 138))
                p.drawLine(QPointF(x, RULER - 8), QPointF(x, RULER))
                p.setPen(QColor(170, 178, 194))
                p.drawText(QPointF(x + 3, 13), fmt_time(t))
            t += step
        # Pistas
        for ti, trk in enumerate(self.project.tracks):
            y = RULER + ti * TRACK_H
            p.fillRect(QRectF(HEAD_W, y, W - HEAD_W, TRACK_H), QColor(24, 28, 38) if ti % 2 else QColor(22, 26, 35))
            p.fillRect(QRectF(0, y, HEAD_W, TRACK_H), QColor(30, 35, 47))
            p.setPen(QColor(205, 212, 226))
            f.setPointSizeF(9)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(10, y, HEAD_W - 20, TRACK_H / 2 + 6), Qt.AlignmentFlag.AlignVCenter, trk.name)
            f.setBold(False)
            f.setPointSizeF(8)
            p.setFont(f)
            state = (tr("silenciada") if trk.muted else "") if trk.kind == "audio" else \
                (tr("oculta") if trk.hidden else "")
            self._paint_lock(p, self.lock_rect(ti), trk.locked)
            p.setPen(QColor(140, 150, 168))
            p.drawText(QRectF(10, y + TRACK_H / 2 - 2, HEAD_W - 12, TRACK_H / 2),
                       Qt.AlignmentFlag.AlignTop, state or tr("Vídeo" if trk.kind == "video" else "Audio"))
            p.setPen(QColor(40, 46, 60))
            p.drawLine(QPointF(0, y + TRACK_H), QPointF(W, y + TRACK_H))
            p.save()
            p.setClipRect(QRectF(HEAD_W, y, W - HEAD_W, TRACK_H))
            for c in trk.clips:
                r = self.clip_rect(ti, c)
                if r.right() < HEAD_W or r.left() > W:
                    continue
                self._paint_clip(p, c, r, trk)
            p.restore()
        # Cabezal
        x = self.x_of(self.playhead)
        if x >= HEAD_W:
            p.setPen(QPen(QColor("#ff5a52"), 1.5))
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            path = QPainterPath()
            path.moveTo(x - 6, 0)
            path.lineTo(x + 6, 0)
            path.lineTo(x, 9)
            path.closeSubpath()
            p.fillPath(path, QColor("#ff5a52"))

    def lock_rect(self, ti: int) -> QRectF:
        """Candado de la cabecera de la pista (bloquear o desbloquear)."""
        return QRectF(HEAD_W - 24, RULER + ti * TRACK_H + 6, 18, 18)

    @staticmethod
    def _paint_lock(p: QPainter, r: QRectF, locked: bool) -> None:
        col = QColor("#ffd34d") if locked else QColor(140, 150, 168, 150)
        p.save()
        p.setPen(QPen(col, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        body = QRectF(r.left() + 3, r.top() + 8, r.width() - 6, r.height() - 9)
        shackle = QRectF(r.left() + 5.5, r.top() + 2, r.width() - 11, 10)
        p.drawArc(shackle, 0, 180 * 16 if locked else 150 * 16)
        p.setBrush(col if locked else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(body, 2, 2)
        p.restore()

    def _paint_clip(self, p: QPainter, c, r: QRectF, trk: Track):
        base = QColor(COLORS.get(c.kind, "#666"))
        missing = c.missing()
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, base.lighter(118))
        g.setColorAt(1, base.darker(125))
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.fillPath(path, QColor("#7a2a2a") if missing else g)
        p.save()
        p.setClipPath(path)
        img = self.thumbs.get(c.src) if c.kind in ("video", "image") else None
        if img is not None and not missing:
            h = r.height() - 18
            w = img.width() * h / max(1, img.height())
            x = r.left()
            while x < r.right():
                p.setOpacity(0.85)
                p.drawImage(QRectF(x, r.top() + 16, w, h), img)
                x += w + 2
                if w < 8:
                    break
            p.setOpacity(1.0)
        wave = self.waves.get(c.src) if (c.kind == "audio" or (c.kind == "video" and c.has_audio)) else None
        if wave and not missing:
            from aero.editors.video.media import WAVE_RATE

            mid = r.bottom() - (r.height() * 0.25 if c.kind == "video" else r.height() * 0.42)
            amp = r.height() * (0.2 if c.kind == "video" else 0.38)
            p.setPen(QPen(QColor(255, 255, 255, 150), 1))
            k = c.speed if c.kind in ("video", "audio") else 1
            for px in range(int(max(r.left(), HEAD_W)), int(min(r.right(), self.width())), 2):
                t_src = c.in_s + ((px - r.left()) / self.pps) * k
                i = int(t_src * WAVE_RATE)
                if 0 <= i < len(wave):
                    a = wave[i] * amp
                    p.drawLine(QPointF(px, mid - a), QPointF(px, mid + a))
        p.restore()
        sel = c.id in self.selected
        p.setPen(QPen(QColor("#ffffff") if sel else QColor(255, 255, 255, 70), 2 if sel else 1))
        p.drawPath(path)
        p.setPen(QColor("white"))
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        from pathlib import Path

        name = c.text.splitlines()[0] if c.kind == "text" and c.text else Path(c.src).name
        label = ("⚠ falta: " if missing else "") + name + (f"  ×{c.speed:g}" if c.speed != 1 else "")
        p.drawText(r.adjusted(6, 1, -4, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(r.width() - 10)))
        if c.transition != "none" and c.kind in ("video", "image", "text"):
            tr_r = self.transition_rect(c, r)
            g2 = QLinearGradient(tr_r.topLeft(), tr_r.topRight())
            g2.setColorAt(0, QColor(255, 255, 255, 200))
            g2.setColorAt(1, QColor(255, 255, 255, 60))
            tp = QPainterPath()
            tp.addRoundedRect(tr_r, 4, 4)
            p.fillPath(tp, g2)
            sel_t = self.selected_transition == c.id
            p.setPen(QPen(QColor("#ffd34d") if sel_t else QColor(30, 30, 30, 160), 2 if sel_t else 1))
            p.drawPath(tp)
            p.setPen(QPen(QColor(30, 30, 30, 200), 1))
            p.drawLine(tr_r.topLeft(), tr_r.bottomRight())
            p.drawLine(tr_r.bottomLeft(), tr_r.topRight())
        if c.fade_in > 0:
            d = c.fade_in * self.pps
            p.setPen(QPen(QColor(255, 255, 255, 160), 1))
            p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.left() + d, r.top() + 14))
        if c.fade_out > 0:
            d = c.fade_out * self.pps
            p.drawLine(QPointF(r.right() - d, r.top() + 14), QPointF(r.right(), r.bottom()))

    # ------------------------------------------------------------------ imán
    def _snap(self, t: float, exclude: set[str]) -> float:
        cands = [self.playhead, 0.0]
        for _tr, c in self.project.all_clips():
            if c.id not in exclude:
                cands += [c.start, c.end]
        best = min(cands, key=lambda x: abs(x - t))
        return best if abs(best - t) * self.pps < SNAP_PX else t

    # ------------------------------------------------------------------ ratón
    def mousePressEvent(self, e):
        pos = e.position()
        self.setFocus()
        if pos.y() < RULER and pos.x() >= HEAD_W:
            self._drag = ("playhead",)
            self.set_playhead(self.t_of(pos.x()))
            return
        if pos.x() < HEAD_W:
            trk = self.track_at(pos.y())
            if trk is not None and e.button() == Qt.MouseButton.LeftButton:
                ti = self.project.tracks.index(trk)
                if self.lock_rect(ti).adjusted(-3, -3, 3, 3).contains(pos):
                    trk.locked = not trk.locked   # bloquear: sin mover, recortar ni transformar sus clips
                elif trk.kind == "audio":
                    trk.muted = not trk.muted
                else:
                    trk.hidden = not trk.hidden
                self.changed.emit()
                self.update()
            return
        tc, tedge = self.hit_transition(pos)
        if tc is not None and e.button() == Qt.MouseButton.LeftButton:
            self.selected = {tc.id}
            self.selected_transition = tc.id
            self.selection_changed.emit()
            if tedge == "edge":
                self.changed.emit()  # punto de deshacer antes de cambiar la duración
                self._drag = ("tr_edge", tc.id)
            self.update()
            return
        self.selected_transition = None
        trk, c, edge = self.hit(pos)
        mods = e.modifiers()
        if c is None:
            if not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                self.selected.clear()
            self.set_playhead(self.t_of(pos.x()))
            self._drag = ("playhead",)
            self.selection_changed.emit()
            self.update()
            return
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            self.selected ^= {c.id}
        elif c.id not in self.selected:
            self.selected = {c.id}
        self.selection_changed.emit()
        self.changed.emit()  # punto de deshacer antes de arrastrar
        starts = {cid: self.project.find(cid)[1].start for cid in self.selected if self.project.find(cid)[1]}
        self._drag = (edge, pos, c.id, starts, c.start)
        self.update()

    def _hover_cursor(self, pos: QPointF) -> None:
        """Cursor según lo que hay bajo el ratón: bordes de clip ↔, clip mano, cabecera de pista dedo."""
        tc, tedge = self.hit_transition(pos) if pos.x() >= HEAD_W else (None, None)
        if pos.x() < HEAD_W and self.track_at(pos.y()) is not None:
            shape = Qt.CursorShape.PointingHandCursor
        elif tc is not None:
            shape = Qt.CursorShape.SizeHorCursor if tedge == "edge" else Qt.CursorShape.PointingHandCursor
        else:
            _tr, c, edge = self.hit(pos)
            shape = (Qt.CursorShape.SizeHorCursor if c is not None and edge in ("in", "out") else
                     Qt.CursorShape.OpenHandCursor if c is not None else Qt.CursorShape.ArrowCursor)
        if self.cursor().shape() != shape:
            self.setCursor(shape)

    def leaveEvent(self, e):
        if self._drag is None:
            self.unsetCursor()
        super().leaveEvent(e)

    def contextMenuEvent(self, e):
        from PySide6.QtWidgets import QMenu

        pos = QPointF(e.pos())
        m = QMenu(self)
        if pos.x() < HEAD_W:
            trk = self.track_at(pos.y())
            if trk is None:
                return
            m.addAction(tr("Subir pista"), lambda: self.request.emit("track_up", trk))
            m.addAction(tr("Bajar pista"), lambda: self.request.emit("track_down", trk))
            m.addAction(tr("Mostrar u ocultar") if trk.kind == "video" else tr("Silenciar o activar"),
                        lambda: self.request.emit("track_toggle", trk))
            m.addAction(tr("Desbloquear pista") if trk.locked else tr("Bloquear pista"),
                        lambda: (setattr(trk, "locked", not trk.locked), self.changed.emit(), self.update()))
            m.addSeparator()
            m.addAction(tr("Eliminar pista"), lambda: self.request.emit("track_remove", trk))
        else:
            _tr, c, _edge = self.hit(pos)
            if c is None:
                m.addAction(tr("Añadir texto aquí"), lambda: self.request.emit("add_text", self.t_of(pos.x())))
            else:
                if c.id not in self.selected:
                    self.selected = {c.id}
                    self.selection_changed.emit()
                    self.update()
                m.addAction(tr("Dividir en el cabezal"), lambda: self.request.emit("split", c.id))
                if c.transition != "none":
                    m.addAction(tr("Quitar la transición"), lambda: self.request.emit("remove_transition", c.id))
                m.addAction(tr("Capa superior"), lambda: self.request.emit("layer_up", c.id))
                m.addAction(tr("Capa inferior"), lambda: self.request.emit("layer_down", c.id))
                m.addSeparator()
                m.addAction(tr("Eliminar"), lambda: self.request.emit("delete", c.id))
        m.exec(e.globalPos())

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is None:
            self._hover_cursor(pos)
            return
        if self._drag[0] == "playhead":
            self.set_playhead(self.t_of(pos.x()))
            return
        if self._drag[0] == "tr_edge":
            c = self.project.find(self._drag[1])[1]
            if c is not None:
                self.request.emit("transition_d", (c.id, max(0.1, self.t_of(pos.x()) - c.start)))
                self.update()
            return
        mode, start, cid, starts, c_start = self._drag
        dt = (pos.x() - start.x()) / self.pps
        if mode == "body":
            if self.cursor().shape() != Qt.CursorShape.ClosedHandCursor:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            new = self._snap(c_start + dt, set(starts))
            shift = new - c_start
            trk = self.track_at(pos.y())
            for oid, s0 in starts.items():
                self.project.move(oid, s0 + shift, trk if oid == cid else None)
        else:
            t = self._snap(self.t_of(pos.x()), {cid})
            self.project.trim(cid, mode, t)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None and self._drag[0] != "playhead":
            self.changed.emit()
        self._drag = None
        self._hover_cursor(e.position())  # nunca se queda el cursor del arrastre

    def wheelEvent(self, e):
        d = e.angleDelta().y() / 120
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.pps * (1.2 ** d), e.position().x())
        else:
            self.offset = max(0.0, self.offset - d * 80 / self.pps)
            self.update()

    def set_playhead(self, t: float):
        self.playhead = max(0.0, t)
        self.update()
        self.playhead_moved.emit(self.playhead)

    # ------------------------------------------------------------------ soltar medios
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasFormat("application/x-aero-media") or md.hasUrls() or md.hasFormat("application/x-aero-effect") \
                or md.hasFormat("application/x-aero-transition"):
            e.acceptProposedAction()

    def _clip_for_transition(self, pos: QPointF):
        """Clip cuyo inicio está más cerca del punto en esa pista (para soltar entre dos clips)."""
        trk = self.track_at(pos.y())
        if trk is None or trk.kind != "video":
            return None
        t = self.t_of(pos.x())
        cands = [c for c in trk.clips if c.kind in ("video", "image", "text")]
        if not cands:
            return None
        best = min(cands, key=lambda c: abs(c.start - t))
        return best if abs(best.start - t) * self.pps < 60 or best.start <= t < best.end else None

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasFormat("application/x-aero-effect"):
            _tr, c, _edge = self.hit(e.position())
            self.request.emit("drop_effect", (c.id if c else None, bytes(md.data("application/x-aero-effect")).decode()))
            e.acceptProposedAction()
            return
        if md.hasFormat("application/x-aero-transition"):
            c = self._clip_for_transition(e.position())
            self.request.emit("drop_transition",
                              (c.id if c else None, bytes(md.data("application/x-aero-transition")).decode()))
            e.acceptProposedAction()
            return
        paths = [bytes(md.data("application/x-aero-media")).decode("utf-8")] if md.hasFormat(
            "application/x-aero-media") else [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        trk = self.track_at(e.position().y())
        t = self.t_of(e.position().x())
        for path in paths:
            self.drop_media.emit(path, trk, t)
        e.acceptProposedAction()
