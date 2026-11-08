"""Documento de AERO Paint (sin interfaz): capas, deshacer/rehacer, relleno, proyecto y exportación.

* Cada capa es una QImage ARGB32 premultiplicada del tamaño del lienzo, con nombre, visibilidad y opacidad.
* Deshacer guarda copias de las capas (QImage comparte memoria hasta que se modifica: barato).
* Proyecto `.aeropaint`: ZIP con `project.json` (versión, tamaño, fondo, capas) y un PNG por capa.
"""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter

PROJECT_EXT = ".aeropaint"
FORMAT_VERSION = 1
EXPORT_FORMATS = {"png": "PNG", "jpg": "JPEG", "bmp": "BMP", "webp": "WEBP"}
MAX_UNDO = 40


@dataclass
class PaintLayer:
    name: str
    image: QImage
    visible: bool = True
    opacity: float = 1.0

    def copy(self) -> "PaintLayer":
        # Copia compartida: QImage solo duplica los píxeles cuando alguien pinta en ella (QPainter separa la
        # copia). Deshacer no duplica las capas que no cambian.
        return PaintLayer(self.name, QImage(self.image), self.visible, self.opacity)


def _blank(size: QSize, color: QColor | None = None) -> QImage:
    img = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(color if color is not None else Qt.GlobalColor.transparent)
    return img


class PaintDocument:
    def __init__(self, width: int = 1280, height: int = 800, background: str = "#ffffff"):
        """`background`: color («#rrggbb») o «transparent»."""
        self.size = QSize(max(1, width), max(1, height))
        self.background = background
        bg = None if background == "transparent" else QColor(background)
        from aero.i18n import tr

        self.layers: list[PaintLayer] = [PaintLayer(tr("Fondo"), _blank(self.size, bg))]
        self.active = 0
        self.undo_stack: list[tuple[str, list[PaintLayer], QSize, int]] = []
        self.redo_stack: list[tuple[str, list[PaintLayer], QSize, int]] = []
        self.dirty = False
        self.path = ""
        self.edits = 0                 # sube con cada cambio: el borrador automático no reescribe lo mismo

    # ------------------------------------------------------------------ deshacer
    def _state(self):
        return [ly.copy() for ly in self.layers], QSize(self.size), self.active

    def checkpoint(self, label: str) -> None:
        layers, size, active = self._state()
        self.undo_stack.append((label, layers, size, active))
        del self.undo_stack[:-MAX_UNDO]
        self.redo_stack.clear()
        self.dirty = True
        self.edits += 1

    def _swap(self, src: list, dst: list) -> bool:
        if not src:
            return False
        label, layers, size, active = src.pop()
        cur_layers, cur_size, cur_active = self._state()
        dst.append((label, cur_layers, cur_size, cur_active))
        self.layers, self.size, self.active = layers, size, min(active, len(layers) - 1)
        self.dirty = True
        self.edits += 1
        return True

    def undo(self) -> bool:
        return self._swap(self.undo_stack, self.redo_stack)

    def redo(self) -> bool:
        return self._swap(self.redo_stack, self.undo_stack)

    # ------------------------------------------------------------------ capas
    @property
    def current(self) -> PaintLayer:
        return self.layers[self.active]

    def add_layer(self, name: str = "", image: QImage | None = None) -> PaintLayer:
        self.checkpoint("Nueva capa")
        img = _blank(self.size)
        if image is not None:
            p = QPainter(img)
            p.drawImage(0, 0, image)
            p.end()
        ly = PaintLayer(name or f"Capa {len(self.layers)}", img)
        self.layers.insert(self.active + 1, ly)
        self.active += 1
        return ly

    def remove_layer(self, i: int) -> bool:
        if len(self.layers) <= 1:
            return False
        self.checkpoint("Eliminar capa")
        del self.layers[i]
        self.active = max(0, min(self.active, len(self.layers) - 1))
        return True

    def move_layer(self, i: int, delta: int) -> None:
        j = max(0, min(len(self.layers) - 1, i + delta))
        if i == j:
            return
        self.checkpoint("Ordenar capas")
        self.layers[i], self.layers[j] = self.layers[j], self.layers[i]
        self.active = j

    # ------------------------------------------------------------------ edición
    def flood_fill(self, x: int, y: int, color: QColor, tolerance: int = 24, clip=None) -> int:
        """Rellena la zona contigua de color parecido en la capa activa. Devuelve los píxeles pintados."""
        import numpy as np

        img = self.current.image
        if not (0 <= x < img.width() and 0 <= y < img.height()):
            return 0
        w, h = img.width(), img.height()
        conv = img.convertToFormat(QImage.Format.Format_ARGB32)
        buf = np.frombuffer(conv.constBits(), dtype=np.uint8).reshape(h, conv.bytesPerLine())[:, : w * 4]
        px = buf.reshape(h, w, 4).astype(np.int16)
        target = px[y, x].copy()
        similar = np.abs(px - target).max(axis=2) <= tolerance
        if clip is not None:
            similar &= clip
        filled = np.zeros((h, w), dtype=bool)
        stack = [(x, y)]
        while stack:  # relleno por tramos horizontales: rápido incluso en lienzos grandes
            cx, cy = stack.pop()
            if filled[cy, cx] or not similar[cy, cx]:
                continue
            row, done = similar[cy], filled[cy]
            left = cx
            while left > 0 and row[left - 1] and not done[left - 1]:
                left -= 1
            right = cx
            while right < w - 1 and row[right + 1] and not done[right + 1]:
                right += 1
            filled[cy, left:right + 1] = True
            for ny in (cy - 1, cy + 1):
                if 0 <= ny < h:
                    seg = similar[ny, left:right + 1] & ~filled[ny, left:right + 1]
                    if seg.any():
                        idx = np.flatnonzero(seg)
                        # un punto de partida por cada tramo contiguo
                        starts = idx[np.r_[True, np.diff(idx) > 1]] + left
                        stack.extend((int(sx), ny) for sx in starts)
        count = int(filled.sum())
        if not count:
            return 0
        self.checkpoint("Rellenar")
        alpha = (filled.astype(np.uint8) * 255).tobytes()
        amask = QImage(alpha, w, h, w, QImage.Format.Format_Alpha8).copy()
        fill = _blank(self.size, color)
        p = QPainter(fill)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        p.drawImage(0, 0, amask)  # solo queda el color donde la máscara es opaca
        p.end()
        q = QPainter(self.current.image)
        q.drawImage(0, 0, fill)
        q.end()
        return count

    def pick(self, x: int, y: int) -> QColor:
        img = self.render()
        if 0 <= x < img.width() and 0 <= y < img.height():
            return img.pixelColor(x, y)
        return QColor("black")

    def crop(self, r: QRect) -> None:
        r = r.intersected(QRect(0, 0, self.size.width(), self.size.height()))
        if r.isEmpty():
            return
        self.checkpoint("Recortar")
        for ly in self.layers:
            ly.image = ly.image.copy(r)
        self.size = r.size()

    def resize_image(self, w: int, h: int) -> None:
        self.checkpoint("Redimensionar")
        for ly in self.layers:
            ly.image = ly.image.scaled(max(1, w), max(1, h), Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
        self.size = QSize(max(1, w), max(1, h))

    def resize_canvas(self, w: int, h: int) -> None:
        """Cambia el tamaño del lienzo sin escalar el dibujo (se amplía con transparente o se recorta)."""
        self.checkpoint("Tamaño del lienzo")
        new = QSize(max(1, w), max(1, h))
        for i, ly in enumerate(self.layers):
            bg = QColor(self.background) if i == 0 and self.background != "transparent" else None
            img = _blank(new, bg)
            p = QPainter(img)
            p.drawImage(0, 0, ly.image)
            p.end()
            ly.image = img
        self.size = new

    # ------------------------------------------------------------------ resultado
    def render(self) -> QImage:
        out = _blank(self.size)
        p = QPainter(out)
        for ly in self.layers:
            if ly.visible and ly.opacity > 0:
                p.setOpacity(ly.opacity)
                p.drawImage(0, 0, ly.image)
        p.end()
        return out

    def export(self, path: str, fmt: str | None = None, quality: int = 92) -> None:
        fmt = (fmt or os.path.splitext(path)[1].lstrip(".")).lower().replace("jpeg", "jpg")
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"Formato no compatible: {fmt}")
        img = self.render()
        if fmt in ("jpg", "bmp"):  # sin transparencia: se aplana sobre blanco
            flat = _blank(self.size, QColor("white"))
            p = QPainter(flat)
            p.drawImage(0, 0, img)
            p.end()
            img = flat
        tmp = path + ".part"
        if not img.save(tmp, EXPORT_FORMATS[fmt], quality):
            raise OSError("No se pudo escribir la imagen.")
        os.replace(tmp, path)

    def draft_job(self):
        """Copia del documento (sin coste: capas compartidas) y la función que la guarda en otro hilo."""
        snap = PaintDocument.__new__(PaintDocument)
        snap.__dict__.update(self.__dict__)
        snap.layers = [ly.copy() for ly in self.layers]
        snap.size = QSize(self.size)
        snap.undo_stack, snap.redo_stack = [], []
        return lambda path: snap.save_project(path, draft=True)

    def save_project(self, path: str, draft: bool = False) -> None:
        meta = {"format": "aero_paint", "version": FORMAT_VERSION, "width": self.size.width(),
                "height": self.size.height(), "background": self.background, "active": self.active,
                "layers": [{"name": ly.name, "visible": ly.visible, "opacity": ly.opacity, "file": f"layer{i}.png"}
                           for i, ly in enumerate(self.layers)]}
        tmp = path + ".part"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("project.json", json.dumps(meta, ensure_ascii=False, indent=1))
            for i, ly in enumerate(self.layers):
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                ly.image.save(buf, "PNG")
                z.writestr(f"layer{i}.png", bytes(ba))
        os.replace(tmp, path)
        if not draft:  # un borrador automático no cambia el archivo del documento ni su estado
            self.path = path
            self.dirty = False

    @classmethod
    def load_project(cls, path: str) -> "PaintDocument":
        with zipfile.ZipFile(path) as z:
            meta = json.loads(z.read("project.json").decode("utf-8"))
            if meta.get("format") != "aero_paint":
                raise ValueError("No es un proyecto de AERO Paint.")
            doc = cls(int(meta["width"]), int(meta["height"]), meta.get("background", "#ffffff"))
            layers = []
            for info in meta["layers"]:
                img = QImage.fromData(z.read(info["file"]), "PNG").convertToFormat(
                    QImage.Format.Format_ARGB32_Premultiplied)
                layers.append(PaintLayer(info.get("name", "Capa"), img, bool(info.get("visible", True)),
                                         float(info.get("opacity", 1.0))))
        doc.layers = layers or doc.layers
        doc.active = max(0, min(int(meta.get("active", 0)), len(doc.layers) - 1))
        doc.path = path
        return doc

    @classmethod
    def from_image(cls, img: QImage, path: str = "") -> "PaintDocument":
        doc = cls(img.width(), img.height(), "transparent")
        doc.layers[0].image = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        doc.layers[0].name = "Imagen"
        doc.path = path
        return doc
