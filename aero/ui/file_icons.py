"""Iconos de categoría de AERO Player: una familia propia, dibujada en vectorial con QPainter.

Lenguaje común: volúmenes suaves de cristal (degradado del color de la categoría, brillo superior en forma de
burbuja, reflejo de agua en la base, borde de luz y sombra ligera). Cuatro formas según el tipo:

* **Página** (documentos, hojas, presentaciones, PDF, código, desconocido): hoja de cristal con esquina doblada y
  una etiqueta de color con su símbolo.
* **Burbuja** (vídeo, audio, imagen, aplicación, acceso directo, sistema, fuente, torrent): baldosa redondeada
  con el símbolo en blanco.
* **Carpeta** (tridimensional, agua), **paquete** (comprimidos) y **disco** (imágenes de disco).

Un icono por categoría (nunca uno por extensión). Se dibujan una vez por tamaño, escala de pantalla y fondo
(claro u oscuro) y se guardan: mostrar miles de archivos solo copia imágenes ya hechas.
"""

from __future__ import annotations

import math
from collections import OrderedDict

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)

# (color claro, color profundo) de cada categoría
PALETTE = {
    "folder": ("#8fe3ff", "#1f86d6"), "video": ("#ff8aa8", "#c2306c"), "audio": ("#6ff0dc", "#0f8d9c"),
    "image": ("#9ce88a", "#279a52"), "document": ("#8cc6ff", "#2f6fd6"), "sheet": ("#83e3a2", "#1d8a52"),
    "slides": ("#ffc07a", "#e0661f"), "pdf": ("#ff8f8f", "#c62f33"), "archive": ("#ffd98a", "#c98419"),
    "app": ("#a7a8ff", "#4d47d8"), "shortcut": ("#8ee8ff", "#2a96d4"), "system": ("#c2cddb", "#5a6a80"),
    "font": ("#d6a6ff", "#7a3fd1"), "code": ("#7ff0cf", "#127a6a"), "torrent": ("#bff07a", "#3d9b25"),
    "disc": ("#eef3fb", "#8798b4"), "unknown": ("#dfe5ee", "#8a96a8"), "installer": ("#ffb0e0", "#a8338f"),
}
PAGE = {"document", "sheet", "slides", "pdf", "code", "unknown"}

_CACHE: OrderedDict[tuple, QPixmap] = OrderedDict()
_MAX = 256


def pixmap(category: str, size: int, dpr: float = 1.0, dark: bool = True, inner: QPixmap | None = None) -> QPixmap:
    """Icono de `category` de `size` píxeles lógicos. `inner`: icono real de un programa para la baldosa de
    aplicación (no se guarda en la caché común)."""
    category = category if category in PALETTE else "unknown"
    key = (category, int(size), round(dpr, 2), dark)
    if inner is None and key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    px = max(8, int(round(size * dpr)))
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.scale(px / 100.0, px / 100.0)       # se dibuja en una caja de 100 × 100
    _draw(p, category, size, dark, inner)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    if inner is None:
        _CACHE[key] = pm
        while len(_CACHE) > _MAX:
            _CACHE.popitem(last=False)
    return pm


def icon_for(path: str, size: int = 20, is_dir: bool | None = None):
    """QIcon de categoría para una ruta (búsqueda, recientes, visores). Solo mira la extensión: no lee el disco
    salvo para saber si es una carpeta cuando no se indica."""
    import os

    from PySide6.QtGui import QGuiApplication, QIcon

    from aero.core.filetypes import by_extension
    from aero.ui.glass import tm

    if is_dir is None:
        is_dir = os.path.isdir(path)
    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if app is not None else 1.0
    return QIcon(pixmap(by_extension(path, is_dir), size, dpr, tm().theme.dark))


def clear_cache() -> None:
    _CACHE.clear()


# ----------------------------------------------------------------------------- piezas comunes

def _c(hex_: str, a: float = 1.0) -> QColor:
    c = QColor(hex_)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def _shadow(p: QPainter, path: QPainterPath, small: bool):
    if small:
        return
    p.save()
    p.translate(0, 3.2)
    p.fillPath(path, _c("#001428", 0.20))
    p.restore()


def _glass(p: QPainter, path: QPainterPath, rect: QRectF, cat: str, dark: bool, small: bool):
    """Volumen de cristal: degradado, brillo de burbuja arriba, reflejo de agua abajo y borde de luz."""
    light, deep = PALETTE[cat]
    _shadow(p, path, small)
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0.0, _c(light))
    g.setColorAt(0.55, _c(QColor(light).darker(108).name()))
    g.setColorAt(1.0, _c(deep))
    p.fillPath(path, g)
    p.save()
    p.setClipPath(path)
    if not small:
        # reflejo de agua: banda clara ondulada en la base
        wave = QPainterPath()
        y = rect.bottom() - rect.height() * 0.24
        wave.moveTo(rect.left(), y)
        wave.cubicTo(rect.left() + rect.width() * 0.3, y - 6, rect.left() + rect.width() * 0.6, y + 6, rect.right(), y - 2)
        wave.lineTo(rect.right(), rect.bottom())
        wave.lineTo(rect.left(), rect.bottom())
        wave.closeSubpath()
        p.fillPath(wave, _c("#ffffff", 0.16))
        if _LARGE[0]:
            _grass(p, rect)
    # brillo de burbuja
    gl = QPainterPath()
    gl.addEllipse(QRectF(rect.left() + rect.width() * 0.06, rect.top() - rect.height() * 0.18,
                         rect.width() * 0.88, rect.height() * 0.62))
    gg = QLinearGradient(QPointF(0, rect.top()), QPointF(0, rect.top() + rect.height() * 0.45))
    gg.setColorAt(0, _c("#ffffff", 0.70 if not small else 0.45))
    gg.setColorAt(1, _c("#ffffff", 0.04))
    p.fillPath(gl, gg)
    p.restore()
    p.setPen(QPen(_c("#ffffff", 0.75 if dark else 0.95), 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.setPen(QPen(_c(QColor(deep).darker(140).name(), 0.35 if dark else 0.55), 1.0))
    p.drawPath(path.translated(0, 0.6))


def _grass(p: QPainter, rect: QRectF):
    """Unas briznas de césped translúcidas en la orilla del agua (solo en tamaños grandes)."""
    p.save()
    base = rect.bottom() - rect.height() * 0.05
    x0 = rect.left() + rect.width() * 0.08
    for i, (dx, h, lean) in enumerate(((0, 0.16, -3), (4, 0.22, 1), (8, 0.14, 4), (13, 0.19, -1), (17, 0.12, 3))):
        blade = QPainterPath()
        x = x0 + dx * rect.width() / 100
        top = base - rect.height() * h
        blade.moveTo(x - 1.6, base)
        blade.quadTo(x + lean * 0.4, (base + top) / 2, x + lean, top)
        blade.quadTo(x + lean * 0.5 + 1.2, (base + top) / 2, x + 1.8, base)
        blade.closeSubpath()
        p.fillPath(blade, _c("#d9ffc4" if i % 2 else "#b6f59a", 0.55))
    p.restore()


def _white(a: float = 1.0) -> QColor:
    return _c("#ffffff", a)


def _emblem_pen(w: float) -> QPen:
    pen = QPen(_white(0.96), w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _soft(p: QPainter, path: QPainterPath, deep: str):
    """Sombra fina debajo del símbolo (se lee mejor sobre el cristal)."""
    p.save()
    p.translate(0, 1.2)
    p.fillPath(path, _c(QColor(deep).darker(150).name(), 0.35))
    p.restore()


# ----------------------------------------------------------------------------- formas

def _bubble_rect() -> QRectF:
    return QRectF(9, 9, 82, 82)


_LARGE = [False]      # tamaño grande (≥ 64 px): se añaden detalles de naturaleza que en pequeño ensuciarían


def _draw(p: QPainter, cat: str, size: int, dark: bool, inner: QPixmap | None):
    small = size <= 24
    _LARGE[0] = size >= 64
    if cat in PAGE:
        _page(p, cat, dark, small)
    elif cat == "folder":
        _folder(p, dark, small)
    elif cat == "archive":
        _box(p, dark, small)
    elif cat == "disc":
        _disc(p, dark, small)
    else:
        r = _bubble_rect()
        path = QPainterPath()
        path.addRoundedRect(r, 24, 24)
        _glass(p, path, r, cat, dark, small)
        if cat in ("app", "shortcut") and inner is not None and not inner.isNull():
            p.drawPixmap(QRectF(24, 24, 52, 52), inner, QRectF(inner.rect()))
        else:
            _EMBLEMS[cat](p, small)


def _page(p: QPainter, cat: str, dark: bool, small: bool):
    light, deep = PALETTE[cat]
    r = QRectF(17, 6, 66, 88)
    fold = 20
    body = QPainterPath()
    body.moveTo(r.left() + 8, r.top())
    body.lineTo(r.right() - fold, r.top())
    body.lineTo(r.right(), r.top() + fold)
    body.lineTo(r.right(), r.bottom() - 8)
    body.quadTo(r.right(), r.bottom(), r.right() - 8, r.bottom())
    body.lineTo(r.left() + 8, r.bottom())
    body.quadTo(r.left(), r.bottom(), r.left(), r.bottom() - 8)
    body.lineTo(r.left(), r.top() + 8)
    body.quadTo(r.left(), r.top(), r.left() + 8, r.top())
    body.closeSubpath()
    _shadow(p, body, small)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0, _c("#ffffff", 0.98))
    g.setColorAt(1, _c(QColor(light).lighter(115).name(), 0.98))
    p.fillPath(body, g)
    # líneas de texto (solo en tamaños medianos y grandes)
    if not small and cat in ("document", "unknown", "code", "pdf"):
        pen = QPen(_c(deep, 0.28), 3.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for i, w in enumerate((36, 44, 30)):
            y = r.top() + 22 + i * 9
            p.drawLine(QPointF(r.left() + 10, y), QPointF(r.left() + 10 + w * (0.7 if i == 0 else 1), y))
    # esquina doblada
    corner = QPainterPath()
    corner.moveTo(r.right() - fold, r.top())
    corner.lineTo(r.right() - fold, r.top() + fold - 5)
    corner.quadTo(r.right() - fold, r.top() + fold, r.right() - fold + 5, r.top() + fold)
    corner.lineTo(r.right(), r.top() + fold)
    corner.closeSubpath()
    cg = QLinearGradient(QPointF(r.right() - fold, r.top()), QPointF(r.right(), r.top() + fold))
    cg.setColorAt(0, _c(light))
    cg.setColorAt(1, _c(deep))
    p.fillPath(corner, cg)
    # etiqueta de color con el símbolo de la categoría
    label = QRectF(r.left() + 6, r.bottom() - 40, r.width() - 12, 32)
    lp = QPainterPath()
    lp.addRoundedRect(label, 10, 10)
    _glass(p, lp, label, cat, dark, True)
    _PAGE_EMBLEMS[cat](p, label, small)
    p.setPen(QPen(_c(deep, 0.55 if dark else 0.7), 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(body)


def _folder(p: QPainter, dark: bool, small: bool):
    light, deep = PALETTE["folder"]
    back = QPainterPath()
    back.moveTo(8, 26)
    back.quadTo(8, 18, 16, 18)
    back.lineTo(38, 18)
    back.quadTo(43, 18, 46, 23)
    back.lineTo(49, 27)
    back.lineTo(84, 27)
    back.quadTo(92, 27, 92, 35)
    back.lineTo(92, 80)
    back.quadTo(92, 88, 84, 88)
    back.lineTo(16, 88)
    back.quadTo(8, 88, 8, 80)
    back.closeSubpath()
    _shadow(p, back, small)
    bg = QLinearGradient(QPointF(0, 18), QPointF(0, 88))
    bg.setColorAt(0, _c(QColor(deep).lighter(120).name()))
    bg.setColorAt(1, _c(QColor(deep).darker(125).name()))
    p.fillPath(back, bg)
    # hoja asomando
    if not small:
        sheet = QPainterPath()
        sheet.addRoundedRect(QRectF(17, 30, 66, 30), 4, 4)
        p.fillPath(sheet, _c("#ffffff", 0.85))
    # frente en perspectiva
    front = QPainterPath()
    front.moveTo(6, 44)
    front.quadTo(6, 38, 12, 38)
    front.lineTo(88, 38)
    front.quadTo(95, 38, 94, 45)
    front.lineTo(91, 80)
    front.quadTo(90, 88, 82, 88)
    front.lineTo(18, 88)
    front.quadTo(10, 88, 9, 80)
    front.closeSubpath()
    _glass(p, front, QRectF(6, 38, 88, 50), "folder", dark, small)


def _box(p: QPainter, dark: bool, small: bool):
    deep = PALETTE["archive"][1]
    r = QRectF(12, 18, 76, 70)
    body = QPainterPath()
    body.addRoundedRect(r, 14, 14)
    _glass(p, body, r, "archive", dark, small)
    # tapa
    lid = QPainterPath()
    lid.addRoundedRect(QRectF(8, 12, 84, 22), 9, 9)
    _glass(p, lid, QRectF(8, 12, 84, 22), "archive", dark, True)
    # cremallera central
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(QColor(deep).darker(130).name(), 0.55))
    p.drawRoundedRect(QRectF(44, 34, 12, 50), 3, 3)
    p.setBrush(_white(0.92))
    steps = 3 if small else 5
    for i in range(steps):
        y = 37 + i * (44 / steps)
        p.drawRoundedRect(QRectF(46 if i % 2 else 50, y, 4, 4), 1, 1)
    p.setBrush(_white(0.95))
    p.drawRoundedRect(QRectF(42, 74, 16, 11), 3, 3)


def _disc(p: QPainter, dark: bool, small: bool):
    light, deep = PALETTE["disc"]
    c = QPointF(50, 50)
    outer = QPainterPath()
    outer.addEllipse(c, 42, 42)
    _shadow(p, outer, small)
    g = QRadialGradient(QPointF(38, 34), 60)
    g.setColorAt(0, _c("#ffffff"))
    g.setColorAt(0.6, _c(light))
    g.setColorAt(1, _c(deep))
    p.fillPath(outer, g)
    if not small:
        # brillo irisado (agua y cristal)
        p.save()
        p.setClipPath(outer)
        for ang, col in ((-35, "#7fe0ff"), (10, "#b5f5a0"), (55, "#ffb6e1")):
            sweep = QPainterPath()
            sweep.moveTo(c)
            sweep.arcTo(QRectF(8, 8, 84, 84), ang, 26)
            sweep.closeSubpath()
            p.fillPath(sweep, _c(col, 0.38))
        p.restore()
    p.setPen(QPen(_c(deep, 0.6), 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(c, 42, 42)
    p.setPen(QPen(_c("#ffffff", 0.8), 1.0))
    p.drawEllipse(c, 22, 22)
    p.setPen(QPen(_c(deep, 0.5), 1.2))
    p.setBrush(_c("#f4f8ff"))
    p.drawEllipse(c, 12, 12)
    p.setBrush(_c("#000000", 0.0) if not dark else _c("#0b1622", 0.0))
    hole = QPainterPath()
    hole.addEllipse(c, 5.5, 5.5)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.fillPath(hole, QColor(0, 0, 0))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)


# ----------------------------------------------------------------------------- símbolos de las burbujas

def _e_video(p, small):
    deep = PALETTE["video"][1]
    frame = QPainterPath()
    frame.addRoundedRect(QRectF(25, 31, 50, 38), 8, 8)
    tri = QPainterPath()
    tri.moveTo(44, 40)
    tri.lineTo(60, 50)
    tri.lineTo(44, 60)
    tri.closeSubpath()
    _soft(p, frame, deep)
    p.setPen(_emblem_pen(5 if small else 4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(frame)
    if not small:
        for x in (25, 75):
            for y in (38, 50, 62):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_white(0.9))
                p.drawEllipse(QPointF(x + (5 if x == 25 else -5), y), 1.8, 1.8)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white())
    p.drawPath(tri)


def _e_audio(p, small):
    deep = PALETTE["audio"][1]
    note = QPainterPath()
    note.addEllipse(QRectF(28, 56, 18, 14))
    note.addEllipse(QRectF(54, 50, 18, 14))
    _soft(p, note, deep)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white())
    p.drawPath(note)
    p.setPen(_emblem_pen(5 if small else 4.4))
    p.drawLine(QPointF(44, 62), QPointF(44, 30))
    p.drawLine(QPointF(70, 56), QPointF(70, 25))
    p.drawLine(QPointF(44, 31), QPointF(70, 25))
    if not small:
        p.setPen(_emblem_pen(2.4))
        wave = QPainterPath()
        wave.moveTo(20, 80)
        for i in range(6):
            wave.quadTo(20 + i * 10 + 5, 75 if i % 2 else 85, 30 + i * 10, 80)
        p.drawPath(wave)


def _e_image(p, small):
    deep = PALETTE["image"][1]
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c("#fff6c2"))
    p.drawEllipse(QPointF(64, 36), 8, 8)
    mount = QPainterPath()
    mount.moveTo(20, 72)
    mount.lineTo(40, 46)
    mount.lineTo(52, 60)
    mount.lineTo(60, 52)
    mount.lineTo(80, 72)
    mount.closeSubpath()
    _soft(p, mount, deep)
    p.setBrush(_white())
    p.drawPath(mount)
    if not small:   # agua
        p.setPen(_emblem_pen(2.6))
        p.drawLine(QPointF(26, 79), QPointF(46, 79))
        p.drawLine(QPointF(52, 79), QPointF(74, 79))


def _e_app(p, small):
    deep = PALETTE["app"][1]
    win = QPainterPath()
    win.addRoundedRect(QRectF(24, 28, 52, 44), 7, 7)
    _soft(p, win, deep)
    p.setPen(_emblem_pen(4.4 if small else 3.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(win)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white())
    p.drawRoundedRect(QRectF(24, 28, 52, 11), 6, 6)
    if not small:
        p.setBrush(_white(0.75))
        p.drawRoundedRect(QRectF(31, 46, 16, 19), 3, 3)
        p.drawRoundedRect(QRectF(51, 46, 18, 8), 3, 3)
        p.drawRoundedRect(QRectF(51, 57, 18, 8), 3, 3)


def _e_shortcut(p, small):
    deep = PALETTE["shortcut"][1]
    arrow = QPainterPath()
    arrow.moveTo(30, 70)
    arrow.cubicTo(30, 48, 42, 40, 60, 40)
    _soft(p, arrow, deep)
    p.setPen(_emblem_pen(7 if small else 6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(arrow)
    head = QPainterPath()
    head.moveTo(56, 27)
    head.lineTo(74, 40)
    head.lineTo(56, 53)
    head.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white())
    p.drawPath(head)


def _e_system(p, small):
    deep = PALETTE["system"][1]
    gear = QPainterPath()
    c = QPointF(50, 50)
    teeth = 8
    for i in range(teeth * 2):
        a = math.pi * 2 * i / (teeth * 2)
        rr = 26 if i % 2 == 0 else 20
        pt = QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a))
        gear.moveTo(pt) if i == 0 else gear.lineTo(pt)
    gear.closeSubpath()
    hole = QPainterPath()
    hole.addEllipse(c, 8.5, 8.5)
    gear = gear.subtracted(hole)
    _soft(p, gear, deep)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white())
    p.drawPath(gear)


def _e_font(p, small):
    deep = PALETTE["font"][1]
    f = QFont("Segoe UI", 1)
    f.setPixelSize(40 if not small else 46)
    f.setBold(True)
    path = QPainterPath()
    path.addText(QPointF(22 if not small else 20, 66 if not small else 68), f, "Aa")
    _soft(p, path, deep)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white())
    p.drawPath(path)


def _e_torrent(p, small):
    deep = PALETTE["torrent"][1]
    down = QPainterPath()
    down.moveTo(38, 26)
    down.lineTo(38, 58)
    up = QPainterPath()
    up.moveTo(62, 74)
    up.lineTo(62, 42)
    _soft(p, down, deep)
    p.setPen(_emblem_pen(7 if small else 6))
    p.drawPath(down)
    p.drawPath(up)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white())
    a = QPainterPath()
    a.moveTo(26, 54)
    a.lineTo(50, 54)
    a.lineTo(38, 70)
    a.closeSubpath()
    b = QPainterPath()
    b.moveTo(50, 46)
    b.lineTo(74, 46)
    b.lineTo(62, 30)
    b.closeSubpath()
    p.drawPath(a)
    p.drawPath(b)


def _e_installer(p, small):
    deep = PALETTE["installer"][1]
    box = QPainterPath()
    box.moveTo(26, 50)
    box.lineTo(26, 74)
    box.quadTo(26, 78, 30, 78)
    box.lineTo(70, 78)
    box.quadTo(74, 78, 74, 74)
    box.lineTo(74, 50)
    _soft(p, box, deep)
    p.setPen(_emblem_pen(6 if small else 5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(box)
    p.drawLine(QPointF(50, 22), QPointF(50, 52))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white())
    head = QPainterPath()
    head.moveTo(37, 46)
    head.lineTo(63, 46)
    head.lineTo(50, 62)
    head.closeSubpath()
    p.drawPath(head)


_EMBLEMS = {"installer": _e_installer, "video": _e_video, "audio": _e_audio, "image": _e_image, "app": _e_app, "shortcut": _e_shortcut,
            "system": _e_system, "font": _e_font, "torrent": _e_torrent}


# ----------------------------------------------------------------------------- símbolos de las páginas

def _label_text(p, r: QRectF, text: str, size: float):
    f = QFont("Segoe UI", 1)
    f.setPixelSize(int(size))
    f.setBold(True)
    p.setFont(f)
    p.setPen(_white())
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)


def _p_document(p, r, small):
    p.setPen(_emblem_pen(3.4))
    for i, w in enumerate((0.62, 0.45)):
        y = r.top() + 11 + i * 10
        p.drawLine(QPointF(r.left() + 9, y), QPointF(r.left() + 9 + r.width() * w, y))


def _p_sheet(p, r, small):
    pen = QPen(_white(0.95), 2.4)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    g = QRectF(r.left() + 10, r.top() + 6, r.width() - 20, r.height() - 12)
    p.drawRoundedRect(g, 3, 3)
    p.drawLine(QPointF(g.left(), g.center().y()), QPointF(g.right(), g.center().y()))
    for k in (1 / 3, 2 / 3):
        x = g.left() + g.width() * k
        p.drawLine(QPointF(x, g.top()), QPointF(x, g.bottom()))


def _p_slides(p, r, small):
    p.setPen(_emblem_pen(2.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    scr = QRectF(r.left() + 12, r.top() + 6, r.width() - 24, r.height() - 14)
    p.drawRoundedRect(scr, 3, 3)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white())
    tri = QPainterPath()
    tri.moveTo(scr.center().x() - 5, scr.center().y() - 6)
    tri.lineTo(scr.center().x() + 7, scr.center().y())
    tri.lineTo(scr.center().x() - 5, scr.center().y() + 6)
    tri.closeSubpath()
    p.drawPath(tri)


def _p_pdf(p, r, small):
    _label_text(p, r, "PDF", 20 if not small else 24)


def _p_code(p, r, small):
    _label_text(p, r, "</>", 20 if not small else 24)


def _p_unknown(p, r, small):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white(0.95))
    for i in range(3):
        p.drawEllipse(QPointF(r.center().x() + (i - 1) * 12, r.center().y()), 3.4, 3.4)


_PAGE_EMBLEMS = {"document": _p_document, "sheet": _p_sheet, "slides": _p_slides, "pdf": _p_pdf, "code": _p_code,
                 "unknown": _p_unknown}
