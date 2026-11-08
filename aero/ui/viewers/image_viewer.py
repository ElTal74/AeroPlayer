"""Visor de imágenes: zoom con rueda, ajustar, 100 %, rotar, navegar por la carpeta y animaciones."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QImageReader, QMovie, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from aero.core.formats import IMAGE

QT_FORMATS = {"." + bytes(f).decode() for f in QImageReader.supportedImageFormats()}


def load_qimage(path: str, max_side: int = 0) -> QImage:
    """Decodifica con Qt (rápido, nativo) y recurre a Pillow para HEIC/AVIF/PSD/etc."""
    ext = Path(path).suffix.lower()
    if ext in QT_FORMATS or ext in (".jpg", ".jpeg", ".jfif"):
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        if max_side:
            sz = reader.size()
            if sz.isValid() and max(sz.width(), sz.height()) > max_side:
                sz.scale(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(sz)
        img = reader.read()
        if not img.isNull():
            return img
    from PIL import Image, ImageOps

    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:
        pass
    with Image.open(path) as src:
        im = ImageOps.exif_transpose(src)
        if max_side:
            im.thumbnail((max_side, max_side))
        im = im.convert("RGBA")
        # Píxeles en bruto: mucho más rápido que codificar y decodificar un PNG intermedio.
        data = im.tobytes("raw", "RGBA")
    img = QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()
    if img.isNull():
        raise ValueError("No se pudo decodificar la imagen.")
    return img


class ImageViewer(QGraphicsView):
    zoom_changed = Signal(float)
    info_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self.item)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setStyleSheet("background: transparent;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.fit_mode = True
        self.rotation = 0
        self.path = ""
        self.siblings: list[str] = []
        self.movie: QMovie | None = None
        self.size_px = (0, 0)

    def set_image(self, path: str, img: QImage) -> None:
        self._stop_movie()
        self.path = path
        self.rotation = 0
        self.flipped = (False, False)
        self._img = img
        self.item.setPixmap(QPixmap.fromImage(img))
        self.size_px = (img.width(), img.height())
        ext = Path(path).suffix.lower()
        if ext in (".gif", ".webp"):
            mv = QMovie(path)
            if mv.isValid() and mv.frameCount() != 1:
                self.movie = mv
                mv.frameChanged.connect(lambda _i: self.item.setPixmap(mv.currentPixmap()))
                mv.start()
        self._apply_transform()
        self.fit()
        self._collect_siblings()

    def _stop_movie(self):
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None

    def clear(self):
        self._stop_movie()
        self.item.setPixmap(QPixmap())
        self._img = None

    def _collect_siblings(self):
        p = Path(self.path)
        try:
            files = sorted((str(f) for f in p.parent.iterdir() if f.suffix.lower() in IMAGE and f.is_file()),
                           key=lambda s: s.lower())
        except OSError:
            files = [self.path]
        self.siblings = files

    def neighbor(self, step: int) -> str | None:
        if not self.siblings or self.path not in self.siblings:
            return None
        i = self.siblings.index(self.path) + step
        if 0 <= i < len(self.siblings):
            return self.siblings[i]
        return None

    def _apply_transform(self):
        self.item.setTransformOriginPoint(self.item.boundingRect().center())
        self.item.setRotation(self.rotation)
        self.scene().setSceneRect(self.item.sceneBoundingRect())

    def rotate_by(self, deg: int):
        self.rotation = (self.rotation + deg) % 360
        self._apply_transform()
        if self.fit_mode:
            self.fit()

    def flip(self, horizontal: bool):
        """Voltea la vista (no modifica el archivo). Las animaciones no se voltean."""
        if self.movie is not None or getattr(self, "_img", None) is None or self._img.isNull():
            return
        h, v = self.flipped
        self.flipped = (not h, v) if horizontal else (h, not v)
        orient = Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical
        self._img = self._img.flipped(orient) if hasattr(self._img, "flipped") else             self._img.mirrored(horizontal, not horizontal)
        self.item.setPixmap(QPixmap.fromImage(self._img))
        self._apply_transform()
        if self.fit_mode:
            self.fit()

    def fit(self):
        self.fit_mode = True
        rect = self.item.sceneBoundingRect()
        if rect.isEmpty():
            return
        self.resetTransform()
        vp = self.viewport().rect()
        scale = min(vp.width() / rect.width(), vp.height() / rect.height(), 1.0)
        self.setTransform(QTransform.fromScale(scale, scale))
        self.centerOn(rect.center())
        self.zoom_changed.emit(scale)

    def actual_size(self):
        self.fit_mode = False
        self.resetTransform()
        self.zoom_changed.emit(1.0)

    def zoom(self, factor: float):
        cur = self.transform().m11()
        new = max(0.02, min(40.0, cur * factor))
        factor = new / cur
        self.fit_mode = False
        self.scale(factor, factor)
        self.zoom_changed.emit(new)

    def wheelEvent(self, e):
        self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_mode:
            QTimer.singleShot(0, self.fit)

    def mouseDoubleClickEvent(self, e):
        if self.fit_mode:
            self.actual_size()
        else:
            self.fit()

    def drawBackground(self, p: QPainter, rect: QRectF):
        # Fondo de cuadros sutil solo bajo la imagen (transparencias visibles)
        r = self.item.sceneBoundingRect().intersected(rect)
        if r.isEmpty():
            return
        brush = QBrush(_checker())
        inv = 1 / max(0.01, self.transform().m11())
        brush.setTransform(QTransform.fromScale(inv, inv))
        p.fillRect(r, brush)


_CHECKER: QPixmap | None = None


def _checker() -> QPixmap:
    global _CHECKER
    if _CHECKER is None:
        _CHECKER = QPixmap(24, 24)
        _CHECKER.fill(QColor(255, 255, 255, 18))
        p = QPainter(_CHECKER)
        p.fillRect(0, 0, 12, 12, QColor(255, 255, 255, 34))
        p.fillRect(12, 12, 12, 12, QColor(255, 255, 255, 34))
        p.end()
    return _CHECKER
