"""Barra lateral de navegación con indicador animado y modo compacto."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QToolButton, QVBoxLayout, QWidget

from aero import APP_NAME
from aero.i18n import tr
from aero.ui.glass import GlassPanel, IconButton, make_app_icon, tm

PAGES = [
    ("home", "Inicio", "home"),
    ("library", "Biblioteca", "library"),
    ("player", "Reproductor", "player"),
    ("viewer", "Visor", "viewer"),
    ("converter", "Conversor", "convert"),
    ("playlists", "Listas y favoritos", "playlists"),
    ("settings", "Ajustes", "settings"),
]


class _Indicator(QWidget):
    def paintEvent(self, e):
        # Burbuja de selección: cuerpo transparente, borde iridiscente y reflejo.
        from aero.ui.glass import paint_bubble

        t = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = min(self.width(), self.height()) / 2 - 1
        paint_bubble(p, QRectF(self.rect()).center(), r, QColor(t.accent), fill=0.30, rim=1.0)


class NavButton(QToolButton):
    def __init__(self, key: str, text: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.key = key
        from aero.i18n import tr

        text = tr(text)
        self.full_text = text
        self.icon_name = icon_name
        self.setText("  " + text)
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(20, 20))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(42)
        self.setStyleSheet("QToolButton { text-align: left; padding-left: 12px; font-size: 10.5pt; border-radius: 11px; }"
                           "QToolButton:checked { background: transparent; border: 1px solid transparent; font-weight: 600; }")
        self.refresh()
        tm().changed.connect(self.refresh)

    def refresh(self):
        self.setIcon(tm().icon(self.icon_name, 20, True))

    def set_compact(self, on: bool):
        self.setText("" if on else "  " + self.full_text)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if on else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)


class Sidebar(GlassPanel):
    navigate = Signal(str)
    compact_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent, radius=20)
        self.compact = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 12)
        lay.setSpacing(3)
        self.logo = QLabel()
        self.logo.setPixmap(make_app_icon(64).scaled(34, 34, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        self.brand = QLabel(APP_NAME)
        self.brand.setStyleSheet("font-family: 'Segoe UI Variable Display','Segoe UI'; font-size: 13.5pt; font-weight: 600;")
        top = QWidget()
        from aero.ui.glass import h_layout

        top.setLayout(h_layout(self.logo, self.brand, None, spacing=10, margins=(6, 0, 0, 0)))
        lay.addWidget(top)
        lay.addSpacing(16)
        self.indicator = _Indicator(self)
        self.indicator.lower()
        self.buttons: dict[str, NavButton] = {}
        for key, text, ic in PAGES:
            b = NavButton(key, text, ic)
            b.clicked.connect(lambda _c=False, k=key: self._clicked(k))
            self.buttons[key] = b
            if key == "settings":
                lay.addStretch(1)
            lay.addWidget(b)
        self.toggle = IconButton("menu", tr("Contraer o expandir la barra lateral"), 18)
        self.toggle.clicked.connect(lambda: self.set_compact(not self.compact))
        lay.addSpacing(6)
        lay.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self._anim = QPropertyAnimation(self.indicator, b"geometry", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.current = "home"
        self.setFixedWidth(224)

    def _clicked(self, key: str):
        self.select(key)
        self.navigate.emit(key)

    def select(self, key: str):
        self.current = key
        b = self.buttons.get(key)
        if not b:
            return
        b.setChecked(True)
        target = b.geometry()
        if tm().reduce_motion or not self.indicator.isVisible() or self.indicator.geometry().isEmpty():
            self.indicator.setGeometry(target)
        else:
            self._anim.stop()
            self._anim.setStartValue(self.indicator.geometry())
            self._anim.setEndValue(target)
            self._anim.start()
        self.indicator.show()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        b = self.buttons.get(self.current)
        if b:
            self.indicator.setGeometry(b.geometry())

    def showEvent(self, e):
        super().showEvent(e)
        self.select(self.current)

    def set_compact(self, on: bool):
        self.compact = on
        self.brand.setVisible(not on)
        for b in self.buttons.values():
            b.set_compact(on)
        self.setFixedWidth(68 if on else 224)
        self.compact_changed.emit(on)
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda: self.select(self.current))
