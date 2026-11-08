"""Componentes visuales base: fondo Aero, paneles de cristal, transiciones, avisos y controles."""

from __future__ import annotations

import math
import time
import weakref

from PySide6.QtCore import (QEvent, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal, QObject)
from PySide6.QtGui import (QBrush, QConicalGradient, QIcon, QTransform, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient, QRegion)
from PySide6.QtWidgets import (QLayout, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QSlider,
                               QStackedWidget, QStyle, QStyleOptionSlider, QToolButton, QVBoxLayout, QWidget)

from aero.ui import icons
from aero.ui.theme import GlassStyle, Theme, custom_theme, get_theme, glass_style


class ThemeManager(QObject):
    """Estado visual global. Los widgets leen `tm()` y escuchan `changed` (tema) o `levels_changed`
    (transparencia e intensidad: solo hace falta repintar, nada se reconstruye)."""
    changed = Signal()
    levels_changed = Signal()
    quality_changed = Signal()
    _inst: "ThemeManager | None" = None

    def __init__(self):
        super().__init__()
        self.theme: Theme = get_theme("burbuja")
        self.glass: GlassStyle = glass_style(self.theme, 0.55, False)
        self.reduce_motion = False
        self.glass_mode = "blur"          # blur | clear | opaque
        self.window_opacity = 1.0         # opacidad del tinte propio del fondo de la ventana
        self.intensity = 0.55
        self.transparency = 0.6
        from aero.core.quality import normalize

        self.quality: dict = normalize({})   # perfil de rendimiento efectivo (aero.core.quality)

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._inst is None:
            cls._inst = ThemeManager()
        return cls._inst

    def apply(self, theme: "Theme | str", intensity: float, glass_mode: str, transparency: float,
              reduce_motion: bool, custom: dict | None = None) -> None:
        if isinstance(theme, str):
            theme = custom_theme(custom) if theme == "custom" else get_theme(theme)
        self.theme = theme
        self.glass_mode = glass_mode if glass_mode in ("blur", "clear", "opaque") else "blur"
        self.reduce_motion = reduce_motion
        self._levels(intensity, transparency)
        icons.pixmap.cache_clear()
        self.changed.emit()

    def _levels(self, intensity: float, transparency: float) -> None:
        self.intensity, self.transparency = intensity, transparency
        self.glass = glass_style(self.theme, intensity, self.glass_mode == "opaque")
        self.glass.shadow *= float(self.quality.get("shadows", 1.0))
        tr = max(0.0, min(1.0, transparency))
        if self.glass_mode == "opaque":
            self.window_opacity = 1.0
        elif self.glass_mode == "blur":
            self.window_opacity = 0.12 + 0.78 * (1.0 - tr)
        else:  # transparente nítido: algo más de tinte para que el texto no compita con lo de detrás
            self.window_opacity = 0.20 + 0.70 * (1.0 - tr)

    def set_levels(self, intensity: float, transparency: float) -> None:
        """Camino rápido de los deslizadores: sin hoja de estilos, sin iconos, sin reconstruir fondos."""
        if (intensity, transparency) == (self.intensity, self.transparency):
            return
        self._levels(intensity, transparency)
        self.levels_changed.emit()

    def set_quality(self, q: dict) -> None:
        """Nuevo perfil de calidad. Solo se reconstruye el fondo si cambia algo estructural."""
        from aero.ui import backdrop_fx

        if q == self.quality:
            return
        old, self.quality = self.quality, dict(q)
        backdrop_fx.QUALITY = self.quality
        self.glass = glass_style(self.theme, self.intensity, self.glass_mode == "opaque")
        self.glass.shadow *= float(self.quality.get("shadows", 1.0))
        self.quality_changed.emit()
        if old.get("blur") != q.get("blur"):
            self.changed.emit()  # las ventanas vuelven a pedir (o quitar) el desenfoque de Windows

    @property
    def blur_enabled(self) -> bool:
        return self.glass_mode == "blur" and bool(self.quality.get("blur", True))

    def icon(self, name: str, size: int = 20, accent_when_checked: bool = False):
        t = self.theme
        return icons.icon(name, t.text, size, t.accent if accent_when_checked else None)


def tm() -> ThemeManager:
    return ThemeManager.instance()


# Widgets que pintan todo su rectángulo (vídeo, visualizador): los cristales de debajo no se repintan
# por ellos. Es la optimización clave en ventanas translúcidas, donde Qt repinta a los antecesores.
OPAQUE_WIDGETS: "weakref.WeakSet[QWidget]" = weakref.WeakSet()


def mark_opaque(w: QWidget, corner: int = 0) -> None:
    w.setProperty("opaqueCorner", corner)
    OPAQUE_WIDGETS.add(w)


def opaque_video(w: QWidget) -> None:
    """Superficie de vídeo: el cristal no se pinta debajo, pero el widget rellena su área de negro OPACO.

    El fotograma lo compone la GPU encima y no cuenta para Windows: si debajo quedara alfa 0, el ratón
    atravesaría el vídeo hacia la ventana de detrás (sin movimiento → los controles no reaparecían,
    el doble clic no llegaba y un clic activaba otra aplicación)."""
    mark_opaque(w)
    pal = w.palette()
    pal.setColor(pal.ColorRole.Window, QColor(0, 0, 0))
    w.setPalette(pal)
    w.setAutoFillBackground(True)


def paint_region(owner: QWidget, region: QRegion) -> QRegion:
    """Región que `owner` debe pintar realmente, descontando hijos opacos visibles (salvo sus esquinas)."""
    for w in list(OPAQUE_WIDGETS):
        try:
            if not w.isVisible() or not owner.isAncestorOf(w):
                continue
        except RuntimeError:
            continue
        r = QRect(w.mapTo(owner, QPoint(0, 0)), w.size())
        hole = QRegion(r)
        c = int(w.property("opaqueCorner") or 0)
        if c:
            for corner in (QRect(r.left(), r.top(), c, c), QRect(r.right() - c + 1, r.top(), c, c),
                           QRect(r.left(), r.bottom() - c + 1, c, c), QRect(r.right() - c + 1, r.bottom() - c + 1, c, c)):
                hole = hole.subtracted(QRegion(corner))
        region = region.subtracted(hole)
    return region


# --------------------------------------------------------------------------- fondo de cristal

def _alpha(color: str, a: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def _blur(img: QImage, factor: int) -> QImage:
    w, h = img.width(), img.height()
    small = img.scaled(max(1, w // factor), max(1, h // factor), Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    return small.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def draw_bubble(p: QPainter, cx: float, cy: float, r: float, strength: float = 1.0, tint: str = "#ffffff") -> None:
    """Burbuja brillante: borde luminoso, reflejo especular y contraluz (sello de Frutiger Aero)."""
    body = QRadialGradient(QPointF(cx, cy), r)
    body.setColorAt(0.0, _alpha(tint, 0.03 * strength))
    body.setColorAt(0.8, _alpha(tint, 0.08 * strength))
    body.setColorAt(0.97, _alpha("#ffffff", 0.45 * strength))
    body.setColorAt(1.0, _alpha("#ffffff", 0.0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(body)
    p.drawEllipse(QPointF(cx, cy), r, r)
    spec = QRadialGradient(QPointF(cx - r * 0.38, cy - r * 0.42), r * 0.42)
    spec.setColorAt(0, _alpha("#ffffff", 0.8 * strength))
    spec.setColorAt(1, _alpha("#ffffff", 0.0))
    p.setBrush(spec)
    p.drawEllipse(QRectF(cx - r * 0.78, cy - r * 0.82, r * 0.8, r * 0.6))


def render_background(t: Theme, w: int, h: int, opacity: float = 1.0) -> QImage:
    """Fondo completo (tinte + decoración) en una imagen. Se usa en vistas previas y mediciones."""
    from aero.ui.backdrop_fx import render_accents, render_tint

    img = QImage(max(1, w), max(1, h), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setOpacity(opacity)
    p.drawImage(0, 0, render_tint(t, w, h))
    p.setOpacity(min(1.0, 0.45 + opacity * 0.55))
    p.drawImage(0, 0, render_accents(t, w, h, skip_moving=False))
    p.end()
    return img


class Backdrop(QWidget):
    """Fondo de la ventana: tinte de cristal sobre el escritorio real, decoración del tema y color ambiental.

    Dos capas a media resolución (tinte y decoración) que solo se renderizan al cambiar el tema o el tamaño;
    la transparencia se aplica como opacidad al pintarlas. Los elementos móviles son sprites con su propio
    temporizador, que solo invalida los rectángulos que ocupan y se detiene si la ventana no se ve.
    """

    # Cada fotograma obliga a Windows a recomponer toda la ventana transparente: el movimiento es lento
    # y 20 fps bastan para que se vea fluido; con la ventana en segundo plano baja a 6 fps.
    FPS_ACTIVE = 20
    FPS_IDLE = 6

    def __init__(self, parent=None, radius: int = 12):
        super().__init__(parent)
        self.radius = radius
        self.flat = False                  # sin acentos (visor minimalista)
        self.flat_opacity: float | None = None
        self.paused = False                # p. ej. mientras se reproduce vídeo
        self._tint: QPixmap | None = None
        self._accents: QPixmap | None = None
        self._base = None                  # indica si ya hay fondo construido
        self._ambient: QPixmap | None = None
        self._ambient_src: QImage | None = None
        self._ambient_alpha = 0.0
        self._sprites: list = []
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(450)
        self._anim.valueChanged.connect(self._set_alpha)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(80)
        self._rebuild_timer.timeout.connect(self._rebuild)
        self._motion = QTimer(self)
        self._motion.setTimerType(Qt.TimerType.CoarseTimer)
        self._motion.timeout.connect(self._tick)
        self._clock = 0.0
        tm().changed.connect(self._rebuild)
        tm().levels_changed.connect(self._levels)
        tm().quality_changed.connect(self._quality)
        from aero.ui.perf import auto_tuner

        auto_tuner().rest_changed.connect(self._rest)
        self._qsig = None

    def _quality(self) -> None:
        q = tm().quality
        sig = tuple(q.get(k) for k in ("bubbles", "clouds", "particles", "decor", "reflections", "motion",
                                         "max_moving"))
        if sig != self._qsig:
            self._qsig = sig
            self._rebuild()
        else:
            self._sync_motion()
        if not q.get("ambient", True) and self._ambient_src is not None:
            self.set_ambient(None)

    def _set_alpha(self, v):
        self._ambient_alpha = float(v)
        self.update()

    def set_ambient(self, img: QImage | None) -> None:
        """La portada de lo que suena tiñe suavemente el cristal (si el perfil de calidad lo permite)."""
        if not tm().quality.get("ambient", True):
            img = None
        self._ambient_src = img if img is not None and not img.isNull() else None
        self._build_ambient()
        self._anim.stop()
        self._anim.setStartValue(self._ambient_alpha)
        self._anim.setEndValue(0.30 if self._ambient_src is not None else 0.0)
        self._anim.setDuration(0 if tm().reduce_motion else 450)
        self._anim.start()

    def _build_ambient(self) -> None:
        if self._ambient_src is None:
            self._ambient = None
            return
        src = self._ambient_src.scaled(24, 24, Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
        self._ambient = QPixmap.fromImage(_blur(src.scaled(192, 120), 2))

    def resizeEvent(self, e):
        self._rebuild_timer.start()
        if self._base is None:
            self._rebuild()

    def _levels(self) -> None:
        if self.flat:
            self._rebuild()
        else:
            self.update()

    def _rebuild(self) -> None:
        from aero.ui.backdrop_fx import build_sprites, has_motion, render_accents, render_tint, split_sprites

        w, h = max(1, self.width()), max(1, self.height())
        t = tm().theme
        self._sprites = []
        self._qsig = tuple(tm().quality.get(k) for k in ("bubbles", "clouds", "particles", "decor", "reflections",
                                                          "motion", "max_moving"))
        if self.flat:
            img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            op = self.flat_opacity if self.flat_opacity is not None else tm().window_opacity * 0.9 + 0.08
            img.fill(_alpha(t.bg[0][1] if t.dark else "#0b1622", op))
            self._tint, self._accents = QPixmap.fromImage(img), None
        else:
            # Se renderiza a media resolución: el fondo es suave y así cuesta 4 veces menos.
            moving = has_motion(t) and not tm().reduce_motion
            hw, hh = max(1, w // 2), max(1, h // 2)
            self._tint = QPixmap.fromImage(render_tint(t, hw, hh))
            static = []
            if moving:
                self._sprites, static = split_sprites(build_sprites(t, w, h))
                dpr = self.devicePixelRatioF()
                for sp in self._sprites:
                    sp.bake(t, dpr)
            self._accents = QPixmap.fromImage(render_accents(t, hw, hh, skip_moving=moving, static=static,
                                                             scale=hw / w))
        self._base = self._tint
        self._sync_motion()
        self.update()

    # ------------------------------------------------------------------ movimiento
    def _rest(self, _on: bool) -> None:
        try:
            self._sync_motion()
        except RuntimeError:  # ventana ya destruida
            pass

    def _sync_motion(self) -> None:
        win = self.window()
        want = (bool(self._sprites) and not self.paused and self.isVisible() and not tm().reduce_motion
                and not win.isMinimized())
        from aero.ui.perf import auto_tuner

        tuner = auto_tuner()
        tuner.wants_motion(self, want)
        run = want and not tuner.resting
        tuner.animating(self, run)
        if run:
            top = int(tm().quality.get("fps", self.FPS_ACTIVE))
            fps = top if win.isActiveWindow() else min(top, self.FPS_IDLE)
            if not self._motion.isActive() or self._motion.interval() != 1000 // fps:
                self._motion.start(1000 // fps)
                self._clock = time.perf_counter()
        else:
            self._motion.stop()

    def set_paused(self, on: bool) -> None:
        self.paused = on
        self._sync_motion()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_motion()

    def hideEvent(self, e):
        super().hideEvent(e)
        try:
            self._motion.stop()
        except RuntimeError:
            return  # cierre de la aplicación: los objetos de Qt ya se destruyeron
        from aero.ui.perf import auto_tuner

        auto_tuner().animating(self, False)
        auto_tuner().wants_motion(self, False)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowStateChange):
            self._sync_motion()

    def _tick(self) -> None:
        from aero.ui.backdrop_fx import step_sprites

        now = time.perf_counter()
        dt = min(0.1, now - (self._clock or now))
        self._clock = now
        before = [sp.rect() for sp in self._sprites]
        step_sprites(self._sprites, tm().theme, self.width(), self.height(), dt)
        for old, sp in zip(before, self._sprites):
            self.update(old.united(sp.rect()))

    def paintEvent(self, e):
        region = paint_region(self, e.region())
        if region.isEmpty():
            return
        p = QPainter(self)
        p.setClipRegion(region)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rounded = not self.window().isMaximized() and not self.window().isFullScreen()
        # Las ventanas «layered» ignoran SetWindowRgn al dibujar: la forma redondeada (con borde suavizado)
        # la da el propio pintado; fuera de la curva el píxel queda totalmente transparente.
        shape = QPainterPath()
        if rounded:
            shape.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        else:
            shape.addRect(QRectF(self.rect()))
        op = 1.0 if self.flat else tm().window_opacity
        for pix, alpha in ((self._tint, op), (self._accents, min(1.0, 0.45 + op * 0.55)),
                           (self._ambient, self._ambient_alpha * (0.8 if tm().theme.dark else 0.5))):
            if pix is None or alpha <= 0.01:
                continue
            brush = QBrush(pix)
            brush.setTransform(QTransform.fromScale(self.width() / max(1, pix.width()),
                                                    self.height() / max(1, pix.height())))
            p.setOpacity(alpha)
            p.fillPath(shape, brush)
        if self._sprites:
            p.setOpacity(min(1.0, 0.45 + op * 0.55))
            p.setClipPath(shape, Qt.ClipOperation.IntersectClip)
            clip = region.boundingRect()
            for sp in self._sprites:
                if sp.rect().intersects(clip):
                    sp.paint(p)
            p.setClipRegion(region)
        p.setOpacity(1.0)
        if rounded:
            r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            p.setPen(QPen(QColor(0, 10, 30, int(60 + 60 * tm().glass.shadow)), 1))
            p.drawRoundedRect(r, self.radius, self.radius)
            hl = QLinearGradient(0, 0, 0, self.height())
            hl.setColorAt(0, QColor(255, 255, 255, 130))
            hl.setColorAt(0.25, QColor(255, 255, 255, 45))
            hl.setColorAt(1, QColor(255, 255, 255, 70))
            p.setPen(QPen(hl, 1))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), self.radius - 1, self.radius - 1)


def find_backdrop(w: QWidget) -> Backdrop | None:
    cur = w.parentWidget()
    while cur is not None:
        if isinstance(cur, Backdrop):
            return cur
        cur = cur.parentWidget()
    return None


class GlassPanel(QWidget):
    """Superficie de cristal: tinte, casquete brillante sutil, borde de luz interior y borde exterior fino."""

    def __init__(self, parent=None, radius: float = 14, nested: bool = False, strong: bool = False):
        super().__init__(parent)
        self.radius = radius
        self.nested = nested
        self.strong = strong
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        tm().changed.connect(self.update)
        tm().levels_changed.connect(self.update)

    def paintEvent(self, e):
        region = paint_region(self, e.region())
        if region.isEmpty():
            return
        t, g = tm().theme, tm().glass
        if not hasattr(self, "_in_glass"):
            # Un panel dentro de otro panel se dibuja como «tarjeta» ligera (sin doble cristal).
            a, self._in_glass = self.parentWidget(), False
            while a is not None:
                if isinstance(a, GlassPanel):
                    self._in_glass = True
                    break
                a = a.parentWidget()
        nested = self.nested or self._in_glass
        p = QPainter(self)
        p.setClipRegion(region)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        if g.solid:
            c = QColor(t.solid)
            if nested:
                c = _alpha(t.text, 0.05)
            p.fillPath(path, c)
            p.setPen(QPen(_alpha(t.text, 0.12), 1))
            p.drawPath(path)
            return
        if nested:
            p.fillPath(path, _alpha(t.glass, 0.05 if t.dark else 0.28))
            p.setPen(QPen(_alpha("#ffffff", 0.14 if t.dark else 0.6), 1))
            p.drawPath(path)
            return
        fill = g.fill * (1.6 if self.strong else 1.0)
        # Con poco tinte de ventana, el panel compensa para que el texto siga siendo legible.
        fill = min(1.0, fill + (1.0 - tm().window_opacity) * (0.16 if t.dark else 0.32))
        grad = QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0, _alpha(t.glass, fill * 1.25))
        grad.setColorAt(1, _alpha(t.glass, fill * 0.85))
        p.fillPath(path, grad)
        if True:
            cap_h = min(r.height() * 0.5, 46.0)
            cap = QLinearGradient(0, r.top(), 0, r.top() + cap_h)
            cap.setColorAt(0, QColor(255, 255, 255, int(255 * g.highlight * 0.35)))
            cap.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(r.left() + 1, r.top() + 1, r.width() - 2, cap_h), cap)
            inner = QPainterPath()
            inner.addRoundedRect(r.adjusted(1, 1, -1, -1), self.radius - 1, self.radius - 1)
            ig = QLinearGradient(0, r.top(), 0, r.bottom())
            ig.setColorAt(0, QColor(255, 255, 255, int(255 * min(1.0, g.border * 1.8))))
            ig.setColorAt(0.4, QColor(255, 255, 255, int(255 * g.border * 0.35)))
            ig.setColorAt(1, QColor(255, 255, 255, int(255 * g.border * 0.6)))
            p.setPen(QPen(ig, 1))
            p.drawPath(inner)
        p.setPen(QPen(QColor(0, 15, 40, 55 if t.dark else 40), 1))
        p.drawPath(path)


# --------------------------------------------------------------------------- controles

class Squish(QObject):
    """Animación «squishy»: al pulsar se aplasta y al soltar rebota con efecto elástico."""

    def __init__(self, widget: QWidget, pressed: float = 0.84, hover: float = 1.0):
        super().__init__(widget)
        self.w = widget
        self.scale = 1.0
        self.pressed_scale, self.hover_scale = pressed, hover
        self.anim = QVariantAnimation(self)
        self.anim.valueChanged.connect(self._set)
        widget.installEventFilter(self)

    def _set(self, v):
        self.scale = float(v)
        self.w.update()

    def to(self, value: float, ms: int, curve: QEasingCurve.Type, amplitude: float = 1.0) -> None:
        if tm().reduce_motion:
            self._set(1.0)
            return
        self.anim.stop()
        self.anim.setStartValue(self.scale)
        self.anim.setEndValue(value)
        self.anim.setDuration(ms)
        ec = QEasingCurve(curve)
        if curve == QEasingCurve.Type.OutElastic:
            ec.setAmplitude(amplitude)
            ec.setPeriod(0.32)
        self.anim.setEasingCurve(ec)
        self.anim.start()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
            self.to(self.pressed_scale, 90, QEasingCurve.Type.OutQuad)
        elif t == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
            self.to(self.hover_scale if self.w.underMouse() else 1.0, 620, QEasingCurve.Type.OutElastic, 1.1)
        elif t == QEvent.Type.Enter and self.hover_scale != 1.0:
            self.to(self.hover_scale, 220, QEasingCurve.Type.OutBack)
        elif t == QEvent.Type.Leave and self.hover_scale != 1.0:
            self.to(1.0, 260, QEasingCurve.Type.OutBack)
        return False


def iridescent_rim(cx: float, cy: float) -> QConicalGradient:
    """Brillo de película de jabón en el borde de una burbuja."""
    g = QConicalGradient(QPointF(cx, cy), 120)
    for pos, col in ((0.0, "#ff9ad5"), (0.18, "#ffe39a"), (0.36, "#9affc9"), (0.55, "#8fe3ff"),
                     (0.75, "#b9a2ff"), (1.0, "#ff9ad5")):
        g.setColorAt(pos, QColor(col))
    return g


def paint_bubble(p: QPainter, c: QPointF, r: float, tint: QColor, fill: float = 0.12, rim: float = 0.9,
                 iridescent: bool = True) -> None:
    """Burbuja transparente: cuerpo casi invisible, borde iridiscente, reflejo especular y contraluz."""
    body = QRadialGradient(c, r)
    t0, t1 = QColor(tint), QColor(tint)
    t0.setAlphaF(fill * 0.35)
    t1.setAlphaF(min(1.0, fill * 1.6))
    body.setColorAt(0.0, t0)
    body.setColorAt(0.82, t1)
    body.setColorAt(1.0, _alpha("#ffffff", 0.55 * rim))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(body)
    p.drawEllipse(c, r, r)
    if iridescent:
        pen = QPen(QBrush(iridescent_rim(c.x(), c.y())), max(1.0, r * 0.07))
        p.setOpacity(p.opacity() * 0.55 * rim)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, r - r * 0.04, r - r * 0.04)
        p.setOpacity(p.opacity() / (0.55 * rim))
    p.setPen(QPen(_alpha("#ffffff", 0.75 * rim), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(c, r - 0.5, r - 0.5)
    spec = QRadialGradient(QPointF(c.x() - r * 0.35, c.y() - r * 0.45), r * 0.55)
    spec.setColorAt(0, _alpha("#ffffff", 0.9 * rim))
    spec.setColorAt(1, _alpha("#ffffff", 0.0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(spec)
    p.drawEllipse(QRectF(c.x() - r * 0.72, c.y() - r * 0.82, r * 0.78, r * 0.5))
    back = QRadialGradient(QPointF(c.x() + r * 0.35, c.y() + r * 0.55), r * 0.4)
    back.setColorAt(0, _alpha("#ffffff", 0.35 * rim))
    back.setColorAt(1, _alpha("#ffffff", 0.0))
    p.setBrush(back)
    p.drawEllipse(QPointF(c.x() + r * 0.3, c.y() + r * 0.55), r * 0.42, r * 0.2)


class IconButton(QToolButton):
    """Botón de icono: al pasar el ratón aparece una burbuja; al pulsar se aplasta y rebota."""

    def __init__(self, name: str, tooltip: str, size: int = 20, checkable: bool = False, parent=None,
                 button: int = 36):
        super().__init__(parent)
        self._name, self._size = name, size
        self.checked_bubble = True
        self.danger = False
        self.setCheckable(checkable)
        from aero.i18n import tr

        self.setToolTip(tr(tooltip) if tooltip else tooltip)
        self.setAccessibleName(tr(tooltip) if tooltip else tooltip)
        self.setIconSize(QSize(size, size))
        self.setFixedSize(button, button)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.squish = Squish(self, 0.84, 1.0)
        self._refresh()
        tm().changed.connect(self._refresh)

    def set_icon_name(self, name: str) -> None:
        self._name = name
        self._refresh()

    def _refresh(self):
        self.setIcon(tm().icon(self._name, self._size, self.isCheckable()))
        self.update()

    def paintEvent(self, e):
        t = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        c = QPointF(self.width() / 2, self.height() / 2)
        s = self.squish.scale
        p.translate(c)
        p.scale(s, s)
        p.translate(-c)
        r = min(self.width(), self.height()) / 2 - 2
        hovered = self.underMouse() and self.isEnabled()
        if self.danger and hovered:
            paint_bubble(p, c, r, QColor(232, 64, 80), fill=0.55, rim=0.9, iridescent=False)
        elif self.isChecked() and self.checked_bubble:
            paint_bubble(p, c, r, QColor(t.accent), fill=0.32, rim=1.0)
        elif hovered or self.isDown():
            paint_bubble(p, c, r, QColor(t.accent if t.dark else "#ffffff"), fill=0.10, rim=0.75)
        if self.hasFocus():
            p.setPen(QPen(QColor(t.accent), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, r + 0.5, r + 0.5)
        if not self.isEnabled():
            p.setOpacity(0.4)
        mode = QIcon.Mode.Normal
        state = QIcon.State.On if self.isChecked() else QIcon.State.Off
        sz = self.iconSize()
        self.icon().paint(p, QRect(round(c.x() - sz.width() / 2), round(c.y() - sz.height() / 2), sz.width(),
                                   sz.height()), Qt.AlignmentFlag.AlignCenter, mode, state)


class PlayButton(QToolButton):
    """Botón principal: burbuja transparente con el icono centrado; al pulsar hace «pop» con onda."""

    def __init__(self, parent=None, size: int = 50):
        super().__init__(parent)
        pad = max(6, size // 6)
        self.setFixedSize(size + pad * 2, size + pad * 2)
        self.bubble = size / 2
        self.playing = False
        from aero.i18n import tr

        self.setToolTip(tr("Reproducir / pausar"))
        self.setAccessibleName(tr("Reproducir o pausar"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.squish = Squish(self, 0.80, 1.04)
        self.ripple = 0.0
        self._ripple = QVariantAnimation(self)
        self._ripple.setDuration(520)
        self._ripple.setStartValue(0.0)
        self._ripple.setEndValue(1.0)
        self._ripple.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._ripple.valueChanged.connect(lambda v: (setattr(self, "ripple", float(v)), self.update()))
        self.pressed.connect(self._pop)
        tm().changed.connect(self.update)

    def _pop(self):
        if not tm().reduce_motion:
            self._ripple.stop()
            self._ripple.start()

    def set_playing(self, on: bool):
        if on != self.playing:
            self.playing = on
            self.update()

    def paintEvent(self, e):
        t = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = self.bubble
        if 0.0 < self.ripple < 1.0:
            ring = QColor(t.accent)
            ring.setAlphaF(0.55 * (1 - self.ripple))
            p.setPen(QPen(ring, 2.0 * (1 - self.ripple) + 0.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rr = r * (1.0 + 0.32 * self.ripple)
            p.drawEllipse(c, rr, rr)
        s = self.squish.scale
        # «Squishy»: al aplastarse se ensancha un poco y pierde altura (conserva el volumen aparente).
        sx, sy = s * (1 + (1 - s) * 0.35), s
        p.translate(c)
        p.scale(sx, sy)
        p.translate(-c)
        paint_bubble(p, c, r, QColor(t.accent), fill=0.16 if not self.underMouse() else 0.24, rim=1.0)
        # Icono centrado de verdad: el triángulo se compensa ópticamente sobre su centroide.
        col = QColor("#ffffff")
        p.setPen(Qt.PenStyle.NoPen)
        shadow = QColor(0, 20, 50, 90)
        k = r * 0.42
        if self.playing:
            bw, gap = k * 0.36, k * 0.34
            for dx in (-gap / 2 - bw, gap / 2):
                for brush, off in ((shadow, 1.0), (col, 0.0)):
                    p.setBrush(brush)
                    p.drawRoundedRect(QRectF(c.x() + dx, c.y() - k * 0.9 + off, bw, k * 1.8), bw * 0.4, bw * 0.4)
        else:
            h = k * 1.9
            w = h * 0.88
            # Equilibrio óptico: a medio camino entre centrar la caja del triángulo y centrar su centroide.
            left = c.x() - w * 0.47
            tri = QPainterPath()
            tri.moveTo(left, c.y() - h / 2)
            tri.lineTo(left + w, c.y())
            tri.lineTo(left, c.y() + h / 2)
            tri.closeSubpath()
            p.setBrush(shadow)
            p.drawPath(tri.translated(0, 1.0))
            p.setBrush(col)
            p.setPen(QPen(col, k * 0.18, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(tri)
        if self.hasFocus():
            p.setPen(QPen(QColor(t.text), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, r + 2, r + 2)


class ClickSlider(QSlider):
    """Deslizador que salta a la posición pulsada. Emite `seek_requested` al soltar."""
    seek_requested = Signal(int)

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sliderReleased.connect(lambda: self.seek_requested.emit(self.value()))

    def _value_at(self, x: int) -> int:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                             QStyle.SubControl.SC_SliderGroove, self)
        handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                             QStyle.SubControl.SC_SliderHandle, self)
        span = groove.width() - handle.width()
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                              x - groove.x() - handle.width() // 2, max(1, span))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                                 QStyle.SubControl.SC_SliderHandle, self)
            if not handle.contains(e.position().toPoint()):
                v = self._value_at(int(e.position().x()))
                self.setValue(v)
                self.seek_requested.emit(v)
                e.accept()
                # Permitir arrastrar inmediatamente tras el clic
        super().mousePressEvent(e)


class CoverArt(QWidget):
    """Portada con esquinas redondeadas, reflejo y marcador por defecto."""

    def __init__(self, size: int = 56, radius: float = 10, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.radius = radius
        self._img: QPixmap | None = None
        self.placeholder = "music"
        tm().changed.connect(self.update)

    def set_image(self, img: QImage | None) -> None:
        if img is None or img.isNull():
            self._img = None
        else:
            dpr = self.devicePixelRatioF()
            px = img.scaled(int(self.width() * dpr), int(self.height() * dpr),
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            pm = QPixmap.fromImage(px)
            pm.setDevicePixelRatio(dpr)
            self._img = pm
        self.update()

    def resizeEvent(self, e):
        self.update()

    def paintEvent(self, e):
        t = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.setClipPath(path)
        if self._img is not None:
            sz = self._img.deviceIndependentSize()
            p.drawPixmap(QRectF((r.width() - sz.width()) / 2, (r.height() - sz.height()) / 2, sz.width(), sz.height()),
                         self._img, QRectF(self._img.rect()))
        else:
            g = QLinearGradient(0, 0, r.width(), r.height())
            g.setColorAt(0, QColor(t.accent))
            g.setColorAt(1, QColor(t.viz[3]))
            p.fillRect(r, g)
            s = r.width() * 0.42
            pm = icons.pixmap(self.placeholder, "#ffffff", int(s))
            p.drawPixmap(QRectF((r.width() - s) / 2, (r.height() - s) / 2, s, s), pm, QRectF(pm.rect()))
        gloss = QLinearGradient(0, 0, 0, r.height() * 0.5)
        gloss.setColorAt(0, QColor(255, 255, 255, 60))
        gloss.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, 0, r.width(), r.height() * 0.5), gloss)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        p.drawPath(path)


class Spinner(QWidget):
    def __init__(self, size: int = 36, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, e):
        self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()

    def _tick(self):
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, e):
        t = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        p.setPen(QPen(QColor(255, 255, 255, 40), 3))
        p.drawEllipse(r)
        pen = QPen(QColor(t.accent), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, -self._angle * 16, 100 * 16)


# --------------------------------------------------------------------------- transiciones y avisos

class FadeStack(QStackedWidget):
    """QStackedWidget con fundido suave entre páginas (desactivable con «reducir animaciones»)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._overlay = QLabel(self)
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._overlay.hide()
        self._effect = QGraphicsOpacityEffect(self._overlay)
        self._overlay.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._overlay.hide)

    def fade_to(self, index: int) -> None:
        if index == self.currentIndex():
            return
        if tm().reduce_motion or not self.isVisible() or self.currentWidget() is None:
            self.setCurrentIndex(index)
            return
        snap = self.currentWidget().grab()
        self._overlay.setPixmap(snap)
        self._overlay.setGeometry(self.rect())
        self.setCurrentIndex(index)
        self._overlay.raise_()
        self._overlay.show()
        self._effect.setOpacity(1.0)
        self._anim.stop()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()


class Toast(GlassPanel):
    """Aviso flotante breve en la esquina inferior derecha."""

    def __init__(self, host: QWidget):
        super().__init__(host, radius=14, strong=True)
        self.host = host
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setMaximumWidth(380)
        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(250)
        self._fade.finished.connect(self._fade_done)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._hide_anim)
        self.hide()

    def show_message(self, text: str, kind: str = "info", ms: int = 3800) -> None:
        name = {"error": "info", "ok": "check"}.get(kind, "info")
        color = "#ff7a8a" if kind == "error" else tm().theme.accent
        self.icon.setPixmap(icons.pixmap(name, color, 20))
        self.text.setText(text)
        self.adjustSize()
        self._reposition()
        self.raise_()
        self.show()
        self._fade.stop()
        self._effect.setOpacity(1.0)
        if not tm().reduce_motion:
            end = self.pos()
            self._pop = QPropertyAnimation(self, b"pos", self)
            self._pop.setDuration(420)
            self._pop.setStartValue(end + QPoint(0, 26))
            self._pop.setEndValue(end)
            self._pop.setEasingCurve(QEasingCurve.Type.OutBack)
            self._pop.start()
        self._timer.start(ms)
        self.setAccessibleDescription(text)

    def _reposition(self):
        hw, hh = self.host.width(), self.host.height()
        self.move(hw - self.width() - 28, hh - self.height() - 124)

    def _hide_anim(self):
        if tm().reduce_motion:
            self.hide()
            return
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _fade_done(self):
        if self._effect.opacity() < 0.05:
            self.hide()


class HoverLight(QObject):
    """Valor 0→1 animado al entrar/salir el ratón: para iluminar o «elevar» sin escalar el widget."""

    def __init__(self, widget: QWidget, ms: int = 160):
        super().__init__(widget)
        self.w = widget
        self.value = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(ms)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._set)
        widget.setAttribute(Qt.WidgetAttribute.WA_Hover)
        widget.installEventFilter(self)

    def _set(self, v):
        self.value = float(v)
        self.w.update()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.Type.Enter, QEvent.Type.Leave):
            end = 1.0 if t == QEvent.Type.Enter else 0.0
            if tm().reduce_motion:
                self._set(end)
            else:
                self.anim.stop()
                self.anim.setStartValue(self.value)
                self.anim.setEndValue(end)
                self.anim.start()
        return False


class _LazyQueue(QObject):
    """Cola de trabajos de pintado diferido (miniaturas): uno por vuelta, para no bloquear la ventana."""

    def __init__(self):
        super().__init__()
        self.jobs: list = []
        self.timer = QTimer(self)
        self.timer.setInterval(8)
        self.timer.timeout.connect(self._run)

    def add(self, fn) -> None:
        self.jobs.append(fn)
        if not self.timer.isActive():
            self.timer.start()

    def _run(self) -> None:
        if not self.jobs:
            self.timer.stop()
            return
        try:
            self.jobs.pop(0)()
        except RuntimeError:
            pass  # el widget ya no existe


_LAZY: _LazyQueue | None = None


def defer_paint(fn) -> None:
    """Encola un trabajo de renderizado caro (se ejecuta en una vuelta posterior del bucle de eventos)."""
    global _LAZY
    if _LAZY is None:
        _LAZY = _LazyQueue()
    _LAZY.add(fn)


def transport_row(*widgets, spacing: int = 8) -> QWidget:
    """Fila de controles de reproducción con una sola línea central.

    La fila mide exactamente lo que su control más alto y cada control se centra verticalmente, así
    ningún botón (p. ej. Play, que es mayor) puede quedar desplazado aunque el contenedor sea pequeño.
    """
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    h = 0
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        else:
            lay.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
            h = max(h, w.minimumHeight(), w.sizeHint().height())
    row.setFixedHeight(h)
    row.setSizePolicy(row.sizePolicy().horizontalPolicy(), row.sizePolicy().Policy.Fixed)
    return row


def h_layout(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        elif isinstance(w, QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return lay


def v_layout(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        elif isinstance(w, QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return lay


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    from aero.i18n import tr

    lb = QLabel(tr(text) if text else text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb


def make_app_icon(size: int = 256) -> QPixmap:
    """Icono de la aplicación dibujado por código: gota de cristal con onda de sonido."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(size * 0.06, size * 0.06, size * 0.88, size * 0.88)
    g = QRadialGradient(r.center().x(), r.top() + r.height() * 0.25, r.width() * 0.8)
    g.setColorAt(0, QColor("#8ff3ff"))
    g.setColorAt(0.45, QColor("#1ea7ff"))
    g.setColorAt(1, QColor("#0a3d8f"))
    p.setBrush(g)
    p.setPen(QPen(QColor(255, 255, 255, 200), size * 0.012))
    p.drawEllipse(r)
    # Onda
    pen = QPen(QColor(255, 255, 255, 235), size * 0.055)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    path = QPainterPath()
    cy = size * 0.56
    path.moveTo(size * 0.22, cy)
    for i in range(1, 61):
        x = size * 0.22 + i * (size * 0.56 / 60)
        env = math.sin(math.pi * i / 60)
        path.lineTo(x, cy - math.sin(i / 60 * math.pi * 4) * size * 0.13 * env)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    # Brillo superior
    gloss = QPainterPath()
    gloss.addEllipse(QRectF(r.left() + r.width() * 0.14, r.top() + r.height() * 0.03, r.width() * 0.72, r.height() * 0.45))
    gg = QLinearGradient(0, r.top(), 0, r.top() + r.height() * 0.48)
    gg.setColorAt(0, QColor(255, 255, 255, 190))
    gg.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillPath(gloss, gg)
    p.end()
    return QPixmap.fromImage(img)
