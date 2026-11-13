"""Acciones visibles según el tipo de archivo abierto (Editar, Recortar, Convertir, Extraer…).

Una sola definición para el visor rápido y el visor de la aplicación: cada acción existe solo si la
aplicación puede hacerla de verdad con ese tipo de archivo (no se muestran botones que no funcionen).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from aero.core.formats import kind_of
from aero.i18n import tr


@dataclass(frozen=True)
class Action:
    key: str
    text: str
    icon: str
    tip: str


EDIT = Action("edit", "Editar", "edit", "Abrir en el editor (E)")
CONVERT = Action("convert", "Convertir", "convert", "Convertir a otro formato")
REVEAL = Action("reveal", "Carpeta", "folder", "Mostrar en el Explorador")

BY_KIND: dict[str, list[Action]] = {
    "image": [EDIT, Action("crop", "Recortar", "crop", "Recortar y girar la imagen"),
              Action("paint", "Dibujar", "brush", "Abrir en AERO Paint para dibujar encima"), CONVERT],
    "video": [Action("edit", "Editar", "edit", "Abrir en el editor de vídeo (E)"), CONVERT],
    "audio": [Action("tags", "Propiedades", "tag", "Título, artista, álbum y demás etiquetas"), CONVERT],
    "pdf": [Action("edit", "Editable", "edit", "Convertir a documento editable (E)"), CONVERT],
    "document": [EDIT, CONVERT],
    "sheet": [EDIT, CONVERT],
    "slides": [EDIT, CONVERT],
    "text": [EDIT],
    "archive": [Action("extract_folder", "Extraer", "drop", "Extraer en una carpeta con su nombre"),
                Action("extract_to", "Extraer en…", "open", "Elegir dónde extraer")],
}


def actions_for(path: str) -> list[Action]:
    kind = "folder" if Path(path).is_dir() else kind_of(path)
    out = list(BY_KIND.get(kind, []))
    if kind == "audio":
        from aero.core.metadata import read_editable

        if read_editable(path) is None:  # formato sin etiquetas editables
            out = [a for a in out if a.key != "tags"]
    if kind != "folder":
        out.append(REVEAL)
    return out


def run(controller, action: str, path: str, parent: QWidget | None = None) -> None:
    """Ejecuta una acción sobre `path` con los servicios del controlador."""
    from aero.core import tools

    if action == "reveal":
        tools.reveal_in_explorer(path)
    elif controller is None:
        return
    elif action == "edit":
        controller.open_editor_for(path)
    elif action == "crop":
        w = controller.open_image_editor(path)
        if w is not None and hasattr(w, "set_tool"):
            w.set_tool("crop")
    elif action == "paint":
        controller.open_paint(path)
    elif action == "convert":
        controller.run_action("convert", [path], immediate=True)
    elif action in ("extract_folder", "extract_to"):
        controller.run_action(action, [path], immediate=True)
    elif action == "tags":
        edit_tags(path, parent)


def edit_tags(path: str, parent: QWidget | None = None) -> bool:
    from PySide6.QtWidgets import QMessageBox

    from aero.core.metadata import read_editable, write_tags
    from aero.ui.pages.library_page import TagDialog

    values = read_editable(path)
    if values is None:
        QMessageBox.information(parent, tr("Propiedades"), tr("Este formato no admite edición de etiquetas."))
        return False
    dlg = TagDialog(path, values, parent)
    if not dlg.exec():
        return False
    try:
        write_tags(path, dlg.values())
    except ValueError as e:
        QMessageBox.warning(parent, tr("Propiedades"), str(e))
        return False
    return True


class ActionBar(QWidget):
    """Fila de botones de acción; se rehace al abrir otro archivo.

    Se adapta al ancho disponible (`fit`): con sitio, icono y texto corto; sin sitio, solo iconos (el texto
    pasa a la descripción emergente); y si ni así caben, se ocultan las acciones del final. Un botón nunca
    se dibuja recortado: su ancho mínimo es siempre el de su contenido.
    """
    triggered = Signal(str)
    ICON_W = 34          # ancho de un botón en modo «solo iconos»

    def __init__(self, parent=None, dark: bool = False):
        super().__init__(parent)
        self.dark = dark
        self.compact = False
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(4)
        self.buttons: dict[str, QPushButton] = {}
        self._texts: dict[str, str] = {}
        self._full: dict[str, int] = {}

    def set_path(self, path: str) -> None:
        from aero.ui import icons
        from aero.ui.glass import tm

        for b in self.buttons.values():
            b.deleteLater()
        self.buttons.clear()
        self._texts.clear()
        self._full.clear()
        color = "#ffffff" if self.dark else tm().theme.text
        for a in actions_for(path):
            text = tr(a.text)
            b = QPushButton(text)
            b.setIcon(icons.icon(a.icon, color, 16))
            b.setIconSize(QSize(16, 16))
            b.setAccessibleName(text)
            b.setProperty("kind", "primary" if a.key in ("edit", "extract_folder") else "flat")
            b.setProperty("tip", tr(a.tip))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if self.dark and b.property("kind") == "flat":
                b.setStyleSheet("color: white;")
            b.clicked.connect(lambda _c=False, k=a.key: self.triggered.emit(k))
            self._lay.addWidget(b)
            self.buttons[a.key] = b
            self._texts[a.key] = text
        self.setVisible(bool(self.buttons))
        self._measure()
        self._apply(self.compact, len(self.buttons))

    def _measure(self) -> None:
        """Ancho de cada botón con su texto (con la hoja de estilo ya aplicada)."""
        for key, b in self.buttons.items():
            b.setText(self._texts[key])
            b.setMinimumWidth(0)
            b.setMaximumWidth(16777215)
            b.ensurePolished()
            self._full[key] = b.sizeHint().width()

    def full_width(self) -> int:
        n = len(self.buttons)
        return sum(self._full.values()) + self._lay.spacing() * max(0, n - 1)

    def compact_width(self, count: int | None = None) -> int:
        n = len(self.buttons) if count is None else count
        return self.ICON_W * n + self._lay.spacing() * max(0, n - 1)

    def fit(self, available: int) -> int:
        """Elige el modo que cabe en `available` píxeles y devuelve el ancho que ocupa la barra."""
        n = len(self.buttons)
        if not n:
            return 0
        if self.full_width() <= available:
            self._apply(False, n)
            return self.full_width()
        while n > 1 and self.compact_width(n) > available:
            n -= 1
        self._apply(True, n)
        return self.compact_width(n)

    def _apply(self, compact: bool, shown: int) -> None:
        self.compact = compact
        for i, (key, b) in enumerate(self.buttons.items()):
            text, tip = self._texts[key], b.property("tip")
            if compact:
                b.setText("")
                b.setFixedWidth(self.ICON_W)
                b.setToolTip(f"{text} — {tip}" if tip else text)
            else:
                b.setText(text)
                b.setMinimumWidth(self._full.get(key, 0))
                b.setMaximumWidth(16777215)
                b.setToolTip(tip)
            b.setVisible(i < shown)
        self.setFixedWidth(self.compact_width(shown) if compact else self.full_width())
