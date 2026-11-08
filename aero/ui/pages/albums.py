"""Álbumes: tarjeta con portada y nombre, ventana de información y editor (nombre, artista y portada recortable).

La personalización vive en la base de datos de AERO Player (tabla `album_info`) y en la carpeta de datos
(`covers/`); los archivos de música nunca se modifican desde aquí.
"""

from __future__ import annotations

import hashlib
import time

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QPushButton,
                               QSlider, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from aero.ui.glasswindow import TrDialog
from aero.core.formats import human_size, human_time
from aero.core.paths import data_dir
from aero.ui import icons
from aero.ui.glass import h_layout, label, tm
from aero.i18n import tr

ALBUM_ROLE = Qt.ItemDataRole.UserRole + 1   # dict con album, title, artist, n, duration
CARD_W, CARD_H, COVER = 176, 230, 150


def covers_dir():
    d = data_dir() / "covers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_cover(img: QImage, album: str) -> str:
    """Guarda una portada personalizada (cuadrada, 600 px) en la carpeta de datos y devuelve su ruta."""
    key = hashlib.sha1(album.encode("utf-8")).hexdigest()[:16]
    path = covers_dir() / f"{key}_{int(time.time())}.png"
    img.scaled(600, 600, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation) \
        .save(str(path), "PNG")
    return str(path)


def load_image(path: str) -> QImage:
    r = QImageReader(path)
    r.setAutoTransform(True)
    return r.read()


class AlbumDelegate(QStyledItemDelegate):
    """Dibuja cada álbum: portada redondeada con borde nítido, nombre centrado y artista en segunda línea.

    Los textos largos se recortan con «…» en una línea fija, así la cuadrícula nunca se descoloca.
    """

    def sizeHint(self, option, index):
        return QSize(CARD_W, CARD_H)

    def paint(self, p: QPainter, option, index):
        t = tm().theme
        data = index.data(ALBUM_ROLE) or {}
        r = QRectF(option.rect)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        cover = QRectF(r.center().x() - COVER / 2 + 0.5, r.top() + 8.5, COVER - 1, COVER - 1)
        if hover or sel:
            card = QPainterPath()
            card.addRoundedRect(QRectF(r).adjusted(4.5, 2.5, -4.5, -2.5), 14, 14)
            c = QColor(t.accent if sel else "#ffffff")
            c.setAlphaF(0.20 if sel else (0.08 if t.dark else 0.35))
            p.fillPath(card, c)
            e = QColor(t.accent if sel else "#ffffff")
            e.setAlphaF(0.75 if sel else 0.30)
            p.setPen(QPen(e, 1))
            p.drawPath(card)
        path = QPainterPath()
        path.addRoundedRect(cover, 12, 12)
        p.save()
        p.setClipPath(path)
        pm = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(pm, QPixmap) and not pm.isNull():
            src = QRectF(pm.rect())
            side = min(src.width(), src.height())
            src = QRectF(src.center().x() - side / 2, src.center().y() - side / 2, side, side)
            p.drawPixmap(cover, pm, src)
        else:
            g = QLinearGradient(cover.topLeft(), cover.bottomRight())
            g.setColorAt(0, QColor(t.accent))
            g.setColorAt(1, QColor(t.accent2))
            p.fillRect(cover, g)
            ic = icons.pixmap("music", "#ffffff", 56)
            p.drawPixmap(QRectF(cover.center().x() - 28, cover.center().y() - 28, 56, 56), ic, QRectF(ic.rect()))
        gloss = QLinearGradient(0, cover.top(), 0, cover.top() + cover.height() * 0.45)
        gloss.setColorAt(0, QColor(255, 255, 255, 70 if hover else 46))
        gloss.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(cover.left(), cover.top(), cover.width(), cover.height() * 0.45), gloss)
        p.restore()
        edge = QColor(t.accent) if (hover or sel) else QColor(255, 255, 255, 110 if t.dark else 200)
        p.setPen(QPen(edge, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # Textos: nombre (una línea) y artista (una línea), centrados con la portada.
        f = QFont(option.font)
        f.setPointSizeF(10)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(t.text))
        text_w = int(COVER + 10)
        tx = r.center().x() - text_w / 2
        title = p.fontMetrics().elidedText(data.get("title") or "Sin álbum", Qt.TextElideMode.ElideRight, text_w)
        p.drawText(QRectF(tx, cover.bottom() + 8, text_w, 20), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   title)
        f2 = QFont(option.font)
        f2.setPointSizeF(8.8)
        p.setFont(f2)
        p.setPen(QColor(t.text2))
        artist = p.fontMetrics().elidedText(data.get("artist") or "Artista desconocido", Qt.TextElideMode.ElideRight,
                                            text_w)
        p.drawText(QRectF(tx, cover.bottom() + 28, text_w, 18), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   artist)
        p.restore()


# ---------------------------------------------------------------------------------------------- recorte
class CropView(QWidget):
    """Vista de recorte cuadrado: arrastrar para encuadrar, rueda o deslizador para acercar."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(260, 260)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.img: QImage | None = None
        self.zoom = 1.0            # 1 = el lado corto llena el cuadro
        self.center = QPointF(0.5, 0.5)
        self._drag: QPointF | None = None

    def set_image(self, img: QImage | None):
        self.img = img if img is not None and not img.isNull() else None
        self.zoom, self.center = 1.0, QPointF(0.5, 0.5)
        self.update()
        self.changed.emit()

    def _scale(self) -> float:
        side = min(self.img.width(), self.img.height())
        return self.width() / side * self.zoom

    def _clamp(self):
        if self.img is None:
            return
        s = self._scale()
        hw = self.width() / s / 2 / self.img.width()
        hh = self.height() / s / 2 / self.img.height()
        self.center = QPointF(min(max(self.center.x(), hw), 1 - hw), min(max(self.center.y(), hh), 1 - hh))

    def set_zoom(self, z: float):
        self.zoom = max(1.0, min(4.0, z))
        self._clamp()
        self.update()
        self.changed.emit()

    def source_rect(self) -> QRect:
        s = self._scale()
        side = self.width() / s
        cx, cy = self.center.x() * self.img.width(), self.center.y() * self.img.height()
        return QRect(int(cx - side / 2), int(cy - side / 2), int(side), int(side))

    def cropped(self) -> QImage | None:
        return None if self.img is None else self.img.copy(self.source_rect())

    def mousePressEvent(self, e):
        self._drag = e.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag is None or self.img is None:
            return
        d = e.position() - self._drag
        self._drag = e.position()
        s = self._scale()
        self.center = QPointF(self.center.x() - d.x() / s / self.img.width(),
                              self.center.y() - d.y() / s / self.img.height())
        self._clamp()
        self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.changed.emit()

    def wheelEvent(self, e):
        self.set_zoom(self.zoom * (1.1 if e.angleDelta().y() > 0 else 1 / 1.1))

    def paintEvent(self, e):
        t = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.setClipPath(path)
        if self.img is None:
            p.fillRect(r, QColor(255, 255, 255, 20))
            p.setPen(QColor(t.text2))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Sin portada")
        else:
            p.drawImage(QRectF(self.rect()), self.img, QRectF(self.source_rect()))
            # Guías de tercios para encuadrar
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            for k in (1, 2):
                x = self.width() * k / 3 + 0.5
                p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
                p.drawLine(QPointF(0, x), QPointF(self.width(), x))
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 170), 1))
        p.drawPath(path)


class AlbumEditDialog(TrDialog):
    """Editar álbum: nombre, artista y portada (desde el equipo, recortable, o restaurar la original)."""

    def __init__(self, album: str, info: dict, original: QImage | None, current: QImage | None, parent=None,
                 texts: dict | None = None):
        super().__init__(parent)
        # `texts` permite reutilizar el editor para carpetas (nombre, descripción y portada).
        tx = {"window": "Editar álbum", "second": "Artista", "restore": "Restaurar original",
              "note": "La personalización se guarda en AERO Player; los archivos de música no se modifican."}
        tx.update(texts or {})
        self.setWindowTitle(tx["window"])
        self.album = album
        self.original = original
        self.cover_mode = "keep"   # keep | new | original
        self.title = QLineEdit(info.get("title") or album)
        self.title.setPlaceholderText(album or "Sin álbum")
        self.artist = QLineEdit(info.get("artist") or "")
        self.artist.setPlaceholderText(info.get("detected_artist") or tx["second"])
        self.crop = CropView()
        self._setting = True
        self.crop.set_image(current if current is not None else original)
        self._setting = False
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(100, 400)
        self.zoom.setAccessibleName(tr("Zoom de la portada"))
        self.zoom.valueChanged.connect(lambda v: self.crop.set_zoom(v / 100))
        self.crop.changed.connect(self._sync_zoom)
        pick = QPushButton(tr("Elegir imagen…"))
        pick.clicked.connect(self._pick)
        restore = QPushButton(tx["restore"])
        restore.setProperty("kind", "flat")
        restore.setToolTip(tr("Vuelve a la portada incluida en los archivos o detectada automáticamente"))
        restore.clicked.connect(self._restore)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.addRow(tr("Nombre"), self.title)
        form.addRow(tx["second"], self.artist)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addSpacing(6)
        right.addWidget(label(tx["note"], "caption", wrap=True))
        right.addStretch(1)
        save = QPushButton(tr("Guardar"))
        save.setProperty("kind", "primary")
        save.clicked.connect(self.accept)
        cancel = QPushButton(tr("Cancelar"))
        cancel.clicked.connect(self.reject)
        right.addLayout(h_layout(None, cancel, save))
        left = QVBoxLayout()
        left.addWidget(self.crop)
        left.addLayout(h_layout(label("Zoom", "caption"), self.zoom, spacing=8))
        left.addLayout(h_layout(pick, restore, spacing=6))
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(20)
        root.addLayout(left)
        root.addLayout(right, 1)
        self.setMinimumWidth(640)

    def _sync_zoom(self):
        self.zoom.blockSignals(True)
        self.zoom.setValue(int(self.crop.zoom * 100))
        self.zoom.blockSignals(False)
        # Cualquier ajuste del encuadre hecho por el usuario produce una portada nueva recortada.
        if not self._setting and self.crop.img is not None:
            self.cover_mode = "new"

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Elegir portada"), "",
                                              "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if path:
            img = load_image(path)
            if not img.isNull():
                self._setting = True
                self.crop.set_image(img)
                self._setting = False
                self.cover_mode = "new"

    def _restore(self):
        self._setting = True
        self.crop.set_image(self.original)
        self._setting = False
        self.cover_mode = "original"

    def result(self) -> dict:
        """title/artist ('' = usar lo detectado) y cover: None (sin cambios), '' (original) o imagen nueva."""
        out = {"title": self.title.text().strip(), "artist": self.artist.text().strip(), "cover": None}
        if out["title"] == self.album:
            out["title"] = ""
        if self.cover_mode == "original":
            out["cover"] = ""
        elif self.cover_mode == "new":
            out["cover"] = self.crop.cropped()
        return out


def album_info_text(name: str, artist: str, d: dict) -> str:
    years = ""
    if d.get("year_min"):
        years = str(d["year_min"]) if d["year_min"] == d["year_max"] else f"{d['year_min']}–{d['year_max']}"
    rows = [("Álbum", name), ("Artista", artist or "Desconocido"), ("Pistas", str(d["tracks"])),
            ("Duración", human_time(d["duration"] or 0)), ("Tamaño", human_size(d["size"] or 0))]
    if years:
        rows.append(("Año", years))
    if d.get("genres"):
        rows.append(("Género", d["genres"].replace(",", ", ")))
    if d.get("formats"):
        rows.append(("Formatos", d["formats"].replace(".", "").upper().replace(",", ", ")))
    rows.append(("Carpeta", d["folder"] + (f"  (+{d['folders'] - 1})" if d["folders"] > 1 else "")))
    return "\n".join(f"{k}: {v}" for k, v in rows)


class AlbumInfoDialog(TrDialog):
    def __init__(self, name: str, artist: str, details: dict, cover: QPixmap | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Información del álbum"))
        art = label()
        if cover is not None and not cover.isNull():
            art.setPixmap(cover.scaled(140, 140, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                       Qt.TransformationMode.SmoothTransformation).copy(0, 0, 140, 140))
        text = label(album_info_text(name, artist, details), wrap=True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ok = QPushButton(tr("Cerrar"))
        ok.clicked.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addLayout(h_layout(art, 12, text, spacing=8))
        lay.addLayout(h_layout(None, ok))
        self.setMinimumWidth(460)
