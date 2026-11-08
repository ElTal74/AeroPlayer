"""Galería de visualizadores: vistas previas animadas, favoritos, colores y ajustes de intensidad, velocidad y
sensibilidad. Elegir uno cambia el visualizador al momento sin interrumpir la música.

Las vistas previas usan una señal de demostración (no la del reproductor) para no alterar el análisis real.
Solo se animan la elegida y la que está bajo el ratón, mientras la galería es visible y a 15 fps.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QGridLayout, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from aero.ui.glasswindow import TrDialog
from aero.ui import icons
from aero.ui.glass import HoverLight, defer_paint, h_layout, label, paint_bubble, tm
from aero.ui.visualizer import SCENE_KEYS, SCENE_NAMES, DemoAnalyzer, Visualizer
from aero.i18n import tr

DESCRIPTIONS = {
    "aero_waves": "Ondas de gel y burbujas",
    "liquid_spectrum": "Espectro líquido simétrico",
    "aurora": "Cortinas de luz",
    "particles": "Partículas desde el centro",
    "eq_classic": "Ecualizador de bloques",
    "glass_bars": "Barras de cristal",
    "energy_flow": "Forma de onda luminosa",
    "nebula": "Nubes de color y estrellas",
    "water_rings": "Gotas y ondas de agua",
    "fluid_motion": "Gotas de luz que se funden",
    "ring": "Espectro circular",
}


class VizCard(QToolButton):
    """Tarjeta con miniatura animada, nombre y estrella de favorito."""
    chosen = Signal(str)
    favorite = Signal(str, bool)

    W, H = 172, 98

    def __init__(self, key: str, settings, parent=None):
        super().__init__(parent)
        self.key = key
        self.s = settings
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.W + 12, self.H + 44)
        self.setToolTip(DESCRIPTIONS.get(key, ""))
        self.setAccessibleName(f"Visualizador {SCENE_NAMES[key]}")
        self.light = HoverLight(self)
        self.viz = Visualizer(DemoAnalyzer())
        self.viz.set_scene_key(key)
        self.viz.resize(self.W, self.H)
        self.img = QImage(self.W * 2, self.H * 2, QImage.Format.Format_ARGB32_Premultiplied)
        self.img.setDevicePixelRatio(2.0)
        self.img.fill(QColor(0, 0, 0, 0))
        self._warm = False
        self._queued = False
        self.clicked.connect(lambda: self.chosen.emit(self.key))

    def is_fav(self) -> bool:
        return self.key in (self.s.get("visualizer_favorites") or [])

    def star_rect(self) -> QRectF:
        return QRectF(self.W - 20, 10, 22, 22)

    def mousePressEvent(self, e):
        if self.star_rect().contains(e.position()):
            self.favorite.emit(self.key, not self.is_fav())
            e.accept()
            return
        super().mousePressEvent(e)

    def render(self, dt: float):
        v = self.viz
        v.intensity, v.speed, v.sensitivity = (float(self.s.get("visualizer_intensity")),
                                               float(self.s.get("visualizer_speed")),
                                               float(self.s.get("visualizer_sensitivity")))
        v.palette_mode, v.custom_color = self.s.get("visualizer_palette"), self.s.get("visualizer_color")
        v.advance(dt)
        p = QPainter(self.img)
        v.paint_frame(p, self.W, self.H, rounded=False)
        p.end()
        self.update()

    def _warm_up(self):
        """Fotograma fijo representativo: la escena se deja correr un momento antes de mostrarla."""
        self._queued = False
        if not self._warm:
            self._warm = True
            for _ in range(30):
                self.render(1 / 30)

    def paintEvent(self, e):
        t = tm().theme
        if not self._warm and not self._queued:
            self._queued = True
            defer_paint(self._warm_up)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(6.5, 4.5, self.W - 1, self.H - 1)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.save()
        p.setClipPath(path)
        p.drawImage(r, self.img)
        p.restore()
        sel = self.isChecked()
        edge = QColor(t.accent) if sel else QColor(255, 255, 255, int(100 + 110 * self.light.value))
        p.setPen(QPen(edge, 2 if sel else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        fav = self.is_fav()
        sr = self.star_rect()
        paint_bubble(p, sr.center(), 11, QColor(t.accent2 if fav else "#ffffff"), fill=0.45 if fav else 0.1,
                     rim=0.9)
        pm = icons.pixmap("star", "#ffffff", 14)
        p.drawPixmap(QRectF(sr.center().x() - 7, sr.center().y() - 7, 14, 14), pm, QRectF(pm.rect()))
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        f.setBold(sel)
        p.setFont(f)
        p.setPen(QColor(t.text))
        p.drawText(QRectF(6, self.H + 8, self.W, 18), Qt.AlignmentFlag.AlignCenter, SCENE_NAMES[self.key])
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(t.text2))
        p.drawText(QRectF(6, self.H + 25, self.W, 16), Qt.AlignmentFlag.AlignCenter,
                   p.fontMetrics().elidedText(DESCRIPTIONS.get(self.key, ""), Qt.TextElideMode.ElideRight, self.W))
        if sel:
            paint_bubble(p, QPointF(r.left() + 14, r.top() + 14), 8, QColor(t.accent), fill=0.6, rim=1.0)


class VisualizerGallery(QWidget):
    """Galería y ajustes de los visualizadores (se usa en Ajustes y en el reproductor)."""

    def __init__(self, settings, columns: int = 4, parent=None):
        super().__init__(parent)
        from aero.ui.pages.theme_studio import ColorButton, ValueSlider

        self.s = settings
        self.cards: dict[str, VizCard] = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        self.grid = grid
        self.columns = columns
        self._layout_cards()

        self.enabled = QCheckBox(tr("Visualizador activado"))
        self.enabled.setChecked(bool(settings.get("visualizer_enabled")))
        self.enabled.toggled.connect(lambda on: settings.set("visualizer_enabled", on))
        full = QCheckBox(tr("Abrir a pantalla completa"))
        full.setToolTip(tr("Al activar el visualizador con música, el reproductor pasa a pantalla completa"))
        full.setChecked(bool(settings.get("visualizer_fullscreen")))
        full.toggled.connect(lambda on: settings.set("visualizer_fullscreen", on))
        ql = QCheckBox(tr("En la vista rápida de audio"))
        ql.setChecked(bool(settings.get("quicklook_visualizer")))
        ql.toggled.connect(lambda on: settings.set("quicklook_visualizer", on))

        self.palette = QButtonGroup(self)
        pal_row = []
        for key, text in (("theme", "Colores del tema"), ("rainbow", "Arcoíris"), ("custom", "Personalizado")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("kind", "flat")
            b.setChecked(settings.get("visualizer_palette") == key)
            b.clicked.connect(lambda _c=False, k=key: self._palette(k))
            self.palette.addButton(b)
            pal_row.append(b)
        self.color = ColorButton("Color", settings.get("visualizer_color"))
        self.color.picked.connect(lambda c: (settings.set("visualizer_color", c), self._palette("custom")))

        sliders = QGridLayout()
        sliders.setHorizontalSpacing(14)
        for i, (key, text) in enumerate((("visualizer_intensity", "Intensidad"), ("visualizer_speed", "Velocidad"),
                                         ("visualizer_sensitivity", "Sensibilidad"))):
            vs = ValueSlider(settings.get(key), text)
            vs.changed.connect(lambda v, k=key: settings.set(k, v))
            sliders.addWidget(label(text, "muted"), i, 0)
            sliders.addWidget(vs, i, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addLayout(grid)
        lay.addLayout(h_layout(*pal_row, self.color, None, spacing=4))
        lay.addLayout(sliders)
        lay.addLayout(h_layout(self.enabled, full, ql, None, spacing=24))

        self._timer = QTimer(self)
        self._timer.setInterval(66)
        self._timer.timeout.connect(self._tick)
        self._last = time.perf_counter()
        settings.changed.connect(self._setting_changed)
        self._sync()

    def _layout_cards(self):
        favs = [k for k in (self.s.get("visualizer_favorites") or []) if k in SCENE_KEYS]
        order = favs + [k for k in SCENE_KEYS if k not in favs]
        for i, key in enumerate(order):
            c = self.cards.get(key)
            if c is None:
                c = VizCard(key, self.s)
                c.chosen.connect(lambda k: self.s.set("visualizer_key", k))
                c.favorite.connect(self._favorite)
                self.cards[key] = c
            self.grid.addWidget(c, i // self.columns, i % self.columns)

    def _favorite(self, key: str, on: bool):
        favs = [k for k in (self.s.get("visualizer_favorites") or []) if k != key]
        if on:
            favs.insert(0, key)
        self.s.set("visualizer_favorites", favs)
        self._layout_cards()

    def _palette(self, key: str):
        self.s.set("visualizer_palette", key)
        for b, k in zip(self.palette.buttons(), ("theme", "rainbow", "custom")):
            b.setChecked(k == key)

    def _setting_changed(self, key: str):
        if key in ("visualizer_key", "visualizer_favorites"):
            self._sync()
        elif key == "visualizer_enabled":
            self.enabled.blockSignals(True)
            self.enabled.setChecked(bool(self.s.get(key)))
            self.enabled.blockSignals(False)

    def _sync(self):
        cur = self.s.get("visualizer_key")
        for k, c in self.cards.items():
            c.setChecked(k == cur)
            c.update()

    def showEvent(self, e):
        super().showEvent(e)
        self._last = time.perf_counter()
        self._timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def _tick(self):
        now = time.perf_counter()
        dt = min(0.1, now - self._last)
        self._last = now
        if not self.isVisible() or not self.window().isActiveWindow() and not self.window().isVisible():
            return
        # Solo se anima la vista previa elegida y la que está bajo el ratón; el resto muestra un fotograma fijo.
        for c in self.cards.values():
            if (c.isChecked() or c.light.value > 0.01) and c.isVisible() and not c.visibleRegion().isEmpty():
                c.render(dt)


class VisualizerDialog(TrDialog):
    """Galería en una ventana propia (desde el reproductor)."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Visualizadores"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addWidget(VisualizerGallery(settings, columns=4))
        close = QPushButton(tr("Cerrar"))
        close.clicked.connect(self.accept)
        lay.addLayout(h_layout(None, close))
