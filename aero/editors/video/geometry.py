"""Geometría única de cada elemento visual en el lienzo: la usan el visor (manipulación directa) y la exportación.

Orden de operaciones (igual que el grafo de FFmpeg de `export.py`):
1. Recorte del original (`crop`: izquierda, arriba, derecha, abajo en fracciones).
2. Giro de 90° en 90° (`rotation`, transpuesta: cambia ancho por alto).
3. Escala: encaje dentro del lienzo × `scale`, y estiramiento `sx` / `sy` sobre los ejes del lienzo.
4. Giro libre (`angle`, grados, horario) alrededor del punto de anclaje (`anchor_x/y`, −1…1 sobre el elemento).
5. El punto de anclaje se coloca en el centro del lienzo + (`pos_x`, `pos_y`) × medio lienzo.

Todo se calcula con números (no con expresiones de FFmpeg): así lo que se ve en el visor es lo que se exporta.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPolygonF, QTransform


@dataclass
class Placement:
    crop_w: float          # tamaño del original tras recortar (antes de girar 90°)
    crop_h: float
    rot90: int             # 0, 90, 180, 270
    w: float               # tamaño del elemento en el lienzo (tras girar 90° y escalar, antes del giro libre)
    h: float
    kx: float              # factores de escala sobre el recorte girado
    ky: float
    anchor: QPointF        # posición del punto de anclaje en el lienzo
    center: QPointF        # centro del elemento en el lienzo (tras el giro libre)
    angle: float           # giro libre en grados


def _crop(clip) -> tuple[float, float, float, float]:
    l, t, r, b = (min(0.95, max(0.0, float(x))) for x in (list(clip.crop or []) + [0, 0, 0, 0])[:4])
    if l + r > 0.95:
        r = max(0.0, 0.95 - l)
    if t + b > 0.95:
        b = max(0.0, 0.95 - t)
    return l, t, r, b


def crop_of(clip) -> tuple[float, float, float, float]:
    """Recorte saneado (izquierda, arriba, derecha, abajo)."""
    return _crop(clip)


def place(W: float, H: float, src_w: float, src_h: float, clip) -> Placement | None:
    """Colocación del clip en un lienzo de W×H. Los títulos (`kind == "text"`) usan su tamaño natural (el texto
    ya se renderiza a la escala del lienzo) y parten de su posición arriba / centro / abajo."""
    if not src_w or not src_h or not W or not H:
        return None
    l, t, r, b = _crop(clip)
    cw, ch = src_w * (1 - l - r), src_h * (1 - t - b)
    rot90 = int(clip.rotation) % 360
    fw, fh = (ch, cw) if rot90 in (90, 270) else (cw, ch)
    s = max(0.01, float(clip.scale))
    text = getattr(clip, "kind", "") == "text"
    full_w, full_h = (src_h, src_w) if rot90 in (90, 270) else (src_w, src_h)
    # El encaje se calcula con el original sin recortar: recortar no agranda lo que queda
    fit = s if text else min(W * s / full_w, H * s / full_h)
    kx, ky = fit * max(0.01, float(clip.sx)), fit * max(0.01, float(clip.sy))
    w, h = fw * kx, fh * ky
    base_y = H / 2
    if text:
        base_y = {"top": H * 0.08 + h / 2, "bottom": H * 0.92 - h / 2}.get(getattr(clip, "text_pos", ""), H / 2)
    anchor = QPointF(W / 2 + float(clip.pos_x) * W / 2, base_y + float(clip.pos_y) * H / 2)
    ang = float(clip.angle)
    ax, ay = float(clip.anchor_x) * w / 2, float(clip.anchor_y) * h / 2
    rad = math.radians(ang)
    # centro = anclaje − R(ángulo)·(desplazamiento del anclaje respecto al centro)
    cx = anchor.x() - (ax * math.cos(rad) - ay * math.sin(rad))
    cy = anchor.y() - (ax * math.sin(rad) + ay * math.cos(rad))
    return Placement(cw, ch, rot90, w, h, kx, ky, anchor, QPointF(cx, cy), ang)


def element_transform(pl: Placement) -> QTransform:
    """De coordenadas del recorte (0…crop_w, 0…crop_h) al lienzo."""
    t = QTransform()
    t.translate(pl.center.x(), pl.center.y())
    t.rotate(pl.angle)
    t.scale(pl.kx, pl.ky)
    t.rotate(pl.rot90)
    t.translate(-pl.crop_w / 2, -pl.crop_h / 2)
    return t


def frame_transform(pl: Placement) -> QTransform:
    """De coordenadas del elemento ya escalado (−w/2…w/2, −h/2…h/2) al lienzo: para el marco de selección."""
    t = QTransform()
    t.translate(pl.center.x(), pl.center.y())
    t.rotate(pl.angle)
    return t


def corners(pl: Placement) -> QPolygonF:
    return frame_transform(pl).map(QPolygonF(QRectF(-pl.w / 2, -pl.h / 2, pl.w, pl.h)))


def even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def export_size(pl: Placement) -> tuple[int, int]:
    """Tamaño (par) al que FFmpeg escala el recorte girado."""
    return even(pl.w), even(pl.h)


def rotated_bbox(w: float, h: float, angle: float) -> tuple[float, float]:
    rad = math.radians(angle)
    c, s = abs(math.cos(rad)), abs(math.sin(rad))
    return w * c + h * s, w * s + h * c
