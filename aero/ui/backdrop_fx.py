"""Fondo decorativo de los temas: tinte, luces y elementos (burbujas, nubes, césped, partículas, reflejos, ondas).

Rendimiento:
* El tinte y los elementos fijos se renderizan una sola vez (a media resolución) en dos capas; cambiar la
  transparencia solo cambia la opacidad con la que se pintan, sin volver a renderizar.
* Con movimiento activado, solo los elementos móviles (burbujas, partículas, nubes) se dibujan cada fotograma
  desde «sprites» prerrenderizados, y solo se invalida el rectángulo que ocupan (nunca la ventana entera).
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QColor, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)

from aero.ui.theme import Theme, _mix

MOVING = ("bubbles", "particles", "clouds", "stars")

# Movimiento del fondo elegido en Ajustes: «on» (activado), «reduced» (reducido) o «static» (fondo fijo).
# Si Windows tiene desactivadas las animaciones, «on» se trata como «reduced».
MOTION: dict = {"mode": "on"}
DEFAULT_SPEED = 0.4      # velocidad si el tema no fija una (los temas antiguos guardaban 0 = sin movimiento)


def motion_mode() -> str:
    mode = MOTION.get("mode", "on")
    if mode == "on" and MOTION.get("os_reduced"):
        return "reduced"
    return mode if mode in ("on", "reduced", "static") else "on"


def os_prefers_reduced_motion() -> bool:
    """Preferencia de Windows «Mostrar animaciones» (Accesibilidad › Efectos visuales)."""
    import os

    if os.name != "nt":
        return False
    try:
        import ctypes

        on = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)  # SPI_GETCLIENTAREAANIMATION
        return not on.value
    except (OSError, AttributeError):
        return False


def effective_speed(t: Theme) -> float:
    mode = motion_mode()
    if mode == "static":
        return 0.0
    speed = float(((t.spec or {}).get("motion") or {}).get("speed", 0.0)) or DEFAULT_SPEED
    return speed * (0.4 if mode == "reduced" else 1.0)


def _alpha(color: str, a: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


# Perfil de calidad activo (aero.core.quality): multiplica la cantidad de cada decoración y limita el movimiento.
QUALITY: dict = {}
_Q_KEY = {"bubbles": "bubbles", "clouds": "clouds", "particles": "particles", "grass": "decor", "sun": "decor",
          "reflections": "reflections", "waves": "reflections", "stars": "decor", "nebula": "decor",
          "planet": "decor", "tropical": "decor"}


def _deco(t: Theme, key: str) -> dict:
    d = (t.spec or {}).get("deco", {}).get(key) or {}
    f = float(QUALITY.get(_Q_KEY.get(key, ""), 1.0))
    amount = float(d.get("amount", 0.5)) * f
    return {"on": bool(d.get("on")) and f > 0.001, "amount": amount, "size": float(d.get("size", 1.0))}


def _place(rnd: random.Random, layout: str, w: float, h: float, kind: str) -> tuple[float, float]:
    """Posición de un elemento según la composición elegida."""
    if kind == "clouds" and layout in ("random", "top"):
        return rnd.uniform(-0.1, 1.0) * w, rnd.uniform(0.0, 0.42) * h
    if layout == "bottom":
        return rnd.uniform(0, 1) * w, rnd.uniform(0.5, 1.0) * h
    if layout == "top":
        return rnd.uniform(0, 1) * w, rnd.uniform(0.0, 0.5) * h
    if layout == "edges":
        side = rnd.randrange(4)
        u = rnd.uniform(0, 1)
        e = rnd.uniform(0.0, 0.14)
        return [(e * w, u * h), ((1 - e) * w, u * h), (u * w, e * h), (u * w, (1 - e) * h)][side]
    return rnd.uniform(0.02, 0.98) * w, rnd.uniform(0.05, 0.98) * h


# ---------------------------------------------------------------------------------------------- piezas
def paint_cloud(p: QPainter, cx: float, cy: float, cw: float, color: QColor, alpha: float, seed: int) -> None:
    """Nube suave hecha de varios lóbulos con degradado radial (sin bordes duros)."""
    rnd = random.Random(seed)
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(7):
        ox, oy = rnd.uniform(-0.42, 0.42) * cw, rnd.uniform(-0.12, 0.10) * cw
        r = rnd.uniform(0.18, 0.32) * cw
        g = QRadialGradient(QPointF(cx + ox, cy + oy), r)
        g.setColorAt(0, _alpha(color.name(), alpha))
        g.setColorAt(0.6, _alpha(color.name(), alpha * 0.55))
        g.setColorAt(1, _alpha(color.name(), 0.0))
        p.setBrush(g)
        p.drawEllipse(QPointF(cx + ox, cy + oy), r, r)


def paint_star(p: QPainter, c: QPointF, r: float, color: str, a: float) -> None:
    """Estrella brillante con destello en cruz (las que titilan en el fondo animado)."""
    paint_particle(p, c, r * 1.4, color, 0.45 * a)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_alpha("#ffffff", a))
    p.drawEllipse(c, r * 0.7, r * 0.7)
    ln = r * 8
    for ax, ay, bx, by in ((c.x() - ln, c.y(), c.x() + ln, c.y()), (c.x(), c.y() - ln, c.x(), c.y() + ln)):
        g = QLinearGradient(ax, ay, bx, by)
        g.setColorAt(0, _alpha(color, 0.0))
        g.setColorAt(0.5, _alpha(color, 0.7 * a))
        g.setColorAt(1, _alpha(color, 0.0))
        p.setPen(QPen(g, max(0.6, r * 0.35)))
        p.drawLine(QPointF(ax, ay), QPointF(bx, by))
    p.setPen(Qt.PenStyle.NoPen)


def paint_particle(p: QPainter, c: QPointF, r: float, color: str, a: float) -> None:
    g = QRadialGradient(c, r * 3)
    g.setColorAt(0, _alpha("#ffffff", a))
    g.setColorAt(0.25, _alpha(color, a * 0.8))
    g.setColorAt(1, _alpha(color, 0.0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(c, r * 3, r * 3)


def _grass(p: QPainter, t: Theme, w: int, h: int, d: dict) -> None:
    rnd = random.Random(7)
    base = _mix(t.accent, "#46b84a", 0.6)
    dark = _mix(base, "#0b2a12", 0.55)
    hill = QPainterPath()
    hill.moveTo(0, h)
    hill.lineTo(0, h * 0.86)
    hill.cubicTo(w * 0.3, h * 0.78, w * 0.65, h * 0.92, w, h * 0.82)
    hill.lineTo(w, h)
    hill.closeSubpath()
    hg = QLinearGradient(0, h * 0.78, 0, h)
    hg.setColorAt(0, _alpha(base, 0.55))
    hg.setColorAt(1, _alpha(dark, 0.75))
    p.fillPath(hill, hg)
    n = int((60 + d["amount"] * 260) * max(0.4, w / 900))
    for _ in range(n):
        x = rnd.uniform(-0.02, 1.02) * w
        ground = h * (0.84 + 0.06 * math.sin(x / w * math.pi * 2.2)) + rnd.uniform(0, h * 0.12)
        bh = rnd.uniform(0.05, 0.16) * h * d["size"]
        lean = rnd.uniform(-0.35, 0.35) * bh
        path = QPainterPath()
        path.moveTo(x - 1.6, ground)
        path.quadTo(x + lean * 0.3, ground - bh * 0.6, x + lean, ground - bh)
        path.quadTo(x + lean * 0.3 + 1.2, ground - bh * 0.55, x + 1.6, ground)
        path.closeSubpath()
        g = QLinearGradient(0, ground - bh, 0, ground)
        g.setColorAt(0, _alpha(_mix(base, "#eaffb0", 0.35), 0.85))
        g.setColorAt(1, _alpha(dark, 0.9))
        p.fillPath(path, g)


def _reflections(p: QPainter, t: Theme, w: int, h: int, d: dict) -> None:
    hl = (t.spec or {}).get("highlight", "#ffffff")
    a = d["amount"]
    for i in range(3):
        band = QPainterPath()
        x0 = w * (0.15 + i * 0.28)
        band.moveTo(x0, 0)
        band.lineTo(x0 + w * 0.10 * d["size"], 0)
        band.lineTo(x0 - w * 0.12, h)
        band.lineTo(x0 - w * 0.20 - w * 0.06 * d["size"], h)
        band.closeSubpath()
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, _alpha(hl, 0.10 * a))
        g.setColorAt(1, _alpha(hl, 0.0))
        p.fillPath(band, g)
    # Cáusticas: líneas finas onduladas como luz sobre agua.
    rnd = random.Random(5)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for _ in range(int(4 + a * 10)):
        y = h * rnd.uniform(0.55, 0.98)
        path = QPainterPath()
        path.moveTo(0, y)
        amp, freq, ph = h * 0.01 * d["size"], rnd.uniform(4, 9), rnd.uniform(0, 6)
        for i in range(1, 49):
            x = w * i / 48
            path.lineTo(x, y + math.sin(i / 48 * freq + ph) * amp)
        p.setPen(QPen(_alpha(hl, rnd.uniform(0.05, 0.16) * a), max(1.0, h * 0.002)))
        p.drawPath(path)


def _waves(p: QPainter, t: Theme, w: int, h: int, d: dict) -> None:
    n = 1 + int(round(d["amount"] * 3))
    hl = (t.spec or {}).get("highlight", "#ffffff")
    for k in range(n):
        dy = k * 0.07 * h * d["size"]
        path = QPainterPath()
        path.moveTo(-0.1 * w, 0.70 * h + dy)
        path.cubicTo(0.25 * w, 0.46 * h + dy, 0.6 * w, 0.86 * h + dy, 1.1 * w, 0.40 * h + dy)
        path.lineTo(1.1 * w, 0.40 * h + dy + 0.06 * h * d["size"])
        path.cubicTo(0.62 * w, 0.95 * h + dy, 0.22 * w, 0.58 * h + dy, -0.1 * w, 0.80 * h + dy)
        path.closeSubpath()
        sg = QLinearGradient(0, 0.4 * h, 0, h)
        sg.setColorAt(0, _alpha(hl, (0.12 if t.dark else 0.3) * (1 - k * 0.22)))
        sg.setColorAt(1, _alpha(hl, 0.0))
        p.fillPath(path, sg)


def _stars(p: QPainter, t: Theme, w: int, h: int, d: dict) -> None:
    """Campo de estrellas: muchos puntos tenues y unas pocas estrellas brillantes con destello en cruz."""
    rnd = random.Random(21)
    hl = (t.spec or {}).get("highlight", "#ffffff")
    n = int((80 + d["amount"] * 520) * max(0.35, w * h / (900 * 560)))
    unit = max(0.6, max(w, h) / 1400) * d["size"]
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(n):
        x, y = rnd.uniform(0, w), rnd.uniform(0, h)
        bright = rnd.random() ** 3  # la mayoría son tenues
        col = (hl, t.accent, t.accent2, "#ffffff", "#ffe9c4")[rnd.randrange(5)] if bright > 0.3 else hl
        r = (0.35 + bright * 1.1) * unit
        p.setBrush(_alpha(col, 0.25 + 0.75 * bright))
        p.drawEllipse(QPointF(x, y), r, r)
        if bright > 0.72:
            paint_particle(p, QPointF(x, y), r * 1.6, col, 0.35 * bright)
            ln = r * (6 + 10 * bright)
            for ax, ay, bx, by in ((x - ln, y, x + ln, y), (x, y - ln, x, y + ln)):
                g = QLinearGradient(ax, ay, bx, by)
                g.setColorAt(0, _alpha(col, 0.0))
                g.setColorAt(0.5, _alpha(col, 0.55 * bright))
                g.setColorAt(1, _alpha(col, 0.0))
                p.setPen(QPen(g, max(0.6, r * 0.45)))
                p.drawLine(QPointF(ax, ay), QPointF(bx, by))
            p.setPen(Qt.PenStyle.NoPen)


def _nebula(p: QPainter, t: Theme, w: int, h: int, d: dict) -> None:
    """Nubes de gas de colores (acentos del tema) superpuestas y muy suaves, con polvo oscuro."""
    rnd = random.Random(33)
    big = max(w, h)
    cols = (t.accent, t.accent2, _mix(t.accent, t.accent2), _mix(t.accent2, "#ff6fa8", 0.4))
    cx0, cy0 = w * rnd.uniform(0.35, 0.65), h * rnd.uniform(0.3, 0.6)
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(int(6 + d["amount"] * 14)):
        ang = rnd.uniform(0, math.tau)
        dist = rnd.uniform(0.0, 0.42) * big
        x, y = cx0 + math.cos(ang) * dist * 1.2, cy0 + math.sin(ang) * dist * 0.55
        r = rnd.uniform(0.10, 0.28) * big * d["size"]
        a = rnd.uniform(0.06, 0.16) * (0.5 + d["amount"])
        c = cols[i % len(cols)]
        g = QRadialGradient(QPointF(x, y), r)
        g.setColorAt(0, _alpha(c, a))
        g.setColorAt(0.5, _alpha(c, a * 0.45))
        g.setColorAt(1, _alpha(c, 0.0))
        p.setBrush(g)
        p.drawEllipse(QPointF(x, y), r, r)
    for _ in range(int(2 + d["amount"] * 4)):  # polvo oscuro, apartado del centro brillante
        ang = rnd.uniform(0, math.tau)
        x, y = cx0 + math.cos(ang) * rnd.uniform(0.18, 0.4) * w, cy0 + math.sin(ang) * rnd.uniform(0.12, 0.3) * h
        r = rnd.uniform(0.04, 0.09) * big * d["size"]
        g = QRadialGradient(QPointF(x, y), r)
        g.setColorAt(0, _alpha("#000000", 0.12 * d["amount"]))
        g.setColorAt(1, _alpha("#000000", 0.0))
        p.setBrush(g)
        p.drawEllipse(QPointF(x, y), r, r)


def _planet(p: QPainter, t: Theme, w: int, h: int, d: dict) -> None:
    """Planeta con atmósfera luminosa, bandas y anillo, en una esquina según la composición."""
    spec = t.spec or {}
    layout = spec.get("layout", "random")
    r = max(w, h) * (0.10 + 0.10 * d["amount"]) * d["size"]
    c = {"bottom": QPointF(w * 0.78, h - r * 0.35), "top": QPointF(w * 0.82, r * 0.55),
         "edges": QPointF(w - r * 0.7, h - r * 0.55)}.get(layout, QPointF(w * 0.84, h * 0.80))
    hl = spec.get("highlight", "#ffffff")
    p.setPen(Qt.PenStyle.NoPen)
    halo = QRadialGradient(c, r * 1.35)
    halo.setColorAt(0.70, _alpha(t.accent, 0.0))
    halo.setColorAt(0.76, _alpha(t.accent, 0.35))
    halo.setColorAt(1.0, _alpha(t.accent, 0.0))
    p.setBrush(halo)
    p.drawEllipse(c, r * 1.35, r * 1.35)
    ring = QPainterPath()
    ring.addEllipse(QPointF(0, 0), r * 1.9, r * 0.42)
    hole = QPainterPath()
    hole.addEllipse(QPointF(0, 0), r * 1.45, r * 0.28)
    ring = ring.subtracted(hole)
    rg = QLinearGradient(-r * 1.9, 0, r * 1.9, 0)
    rg.setColorAt(0, _alpha(t.accent2, 0.05))
    rg.setColorAt(0.5, _alpha(t.accent2, 0.38))
    rg.setColorAt(1, _alpha(t.accent2, 0.05))

    def ring_half(front: bool) -> None:
        half = QPainterPath()
        half.addRect(QRectF(-r * 2, 0 if front else -r, r * 4, r))
        p.save()
        p.translate(c)
        p.rotate(-18)
        p.fillPath(ring.intersected(half), rg)
        p.restore()

    ring_half(False)  # la mitad trasera del anillo queda detrás del planeta
    body = QRadialGradient(QPointF(c.x() - r * 0.45, c.y() - r * 0.45), r * 1.6)
    body.setColorAt(0, QColor(_mix(t.accent, "#ffffff", 0.35)))
    body.setColorAt(0.45, QColor(_mix(t.accent, t.bg[1][1], 0.45)))
    body.setColorAt(1, QColor(_mix(t.bg[0][1], "#000000", 0.6)))
    p.setBrush(body)
    p.drawEllipse(c, r, r)
    clip = QPainterPath()
    clip.addEllipse(c, r, r)
    box = QRectF(c.x() - r, c.y() - r, r * 2, r * 2)
    p.save()
    p.setClipPath(clip)
    rnd = random.Random(9)
    for _ in range(5):
        y = c.y() + rnd.uniform(-0.8, 0.8) * r
        band = QLinearGradient(0, y - r * 0.08, 0, y + r * 0.08)
        band.setColorAt(0, _alpha(t.accent2, 0.0))
        band.setColorAt(0.5, _alpha(t.accent2, 0.14))
        band.setColorAt(1, _alpha(t.accent2, 0.0))
        p.fillRect(QRectF(c.x() - r, y - r * 0.08, r * 2, r * 0.16), band)
    shade = QRadialGradient(QPointF(c.x() + r * 0.6, c.y() + r * 0.6), r * 1.5)
    shade.setColorAt(0, _alpha("#000000", 0.55))
    shade.setColorAt(1, _alpha("#000000", 0.0))
    p.fillRect(box, shade)
    shine = QRadialGradient(QPointF(c.x() - r * 0.4, c.y() - r * 0.5), r * 0.5)
    shine.setColorAt(0, _alpha(hl, 0.35))
    shine.setColorAt(1, _alpha(hl, 0.0))
    p.fillRect(box, shine)
    p.restore()
    ring_half(True)


def _palm_leaf(p: QPainter, base: QPointF, angle: float, length: float, color: QColor, rnd: random.Random) -> None:
    """Hoja de palmera: nervio curvo y foliolos afilados a ambos lados, con degradado (vectorial, sin imágenes)."""
    p.save()
    p.translate(base)
    p.rotate(angle)
    droop = length * 0.28
    spine = QPainterPath()
    spine.moveTo(0, 0)
    spine.quadTo(length * 0.5, -droop * 0.6, length, droop)
    n = 22
    for i in range(1, n):
        t = i / n
        pt = spine.pointAtPercent(t)
        ang = spine.angleAtPercent(t)
        size = length * 0.32 * math.sin(math.pi * min(1.0, t * 1.15)) * (1 - t * 0.35)
        for side in (-1, 1):
            leaf = QPainterPath()
            a = math.radians(-ang + side * (62 + rnd.uniform(-6, 6)))
            tip = QPointF(pt.x() + math.cos(a) * size, pt.y() + math.sin(a) * size + size * 0.25)
            w = max(1.5, size * 0.11)
            leaf.moveTo(pt)
            ctrl1 = QPointF((pt.x() + tip.x()) / 2 - math.sin(a) * w, (pt.y() + tip.y()) / 2 + math.cos(a) * w)
            ctrl2 = QPointF((pt.x() + tip.x()) / 2 + math.sin(a) * w, (pt.y() + tip.y()) / 2 - math.cos(a) * w)
            leaf.quadTo(ctrl1, tip)
            leaf.quadTo(ctrl2, pt)
            g = QLinearGradient(pt, tip)
            c1, c2 = QColor(color), QColor(color)
            c1.setAlphaF(color.alphaF())
            c2 = c2.lighter(125)
            c2.setAlphaF(color.alphaF() * 0.85)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.fillPath(leaf, g)
    pen = QPen(color.darker(130), max(1.0, length * 0.012))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.strokePath(spine, pen)
    p.restore()


def _tropical(p: QPainter, t: Theme, w: int, h: int, d: dict) -> None:
    """Playa tropical: horizonte con mar, reflejos del sol, orilla de arena y palmeras en las esquinas."""
    spec = t.spec or {}
    hl = spec.get("highlight", "#ffffff")
    amt, big = d["amount"], max(w, h)
    horizon = h * 0.58
    # Mar: degradado turquesa hacia el horizonte, con brillo del sol
    sea = QLinearGradient(0, horizon, 0, h)
    sea.setColorAt(0, _alpha(_mix(t.accent, "#ffffff", 0.25), 0.55 * amt + 0.15))
    sea.setColorAt(0.55, _alpha(t.accent, 0.55 * amt + 0.2))
    sea.setColorAt(1, _alpha(_mix(t.accent, t.bg[0][1], 0.5), 0.7 * amt + 0.2))
    p.fillRect(QRectF(0, horizon, w, h - horizon), sea)
    sun_x = w * 0.62
    glow = QRadialGradient(QPointF(sun_x, horizon), big * 0.22)
    glow.setColorAt(0, _alpha("#fff6d6", 0.55 * amt + 0.2))
    glow.setColorAt(1, _alpha("#fff6d6", 0.0))
    p.fillRect(QRectF(0, 0, w, h), glow)
    rnd = random.Random(41)
    p.setPen(Qt.PenStyle.NoPen)
    for _i in range(int(18 + 30 * amt)):  # destellos del sol sobre el agua
        y = horizon + (h - horizon) * (rnd.random() ** 1.6) * 0.5
        spread = (y - horizon) / max(1.0, h - horizon) * w * 0.35 + w * 0.03
        x = sun_x + rnd.uniform(-spread, spread)
        ln = rnd.uniform(0.01, 0.04) * w
        p.setBrush(_alpha(hl, rnd.uniform(0.25, 0.6) * amt))
        p.drawRoundedRect(QRectF(x - ln / 2, y, ln, max(1.0, h * 0.003)), 1, 1)
    # Olas suaves y orilla de arena con espuma
    sand_top = h * 0.84
    shore = QPainterPath()
    shore.moveTo(0, h)
    shore.lineTo(0, sand_top + h * 0.03)
    shore.cubicTo(w * 0.3, sand_top - h * 0.03, w * 0.65, sand_top + h * 0.06, w, sand_top - h * 0.01)
    shore.lineTo(w, h)
    shore.closeSubpath()
    sand = QLinearGradient(0, sand_top - h * 0.03, 0, h)
    sand.setColorAt(0, _alpha("#f6e6c4", 0.85))
    sand.setColorAt(1, _alpha("#e3c48f", 0.9))
    p.fillPath(shore, sand)
    foam = QPen(_alpha("#ffffff", 0.7), max(1.5, h * 0.006))
    foam.setCapStyle(Qt.PenCapStyle.RoundCap)
    edge = QPainterPath()
    edge.moveTo(0, sand_top + h * 0.03)
    edge.cubicTo(w * 0.3, sand_top - h * 0.03, w * 0.65, sand_top + h * 0.06, w, sand_top - h * 0.01)
    p.strokePath(edge, foam)
    # Palmeras: tronco curvo con anillos y un abanico de hojas
    leaf = QColor(_mix("#1f8a4c", t.accent2, 0.25))
    leaf.setAlphaF(0.92)
    for side in (-1, 1) if d["size"] >= 0.5 else (1,):
        rnd2 = random.Random(7 if side < 0 else 13)
        root = QPointF(w * (0.06 if side < 0 else 0.94), h * 1.02)
        top = QPointF(root.x() + side * -w * 0.06 * d["size"], h * (0.30 if side > 0 else 0.38))
        trunk = QPainterPath()
        trunk.moveTo(root)
        trunk.quadTo(QPointF(root.x() - side * w * 0.07, (root.y() + top.y()) / 2), top)
        width = big * 0.018 * d["size"]
        tp = QPen(_alpha("#7a5532", 0.95), width)
        tp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.strokePath(trunk, tp)
        ring = QPen(_alpha("#5b3e22", 0.55), max(1.0, width * 0.18))
        p.setPen(ring)
        for k in range(1, 14):
            pt = trunk.pointAtPercent(k / 14)
            p.drawLine(QPointF(pt.x() - width * 0.45, pt.y()), QPointF(pt.x() + width * 0.45, pt.y() + width * 0.15))
        p.setPen(Qt.PenStyle.NoPen)
        length = big * 0.17 * d["size"]
        for a in (-150, -115, -80, -45, -10, 25, 200, 165):
            _palm_leaf(p, top, a + rnd2.uniform(-8, 8), length * rnd2.uniform(0.8, 1.05), leaf, rnd2)
        coco = QRadialGradient(QPointF(top.x() - width * 0.2, top.y() + width * 0.6), width * 0.9)
        coco.setColorAt(0, _alpha("#8b6a3c", 1.0))
        coco.setColorAt(1, _alpha("#4a3418", 1.0))
        p.setBrush(coco)
        for dx in (-0.6, 0.5, 0.0):
            p.drawEllipse(QPointF(top.x() + dx * width, top.y() + width * 0.7), width * 0.55, width * 0.55)


def render_tint(t: Theme, w: int, h: int) -> QImage:
    """Capa de color: degradado, luces de color e imagen de fondo propia."""
    img = QImage(max(1, w), max(1, h), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    g = QLinearGradient(0, 0, w * 0.6, h)
    for pos, col in t.bg:
        g.setColorAt(pos, QColor(col))
    p.fillRect(0, 0, w, h, g)
    path = (t.spec or {}).get("image") or ""
    if path:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        src = reader.read()
        if not src.isNull():
            src = src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                             Qt.TransformationMode.SmoothTransformation)
            p.setOpacity(float((t.spec or {}).get("image_opacity", 0.55)))
            p.drawImage(QRectF((w - src.width()) / 2, (h - src.height()) / 2, src.width(), src.height()), src)
            p.setOpacity(1.0)
    big = max(w, h)
    for col, x, y, r in t.orbs:
        rg = QRadialGradient(QPointF(x * w, y * h), r * big)
        rg.setColorAt(0, _alpha(col, 0.35 * float((t.spec or {}).get("orb", 1.0))))
        rg.setColorAt(1, _alpha(col, 0.0))
        p.fillRect(0, 0, w, h, rg)
    p.end()
    return img


def render_accents(t: Theme, w: int, h: int, skip_moving: bool, static: list | None = None,
                   scale: float = 1.0) -> QImage:
    """Capa de luz y decoración fija. Con movimiento, solo se hornean aquí los elementos que no se mueven
    (`static`, en coordenadas de ventana multiplicadas por `scale`); los móviles van en sprites."""
    img = QImage(max(1, w), max(1, h), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    spec = t.spec or {}
    hl = spec.get("highlight", "#ffffff")
    big = max(w, h)
    sun = _deco(t, "sun")
    if sun["on"]:
        glow = QRadialGradient(QPointF(w * 0.08, -h * 0.1), big * 0.45 * sun["size"])
        glow.setColorAt(0, _alpha(hl, (0.22 if t.dark else 0.5) * (0.4 + sun["amount"])))
        glow.setColorAt(1, _alpha(hl, 0.0))
        p.fillRect(0, 0, w, h, glow)
    for key, fn in (("stars", _stars), ("nebula", _nebula), ("reflections", _reflections), ("waves", _waves),
                    ("planet", _planet), ("tropical", _tropical)):
        d = _deco(t, key)
        if d["on"]:
            fn(p, t, w, h, d)
    if not skip_moving:
        for sp in build_sprites(t, w, h, scale=1.0):
            sp.paint(p)
    elif static:
        p.save()
        p.scale(scale, scale)
        for sp in static:
            sp.paint(p, t)
        p.restore()
    grass = _deco(t, "grass")
    if grass["on"]:
        _grass(p, t, w, h, grass)
    p.end()
    return img


# ---------------------------------------------------------------------------------------------- sprites
class Sprite:
    __slots__ = ("kind", "x", "y", "r", "phase", "pix", "speed", "seed", "alpha", "glow")

    def __init__(self, kind, x, y, r, seed, speed, alpha=1.0):
        self.kind, self.x, self.y, self.r, self.seed, self.speed, self.alpha = kind, x, y, r, seed, speed, alpha
        self.phase = (seed % 100) / 100 * math.tau
        self.glow = 1.0          # brillo actual de las estrellas que titilan
        self.pix: QPixmap | None = None

    def extent(self) -> float:
        return self.r * {"bubbles": 1.0, "particles": 3.0, "stars": 9.0}.get(self.kind, 0.9)

    def rect(self) -> QRect:
        e = self.extent() + 2
        return QRect(int(self.x - e), int(self.y - e), int(e * 2) + 2, int(e * 2) + 2)

    def paint(self, p: QPainter, theme: Theme | None = None) -> None:
        if self.pix is not None:
            e = self.extent()
            if self.kind == "stars":
                p.save()
                p.setOpacity(p.opacity() * self.glow)
            p.drawPixmap(QRectF(self.x - e, self.y - e, e * 2, e * 2), self.pix, QRectF(self.pix.rect()))
            if self.kind == "stars":
                p.restore()
            return
        from aero.ui.glass import paint_bubble, tm

        t = theme or tm().theme
        if self.kind == "bubbles":
            paint_bubble(p, QPointF(self.x, self.y), self.r, QColor(t.accent), fill=0.05, rim=self.alpha)
        elif self.kind == "particles":
            paint_particle(p, QPointF(self.x, self.y), self.r, t.accent2 if self.seed % 2 else t.accent,
                           0.55 * self.alpha)
        elif self.kind == "stars":
            paint_star(p, QPointF(self.x, self.y), self.r, (t.spec or {}).get("highlight", "#ffffff"),
                       self.alpha * (self.glow if self.pix is None else 1.0))
        else:
            paint_cloud(p, self.x, self.y, self.r * 2, QColor("#ffffff"), (0.16 if t.dark else 0.55) * self.alpha,
                        self.seed)

    def bake(self, theme: Theme, dpr: float = 1.0) -> None:
        """Prerrenderiza el elemento una vez para dibujarlo barato en cada fotograma."""
        e = self.extent()
        size = max(2, int(math.ceil(e * 2 * dpr)))
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(dpr, dpr)
        x, y = self.x, self.y
        self.x, self.y = e, e
        self.pix = None
        self.paint(p, theme)
        self.x, self.y = x, y
        p.end()
        pm = QPixmap.fromImage(img)
        self.pix = pm


def build_sprites(t: Theme, w: int, h: int, scale: float = 1.0) -> list[Sprite]:
    """Lista determinista de elementos móviles según el tema (mismo resultado en cada reconstrucción)."""
    spec = t.spec or {}
    layout = spec.get("layout", "random")
    big = max(w, h)
    out: list[Sprite] = []
    rnd = random.Random(11)
    b = _deco(t, "bubbles")
    if b["on"]:
        for i in range(int(3 + b["amount"] * 30)):
            x, y = _place(rnd, layout, w, h, "bubbles")
            r = rnd.uniform(0.010, 0.042) * big * b["size"]
            out.append(Sprite("bubbles", x, y, r, i, rnd.uniform(0.6, 1.4), rnd.uniform(0.45, 0.85)))
    pa = _deco(t, "particles")
    if pa["on"]:
        for i in range(int(8 + pa["amount"] * 70)):
            x, y = _place(rnd, layout, w, h, "particles")
            r = rnd.uniform(0.0016, 0.0042) * big * pa["size"]
            out.append(Sprite("particles", x, y, r, 100 + i, rnd.uniform(0.5, 1.6), rnd.uniform(0.5, 1.0)))
    s = _deco(t, "stars")
    if s["on"]:
        # Unas pocas estrellas brillantes que titilan (las demás del campo de estrellas son fijas)
        srnd = random.Random(29)
        for i in range(int(4 + s["amount"] * 10)):
            x, y = srnd.uniform(0.03, 0.97) * w, srnd.uniform(0.03, 0.97) * h
            r = srnd.uniform(0.0011, 0.0022) * big * s["size"]
            out.append(Sprite("stars", x, y, r, 500 + i, srnd.uniform(0.5, 1.4), srnd.uniform(0.7, 1.0)))
    c = _deco(t, "clouds")
    if c["on"]:
        for i in range(int(2 + c["amount"] * 7)):
            x, y = _place(rnd, layout, w, h, "clouds")
            r = rnd.uniform(0.07, 0.14) * big * c["size"]
            out.append(Sprite("clouds", x, y, r, 300 + i, rnd.uniform(0.3, 0.7), rnd.uniform(0.6, 1.0)))
    return out


MAX_MOVING = 14


def split_sprites(sprites: list[Sprite]) -> tuple[list[Sprite], list[Sprite]]:
    """Solo unos pocos elementos se mueven de verdad (repartidos entre tipos); el resto queda fijo en el fondo.

    Cada fotograma obliga a recomponer la ventana transparente en la zona que cambia: con muchos elementos
    móviles esa zona acaba siendo casi toda la ventana. Con un máximo de 14 la zona es pequeña.
    """
    limit = int(QUALITY.get("max_moving", MAX_MOVING))
    if motion_mode() == "reduced":
        limit = min(limit, 6)
    if limit <= 0:
        return [], sprites
    if len(sprites) <= limit:
        return sprites, []
    step = len(sprites) / limit
    pick = {int(i * step) for i in range(limit)}
    moving = [s for i, s in enumerate(sprites) if i in pick]
    return moving, [s for i, s in enumerate(sprites) if i not in pick]


def has_motion(t: Theme) -> bool:
    if effective_speed(t) <= 0.0 or not QUALITY.get("motion", True):
        return False
    return any(_deco(t, k)["on"] for k in MOVING)


def step_sprites(sprites: list[Sprite], t: Theme, w: int, h: int, dt: float) -> None:
    """Avanza los elementos móviles. Las burbujas suben con un leve vaivén; las nubes derivan."""
    motion = (t.spec or {}).get("motion") or {}
    speed = effective_speed(t) * 60.0 * float(QUALITY.get("anim_speed", 1.0))  # px/s a velocidad 1
    d = motion.get("dir", "up")
    dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(d, (0, -1))
    for s in sprites:
        if s.kind == "stars":  # no se desplazan: cambian de brillo suavemente
            s.phase += dt * 1.6 * s.speed * (0.5 if motion_mode() == "reduced" else 1.0)
            s.glow = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(s.phase)) ** 2
            continue
        v = speed * s.speed * (0.35 if s.kind == "clouds" else 1.0)
        if s.kind == "clouds":
            cx, cy = (dx or 1) * v * dt, 0.0
        else:
            s.phase += dt * 1.3 * s.speed
            wob = math.sin(s.phase) * 12 * dt
            cx, cy = dx * v * dt + (wob if dy else 0), dy * v * dt + (wob if dx else 0)
        s.x += cx
        s.y += cy
        e = s.extent()
        if s.x < -e:
            s.x = w + e
        elif s.x > w + e:
            s.x = -e
        if s.y < -e:
            s.y = h + e
        elif s.y > h + e:
            s.y = -e
