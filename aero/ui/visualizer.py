"""Visualizadores de audio reactivos al sonido real (espectro por FFT, nivel, graves y pulsos).

Cada escena tiene su propia forma de dibujar, no son variaciones de la misma animación:

* Aero Waves — capas de ondas suaves con brillo de gel y burbujas que suben con los golpes.
* Liquid Spectrum — espectro simétrico con forma de líquido (curva continua, reflejo y menisco).
* Aurora — cortinas de luz que ondulan con la energía de cada zona del espectro (con estela).
* Particles — partículas que salen del centro con la fuerza de cada banda (con estela).
* Equalizer Classic — ecualizador de bloques tipo LED con picos que caen.
* Glass Bars — barras de cristal con reflejo especular y espejo en el suelo.
* Energy Flow — líneas de energía con la forma de onda real y halo en los pulsos (con estela).
* Nebula — nubes de color que giran y laten con graves, medios y agudos, y estrellas (con estela).
* Water Rings — anillos concéntricos que nacen con cada golpe, como gotas sobre agua.
* Fluid Motion — gotas de luz que se mueven, se funden y cambian de tamaño con la música.
* Anillo — espectro circular simétrico con una estela breve.

Rendimiento: un solo temporizador por visualizador visible; las escenas con estela dibujan sobre un búfer
a resolución reducida; todo lo repetitivo se agrupa en pocos trazados. Parámetros: intensidad (brillo y
amplitud), velocidad (tiempo y deriva de color) y sensibilidad (ganancia sobre el espectro real).
"""

from __future__ import annotations

import math
import random
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
                           QRadialGradient)
from PySide6.QtWidgets import QWidget

from aero.ui.glass import mark_opaque, tm

SCENES_DEF = [
    ("aero_waves", "Aero Waves", False),
    ("liquid_spectrum", "Liquid Spectrum", False),
    ("aurora", "Aurora", True),
    ("particles", "Particles", True),
    ("eq_classic", "Equalizer Classic", False),
    ("glass_bars", "Glass Bars", False),
    ("energy_flow", "Energy Flow", True),
    ("nebula", "Nebula", True),
    ("water_rings", "Water Rings", False),
    ("fluid_motion", "Fluid Motion", True),
    ("ring", "Anillo", True),
]
SCENE_KEYS = [k for k, _n, _t in SCENES_DEF]
SCENE_NAMES = {k: n for k, n, _t in SCENES_DEF}
TRAIL = {k for k, _n, t in SCENES_DEF if t}
SCENES = [n for _k, n, _t in SCENES_DEF]         # nombres en orden (compatibilidad)
LEGACY = ["glass_bars", "energy_flow", "particles", "aurora", "ring"]   # índices antiguos de visualizer_scene
# Cuánto se borra la estela en cada fotograma (0-255): más alto = estela más corta y sin saturar a blanco.
TRAIL_FADE = {"aurora": 56, "particles": 64, "energy_flow": 70, "nebula": 48, "fluid_motion": 64, "ring": 170}


def _hue_color(h: float, s: float = 0.85, v: float = 1.0, a: float = 1.0) -> QColor:
    c = QColor.fromHsvF(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


class DemoAnalyzer:
    """Señal sintética para las vistas previas de la galería cuando no suena nada."""

    def __init__(self, bands: int = 64):
        self.bands = bands
        self.spectrum = np.zeros(bands, dtype=np.float32)
        self.peaks = np.zeros(bands, dtype=np.float32)
        self.level = self.bass = self.beat = 0.0
        self._t = 0.0
        self._x = np.linspace(0, 1, bands, dtype=np.float32)

    def update(self, dt: float = 1 / 30) -> None:
        self._t += dt
        t = self._t
        kick = max(0.0, math.sin(t * math.pi * 2.0)) ** 8
        env = 0.55 + 0.25 * np.sin(self._x * 9 + t * 1.7) + 0.15 * np.sin(self._x * 23 - t * 2.9)
        target = np.clip(env * (1.0 - self._x * 0.45) + kick * 0.5 * (1 - self._x) ** 3, 0, 1).astype(np.float32)
        self.spectrum = self.spectrum * 0.6 + target * 0.4
        self.peaks = np.maximum(self.peaks - 0.01, self.spectrum)
        self.level = float(self.spectrum.mean())
        self.bass = float(self.spectrum[:8].mean())
        self.beat = max(self.beat * 0.85, kick)

    def latest(self, count: int) -> np.ndarray:
        x = np.linspace(0, 1, count, dtype=np.float32)
        t = self._t
        return (0.5 * np.sin(x * 60 + t * 9) * np.sin(x * 7 + t) * (0.4 + self.level)).astype(np.float32)


class Visualizer(QWidget):
    def __init__(self, analyzer, parent=None):
        super().__init__(parent)
        self.analyzer = analyzer
        self.key = "glass_bars"
        self.low_power = False
        self.intensity, self.speed, self.sensitivity = 0.7, 0.5, 0.5
        self.palette_mode, self.custom_color = "theme", "#8fe3ff"
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(120, 60)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._frame)
        self._trail: QImage | None = None
        self._particles: list[list[float]] = []
        self._rings: list[list[float]] = []
        self._bubbles: list[list[float]] = []
        self._eq_peaks = np.zeros(32, dtype=np.float32)
        self._hue = 0.55
        self._t = 0.0
        self._last = time.perf_counter()
        self.active = False
        self._title = ""
        self._settings = None
        self.spec = np.zeros(64, dtype=np.float32)
        mark_opaque(self, 14)

    # ------------------------------------------------------------------ configuración
    @property
    def scene(self) -> int:
        return SCENE_KEYS.index(self.key)

    def configure(self, settings) -> None:
        """Lee y sigue los ajustes del visualizador (intensidad, velocidad, sensibilidad y colores)."""
        self._settings = settings
        self._read_settings()
        settings.changed.connect(self._setting_changed)
        from aero.ui.glass import tm

        tm().quality_changed.connect(self._read_settings)

    def _setting_changed(self, key: str) -> None:
        if key == "visualizer_key":
            self.set_scene_key(self._settings.get(key))
        elif key.startswith("visualizer_"):
            self._read_settings()

    def _read_settings(self) -> None:
        s = self._settings
        if s is None:
            return
        self.intensity = float(s.get("visualizer_intensity"))
        self.speed = float(s.get("visualizer_speed"))
        self.sensitivity = float(s.get("visualizer_sensitivity"))
        self.palette_mode = s.get("visualizer_palette")
        self.custom_color = s.get("visualizer_color")
        from aero.ui.glass import tm

        detail = tm().quality.get("viz", "normal")
        self.detail = detail
        lp = bool(s.get("visualizer_low_power")) or detail == "low"
        if lp != self.low_power:
            self.set_low_power(lp)

    def set_scene(self, i: int) -> None:
        self.set_scene_key(SCENE_KEYS[i % len(SCENE_KEYS)])

    def set_scene_key(self, key: str) -> None:
        self.key = key if key in SCENE_KEYS else "glass_bars"
        self._trail = None
        self._particles.clear()
        self._rings.clear()
        self._bubbles.clear()
        self.update()

    def set_low_power(self, on: bool) -> None:
        self.low_power = on
        self._trail = None
        if self._timer.isActive():
            self._timer.start(33 if on else 16)

    def set_caption(self, text: str) -> None:
        self._title = text

    def start(self) -> None:
        from aero.ui.perf import auto_tuner

        self.active = True
        self._last = time.perf_counter()
        self._timer.start(33 if self.low_power else 16)
        auto_tuner().animating(self, True)

    def stop(self) -> None:
        from aero.ui.perf import auto_tuner

        self.active = False
        self._timer.stop()
        auto_tuner().animating(self, False)

    def _frame(self) -> None:
        now = time.perf_counter()
        dt = min(0.1, now - self._last)
        self._last = now
        self.advance(dt)
        self.update()

    def advance(self, dt: float) -> None:
        """Avanza el tiempo y lee el audio. Separado del pintado para poder renderizar miniaturas."""
        self.analyzer.update(dt)
        k = 0.4 + 1.6 * self.speed
        self._t += dt * k
        self._hue = (self._hue + dt * k * (0.012 + 0.05 * self.analyzer.level)) % 1.0
        gain = 0.55 + 1.5 * self.sensitivity
        self.spec = np.clip(np.asarray(self.analyzer.spectrum, dtype=np.float32) * gain, 0, 1)

    def resizeEvent(self, e):
        self._trail = None

    # ------------------------------------------------------------------ colores
    def col(self, f: float, a: float = 1.0, s: float = 0.7, v: float = 1.0) -> QColor:
        """Color en la posición f (0-1) de la paleta elegida: tema, arcoíris o personalizado."""
        if self.palette_mode == "rainbow":
            return _hue_color(self._hue + f * 0.8, s, v, a)
        if self.palette_mode == "custom":
            base = QColor(self.custom_color)
            h = base.hsvHueF() if base.hsvHueF() >= 0 else 0.55
            return _hue_color(h + (f - 0.5) * 0.12 + math.sin(self._t * 0.3) * 0.02, max(0.25, base.hsvSaturationF()),
                              v, a)
        pal = tm().theme.viz
        x = (f * (len(pal) - 1) + self._t * 0.05) % (len(pal) - 1)
        i = int(x)
        c0, c1 = QColor(pal[i]), QColor(pal[min(len(pal) - 1, i + 1)])
        u = x - i
        c = QColor(int(c0.red() + (c1.red() - c0.red()) * u), int(c0.green() + (c1.green() - c0.green()) * u),
                   int(c0.blue() + (c1.blue() - c0.blue()) * u))
        # Los colores del tema suelen ser pastel; en luz aditiva se saturan para no acabar en blanco.
        h = c.hsvHueF() if c.hsvHueF() >= 0 else 0.55
        return _hue_color(h, max(c.hsvSaturationF(), s), c.valueF() * v, a)

    # ------------------------------------------------------------------ pintado
    def paintEvent(self, e):
        p = QPainter(self)
        self.paint_frame(p, self.width(), self.height(), rounded=True)
        if self._title:
            p.setPen(QColor(255, 255, 255, 150))
            f = p.font()
            f.setPointSizeF(10)
            p.setFont(f)
            p.drawText(QRectF(16, self.height() - 34, self.width() - 32, 24),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._title)

    def paint_frame(self, p: QPainter, w: int, h: int, rounded: bool = True) -> None:
        t = tm().theme
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if rounded:
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(0, 0, w, h), 14, 14)
            p.setClipPath(clip)
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor(t.bg[0][1]).darker(150) if t.dark else QColor("#08223f"))
        bg.setColorAt(1, QColor(t.bg[1][1]).darker(180) if t.dark else QColor("#0b3b66"))
        if self.key in TRAIL:
            self._paint_trail_scene(p, w, h, bg)
        else:
            p.fillRect(QRectF(0, 0, w, h), bg)
            getattr(self, "_s_" + self.key)(p, w, h)

    def _paint_trail_scene(self, p: QPainter, w: int, h: int, bg) -> None:
        # Las estelas son difusas por naturaleza: media resolución basta y cuesta 4 veces menos.
        scale = 0.35 if self.low_power else (0.7 if getattr(self, "detail", "normal") == "high" else 0.5)
        tw, th = max(1, int(w * scale)), max(1, int(h * scale))
        if self._trail is None or self._trail.width() != tw or self._trail.height() != th:
            self._trail = QImage(tw, th, QImage.Format.Format_ARGB32_Premultiplied)
            self._trail.fill(QColor(0, 0, 0))
        q = QPainter(self._trail)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.fillRect(0, 0, tw, th, QColor(0, 0, 0, TRAIL_FADE.get(self.key, 36)))
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        getattr(self, "_s_" + self.key)(q, tw, th)
        q.end()
        p.fillRect(QRectF(0, 0, w, h), bg)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(0, 0, w, h), self._trail)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

    def _bands(self, n: int) -> np.ndarray:
        spec = self.spec
        if n >= len(spec):
            return spec
        return spec[: (len(spec) // n) * n].reshape(n, -1).mean(axis=1)

    # ------------------------------------------------------------------ escenas
    def _s_aero_waves(self, p: QPainter, w: int, h: int) -> None:
        a = self.analyzer
        I = self.intensity
        layers = 2 if self.low_power else 3
        pts = 24
        for k in range(layers):
            seg = self._bands(pts)
            path = QPainterPath()
            base = h * (0.80 - k * 0.11)
            path.moveTo(0, h)
            prev = None
            for i in range(pts + 1):
                x = w * i / pts
                v = float(seg[min(i, pts - 1)])
                y = base - (v * h * 0.32 * (0.5 + I)) * (1 - k * 0.15) \
                    - math.sin(i / pts * math.pi * 2 + self._t * (0.8 + k * 0.3)) * h * 0.04
                if prev is None:
                    path.lineTo(x, y)
                else:
                    mx = (prev[0] + x) / 2
                    path.cubicTo(mx, prev[1], mx, y, x, y)
                prev = (x, y)
            path.lineTo(w, h)
            path.closeSubpath()
            g = QLinearGradient(0, base - h * 0.35, 0, h)
            g.setColorAt(0, self.col(k / layers, 0.55 * (0.5 + I) - k * 0.06))
            g.setColorAt(1, self.col(k / layers + 0.2, 0.05))
            p.fillPath(path, g)
            p.setPen(QPen(QColor(255, 255, 255, int(110 * (0.4 + I) / (1 + k))), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        # Burbujas que nacen con los golpes de graves
        if a.beat > 0.6 and len(self._bubbles) < 30:
            for _ in range(2):
                self._bubbles.append([random.uniform(0.05, 0.95) * w, h + 10, random.uniform(4, 12) * (0.6 + I), 1.0])
        alive = []
        sprite = self._bubble_sprite()
        for b in self._bubbles:
            b[1] -= (1.2 + b[2] * 0.08) * (0.5 + self.speed) * (h / 200)
            b[3] -= 0.006
            if b[1] > -20 and b[3] > 0:
                alive.append(b)
                p.setOpacity(b[3])
                x = b[0] + math.sin(b[1] * 0.05) * 4
                p.drawImage(QRectF(x - b[2], b[1] - b[2], b[2] * 2, b[2] * 2), sprite)
        p.setOpacity(1.0)
        self._bubbles = alive

    def _draw_glow(self, p: QPainter, c: QPointF, r: float, color: QColor, alpha: float) -> None:
        """Halo radial grande: se escala una textura pequeña prerrenderizada en lugar de calcular un degradado
        píxel a píxel sobre cientos de miles de píxeles en cada fotograma."""
        key = color.name()
        cache = self.__dict__.setdefault("_glows", {})
        img = cache.get(key)
        if img is None:
            img = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            q = QPainter(img)
            g = QRadialGradient(QPointF(48, 48), 48)
            c0 = QColor(color)
            g.setColorAt(0, c0)
            c0 = QColor(color)
            c0.setAlpha(0)
            g.setColorAt(1, c0)
            q.fillRect(0, 0, 96, 96, g)
            q.end()
            if len(cache) > 24:
                cache.clear()
            cache[key] = img
        p.save()
        p.setOpacity(max(0.0, min(1.0, alpha)))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(c.x() - r, c.y() - r, r * 2, r * 2), img)
        p.restore()

    def _bubble_sprite(self) -> QImage:
        """Burbuja prerrenderizada una vez (dibujar la iridiscencia en cada fotograma es caro)."""
        key = self.col(0.3).name()
        if getattr(self, "_bubble_key", None) != key:
            from aero.ui.glass import paint_bubble

            img = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            q = QPainter(img)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_bubble(q, QPointF(32, 32), 31, QColor(key), fill=0.1, rim=1.0)
            q.end()
            self._bubble_img, self._bubble_key = img, key
        return self._bubble_img

    def _s_liquid_spectrum(self, p: QPainter, w: int, h: int) -> None:
        I = self.intensity
        n = 32 if self.low_power else 48
        v = self._bands(n)
        mid = h * 0.5
        amp = h * 0.42 * (0.45 + 0.6 * I)
        top = QPainterPath()
        xs = [w * 0.04 + (w * 0.92) * i / (n - 1) for i in range(n)]
        # Simétrico respecto al centro: graves en el centro, agudos hacia los lados.
        vals = [float(v[abs(i - n // 2) * 2 % n]) for i in range(n)]
        top.moveTo(xs[0], mid)
        prev = (xs[0], mid - vals[0] * amp)
        top.lineTo(*prev)
        for x, val in zip(xs[1:], vals[1:]):
            y = mid - val * amp
            mx = (prev[0] + x) / 2
            top.cubicTo(mx, prev[1], mx, y, x, y)
            prev = (x, y)
        top.lineTo(xs[-1], mid)
        g = QLinearGradient(0, mid - amp, 0, mid)
        g.setColorAt(0, self.col(0.0, 0.95))
        g.setColorAt(0.6, self.col(0.5, 0.75))
        g.setColorAt(1, self.col(1.0, 0.55))
        p.fillPath(top, g)
        # Reflejo (líquido): el mismo contorno invertido y atenuado
        p.save()
        p.translate(0, mid)
        p.scale(1, -0.55)
        p.translate(0, -mid)
        p.setOpacity(0.35)
        p.fillPath(top, g)
        p.restore()
        # Menisco brillante
        p.setPen(QPen(QColor(255, 255, 255, int(150 + 80 * I)), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(top)
        gl = QLinearGradient(0, mid - amp, 0, mid - amp * 0.4)
        gl.setColorAt(0, QColor(255, 255, 255, 70))
        gl.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(top, gl)
        p.fillRect(QRectF(0, mid, w, 1), self.col(0.5, 0.6))

    def _s_aurora(self, q: QPainter, w: int, h: int) -> None:
        bands = self.spec
        t = self._t
        steps = 48 if self.low_power else 96
        for k in range(4):
            seg = bands[k * len(bands) // 4:(k + 1) * len(bands) // 4]
            energy = float(seg.mean()) if len(seg) else 0.0
            path = QPainterPath()
            base = h * (0.35 + k * 0.12)
            path.moveTo(0, h)
            for i in range(steps + 1):
                x = w * i / steps
                y = base + math.sin(i / steps * math.pi * (2 + k) + t * (0.6 + k * 0.25)) * h * (0.05 + energy * 0.22)
                y += math.sin(i / steps * 11 + t * 1.7) * h * 0.015
                path.lineTo(x, y)
            path.lineTo(w, h)
            path.closeSubpath()
            g = QLinearGradient(0, base - h * 0.25, 0, h)
            g.setColorAt(0, self.col(k / 4, 0.0))
            g.setColorAt(0.25, self.col(k / 4, (0.05 + energy * 0.16) * (0.4 + self.intensity)))
            g.setColorAt(1, self.col(k / 4 + 0.1, 0.0, v=0.5))
            q.fillPath(path, g)

    def _s_particles(self, q: QPainter, w: int, h: int) -> None:
        a = self.analyzer
        cx, cy = w / 2, h / 2
        limit = 160 if self.low_power else 360
        spawn = int((2 + a.level * 14 + a.beat * 26) * (0.5 + self.intensity))
        spec = self.spec
        for _ in range(spawn):
            if len(self._particles) >= limit:
                break
            band = random.randrange(len(spec))
            ang = random.uniform(0, math.tau)
            speed = (0.6 + spec[band] * 5 + a.beat * 3) * (w / 600) * (0.5 + self.speed)
            self._particles.append([cx, cy, math.cos(ang) * speed, math.sin(ang) * speed, 1.0, band / len(spec)])
        alive = []
        # Agrupadas en 4 colores x 3 tamaños: 12 llamadas de dibujo por fotograma en vez de cientos.
        buckets: dict[tuple[int, int], QPolygonF] = {}
        for pt in self._particles:
            pt[0] += pt[2]
            pt[1] += pt[3]
            pt[2] *= 1.01
            pt[3] *= 1.01
            pt[4] -= 0.012
            if pt[4] > 0 and -10 < pt[0] < w + 10 and -10 < pt[1] < h + 10:
                alive.append(pt)
                key = (min(3, int(pt[5] * 4)), min(2, int((1 - pt[4]) * 3)))
                buckets.setdefault(key, QPolygonF()).append(QPointF(pt[0], pt[1]))
        for (ci, si), poly in buckets.items():
            pen = QPen(self.col(ci / 3, 0.55 - si * 0.15), 2.0 + si * 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            q.setPen(pen)
            q.drawPoints(poly)
        self._particles = alive
        cr = 40 + a.bass * 90
        core = QRadialGradient(QPointF(cx, cy), cr)
        core.setColorAt(0, self.col(0.2, 0.12 + 0.25 * a.beat, s=0.5))
        core.setColorAt(1, QColor(0, 0, 0, 0))
        q.fillRect(QRectF(cx - cr, cy - cr, cr * 2, cr * 2), core)

    def _s_eq_classic(self, p: QPainter, w: int, h: int) -> None:
        n = 16 if self.low_power else 24
        v = self._bands(n)
        if len(self._eq_peaks) != n:
            self._eq_peaks = np.zeros(n, dtype=np.float32)
        self._eq_peaks = np.maximum(self._eq_peaks - 0.015 * (0.5 + self.speed), v)
        rows = 16
        gap = 3.0
        bw = (w - 30 - gap * (n - 1)) / n
        bh = (h - 30 - 2 * (rows - 1)) / rows
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        lit: list[list[QRectF]] = [[], [], []]
        dim: list[QRectF] = []
        for i in range(n):
            on = int(round(float(v[i]) * rows * (0.6 + 0.5 * self.intensity)))
            x = 15 + i * (bw + gap)
            for r in range(rows):
                y = h - 15 - (r + 1) * bh - r * 2
                zone = 0 if r < rows * 0.6 else (1 if r < rows * 0.85 else 2)
                (lit[zone] if r < on else dim).append(QRectF(x, y, bw, bh))
            pk = min(rows - 1, int(float(self._eq_peaks[i]) * rows * (0.6 + 0.5 * self.intensity)))
            py = h - 15 - (pk + 1) * bh - pk * 2
            p.fillRect(QRectF(x, py, bw, max(2.0, bh * 0.35)), QColor(255, 255, 255, 220))
        # drawRects(): camino rápido de rectángulos (un trazado con cientos de celdas es mucho más lento).
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 14))
        p.drawRects(dim)
        zones = [self.col(0.0), self.col(0.5), self.col(1.0)] if self.palette_mode != "theme" else \
            [QColor("#3ff07a"), QColor("#ffe24f"), QColor("#ff5a5a")]
        for cells, c in zip(lit, zones):
            if cells:
                p.setBrush(c)
                p.drawRects(cells)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _s_glass_bars(self, p: QPainter, w: int, h: int) -> None:
        a = self.analyzer
        spec, peaks = self.spec, np.clip(np.asarray(a.peaks) * (0.55 + 1.5 * self.sensitivity), 0, 1)
        if self.low_power:
            spec = spec.reshape(-1, 2).mean(axis=1)
            peaks = peaks.reshape(-1, 2).max(axis=1)
        n = len(spec)
        gap = 3.0
        bw = max(2.0, (w - 40 - gap * (n - 1)) / n)
        base, maxh = h * 0.66, h * 0.58 * (0.6 + 0.5 * self.intensity)
        bars, refl, caps = [], [], []
        x = 20.0
        # Rectángulos alineados a píxel y sin suavizado: nítidos y unas 6 veces más baratos que curvas.
        # drawRects() va por el camino rápido de rectángulos (casi 4 veces más rápido que un trazado).
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(Qt.PenStyle.NoPen)
        for v, pk in zip(spec.tolist(), peaks.tolist()):
            bh = max(2.0, v * maxh)
            bars.append(QRectF(round(x), round(base - bh), max(1, round(bw)), round(bh)))
            refl.append(QRectF(x, base + 2, bw, bh * 0.45))
            caps.append(QRectF(x, base - pk * maxh - 4, bw, 2))
            x += bw + gap
        hue = QLinearGradient(20, 0, w - 20, 0)
        for k in range(7):
            hue.setColorAt(k / 6, self.col(k / 6, 1.0, s=0.62))
        p.setBrush(hue)
        p.drawRects(bars)
        gloss = QLinearGradient(0, base - maxh, 0, base)
        gloss.setColorAt(0, QColor(255, 255, 255, 110))
        gloss.setColorAt(0.48, QColor(255, 255, 255, 40))
        gloss.setColorAt(0.5, QColor(255, 255, 255, 8))
        gloss.setColorAt(1, QColor(0, 0, 0, 60))
        p.setBrush(gloss)
        p.drawRects(bars)
        p.setOpacity(0.22)
        p.setBrush(hue)
        p.drawRects(refl)
        p.setOpacity(1.0)
        p.setBrush(QColor(255, 255, 255, 200))
        p.drawRects(caps)
        p.setBrush(Qt.BrushStyle.NoBrush)
        hl = QLinearGradient(0, 0, w, 0)
        hl.setColorAt(0, QColor(255, 255, 255, 0))
        hl.setColorAt(0.5, self.col(0.5, 0.6 + 0.4 * a.beat, s=0.3))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, base, w, 1.5), hl)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def _s_energy_flow(self, q: QPainter, w: int, h: int) -> None:
        a = self.analyzer
        n = 120 if self.low_power else 220
        samples = np.clip(a.latest(n * 4)[::4] * (0.6 + 1.6 * self.sensitivity), -1, 1)
        mid = h / 2
        amp = h * 0.38 * (0.5 + self.intensity * 0.7)
        xs = np.linspace(0, w, n)
        for layer in range(3):
            pts = QPolygonF()
            ys = mid + samples * amp * (1.0 - layer * 0.25) + (layer - 1) * h * 0.06 * a.bass
            for x, y in zip(xs.tolist(), ys.tolist()):
                pts.append(QPointF(x, y))
            # Trazo cosmético de 1 px: la forma de onda zigzaguea mucho y un trazo grueso suavizado es
            # muy caro de calcular; el brillo lo aporta la estela acumulada.
            pen = QPen(self.col(layer * 0.3, 0.55 - layer * 0.15), 1.0)
            pen.setCosmetic(True)
            q.setPen(pen)
            q.drawPolyline(pts)
        if a.beat > 0.3:
            rr = w * 0.4
            rg = QRadialGradient(QPointF(w / 2, mid), rr)
            rg.setColorAt(0, self.col(0.7, 0.18 * a.beat))
            rg.setColorAt(1, QColor(0, 0, 0, 0))
            q.fillRect(QRectF(w / 2 - rr, mid - rr, rr * 2, rr * 2).intersected(QRectF(0, 0, w, h)), rg)

    def _s_nebula(self, q: QPainter, w: int, h: int) -> None:
        a = self.analyzer
        t = self._t
        cx, cy = w / 2, h / 2
        bands = self._bands(3)
        q.setPen(Qt.PenStyle.NoPen)
        for k in range(6):
            energy = float(bands[k % 3])
            ang = t * (0.25 + k * 0.07) * (1 if k % 2 else -1) + k * 1.05
            rad = min(w, h) * (0.12 + 0.18 * (k % 3) / 2)
            x, y = cx + math.cos(ang) * rad * 1.5, cy + math.sin(ang) * rad
            r = min(w, h) * (0.18 + 0.30 * energy) * (0.6 + 0.5 * self.intensity)
            g = QRadialGradient(QPointF(x, y), r)
            g.setColorAt(0, self.col(k / 6, (0.04 + 0.10 * energy) * (0.5 + self.intensity)))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            q.setBrush(g)
            q.drawEllipse(QPointF(x, y), r, r)
        # Estrellas que parpadean con los agudos
        rnd = random.Random(int(t * 4))
        stars = 6 if self.low_power else 14
        hi = float(self.spec[-16:].mean())
        for _ in range(stars):
            sx, sy = rnd.uniform(0, w), rnd.uniform(0, h)
            q.setBrush(QColor(255, 255, 255, int(60 + 180 * hi * rnd.random())))
            q.drawEllipse(QPointF(sx, sy), 1.2, 1.2)
        if a.beat > 0.5:
            core = QRadialGradient(QPointF(cx, cy), min(w, h) * 0.3)
            core.setColorAt(0, self.col(0.5, 0.15 * a.beat, s=0.3))
            core.setColorAt(1, QColor(0, 0, 0, 0))
            q.fillRect(0, 0, w, h, core)

    def _s_water_rings(self, p: QPainter, w: int, h: int) -> None:
        a = self.analyzer
        cx, cy = w / 2, h / 2
        maxr = math.hypot(w, h) / 2
        if (a.beat > 0.55 and (not self._rings or self._rings[-1][0] > 0.08)) or \
                (a.level > 0.25 and random.random() < 0.04):
            drop = (cx, cy) if a.beat > 0.55 else (random.uniform(0.2, 0.8) * w, random.uniform(0.25, 0.75) * h)
            self._rings.append([0.0, drop[0], drop[1], 0.5 + 0.5 * a.level, random.random()])
        step = 0.006 * (0.5 + 1.5 * self.speed)
        alive = []
        p.setBrush(Qt.BrushStyle.NoBrush)
        for r in self._rings:
            r[0] += step
            if r[0] < 1.0:
                alive.append(r)
                rad = r[0] * maxr
                alpha = (1 - r[0]) ** 1.5 * r[3] * (0.5 + self.intensity)
                p.setPen(QPen(self.col(r[4], alpha), 2.5 * (1 - r[0]) + 0.8))
                p.drawEllipse(QPointF(r[1], r[2]), rad, rad * 0.62)
                p.setPen(QPen(QColor(255, 255, 255, int(90 * alpha)), 1))
                p.drawEllipse(QPointF(r[1], r[2]), rad * 0.94, rad * 0.94 * 0.62)
        self._rings = alive[-40:]
        # Superficie: ondas del espectro alrededor del centro
        n = 48
        v = self._bands(n)
        path = QPainterPath()
        base = min(w, h) * 0.16
        for i in range(n + 1):
            ang = i / n * math.tau
            rr = base * (1 + 0.35 * float(v[i % n]) * (0.5 + self.intensity))
            pt = QPointF(cx + math.cos(ang) * rr * 1.3, cy + math.sin(ang) * rr * 0.62 * 1.3)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        g = QRadialGradient(QPointF(cx, cy), base * 1.6)
        g.setColorAt(0, self.col(0.3, 0.35))
        g.setColorAt(1, self.col(0.6, 0.05))
        p.fillPath(path, g)
        p.setPen(QPen(QColor(255, 255, 255, 120), 1.2))
        p.drawPath(path)

    def _s_fluid_motion(self, q: QPainter, w: int, h: int) -> None:
        t = self._t
        bands = self._bands(5)
        q.setPen(Qt.PenStyle.NoPen)
        for k in range(5):
            e = float(bands[k])
            x = w * (0.5 + 0.38 * math.sin(t * (0.31 + k * 0.07) + k * 1.3))
            y = h * (0.5 + 0.34 * math.sin(t * (0.43 + k * 0.05) + k * 2.1))
            r = min(w, h) * (0.14 + 0.22 * e) * (0.6 + 0.5 * self.intensity)
            g = QRadialGradient(QPointF(x, y), r)
            g.setColorAt(0, self.col(k / 5, 0.22 * (0.5 + self.intensity)))
            g.setColorAt(0.55, self.col(k / 5, 0.07 * (0.5 + self.intensity)))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            q.setBrush(g)
            q.drawEllipse(QPointF(x, y), r, r)

    def _s_ring(self, p: QPainter, w: int, h: int) -> None:
        a = self.analyzer
        cx, cy = w / 2, h / 2
        base = min(w, h) * (0.2 + a.bass * 0.04)
        spec = self.spec
        n = len(spec)
        gr = base * 2.4
        self._draw_glow(p, QPointF(cx, cy), gr, self.col(0.0), 0.25 + 0.3 * a.beat)
        # Cada radio es un cuadrilátero convexo con un degradado radial común. drawConvexPolygon() usa el
        # rasterizador rápido de polígonos convexos: 3 veces más barato que rellenar un trazado con todos.
        half = max(1.0, base * math.pi / n * 0.35)
        top = base + 8 + min(w, h) * 0.3 * (0.6 + 0.5 * self.intensity)
        g = QRadialGradient(QPointF(cx, cy), top)
        g.setColorAt(base / top, self.col(0.0, 0.75))
        g.setColorAt(min(1.0, (base + top) / 2 / top), self.col(0.5, 0.65))
        g.setColorAt(1.0, self.col(1.0, 0.55))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        for i in range(n):
            r2 = base + 8 + float(spec[i]) * (top - base - 8)
            for mirror in (1, -1):
                ang = -math.pi / 2 + mirror * (i + 0.5) / n * math.pi
                ca, sa = math.cos(ang), math.sin(ang)
                nx, ny = -sa * half, ca * half
                p.drawConvexPolygon(QPolygonF([QPointF(cx + ca * base + nx, cy + sa * base + ny),
                                               QPointF(cx + ca * r2 + nx, cy + sa * r2 + ny),
                                               QPointF(cx + ca * r2 - nx, cy + sa * r2 - ny),
                                               QPointF(cx + ca * base - nx, cy + sa * base - ny)]))
        p.setPen(QPen(QColor(255, 255, 255, 120), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), base - 6, base - 6)
