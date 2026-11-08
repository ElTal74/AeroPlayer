"""Ventana de cristal sin marco: transparencia real, bordes redimensionables, arrastre nativo y botones propios."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import QDialog, QApplication, QHBoxLayout, QVBoxLayout, QWidget

from aero.ui import winfx
from aero.ui.corners import RADII
from aero.ui.glass import Backdrop, IconButton, tm

RADIUS = RADII["window"]  # igual que el redondeo de Windows 11, que es el que recorta el desenfoque


EDGE = 6


def _edge_cursor(edges) -> Qt.CursorShape | None:
    L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
    if edges in (L | T, R | B):
        return Qt.CursorShape.SizeFDiagCursor
    if edges in (R | T, L | B):
        return Qt.CursorShape.SizeBDiagCursor
    if edges in (L, R):
        return Qt.CursorShape.SizeHorCursor
    if edges in (T, B):
        return Qt.CursorShape.SizeVerCursor
    return None


class _EdgeFilter(QObject):
    """Redimensionado por los bordes aunque los hijos cubran toda la ventana.

    El cursor de borde se pone en la propia ventana (no un cursor global de la aplicación): así nunca se
    queda «enganchado» al pasar a otra ventana, a una superficie de vídeo o fuera de la ventana, y los
    hijos con cursor propio (botones, línea de tiempo) siguen mostrando el suyo.
    """

    def __init__(self, win: "GlassWindow"):
        super().__init__(win)
        self.win = win
        self._holder: QWidget | None = None   # ventana (o capa) en la que pusimos el cursor de borde

    def _edges(self, gpos: QPoint) -> Qt.Edge:
        w = self.win
        e = Qt.Edge(0)
        if w.isMaximized() or w.isFullScreen() or not w.resizable or not w.isVisible():
            return e
        p = w.mapFromGlobal(gpos)
        if not w.rect().contains(p):
            return e
        if p.x() <= EDGE:
            e |= Qt.Edge.LeftEdge
        elif p.x() >= w.width() - EDGE:
            e |= Qt.Edge.RightEdge
        if p.y() <= EDGE:
            e |= Qt.Edge.TopEdge
        elif p.y() >= w.height() - EDGE:
            e |= Qt.Edge.BottomEdge
        return e

    def _set(self, holder: QWidget | None, shape) -> None:
        if self._holder is not None and (holder is not self._holder or shape is None):
            try:
                self._holder.unsetCursor()
            except RuntimeError:
                pass
            self._holder = None
        if holder is not None and shape is not None:
            holder.setCursor(shape)
            self._holder = holder

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.HoverMove, QEvent.Type.Leave):
            return False
        if not isinstance(obj, QWidget):
            return False
        top = obj.window()
        if getattr(top, "drag_target", top) is not self.win:
            if self._holder is not None and t != QEvent.Type.Leave:
                self._set(None, None)  # el ratón está en otra ventana: fuera el cursor de borde
            return False
        if t == QEvent.Type.Leave:
            if obj is top:
                self._set(None, None)
            return False
        edges = self._edges(QCursor.pos())
        if t == QEvent.Type.MouseButtonPress:
            if edges and ev.button() == Qt.MouseButton.LeftButton and self.win.windowHandle() is not None:
                self._set(None, None)
                self.win.windowHandle().startSystemResize(edges)
                return True
            return False
        if not (ev.buttons() if hasattr(ev, "buttons") else 0):
            self._set(top, _edge_cursor(edges) if edges else None)
        return False


class OverlayWindow(QWidget):
    """Ventana transparente de controles encima de otra (vídeo); sus bordes redimensionan la de debajo
    (atributo `drag_target`)."""


class DragArea(QWidget):
    """Zona que mueve la ventana (con Snap de Windows) y maximiza con doble clic."""
    double_clicked = Signal()

    def _target(self) -> QWidget:
        return getattr(self.window(), "drag_target", self.window())

    def mousePressEvent(self, e):
        w = self._target()
        if e.button() == Qt.MouseButton.LeftButton and w.windowHandle() is not None:
            w.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        w = self._target()
        if getattr(w, "resizable", True):
            w.showNormal() if w.isMaximized() else w.showMaximized()
        self.double_clicked.emit()


class CloseButton(IconButton):
    """Cerrar: se vuelve roja al pasar el ratón, como en Windows."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.danger = True


class WindowButtons(QWidget):
    def __init__(self, win: QWidget, maximize: bool = True, parent=None):
        super().__init__(parent)
        self.win = win
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.min = IconButton("minus", "Minimizar", 14, button=32)
        self.min.clicked.connect(win.showMinimized)
        lay.addWidget(self.min)
        self.max = None
        if maximize:
            self.max = IconButton("maximize", "Maximizar", 14, button=32)
            self.max.clicked.connect(lambda: win.showNormal() if win.isMaximized() else win.showMaximized())
            lay.addWidget(self.max)
        self.close_btn = CloseButton("close", "Cerrar", 14, button=32)
        self.close_btn.clicked.connect(win.close)
        lay.addWidget(self.close_btn)
        for b in (self.min, self.max, self.close_btn):
            if b is not None:
                b.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def sync(self):
        if self.max is not None:
            self.max.set_icon_name("restore" if self.win.isMaximized() else "maximize")
            self.max.setToolTip("Restaurar" if self.win.isMaximized() else "Maximizar")


class GlassWindow(QWidget):
    """Base de todas las ventanas de AERO Player. El contenido se coloca en `self.backdrop`."""

    def __init__(self, flags=Qt.WindowType(0), flat: bool = False, resizable: bool = True):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resizable = resizable
        self.backdrop = Backdrop(self, RADIUS)
        self.backdrop.flat = flat
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.backdrop)
        self._edge = _EdgeFilter(self)
        QApplication.instance().installEventFilter(self._edge)
        self._buttons: list[WindowButtons] = []
        tm().changed.connect(self.apply_glass)

    def window_buttons(self, maximize: bool = True) -> WindowButtons:
        b = WindowButtons(self, maximize)
        self._buttons.append(b)
        return b

    def apply_glass(self) -> None:
        if not self.isVisible():
            return
        hwnd = int(self.winId())
        t = tm().theme
        base = QColor(t.bg[1][1])
        tint = (0x30 << 24) | (base.blue() << 16) | (base.green() << 8) | base.red()
        winfx.set_round_corners(hwnd, True)
        # Sin desenfoque en perfiles ligeros: el acrílico lo calcula la GPU del sistema en cada recomposición.
        winfx.set_glass(hwnd, "blur" if tm().blur_enabled else ("clear" if tm().glass_mode == "blur"
                                                                 else tm().glass_mode), tint)
        self._update_region()

    def _update_region(self) -> None:
        if not self.isVisible():
            return
        full = self.isMaximized() or self.isFullScreen()
        dpr = self.devicePixelRatioF()
        winfx.set_round_region(int(self.winId()), round(self.width() * dpr), round(self.height() * dpr),
                               0 if full else round(RADIUS * dpr))

    def showEvent(self, e):
        if not getattr(self, "_translated", False):
            # Red de seguridad: textos fijos que llegaron por variables se traducen al mostrarse por primera vez
            self._translated = True
            from aero.i18n.widgets import translate_tree

            translate_tree(self)
        super().showEvent(e)
        self.apply_glass()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_region()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            self._update_region()
            self.backdrop.update()
            for b in self._buttons:
                b.sync()


def kill_override_cursor() -> None:
    while QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()



class TrDialog(QDialog):
    """Diálogo propio de AERO: al mostrarse por primera vez traduce sus textos fijos (ver `aero.i18n.widgets`)."""

    def showEvent(self, e):
        if not getattr(self, "_translated", False):
            self._translated = True
            from aero.i18n.widgets import translate_tree

            translate_tree(self)
        super().showEvent(e)
