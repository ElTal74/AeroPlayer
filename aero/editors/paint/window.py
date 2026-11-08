"""Ventana de AERO Paint: lienzo central, herramientas a la izquierda, colores y capas a la derecha.

Las opciones de cada herramienta aparecen encima del lienzo solo cuando tienen sentido (grosor y opacidad
para pinceles, tolerancia para el relleno, tamaño de letra para el texto…).
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QGridLayout, QInputDialog, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QSpinBox, QToolButton, QVBoxLayout, QWidget)

from aero.editors.paint.canvas import BRUSHES, PaintCanvas
from aero.editors.paint.document import EXPORT_FORMATS, PROJECT_EXT, PaintDocument
from aero.ui.glass import GlassPanel, IconButton, h_layout, label, tm, v_layout
from aero.ui.glasswindow import DragArea, GlassWindow, TrDialog
from aero.i18n import tr

# (clave, icono, nombre, atajo)
TOOLS = [
    ("pencil", "pencil", "Lápiz", "P"), ("brush", "brush", "Pincel", "B"), ("eraser", "eraser", "Borrador", "E"),
    ("line", "line", "Línea", "L"), ("rect", "rect", "Rectángulo", "R"), ("ellipse", "ellipse", "Elipse", "O"),
    ("triangle", "triangle", "Triángulo", ""), ("star", "star_shape", "Estrella", ""),
    ("fill", "bucket", "Relleno", "G"), ("picker", "picker", "Cuentagotas", "I"), ("text", "text_tool", "Texto", "T"),
    ("select", "select", "Selección", "M"), ("lasso", "lasso", "Selección libre", ""),
    ("crop", "crop", "Recortar", "C"), ("hand", "move", "Mover el lienzo", "H"),
]
PALETTE = ["#000000", "#3c3c3c", "#7f7f7f", "#c3c3c3", "#ffffff", "#7a1f1f", "#d62828", "#f77f00", "#fcbf49",
           "#ffe66d", "#2a9d3f", "#7ed957", "#0a9396", "#94d2bd", "#1f6feb", "#7fb7ff", "#3a0ca3", "#9d4edd",
           "#f72585", "#ffafcc", "#6f4e37", "#c8a27c", "#264653", "#e9c46a"]
IMAGE_FILTER = "Imágenes (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff)"


class Swatch(QToolButton):
    def __init__(self, color: str, size: int = 20, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(size, size)
        self.setToolTip(self.color.name())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._paint()

    def set_color(self, c: QColor):
        self.color = QColor(c)
        self.setToolTip(self.color.name())
        self._paint()

    def _paint(self):
        pm = QPixmap(self.size() * 2)
        pm.fill(self.color)
        self.setIcon(QIcon(pm))
        self.setIconSize(self.size() - QSize(6, 6))


class NewCanvasDialog(TrDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Lienzo nuevo"))
        self.w, self.h = QSpinBox(), QSpinBox()
        for sp, v in ((self.w, 1280), (self.h, 800)):
            sp.setRange(1, 10000)
            sp.setValue(v)
            sp.setSuffix(tr(" px"))
        self.bg = QComboBox()
        for k, t in (("#ffffff", "Blanco"), ("transparent", "Transparente"), ("custom", "Otro color…")):
            self.bg.addItem(t, k)
        self.custom = "#ffffff"
        self.bg.currentIndexChanged.connect(self._bg)
        form = QFormLayout()
        form.addRow(tr("Ancho"), self.w)
        form.addRow(tr("Alto"), self.h)
        form.addRow(tr("Fondo"), self.bg)
        ok = QPushButton(tr("Crear"))
        ok.setProperty("kind", "primary")
        ok.clicked.connect(self.accept)
        cancel = QPushButton(tr("Cancelar"))
        cancel.clicked.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(h_layout(None, cancel, ok))

    def _bg(self):
        if self.bg.currentData() == "custom":
            c = QColorDialog.getColor(QColor(self.custom), self, "Color de fondo")
            if c.isValid():
                self.custom = c.name()

    def background(self) -> str:
        k = self.bg.currentData()
        return self.custom if k == "custom" else k


class PaintEditor(QWidget):
    """AERO Paint completo en un widget: se usa como apartado «Paint» de la ventana principal y dentro de la
    ventana independiente (`PaintWindow`). `window_buttons` solo se pasa en la ventana independiente."""

    title_changed = Signal(str)

    def __init__(self, path: str = "", controller=None, window_buttons=None):
        super().__init__()
        self.controller = controller
        self.embedded = window_buttons is None
        self.setAcceptDrops(True)
        self.recent: list[str] = []
        self.canvas = PaintCanvas()
        self.canvas.changed.connect(self._sync)
        self.canvas.zoom_changed.connect(lambda z: self.zoom_lbl.setText(f"{z * 100:.0f} %"))
        self.canvas.color_picked.connect(self._picked)

        # ---------------------------------------------------------- barra superior
        bar = QWidget() if self.embedded else DragArea()
        self.title = label(tr("AERO Paint"), "h3")
        self.info = label("", "caption")
        top = []
        for ic, tip, fn in (("files", "Lienzo nuevo (Ctrl+N)", self.new_canvas), ("open", "Abrir (Ctrl+O)", self.open),
                            ("save", "Guardar proyecto (Ctrl+S)", self.save_project),
                            ("undo", "Deshacer (Ctrl+Z)", self.undo), ("redo", "Rehacer (Ctrl+Y)", self.redo)):
            b = IconButton(ic, tip, 18)
            b.clicked.connect(fn)
            top.append(b)
        zo, zi, fit = IconButton("zoom_out", "Alejar", 18), IconButton("zoom_in", "Acercar", 18), \
            IconButton("fit", tr("Ajustar a la pantalla (0)"), 18)
        zo.clicked.connect(lambda: self._zoom(1 / 1.25))
        zi.clicked.connect(lambda: self._zoom(1.25))
        fit.clicked.connect(self.canvas.fit)
        self.zoom_lbl = label("100 %", "caption")
        self.grid_btn = IconButton("grid", tr("Cuadrícula"), 18, checkable=True)
        self.grid_btn.toggled.connect(lambda on: (setattr(self.canvas, "grid", on), self.canvas.update()))
        export = QPushButton(tr("Exportar…"))
        export.setProperty("kind", "primary")
        export.clicked.connect(self.export_dialog)
        bar.setLayout(h_layout(14, v_layout(self.title, self.info, spacing=0), 16, *top, 12, zo, self.zoom_lbl, zi,
                               fit, self.grid_btn, None, export, *(() if self.embedded else (10, window_buttons)), spacing=3,
                               margins=(0, 8, 10, 8)))

        # ---------------------------------------------------------- herramientas
        self.tool_group = QButtonGroup(self)
        self.tool_buttons: dict[str, QToolButton] = {}
        tools_w = QWidget()
        grid = QGridLayout(tools_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)
        for i, (key, ic, name, sc) in enumerate(TOOLS):
            b = QToolButton()
            b.setIcon(tm().icon(ic, 20))
            b.setIconSize(QSize(20, 20))
            b.setFixedSize(40, 40)
            b.setCheckable(True)
            b.setToolTip(f"{tr(name)} ({sc})" if sc else tr(name))
            b.setAccessibleName(tr(name))
            b.clicked.connect(lambda _c=False, k=key: self.set_tool(k))
            self.tool_group.addButton(b)
            self.tool_buttons[key] = b
            grid.addWidget(b, i // 2, i % 2)
            if sc:
                QShortcut(QKeySequence(sc), self, activated=lambda k=key: self.set_tool(k))

        # ---------------------------------------------------------- opciones de la herramienta
        self.size = QSpinBox()
        self.size.setRange(1, 400)
        self.size.setValue(self.canvas.width_px)
        self.size.setSuffix(tr(" px"))
        self.size.valueChanged.connect(lambda v: setattr(self.canvas, "width_px", v))
        from aero.ui.pages.theme_studio import ValueSlider

        self.op = ValueSlider(1.0, "Opacidad", minimum=5, maximum=100)
        self.op.changed.connect(lambda v: setattr(self.canvas, "opacity", v))
        self.brush = QComboBox()
        for k, t in BRUSHES.items():
            self.brush.addItem(t, k)
        self.brush.currentIndexChanged.connect(lambda _i: setattr(self.canvas, "brush", self.brush.currentData()))
        self.fill_shapes = QCheckBox(tr("Rellenar con el color 2"))
        self.fill_shapes.toggled.connect(lambda on: setattr(self.canvas, "fill_shapes", on))
        self.tol = QSpinBox()
        self.tol.setRange(0, 255)
        self.tol.setValue(self.canvas.tolerance)
        self.tol.valueChanged.connect(lambda v: setattr(self.canvas, "tolerance", v))
        self.font_px = QSpinBox()
        self.font_px.setRange(6, 600)
        self.font_px.setValue(self.canvas.font_size)
        self.font_px.setSuffix(tr(" px"))
        self.font_px.valueChanged.connect(lambda v: setattr(self.canvas, "font_size", v))
        self.sel_crop = QPushButton(tr("Recortar a la selección"))
        self.sel_crop.clicked.connect(self.canvas.crop_to_selection)
        self.sel_clear = QPushButton(tr("Borrar dentro"))
        self.sel_clear.setProperty("kind", "flat")
        self.sel_clear.clicked.connect(self.canvas.clear_selection_area)
        self.opt_parts = {
            "size": h_layout(label("Grosor", "caption"), self.size, spacing=6),
            "op": h_layout(label("Opacidad", "caption"), self.op, spacing=6),
            "brush": h_layout(label("Tipo", "caption"), self.brush, spacing=6),
            "fill": self.fill_shapes, "tol": h_layout(label("Tolerancia", "caption"), self.tol, spacing=6),
            "font": h_layout(label(tr("Tamaño"), "caption"), self.font_px, spacing=6),
            "sel": h_layout(self.sel_crop, self.sel_clear, spacing=6),
        }
        self.options = QWidget()
        ol = h_layout(spacing=16, margins=(4, 0, 4, 0))
        self._opt_widgets = {}
        for k, part in self.opt_parts.items():
            if isinstance(part, QWidget):
                holder = part
            else:
                holder = QWidget()
                holder.setLayout(part)
            ol.addWidget(holder)
            self._opt_widgets[k] = holder
        ol.addStretch(1)
        self.options.setLayout(ol)

        # ---------------------------------------------------------- colores
        self.c1, self.c2 = Swatch(self.canvas.primary.name(), 34), Swatch(self.canvas.secondary.name(), 26)
        self.c1.setToolTip(tr("Color 1 (clic izquierdo)"))
        self.c2.setToolTip(tr("Color 2 (clic derecho)"))
        self.c1.clicked.connect(lambda: self._custom(1))
        self.c2.clicked.connect(lambda: self._custom(2))
        swap = IconButton("swap", tr("Intercambiar colores (X)"), 16)
        swap.clicked.connect(self.swap_colors)
        QShortcut(QKeySequence("X"), self, activated=self.swap_colors)
        pal = QGridLayout()
        pal.setSpacing(3)
        for i, c in enumerate(PALETTE):
            s = Swatch(c, 22)
            s.clicked.connect(lambda _c=False, col=c: self.set_color(QColor(col)))
            pal.addWidget(s, i // 6, i % 6)
        self.recent_row = h_layout(spacing=3)
        more = QPushButton(tr("Más colores…"))
        more.setProperty("kind", "flat")
        more.clicked.connect(lambda: self._custom(1))

        # ---------------------------------------------------------- capas
        self.layer_list = QListWidget()
        self.layer_list.setAccessibleName(tr("Capas"))
        self.layer_list.currentRowChanged.connect(self._select_layer)
        self.layer_list.itemChanged.connect(self._layer_changed)
        self.layer_list.itemDoubleClicked.connect(self._rename)
        self.l_op = ValueSlider(1.0, "Opacidad de la capa", minimum=0, maximum=100)
        self.l_op.changed.connect(self._layer_opacity)
        lacts = h_layout(*[self._icon(ic, tip, fn) for ic, tip, fn in (
            ("plus", "Nueva capa", self.add_layer), ("up", "Subir", lambda: self._move_layer(1)),
            ("down", "Bajar", lambda: self._move_layer(-1)), ("trash", "Eliminar capa", self.remove_layer))],
            None, spacing=2)
        canvas_btn = QPushButton(tr("Tamaño…"))
        canvas_btn.setToolTip(tr("Redimensionar la imagen o el lienzo"))
        canvas_btn.clicked.connect(self.resize_dialog)

        side = GlassPanel(radius=14, nested=True)
        side.setFixedWidth(250)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 12, 14, 12)
        sl.setSpacing(8)
        sl.addWidget(label("Colores", "h3"))
        sl.addLayout(h_layout(self.c1, self.c2, swap, None, spacing=6))
        sl.addLayout(pal)
        sl.addWidget(label("Recientes", "caption"))
        sl.addLayout(self.recent_row)
        sl.addWidget(more)
        sl.addSpacing(6)
        sl.addWidget(label("Capas", "h3"))
        sl.addWidget(self.layer_list, 1)
        sl.addLayout(lacts)
        sl.addLayout(h_layout(label("Opacidad", "caption"), self.l_op, spacing=6))
        sl.addWidget(canvas_btn)

        left = QVBoxLayout()
        left.addWidget(tools_w)
        left.addStretch(1)
        center = QVBoxLayout()
        center.setSpacing(6)
        center.addWidget(self.options)
        center.addWidget(self.canvas, 1)
        body = h_layout(spacing=10, margins=(10, 0, 10, 10))
        body.addLayout(left)
        body.addLayout(center, 1)
        body.addWidget(side)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(bar)
        root.addLayout(body, 1)
        for seq, fn in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                        ("Ctrl+S", self.save_project), ("Ctrl+O", self.open), ("Ctrl+N", self.new_canvas),
                        ("Ctrl+E", self.export_dialog), ("0", self.canvas.fit)):
            sc = QShortcut(QKeySequence(seq), self, activated=fn)
            # Solo con el foco en Paint: en la ventana principal no choca con los atajos de otros apartados.
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        if path:
            self.load(path)
        else:
            self.set_doc(PaintDocument())
        self.set_tool("brush")
        from aero.core.drafts import Autosaver

        self.autosaver = Autosaver(
            self, "paint", PROJECT_EXT, lambda: self.doc.dirty, lambda: self.doc.draft_job(),
            lambda: Path(self.doc.path).stem if self.doc.path else tr("Dibujo"), lambda: self.doc.path,
            token=lambda: (id(self.doc), self.doc.edits), busy=lambda: self.canvas._drag is not None,
            settings=getattr(controller, "settings", None), background=True)

    # ------------------------------------------------------------------ documento
    def set_doc(self, doc: PaintDocument):
        self.doc = doc
        self.canvas.set_document(doc)
        self._sync()

    def load(self, path: str) -> bool:
        try:
            if path.lower().endswith(PROJECT_EXT):
                doc = PaintDocument.load_project(path)
            else:
                from aero.ui.viewers.image_viewer import load_qimage

                img = load_qimage(path)
                if img.isNull():
                    raise ValueError("No se pudo leer la imagen.")
                doc = PaintDocument.from_image(img, path)
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.warning(self, tr("Abrir"), tr("No se pudo abrir «{v0}»: {e}", v0=Path(path).name, e=e))
            return False
        self.set_doc(doc)
        return True

    def new_canvas(self):
        if not self._confirm_discard():
            return
        dlg = NewCanvasDialog(self)
        if dlg.exec():
            self.set_doc(PaintDocument(dlg.w.value(), dlg.h.value(), dlg.background()))

    def open(self):
        if not self._confirm_discard():
            return
        f, _ = QFileDialog.getOpenFileName(self, tr("Abrir"), "", f"{IMAGE_FILTER};;Proyecto de AERO Paint (*{PROJECT_EXT})")
        if f:
            self.load(f)

    def save_project(self) -> bool:
        target = self.doc.path if self.doc.path.lower().endswith(PROJECT_EXT) else ""
        if not target:
            base = Path(self.doc.path).with_suffix(PROJECT_EXT) if self.doc.path else Path.home() / f"Dibujo{PROJECT_EXT}"
            target, _ = QFileDialog.getSaveFileName(self, tr("Guardar proyecto"), str(base),
                                                    f"Proyecto de AERO Paint (*{PROJECT_EXT})")
            if not target:
                return False
        self.doc.save_project(target)
        self._sync()
        self.info.setText(f"Guardado {Path(target).name}")
        return True

    def export_dialog(self):
        base = Path(self.doc.path).stem if self.doc.path else tr("Dibujo")
        folder = Path(self.doc.path).parent if self.doc.path else Path.home()
        filters = ";;".join(f"{v} (*.{k})" for k, v in EXPORT_FORMATS.items())
        f, chosen = QFileDialog.getSaveFileName(self, tr("Exportar"), str(folder / f"{base}.png"), filters)
        if not f:
            return
        ext = Path(f).suffix.lower().lstrip(".")
        if ext == "jpeg":
            ext = "jpg"
        if ext not in EXPORT_FORMATS:
            ext = "png"
            f += ".png"
        if os.path.abspath(f) == os.path.abspath(self.doc.path or "") and QMessageBox.question(
                self, tr("Exportar"), tr("Vas a sustituir la imagen original. ¿Continuar?")) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.doc.export(f, ext)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, tr("Exportar"), str(e))
            return
        note = " (sin transparencia: JPG y BMP no la admiten)" if ext in ("jpg", "bmp") else ""
        self.info.setText(f"Exportado {Path(f).name}{note}")

    def _confirm_discard(self) -> bool:
        if not getattr(self, "doc", None) or not self.doc.dirty:
            return True
        r = QMessageBox.question(self, tr("AERO Paint"), tr("Hay cambios sin guardar. ¿Descartarlos?"))
        return r == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------------ herramientas y colores
    def set_tool(self, key: str):
        self.canvas.tool = key
        self.tool_buttons[key].setChecked(True)
        shown = {"pencil": {"size", "op"}, "brush": {"size", "op", "brush"}, "eraser": {"size"},
                 "line": {"size", "op"}, "rect": {"size", "op", "fill"}, "ellipse": {"size", "op", "fill"},
                 "triangle": {"size", "op", "fill"}, "star": {"size", "op", "fill"}, "fill": {"tol"},
                 "text": {"font"}, "select": {"sel"}, "lasso": {"sel"}, "crop": set(), "picker": set(),
                 "hand": set()}[key]
        for k, w in self._opt_widgets.items():
            w.setVisible(k in shown)
        if key == "pencil" and self.size.value() > 4:
            self.size.setValue(2)
        cursor = {"hand": Qt.CursorShape.OpenHandCursor, "text": Qt.CursorShape.IBeamCursor}.get(
            key, Qt.CursorShape.CrossCursor)
        self.canvas.setCursor(cursor)

    def set_color(self, c: QColor, which: int = 1):
        if which == 1:
            self.canvas.primary = QColor(c)
            self.c1.set_color(c)
        else:
            self.canvas.secondary = QColor(c)
            self.c2.set_color(c)
        name = QColor(c).name()
        if name not in self.recent:
            self.recent.insert(0, name)
            del self.recent[8:]
            while self.recent_row.count():
                it = self.recent_row.takeAt(0)
                if it.widget():
                    it.widget().hide()
                    it.widget().deleteLater()
            for col in self.recent:
                s = Swatch(col, 22)
                s.clicked.connect(lambda _c=False, cc=col: self.set_color(QColor(cc)))
                self.recent_row.addWidget(s)
            self.recent_row.addStretch(1)

    def swap_colors(self):
        a, b = QColor(self.canvas.primary), QColor(self.canvas.secondary)
        self.set_color(b, 1)
        self.set_color(a, 2)

    def _custom(self, which: int):
        cur = self.canvas.primary if which == 1 else self.canvas.secondary
        c = QColorDialog.getColor(cur, self, "Elegir color", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if c.isValid():
            self.set_color(c, which)

    def _picked(self, c: QColor):
        self.set_color(c, 1)
        self.set_tool("brush")

    def _zoom(self, k: float):
        self.canvas.auto_fit = False
        self.canvas.set_zoom(self.canvas.zoom * k)

    def undo(self):
        if self.doc.undo():
            self.canvas.update()
            self._sync()

    def redo(self):
        if self.doc.redo():
            self.canvas.update()
            self._sync()

    # ------------------------------------------------------------------ capas
    def _icon(self, ic, tip, fn):
        b = IconButton(ic, tip, 16, button=30)
        b.clicked.connect(fn)
        return b

    def add_layer(self):
        self.doc.add_layer()
        self._sync()

    def remove_layer(self):
        if not self.doc.remove_layer(self.doc.active):
            self.info.setText(tr("Tiene que quedar al menos una capa"))
        self.canvas.update()
        self._sync()

    def _move_layer(self, delta: int):
        self.doc.move_layer(self.doc.active, delta)
        self.canvas.update()
        self._sync()

    def _row_to_index(self, row: int) -> int:
        return len(self.doc.layers) - 1 - row

    def _select_layer(self, row: int):
        if row < 0 or getattr(self, "_syncing", False):
            return
        self.doc.active = self._row_to_index(row)
        self.l_op.set_value(self.doc.current.opacity)

    def _layer_changed(self, item: QListWidgetItem):
        if getattr(self, "_syncing", False):
            return
        ly = self.doc.layers[self._row_to_index(self.layer_list.row(item))]
        on = item.checkState() == Qt.CheckState.Checked
        if ly.visible != on:
            self.doc.checkpoint("Mostrar u ocultar capa")
            ly.visible = on
            self.canvas.update()

    def _rename(self, item: QListWidgetItem):
        ly = self.doc.layers[self._row_to_index(self.layer_list.row(item))]
        name, ok = QInputDialog.getText(self, tr("Renombrar capa"), tr("Nombre:"), text=ly.name)
        if ok and name.strip():
            ly.name = name.strip()
            self.doc.dirty = True
            self.doc.edits += 1
            self._sync()

    def _layer_opacity(self, v: float):
        if getattr(self, "_syncing", False):
            return
        self.doc.current.opacity = v
        self.doc.dirty = True
        self.doc.edits += 1
        self.canvas.update()

    def resize_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Tamaño"))
        w, h = QSpinBox(), QSpinBox()
        for sp, v in ((w, self.doc.size.width()), (h, self.doc.size.height())):
            sp.setRange(1, 10000)
            sp.setValue(v)
            sp.setSuffix(tr(" px"))
        mode = QComboBox()
        mode.addItem(tr("Escalar la imagen"), "image")
        mode.addItem(tr("Cambiar el lienzo (sin escalar)"), "canvas")
        form = QFormLayout(dlg)
        form.addRow(tr("Ancho"), w)
        form.addRow(tr("Alto"), h)
        form.addRow(tr("Modo"), mode)
        ok = QPushButton(tr("Aplicar"))
        ok.setProperty("kind", "primary")
        ok.clicked.connect(dlg.accept)
        form.addRow(ok)
        if dlg.exec():
            (self.doc.resize_image if mode.currentData() == "image" else self.doc.resize_canvas)(w.value(), h.value())
            self.canvas.fit()
            self._sync()

    # ------------------------------------------------------------------ estado
    def _sync(self):
        d = self.doc
        name = Path(d.path).name if d.path else tr("Sin título")
        self.title.setText(f"{name}{' •' if d.dirty else ''}")
        self.title_changed.emit(f"{name} · AERO Paint")
        self.info.setText(tr("{v0} × {v1} px", v0=d.size.width(), v1=d.size.height()))
        self._syncing = True
        self.layer_list.clear()
        for ly in reversed(d.layers):
            it = QListWidgetItem(tm().icon("layers", 16), ly.name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if ly.visible else Qt.CheckState.Unchecked)
            it.setToolTip(tr("Doble clic para renombrar"))
            self.layer_list.addItem(it)
        self.layer_list.setCurrentRow(len(d.layers) - 1 - d.active)
        self.l_op.set_value(d.current.opacity)
        self._syncing = False

    # ------------------------------------------------------------------ arrastrar y soltar
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        from aero.ui.viewers.image_viewer import load_qimage

        img = load_qimage(paths[0])
        if img.isNull():
            return
        if self.doc.dirty or len(self.doc.layers) > 1:
            self.doc.add_layer(Path(paths[0]).stem, img)  # con un dibujo en marcha: se añade como capa
            self.canvas.update()
            self._sync()
        else:
            self.load(paths[0])

    def can_close(self) -> bool:
        return self._confirm_discard()


class PaintWindow(GlassWindow):
    """Ventana independiente de AERO Paint (abrir una imagen, desde el editor de imágenes o un borrador)."""

    def __init__(self, path: str = "", controller=None):
        super().__init__(Qt.WindowType(0), flat=True)
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumSize(980, 640)
        self.backdrop.flat_opacity = 0.95
        self.editor = PaintEditor(path, controller, self.window_buttons())
        self.editor.title_changed.connect(self.setWindowTitle)
        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.editor)
        self.editor._sync()

    def __getattr__(self, name):
        # El resto de la API (doc, canvas, autosaver, load…) es la del editor.
        ed = self.__dict__.get("editor")
        if ed is None:
            raise AttributeError(name)
        return getattr(ed, name)

    def closeEvent(self, e):
        if not self.editor.can_close():
            e.ignore()
            return
        super().closeEvent(e)
        if self.controller is not None:
            self.controller.editor_closed(self)


def open_paint(path: str = "", controller=None) -> PaintWindow:
    w = PaintWindow(path, controller)
    w.resize(1320, 840)
    w.show()
    w.raise_()
    w.activateWindow()
    return w
