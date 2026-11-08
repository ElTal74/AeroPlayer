"""Documento del editor de imágenes: capas, ajustes no destructivos, historial y proyectos.

* La capa «Fondo» es la imagen original a resolución completa. Las demás son imágenes superpuestas o capas
  de dibujo, con posición, escala, giro, opacidad y visibilidad.
* Los ajustes de color son parámetros (no tocan píxeles) y se aplican al fondo al dibujar y al exportar.
* Historial por instantáneas: copiar una `QImage` comparte los píxeles hasta que se modifican, así que una
  instantánea solo cuesta memoria en la capa que de verdad cambia. Máximo `HISTORY` pasos.
* El archivo original no se modifica nunca desde aquí: guardar y exportar escriben donde se les indica.
"""

from __future__ import annotations

import copy
import json
import math
import zipfile
from dataclasses import dataclass, field

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform

from aero.editors.image import adjust

HISTORY = 40
PROJECT_EXT = ".aeroimg"


@dataclass
class Layer:
    name: str
    image: QImage
    x: float = 0.0          # posición del centro en coordenadas del lienzo
    y: float = 0.0
    scale: float = 1.0
    angle: float = 0.0
    opacity: float = 1.0
    visible: bool = True
    background: bool = False

    def transform(self) -> QTransform:
        t = QTransform()
        t.translate(self.x, self.y)
        t.rotate(self.angle)
        t.scale(self.scale, self.scale)
        t.translate(-self.image.width() / 2, -self.image.height() / 2)
        return t

    def bounds(self) -> QRectF:
        return self.transform().mapRect(QRectF(0, 0, self.image.width(), self.image.height()))

    def clone(self) -> "Layer":
        return copy.copy(self)  # la QImage se comparte hasta que alguien pinta en ella


@dataclass
class State:
    layers: list[Layer]
    adjust: dict
    active: int


@dataclass
class ImageDocument:
    path: str = ""
    layers: list[Layer] = field(default_factory=list)
    adjust: dict = field(default_factory=lambda: dict(adjust.NEUTRAL))
    active: int = 0
    undo_stack: list[tuple[str, State]] = field(default_factory=list)
    redo_stack: list[tuple[str, State]] = field(default_factory=list)
    version: int = 0        # sube con cada cambio (cachés de la vista)
    dirty: bool = False

    # ------------------------------------------------------------------ creación
    @classmethod
    def from_image(cls, img: QImage, path: str = "") -> "ImageDocument":
        img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        from aero.i18n import tr

        bg = Layer(tr("Fondo"), img, img.width() / 2, img.height() / 2, background=True)
        return cls(path, [bg])

    @property
    def size(self) -> QSize:
        return self.layers[0].image.size()

    @property
    def background(self) -> Layer:
        return self.layers[0]

    @property
    def current(self) -> Layer:
        return self.layers[min(self.active, len(self.layers) - 1)]

    # ------------------------------------------------------------------ historial
    def _state(self) -> State:
        return State([ly.clone() for ly in self.layers], dict(self.adjust), self.active)

    def checkpoint(self, label: str) -> None:
        """Guardar el estado ANTES de un cambio."""
        self.undo_stack.append((label, self._state()))
        del self.undo_stack[:-HISTORY]
        self.redo_stack.clear()
        self.dirty = True

    def _restore(self, st: State) -> None:
        self.layers, self.adjust, self.active = st.layers, st.adjust, st.active
        self.version += 1

    def undo(self) -> str:
        if not self.undo_stack:
            return ""
        label, st = self.undo_stack.pop()
        self.redo_stack.append((label, self._state()))
        self._restore(st)
        return label

    def redo(self) -> str:
        if not self.redo_stack:
            return ""
        label, st = self.redo_stack.pop()
        self.undo_stack.append((label, self._state()))
        self._restore(st)
        return label

    def changed(self) -> None:
        self.version += 1
        self.dirty = True

    # ------------------------------------------------------------------ composición y tamaño del lienzo
    def _all(self, fn) -> None:
        """Aplica una transformación del lienzo a todas las capas (recorte, giro, volteo…)."""
        for ly in self.layers:
            fn(ly)
        self.changed()

    def crop(self, r: QRect) -> None:
        r = r.intersected(QRect(0, 0, self.size.width(), self.size.height()))
        if r.width() < 1 or r.height() < 1:
            return
        self.checkpoint("Recortar")

        def f(ly: Layer):
            if ly.background:
                ly.image = ly.image.copy(r)
                ly.x, ly.y = r.width() / 2, r.height() / 2
            else:
                ly.x -= r.x()
                ly.y -= r.y()
        self._all(f)

    def resize(self, w: int, h: int) -> None:
        w, h = max(1, int(w)), max(1, int(h))
        sx, sy = w / self.size.width(), h / self.size.height()
        self.checkpoint("Cambiar tamaño")

        def f(ly: Layer):
            if ly.background:
                ly.image = ly.image.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
                ly.x, ly.y = w / 2, h / 2
            else:
                ly.x, ly.y, ly.scale = ly.x * sx, ly.y * sy, ly.scale * (sx + sy) / 2
        self._all(f)

    def rotate90(self, clockwise: bool = True) -> None:
        self.checkpoint("Girar")
        W, H = self.size.width(), self.size.height()

        def f(ly: Layer):
            if ly.background:
                ly.image = ly.image.transformed(QTransform().rotate(90 if clockwise else -90))
                ly.x, ly.y = H / 2, W / 2
            else:
                ly.x, ly.y = (H - ly.y, ly.x) if clockwise else (ly.y, W - ly.x)
                ly.angle += 90 if clockwise else -90
        self._all(f)

    def flip(self, horizontal: bool = True) -> None:
        self.checkpoint("Voltear")
        W, H = self.size.width(), self.size.height()

        def f(ly: Layer):
            if ly.background:
                ly.image = ly.image.flipped(Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical)
            elif horizontal:
                ly.x, ly.angle = W - ly.x, -ly.angle
                ly.image = ly.image.flipped(Qt.Orientation.Horizontal)
            else:
                ly.y, ly.angle = H - ly.y, -ly.angle
                ly.image = ly.image.flipped(Qt.Orientation.Vertical)
        self._all(f)

    def straighten(self, degrees: float) -> None:
        """Endereza girando un ángulo pequeño y recorta al mayor rectángulo sin esquinas vacías."""
        if abs(degrees) < 0.01:
            return
        self.checkpoint("Enderezar")
        W, H = self.size.width(), self.size.height()
        a = math.radians(abs(degrees))
        # Mayor rectángulo con la misma proporción dentro del rectángulo girado
        cos, sin = math.cos(a), math.sin(a)
        k = min(W / (W * cos + H * sin), H / (W * sin + H * cos))
        nw, nh = max(1, int(W * k)), max(1, int(H * k))
        bg = self.background.image
        out = QImage(nw, nh, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(0)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(nw / 2, nh / 2)
        p.rotate(degrees)
        p.translate(-W / 2, -H / 2)
        p.drawImage(0, 0, bg)
        p.end()
        dx, dy = (W - nw) / 2, (H - nh) / 2

        def f(ly: Layer):
            if ly.background:
                ly.image = out
                ly.x, ly.y = nw / 2, nh / 2
            else:
                ly.x -= dx
                ly.y -= dy
        self._all(f)

    def add_margins(self, left: int, top: int, right: int, bottom: int, color: QColor) -> None:
        W, H = self.size.width(), self.size.height()
        nw, nh = W + left + right, H + top + bottom
        if nw < 1 or nh < 1:
            return
        self.checkpoint("Márgenes")
        out = QImage(nw, nh, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(color)
        p = QPainter(out)
        p.drawImage(left, top, self.background.image)
        p.end()

        def f(ly: Layer):
            if ly.background:
                ly.image = out
                ly.x, ly.y = nw / 2, nh / 2
            else:
                ly.x += left
                ly.y += top
        self._all(f)

    # ------------------------------------------------------------------ píxeles
    def _region_op(self, r: QRect, label: str, op) -> bool:
        """Aplica `op` a la zona `r` (coordenadas del lienzo) de la capa activa. False si no la toca."""
        ly = self.current
        r = r.intersected(QRect(0, 0, self.size.width(), self.size.height())) if ly.background else r
        if not ly.background:
            # Las coordenadas del lienzo se pasan a las de la capa (con giro, el rectángulo que lo envuelve)
            inv, _ok = ly.transform().inverted()
            r = inv.mapRect(QRectF(r)).toAlignedRect().intersected(ly.image.rect())
        if r.width() < 1 or r.height() < 1:
            return False
        self.checkpoint(label)
        part = ly.image.copy(r)
        part = op(part)
        img = ly.image.copy()
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawImage(r.topLeft(), part)
        p.end()
        ly.image = img
        self.changed()
        return True

    def pixelate(self, r: QRect, block: int) -> bool:
        block = max(2, int(block))

        def op(part: QImage) -> QImage:
            small = part.scaled(max(1, part.width() // block), max(1, part.height() // block),
                                Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            return small.scaled(part.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.FastTransformation)
        return self._region_op(r, "Pixelar", op)

    def mosaic(self, r: QRect, block: int) -> bool:
        """Pixelado con juntas finas entre teselas."""
        block = max(4, int(block))

        def op(part: QImage) -> QImage:
            small = part.scaled(max(1, part.width() // block), max(1, part.height() // block),
                                Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            big = small.scaled(part.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.FastTransformation).convertToFormat(
                QImage.Format.Format_ARGB32_Premultiplied)
            p = QPainter(big)
            p.setPen(QColor(0, 0, 0, 70))
            for x in range(0, big.width(), block):
                p.drawLine(x, 0, x, big.height())
            for y in range(0, big.height(), block):
                p.drawLine(0, y, big.width(), y)
            p.end()
            return big
        return self._region_op(r, "Mosaico", op)

    def blur_region(self, r: QRect, radius: int) -> bool:
        def op(part: QImage) -> QImage:
            x = adjust.to_array(part)
            rr = max(1, int(radius))
            x[..., :3] = adjust.box_blur(adjust.box_blur(x[..., :3], rr), rr)
            return adjust.from_array(x).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        return self._region_op(r, "Desenfocar zona", op)

    def low_resolution(self, factor: int) -> None:
        """Efecto de baja resolución en toda la imagen (sin cambiar sus dimensiones)."""
        factor = max(2, int(factor))
        self._region_op(QRect(0, 0, self.size.width(), self.size.height()), "Baja resolución",
                        lambda part: part.scaled(max(1, part.width() // factor), max(1, part.height() // factor),
                                                 Qt.AspectRatioMode.IgnoreAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation).scaled(
                            part.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.FastTransformation))

    # ------------------------------------------------------------------ capas
    def drawing_layer(self) -> Layer:
        """Capa donde se dibuja: la activa si no es el fondo; si no, una capa «Dibujo» nueva del tamaño del lienzo."""
        if not self.current.background and self.current.scale == 1.0 and self.current.angle == 0.0 \
                and self.current.image.size() == self.size:
            return self.current
        img = QImage(self.size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        n = sum(1 for ly in self.layers if ly.name.startswith("Dibujo")) + 1
        ly = Layer(f"Dibujo {n}", img, self.size.width() / 2, self.size.height() / 2)
        self.layers.append(ly)
        self.active = len(self.layers) - 1
        return ly

    def add_image_layer(self, img: QImage, name: str) -> None:
        self.checkpoint("Añadir imagen")
        img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        W, H = self.size.width(), self.size.height()
        scale = min(1.0, 0.6 * min(W / img.width(), H / img.height()))
        self.layers.append(Layer(name, img, W / 2, H / 2, scale=scale))
        self.active = len(self.layers) - 1
        self.changed()

    def duplicate_layer(self, i: int) -> None:
        if self.layers[i].background:
            return
        self.checkpoint("Duplicar capa")
        ly = self.layers[i].clone()
        ly.name += " (copia)"
        ly.x += 20
        ly.y += 20
        self.layers.insert(i + 1, ly)
        self.active = i + 1
        self.changed()

    def remove_layer(self, i: int) -> None:
        if self.layers[i].background:
            return
        self.checkpoint("Eliminar capa")
        del self.layers[i]
        self.active = max(0, min(self.active, len(self.layers) - 1))
        self.changed()

    def move_layer(self, i: int, step: int) -> None:
        j = i + step
        if self.layers[i].background or j < 1 or j >= len(self.layers):
            return
        self.checkpoint("Ordenar capas")
        self.layers[i], self.layers[j] = self.layers[j], self.layers[i]
        self.active = j
        self.changed()

    # ------------------------------------------------------------------ resultado
    def render(self, scale: float = 1.0, base: QImage | None = None) -> QImage:
        """Imagen final: fondo con ajustes y capas encima. `base` permite pasar un fondo ya ajustado."""
        W, H = self.size.width(), self.size.height()
        out = QImage(max(1, round(W * scale)), max(1, round(H * scale)), QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(0)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(scale, scale)
        if base is None:
            base = adjust.apply(self.background.image, self.adjust)
        if self.background.visible:
            p.drawImage(QRectF(0, 0, W, H), base)
        for ly in self.layers[1:]:
            if ly.visible:
                p.save()
                p.setOpacity(ly.opacity)
                p.setTransform(ly.transform(), True)
                p.drawImage(QPointF(0, 0), ly.image)
                p.restore()
        p.end()
        return out

    # ------------------------------------------------------------------ proyectos
    def save_project(self, path: str) -> None:
        """Proyecto editable: capas en PNG sin pérdida y ajustes en JSON, en un único archivo .aeroimg (ZIP)."""
        meta = {"format": "aero_image_project", "version": 1, "source": self.path, "adjust": self.adjust,
                "active": self.active, "layers": []}
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
            for i, ly in enumerate(self.layers):
                name = f"capa_{i:03d}.png"
                z.writestr(name, _png_bytes(ly.image))
                meta["layers"].append({"file": name, "name": ly.name, "x": ly.x, "y": ly.y, "scale": ly.scale,
                                       "angle": ly.angle, "opacity": ly.opacity, "visible": ly.visible,
                                       "background": ly.background})
            z.writestr("proyecto.json", json.dumps(meta, ensure_ascii=False, indent=1))
        self.dirty = False

    @classmethod
    def load_project(cls, path: str) -> "ImageDocument":
        with zipfile.ZipFile(path) as z:
            meta = json.loads(z.read("proyecto.json"))
            if meta.get("format") != "aero_image_project":
                raise ValueError("No es un proyecto de imagen de AERO Player.")
            layers = []
            for m in meta["layers"]:
                if "/" in m["file"] or "\\" in m["file"] or ".." in m["file"]:
                    raise ValueError("Proyecto dañado.")
                img = QImage.fromData(z.read(m["file"]), "PNG").convertToFormat(
                    QImage.Format.Format_ARGB32_Premultiplied)
                layers.append(Layer(m["name"], img, float(m["x"]), float(m["y"]), float(m["scale"]),
                                    float(m["angle"]), float(m["opacity"]), bool(m["visible"]), bool(m["background"])))
        a = dict(adjust.NEUTRAL)
        a.update({k: v for k, v in (meta.get("adjust") or {}).items() if k in adjust.NEUTRAL})
        doc = cls(meta.get("source", ""), layers, a, int(meta.get("active", 0)))
        return doc


def _png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba.data())


def encode(img: QImage, fmt: str, quality: int) -> bytes:
    """Codifica en memoria (también sirve para estimar el tamaño final antes de guardar)."""
    fmt = fmt.lower()
    if fmt in ("jpg", "jpeg", "bmp"):
        flat = QImage(img.size(), QImage.Format.Format_RGB32)
        flat.fill(QColor("white"))
        p = QPainter(flat)
        p.drawImage(0, 0, img)
        p.end()
        img = flat
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = img.save(buf, {"jpeg": "JPG"}.get(fmt, fmt.upper()), quality if fmt in ("jpg", "jpeg", "webp") else -1)
    buf.close()
    if not ok:
        raise ValueError(f"No se puede escribir en formato {fmt.upper()}.")
    return bytes(ba.data())
