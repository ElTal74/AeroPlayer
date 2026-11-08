"""Sistema único de esquinas y bordes de ventana.

* `RADII`: radios de toda la interfaz (ventanas, paneles, tarjetas, controles, menús). Los componentes los
  leen de aquí en lugar de usar números sueltos.
* `install(app)`: al mostrarse cualquier ventana de primer nivel (diálogos, mensajes, menús, desplegables,
  descripciones, capas sobre vídeo, editores…) se le pide a Windows 11 que la redondee. Es lo único que
  recorta también el desenfoque, las sombras y las superficies nativas de vídeo, así que nada sobresale.
  Las ventanas maximizadas o a pantalla completa quedan rectas (como en Windows).
"""

from __future__ import annotations

import ctypes
import os

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget

RADII = {
    "window": 8,      # igual que Windows 11, que es quien recorta el desenfoque
    "panel": 14,      # paneles de cristal principales
    "card": 12,       # tarjetas y secciones
    "control": 8,     # botones, campos, desplegables
    "menu": 8,        # menús y ventanas emergentes
    "chip": 6,
}

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND, DWMWCP_ROUND, DWMWCP_ROUNDSMALL = 1, 2, 3


def set_corner(hwnd: int, preference: int) -> None:
    if os.name != "nt":
        return
    try:
        v = ctypes.c_int(preference)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(v),
                                                   ctypes.sizeof(v))
    except (OSError, AttributeError):
        pass


def preference_for(w: QWidget) -> int:
    if w.isFullScreen() or w.isMaximized():
        return DWMWCP_DONOTROUND
    if w.windowType() in (Qt.WindowType.Popup, Qt.WindowType.ToolTip) or w.inherits("QMenu") \
            or w.inherits("QComboBoxPrivateContainer"):
        return DWMWCP_ROUNDSMALL
    return DWMWCP_ROUND


def apply(w: QWidget) -> None:
    if w.isWindow() and w.testAttribute(Qt.WidgetAttribute.WA_WState_Created) and not getattr(w, "square", False):
        set_corner(int(w.winId()), preference_for(w))


class _CornerPolicy(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Show, QEvent.Type.WindowStateChange) and isinstance(obj, QWidget) \
                and obj.isWindow():
            apply(obj)
        return False


_policy: _CornerPolicy | None = None


def install(app: QApplication) -> None:
    """Activa el redondeo uniforme en toda la aplicación (una sola vez)."""
    global _policy
    if _policy is None and os.name == "nt":
        _policy = _CornerPolicy(app)
        app.installEventFilter(_policy)
