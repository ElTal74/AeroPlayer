"""Ventana del editor de imágenes.

Distribución pensada para la tarea: el lienzo manda; a la izquierda, seis categorías; a la derecha, solo las
herramientas de la categoría elegida. Nada de cientos de botones a la vista.

Guardado no destructivo: «Guardar» ofrece una copia (por defecto), un proyecto editable o, con confirmación
explícita, sobrescribir el original. Exportar elige formato, calidad y tamaño y muestra el peso estimado.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout,
                               QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSlider, QSpinBox,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from aero.core.formats import human_size
from aero.editors.image import adjust
from aero.editors.image.canvas import ASPECTS, ImageCanvas
from aero.editors.image.document import PROJECT_EXT, ImageDocument, encode
from aero.ui.collapsible import Collapsible
from aero.ui.glass import GlassPanel, IconButton, h_layout, label, tm, v_layout
from aero.ui.glasswindow import DragArea, GlassWindow, TrDialog
from aero.i18n import tr

FORMATS = [("PNG", "png"), ("JPG", "jpg"), ("WebP", "webp"), ("BMP", "bmp"), ("TIFF", "tiff")]
# (clave, icono, nombre corto, descripción en la ayuda emergente)
CATEGORIES = [
    ("select", "select", "Selección", "Elegir una zona de la foto"),
    ("crop", "crop", "Recortar", "Recortar, girar y enderezar"),
    ("resize", "fit", "Tamaño", "Cambiar el tamaño y añadir márgenes"),
    ("adjust", "sliders", "Ajustes", "Brillo, contraste, color…"),
    ("filters", "star", "Filtros", "Estilos listos para aplicar"),
    ("text", "text_tool", "Texto", "Escribir sobre la foto"),
    ("draw", "brush", "Dibujo", "Pincel, flechas y formas"),
    ("pixels", "pixel", "Píxeles", "Pixelar y desenfocar zonas"),
    ("layers", "layers", "Capas", "Imágenes superpuestas"),
    ("export", "save", "Exportar", "Guardar y exportar"),
]
LEGACY = {"compose": "crop", "color": "adjust"}  # nombres anteriores de las categorías


def _load(path: str):
    """Hilo de trabajo: proyecto .aeroimg o imagen (resolución completa)."""
    if path.lower().endswith(PROJECT_EXT):
        return ImageDocument.load_project(path)
    from aero.ui.viewers.image_viewer import load_qimage

    img = load_qimage(path)
    if img.isNull():
        raise ValueError("No se pudo leer la imagen.")
    return ImageDocument.from_image(img, path)


def _export_job(doc: ImageDocument, path: str, fmt: str, quality: int, scale: float) -> int:
    data = encode(doc.render(scale), fmt, quality)
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)  # nunca queda un archivo a medio escribir
    return len(data)


def _snapshot(doc: ImageDocument) -> ImageDocument:
    """Copia ligera para trabajar en otro hilo mientras se sigue editando."""
    st = doc._state()
    return ImageDocument(doc.path, st.layers, st.adjust, st.active)


class EditorWindow(GlassWindow):
    closed = Signal()

    def __init__(self, path: str, controller=None):
        super().__init__(Qt.WindowType(0), flat=True)
        self.controller = controller
        self.path = os.path.abspath(path)
        self.doc: ImageDocument | None = None
        self.project_path = self.path if self.path.lower().endswith(PROJECT_EXT) else ""
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("{v0} · Editor · AERO Player", v0=Path(path).name))
        self.setMinimumSize(980, 640)
        self.backdrop.flat_opacity = 0.94
        self._adj_open = False
        self._came_from = ""
        self._adj_timer = QTimer(self)
        self._adj_timer.setSingleShot(True)
        self._adj_timer.setInterval(700)
        self._adj_timer.timeout.connect(lambda: setattr(self, "_adj_open", False))

        self.canvas = ImageCanvas()
        self.canvas.changed.connect(self._sync_title)
        self.canvas.zoom_changed.connect(lambda z: self.zoom_lbl.setText(f"{z * 100:.0f} %"))
        self.canvas.layer_moved.connect(self._sync_layer_props)

        # ---------------------------------------------------------- barra superior
        bar = DragArea()
        self.title = label(Path(path).name, "h3")
        self.info = label("", "caption")
        self.btn_undo = IconButton("undo", tr("Deshacer (Ctrl+Z)"), 18)
        self.btn_redo = IconButton("redo", tr("Rehacer (Ctrl+Y)"), 18)
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo.clicked.connect(self.redo)
        zo = IconButton("zoom_out", "Alejar", 18)
        zi = IconButton("zoom_in", "Acercar", 18)
        fit = IconButton("fit", tr("Ajustar a la ventana (0)"), 18)
        zo.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.zoom / 1.25))
        zi.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.zoom * 1.25))
        fit.clicked.connect(self.canvas.fit)
        self.zoom_lbl = label("100 %", "caption")
        self.zoom_lbl.setMinimumWidth(46)
        self.zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        save = QPushButton(tr("Guardar"))
        save.clicked.connect(self.save)
        save_as = QPushButton(tr("Guardar como…"))
        save_as.setProperty("kind", "flat")
        save_as.clicked.connect(self.save_as)
        export = QPushButton(tr("Exportar…"))
        export.setProperty("kind", "primary")
        export.clicked.connect(self.export_dialog)
        bar.setLayout(h_layout(14, v_layout(self.title, self.info, spacing=0), 18, self.btn_undo, self.btn_redo, 14,
                               zo, self.zoom_lbl, zi, fit, None, save_as, save, export, 10, self.window_buttons(),
                               spacing=4, margins=(0, 8, 10, 8)))

        # ---------------------------------------------------------- herramientas (barra izquierda) y panel
        # Cada herramienta: icono y nombre corto; a la derecha solo sus opciones. Lo avanzado, plegado.
        self._tool_buttons: dict[str, QToolButton] = {}
        self._color_buttons = []
        self.rail = QButtonGroup(self)
        rail_w = QWidget()
        rail = QVBoxLayout(rail_w)
        rail.setContentsMargins(0, 0, 0, 0)
        rail.setSpacing(2)
        self.pages = QStackedWidget()
        self._page_index = {}
        for key, ic, text, tip in CATEGORIES:
            b = QToolButton()
            b.setIcon(tm().icon(ic, 20))
            b.setIconSize(QSize(20, 20))
            b.setText(text)
            b.setToolTip(tip)
            b.setAccessibleName(text)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setCheckable(True)
            b.setFixedSize(70, 54)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            f = b.font()
            f.setPointSizeF(8.5)
            b.setFont(f)
            b.clicked.connect(lambda _c=False, k=key: self.show_category(k))
            self.rail.addButton(b)
            rail.addWidget(b)
            self._page_index[key] = (b, self.pages.addWidget(getattr(self, f"_page_{key}")()))
        rail.addStretch(1)
        side = GlassPanel(radius=14, nested=True)
        side.setFixedWidth(290)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 14, 16, 14)
        self.page_title = label("", "h3")
        sl.addWidget(self.page_title)
        sl.addWidget(self.pages, 1)

        body = QHBoxLayout()
        body.setContentsMargins(10, 0, 10, 10)
        body.setSpacing(10)
        body.addWidget(rail_w)
        body.addWidget(self.canvas, 1)
        body.addWidget(side)
        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(bar)
        root.addLayout(body, 1)

        for seq, fn in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                        ("Ctrl+S", self.save), ("Ctrl+Shift+S", self.save_as), ("Ctrl+E", self.export_dialog),
                        ("0", self.canvas.fit)):
            QShortcut(QKeySequence(seq), self, activated=fn)
        self.show_category("crop")
        self._load()
        from aero.core.drafts import Autosaver

        self.autosaver = Autosaver(
            self, "image", PROJECT_EXT, lambda: self.doc is not None and self.doc.dirty,
            lambda: _snapshot(self.doc).save_project, lambda: Path(self.path).stem, lambda: self.path,
            token=lambda: self.doc.version if self.doc is not None else None,
            settings=getattr(controller, "settings", None), background=True)

    # ------------------------------------------------------------------ carga
    def _load(self):
        from aero.core.tasks import tasks

        path = self.path
        self.info.setText(tr("Abriendo…"))
        tasks().submit(lambda: _load(path), "interactive", self._loaded,
                       lambda e: (self.info.setText(tr("No se pudo abrir: {e}", e=e))), self)

    def _loaded(self, doc: ImageDocument):
        self.doc = doc
        self.canvas.set_document(doc)
        self._sync_all()
        if self.canvas.tool == "crop":
            self.canvas.start_crop(ASPECTS[self.aspect.currentText()])

    # ------------------------------------------------------------------ piezas de los paneles
    def _icon_btn(self, ic, tip, fn, text: str = ""):
        b = QToolButton()
        b.setIcon(tm().icon(ic, 18))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        if text:
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setFixedSize(60, 52)
        else:
            b.setFixedSize(38, 38)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(fn)
        return b

    def _primary(self, text: str, fn) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("kind", "primary")
        b.clicked.connect(fn)
        return b

    def _flat(self, text: str, fn) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("kind", "flat")
        b.clicked.connect(fn)
        return b

    def _page(self, *items) -> QWidget:
        w = QWidget()
        w.setLayout(v_layout(*items, None, spacing=8))
        return w

    # ------------------------------------------------------------------ páginas
    def _page_select(self) -> QWidget:
        self.sel_info = label(tr("Arrastra sobre la foto"), "caption")
        return self._page(
            self.sel_info,
            h_layout(self._icon_btn("crop", "Recortar a la selección", self._crop_to_selection, "Recortar"),
                     self._icon_btn("pixel", "Pixelar la selección", lambda: self._region(
                         lambda d, r: d.pixelate(r, self.block.value())), "Pixelar"),
                     self._icon_btn("close", "Quitar la selección", self._clear_selection, "Quitar"), None,
                     spacing=4))

    def _page_crop(self) -> QWidget:
        self.aspect = QComboBox()
        self.aspect.addItems(list(ASPECTS))
        self.aspect.setAccessibleName(tr("Proporción del recorte"))
        self.aspect.currentTextChanged.connect(lambda t: self.doc and self.canvas.start_crop(ASPECTS[t]))
        rot = h_layout(*[self._icon_btn(ic, tip, fn) for ic, tip, fn in (
            ("rotate_left", "Girar a la izquierda", lambda: self._op(lambda d: d.rotate90(False))),
            ("rotate", "Girar a la derecha", lambda: self._op(lambda d: d.rotate90(True))),
            ("flip_h", "Voltear horizontal", lambda: self._op(lambda d: d.flip(True))),
            ("flip_v", "Voltear vertical", lambda: self._op(lambda d: d.flip(False))))], None, spacing=4)
        self.straight = QSlider(Qt.Orientation.Horizontal)
        self.straight.setRange(-450, 450)
        self.straight.setAccessibleName(tr("Enderezar"))
        self.straight_lbl = label("0,0°", "caption")
        self.straight.valueChanged.connect(lambda v: self.straight_lbl.setText(f"{v / 10:.1f}°".replace(".", ",")))
        straight_ok = self._flat("Aplicar", lambda: (self._op(lambda d: d.straighten(self.straight.value() / 10)),
                                                     self.straight.setValue(0)))
        return self._page(
            label(tr("Proporción"), "muted"), self.aspect,
            h_layout(self._primary("Recortar", lambda: (self.canvas.apply_crop(), self._sync_all())),
                     self._flat(tr("Cancelar"), lambda: (setattr(self.canvas, "crop_rect", None),
                                                      self.canvas.update())), spacing=6), 6,
            label("Girar", "muted"), rot,
            Collapsible("Enderezar", v_layout(h_layout(self.straight, self.straight_lbl, spacing=8), straight_ok,
                                              spacing=6)))

    def _page_resize(self) -> QWidget:
        self.res_w, self.res_h = QSpinBox(), QSpinBox()
        for sp in (self.res_w, self.res_h):
            sp.setRange(1, 30000)
            sp.setSuffix(tr(" px"))
            sp.setKeyboardTracking(False)
        self.keep = QCheckBox(tr("Mantener proporción"))
        self.keep.setChecked(True)
        self.res_w.valueChanged.connect(lambda v: self._ratio("w", v))
        self.res_h.valueChanged.connect(lambda v: self._ratio("h", v))
        quick = h_layout(*[self._flat(f"{p} %", lambda _c=False, p=p: self._scale_to(p)) for p in (25, 50, 75)],
                         None, spacing=4)
        self.margin = QSpinBox()
        self.margin.setRange(1, 2000)
        self.margin.setValue(40)
        self.margin.setSuffix(tr(" px"))
        from aero.ui.pages.theme_studio import ColorButton

        self.margin_color = ColorButton("Color", "#ffffff")
        m_ok = self._flat(tr("Añadir márgenes"), lambda: self._op(lambda d: d.add_margins(
            *(self.margin.value(),) * 4, QColor(self.margin_color.color)), fit=True))
        return self._page(
            h_layout(self.res_w, label("×", "caption"), self.res_h, spacing=6), self.keep, quick,
            self._primary("Aplicar tamaño", lambda: self._op(
                lambda d: d.resize(self.res_w.value(), self.res_h.value()), fit=True)),
            Collapsible(tr("Márgenes"), v_layout(h_layout(self.margin, self.margin_color, spacing=6), m_ok, spacing=6)))

    def _page_adjust(self) -> QWidget:
        from aero.ui.pages.theme_studio import ValueSlider

        self.adj_sliders: dict[str, ValueSlider] = {}

        def grid_for(keys):
            g = QGridLayout()
            g.setVerticalSpacing(2)
            for i, key in enumerate(keys):
                lo = 0 if key in adjust.POSITIVE_ONLY else -100
                vs = ValueSlider(0.0, adjust.LABELS[key], minimum=lo, maximum=100, suffix="")
                vs.changed.connect(lambda v, k=key: self.set_adjust(k, v))
                g.addWidget(label(adjust.LABELS[key], "caption"), i, 0)
                g.addWidget(vs, i, 1)
                self.adj_sliders[key] = vs
            return g

        basic = ["brightness", "contrast", "saturation", "temperature"]
        more = [k for k in adjust.SLIDERS if k not in basic]
        self.bw = QCheckBox(tr("Blanco y negro"))
        self.bw.toggled.connect(lambda on: self.set_adjust("grayscale", on))
        self.sepia = QCheckBox(tr("Sepia"))
        self.sepia.toggled.connect(lambda on: self.set_adjust("sepia", on))
        return self._page(grid_for(basic), h_layout(self.bw, self.sepia, None),
                          Collapsible(tr("Más ajustes"), grid_for(more)),
                          h_layout(None, self._flat("Restablecer", lambda: self.apply_preset("Original"))))

    def _page_filters(self) -> QWidget:
        self.filter_grid = QGridLayout()
        self.filter_grid.setSpacing(6)
        self.filter_buttons: dict[str, QToolButton] = {}
        for i, name in enumerate(adjust.PRESETS):
            b = QToolButton()
            b.setText({"Blanco y negro": "Monocromo"}.get(name, name))
            b.setToolTip(f"Filtro {name}")
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(72, 54))
            b.setFixedSize(82, 80)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, n=name: self.apply_preset(n))
            self.filter_buttons[name] = b
            self.filter_grid.addWidget(b, i // 3, i % 3)
        self._thumbs_version = None
        return self._page(self.filter_grid)

    def _page_pixels(self) -> QWidget:
        self.block = QSpinBox()
        self.block.setRange(2, 200)
        self.block.setValue(16)
        self.block.setSuffix(tr(" px"))
        self.block.setAccessibleName(tr("Tamaño de los píxeles"))
        self.pixel_target = label("", "caption")
        acts = h_layout(
            self._icon_btn("pixel", "Pixelar la zona (o toda la imagen)", lambda: self._region(
                lambda d, r: d.pixelate(r, self.block.value())), "Pixelar"),
            self._icon_btn("grid", "Mosaico", lambda: self._region(
                lambda d, r: d.mosaic(r, self.block.value())), "Mosaico"),
            self._icon_btn("drop", "Desenfocar la zona", lambda: self._region(
                lambda d, r: d.blur_region(r, max(2, self.block.value() // 2))), "Desenfocar"), None, spacing=4)
        low = self._flat(tr("Baja resolución"), lambda: self._op(lambda d: d.low_resolution(max(2, self.block.value() // 2))))
        low.setToolTip(tr("Toda la imagen"))
        tip = label(tr("Arrastra sobre la foto para elegir la zona"), "caption")
        return self._page(tip, self.pixel_target, h_layout(label(tr("Tamaño"), "muted"), self.block, None), acts,
                          Collapsible(tr("Toda la imagen"), v_layout(low)))

    def _tool_row(self, tools) -> QWidget:
        row = QWidget()
        lay = QGridLayout()
        lay.setSpacing(4)
        lay.setContentsMargins(0, 0, 0, 0)
        for i, (key, ic, tip) in enumerate(tools):
            b = QToolButton()
            b.setIcon(tm().icon(ic, 20))
            b.setIconSize(QSize(20, 20))
            b.setText(tip)
            b.setToolTip(tip)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setFixedSize(76, 52)
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, k=key: self.set_tool(k))
            self._tool_buttons[key] = b
            lay.addWidget(b, i // 3, i % 3)
        row.setLayout(lay)
        return row

    def _stroke_controls(self) -> list:
        from aero.ui.pages.theme_studio import ColorButton, ValueSlider

        color = ColorButton("Color", self.canvas.color.name())
        color.picked.connect(lambda c: (setattr(self.canvas, "color", QColor(c)), self._sync_colors(c)))
        self._color_buttons.append(color)
        width = QSpinBox()
        width.setRange(1, 400)
        width.setValue(self.canvas.width_px)
        width.setSuffix(tr(" px"))
        width.valueChanged.connect(lambda v: setattr(self.canvas, "width_px", v))
        op = ValueSlider(1.0, "Opacidad", minimum=5, maximum=100)
        op.changed.connect(lambda v: setattr(self.canvas, "opacity", v))
        return [color, h_layout(label("Grosor", "muted"), width, None), h_layout(label("Opacidad", "muted"), op)]

    def _page_draw(self) -> QWidget:
        fill = QCheckBox(tr("Rellenar formas"))
        fill.toggled.connect(lambda on: setattr(self.canvas, "fill", on))
        row = self._tool_row([("brush", "brush", "Pincel"), ("highlight", "highlight", "Resaltar"),
                              ("line", "line", "Línea"), ("arrow", "arrow", "Flecha"), ("rect", "rect", "Rectángulo"),
                              ("ellipse", "ellipse", "Elipse")])
        tip = label(tr("Mayús: líneas rectas y formas regulares"), "caption")
        return self._page(row, *self._stroke_controls(), fill, tip)

    def _page_text(self) -> QWidget:
        from aero.ui.pages.theme_studio import ColorButton

        size = QSpinBox()
        size.setRange(6, 1000)
        size.setValue(self.canvas.font_size)
        size.setSuffix(tr(" px"))
        size.valueChanged.connect(lambda v: setattr(self.canvas, "font_size", v))
        bold = QCheckBox(tr("Negrita"))
        bold.setChecked(True)
        bold.toggled.connect(lambda on: setattr(self.canvas, "bold", on))
        color = ColorButton("Color", self.canvas.color.name())
        color.picked.connect(lambda c: (setattr(self.canvas, "color", QColor(c)), self._sync_colors(c)))
        self._color_buttons.append(color)
        return self._page(label(tr("Haz clic en la foto para escribir"), "caption"),
                          h_layout(label(tr("Tamaño"), "muted"), size, None), bold, color)

    def _page_layers(self) -> QWidget:
        from aero.ui.pages.theme_studio import ValueSlider

        self.layer_list = QListWidget()
        self.layer_list.setAccessibleName(tr("Capas"))
        self.layer_list.currentRowChanged.connect(self._select_layer)
        self.layer_list.itemChanged.connect(self._layer_visibility)
        acts = h_layout(*[self._icon_btn(ic, tip, fn) for ic, tip, fn in (
            ("plus", "Añadir una imagen como capa", self.import_image),
            ("up", "Subir", lambda: self._layer_op(lambda d, i: d.move_layer(i, 1))),
            ("down", "Bajar", lambda: self._layer_op(lambda d, i: d.move_layer(i, -1))),
            ("list_add", "Duplicar", lambda: self._layer_op(lambda d, i: d.duplicate_layer(i))),
            ("trash", "Eliminar", lambda: self._layer_op(lambda d, i: d.remove_layer(i))))], None, spacing=4)
        self.l_opacity = ValueSlider(1.0, "Opacidad de la capa", minimum=0, maximum=100)
        self.l_opacity.changed.connect(lambda v: self._layer_prop("opacity", v))
        self.l_scale = QSpinBox()
        self.l_scale.setRange(1, 1000)
        self.l_scale.setSuffix(" %")
        self.l_scale.valueChanged.connect(lambda v: self._layer_prop("scale", v / 100))
        self.l_angle = QSpinBox()
        self.l_angle.setRange(-180, 180)
        self.l_angle.setSuffix("°")
        self.l_angle.setWrapping(True)
        self.l_angle.valueChanged.connect(lambda v: self._layer_prop("angle", float(v)))
        form = QFormLayout()
        form.addRow(tr("Opacidad"), self.l_opacity)
        form.addRow(tr("Tamaño"), self.l_scale)
        form.addRow(tr("Giro"), self.l_angle)
        self.layer_props = QWidget()
        self.layer_props.setLayout(form)
        return self._page(self.layer_list, acts, self.layer_props)

    def _page_export(self) -> QWidget:
        exp = self._primary("Exportar…", self.export_dialog)
        exp.setToolTip(tr("Formato, calidad y tamaño (Ctrl+E)"))
        copy = self._flat(tr("Guardar una copia…"), self.save_as)
        proj = self._flat(tr("Proyecto editable…"), lambda: self.save_as(project=True))
        proj.setToolTip(tr("Conserva capas y ajustes para seguir editando"))
        over = self._flat(tr("Sobrescribir el original"), self._overwrite)
        over.setProperty("kind", "danger")
        return self._page(exp, copy, proj, 10, over, label(tr("El original no cambia salvo que lo sobrescribas."),
                                                           "caption", wrap=True))

    # ------------------------------------------------------------------ herramientas
    def show_category(self, key: str):
        key = LEGACY.get(key, key)
        b, idx = self._page_index[key]
        b.setChecked(True)
        self.pages.setCurrentIndex(idx)
        self.page_title.setText(next(t for k, _i, t, _tip in CATEGORIES if k == key))
        tool = {"select": "select", "crop": "crop", "resize": "hand", "adjust": "hand", "filters": "hand",
                "pixels": "select", "draw": "brush", "text": "text", "layers": "move", "export": "hand"}[key]
        self.set_tool(tool)
        if key == "crop" and self.doc is not None:
            self.canvas.start_crop(ASPECTS[self.aspect.currentText()])
        elif self.canvas.crop_rect is not None:
            self.canvas.crop_rect = None
        if key not in ("pixels", "select"):
            self.canvas.selection = None
        elif self.doc is not None and key == "pixels":
            # Los efectos de píxel se aplican a la foto; para otra capa, elígela antes en «Capas».
            if self._came_from != "layers":
                self.doc.active = 0
            self.pixel_target.setText(tr("Se aplica a: {v0}", v0=self.doc.current.name))
        if key == "filters":
            self._filter_thumbs()
        self._came_from = key
        self.canvas.update()

    def set_tool(self, tool: str):
        if tool == "crop" and getattr(self, "_page_index", None) and \
                self.pages.currentIndex() != self._page_index["crop"][1]:
            self.show_category("crop")  # p. ej. «Recortar» desde el visor
            return
        self.canvas.tool = tool
        for k, b in getattr(self, "_tool_buttons", {}).items():
            b.setChecked(k == tool)

    def _sync_colors(self, c: str):
        for b in self._color_buttons:
            b.set_color(c)

    def _crop_to_selection(self):
        r = self.canvas.selection_rect()
        if self.doc is None or r is None:
            self.info.setText(tr("Primero arrastra sobre la foto"))
            return
        self._op(lambda d: d.crop(r), fit=True)

    def _clear_selection(self):
        self.canvas.selection = None
        self.canvas.update()

    def _scale_to(self, pct: int):
        if self.doc is None:
            return
        s = self.doc.size
        self.res_w.setValue(max(1, round(s.width() * pct / 100)))
        self.res_h.setValue(max(1, round(s.height() * pct / 100)))

    def _filter_thumbs(self):
        """Miniaturas de cada filtro sobre la propia foto (en segundo plano, una vez por versión)."""
        if self.doc is None or self._thumbs_version == self.doc.version:
            return
        from aero.core.tasks import tasks

        self._thumbs_version = self.doc.version
        snap = _snapshot(self.doc)

        def job():
            from PySide6.QtCore import Qt as _Qt

            base = snap.render(1.0)
            small = base.scaled(144, 108, _Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                _Qt.TransformationMode.SmoothTransformation)
            out = {}
            for name, preset in adjust.PRESETS.items():
                a = dict(adjust.NEUTRAL)
                a.update(preset)
                out[name] = adjust.apply(small, a, small.width() / max(1, base.width()))
            return out

        def done(images):
            from PySide6.QtGui import QIcon, QPixmap

            for name, img in images.items():
                b = self.filter_buttons.get(name)
                if b is not None:
                    b.setIcon(QIcon(QPixmap.fromImage(img)))

        tasks().submit(job, "interactive", done, lambda _e: None, self)

    # ------------------------------------------------------------------ operaciones
    def _op(self, fn, fit: bool = False):
        if self.doc is None:
            return
        fn(self.doc)
        self.canvas.selection = None
        self.canvas.refresh()
        if fit:
            self.canvas.fit()
        self._sync_all()

    def _region(self, fn):
        if self.doc is None:
            return
        r = self.canvas.selection_rect()
        if r is None:
            from PySide6.QtCore import QRect

            r = QRect(0, 0, self.doc.size.width(), self.doc.size.height())
        result = []
        self._op(lambda d: result.append(fn(d, r)))
        if result and result[0] is False:
            self.info.setText(tr("La zona elegida no toca la capa «{v0}»", v0=self.doc.current.name))

    def set_adjust(self, key: str, value):
        if self.doc is None or self.doc.adjust.get(key) == value:
            return
        if not self._adj_open:
            self.doc.checkpoint("Ajustes de color")
            self._adj_open = True
        self._adj_timer.start()
        self.doc.adjust[key] = value
        self.doc.changed()
        self.canvas.refresh()

    def apply_preset(self, name: str):
        if self.doc is None:
            return
        self.doc.checkpoint(f"Filtro {name}")
        a = dict(adjust.NEUTRAL)
        a.update(adjust.PRESETS[name])
        self.doc.adjust = a
        self.doc.changed()
        self.canvas.refresh()
        self._sync_adjust()

    def undo(self):
        if self.doc and self.doc.undo():
            self.canvas.refresh()
            self._sync_all()

    def redo(self):
        if self.doc and self.doc.redo():
            self.canvas.refresh()
            self._sync_all()

    # ------------------------------------------------------------------ capas
    def import_image(self):
        if self.doc is None:
            return
        f, _ = QFileDialog.getOpenFileName(self, tr("Importar imagen"), str(Path(self.path).parent),
                                           "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.heic *.avif)")
        if not f:
            return
        from aero.ui.viewers.image_viewer import load_qimage

        img = load_qimage(f)
        if img.isNull():
            QMessageBox.warning(self, tr("Importar imagen"), tr("No se pudo leer la imagen."))
            return
        self.doc.add_image_layer(img, Path(f).stem)
        self.set_tool("move")
        self.canvas.refresh()
        self._sync_all()

    def _layer_op(self, fn):
        if self.doc is None:
            return
        fn(self.doc, self.doc.active)
        self.canvas.refresh()
        self._sync_all()

    def _select_layer(self, row: int):
        if self.doc is None or row < 0 or getattr(self, "_syncing", False):
            return
        self.doc.active = len(self.doc.layers) - 1 - row
        self._sync_layer_props()
        self.canvas.update()

    def _layer_visibility(self, item: QListWidgetItem):
        if self.doc is None or getattr(self, "_syncing", False):
            return
        i = len(self.doc.layers) - 1 - self.layer_list.row(item)
        on = item.checkState() == Qt.CheckState.Checked
        if self.doc.layers[i].visible != on:
            self.doc.checkpoint("Mostrar u ocultar capa")
            self.doc.layers[i].visible = on
            self.doc.changed()
            self.canvas.refresh()

    def _layer_prop(self, key: str, value):
        if self.doc is None or getattr(self, "_syncing", False) or self.doc.current.background:
            return
        ly = self.doc.current
        if getattr(ly, key) == value:
            return
        if not self._adj_open:
            self.doc.checkpoint("Propiedades de capa")
            self._adj_open = True
        self._adj_timer.start()
        setattr(ly, key, value)
        self.doc.changed()
        self.canvas.refresh()

    # ------------------------------------------------------------------ sincronización
    def _sync_title(self):
        if self.doc is None:
            return
        s = self.doc.size
        self.info.setText(tr("{v0} × {v1} px", v0=s.width(), v1=s.height()) + (tr(" · sin guardar") if self.doc.dirty else ""))
        self.btn_undo.setEnabled(bool(self.doc.undo_stack))
        self.btn_redo.setEnabled(bool(self.doc.redo_stack))
        self.btn_undo.setToolTip("Deshacer " + self.doc.undo_stack[-1][0].lower() + " (Ctrl+Z)"
                                 if self.doc.undo_stack else tr("Deshacer (Ctrl+Z)"))

    def _sync_adjust(self):
        a = self.doc.adjust
        for k, vs in self.adj_sliders.items():
            vs.set_value(float(a.get(k, 0.0)))
        for cb, k in ((self.bw, "grayscale"), (self.sepia, "sepia")):
            cb.blockSignals(True)
            cb.setChecked(bool(a.get(k)))
            cb.blockSignals(False)

    def _sync_layer_props(self):
        if self.doc is None:
            return
        self._syncing = True
        ly = self.doc.current
        self.layer_props.setEnabled(not ly.background)
        self.l_opacity.set_value(ly.opacity)
        self.l_scale.setValue(int(round(ly.scale * 100)))
        self.l_angle.setValue(int(round(((ly.angle + 180) % 360) - 180)))
        self._syncing = False

    def _sync_all(self):
        if self.doc is None:
            return
        self._syncing = True
        s = self.doc.size
        for sp, v in ((self.res_w, s.width()), (self.res_h, s.height())):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)
        self.layer_list.clear()
        for ly in reversed(self.doc.layers):
            it = QListWidgetItem(tm().icon("image" if ly.background else "layers", 18), ly.name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if ly.visible else Qt.CheckState.Unchecked)
            self.layer_list.addItem(it)
        self.layer_list.setCurrentRow(len(self.doc.layers) - 1 - self.doc.active)
        self._syncing = False
        self._sync_adjust()
        self._sync_layer_props()
        self._sync_title()

    def _ratio(self, which: str, v: int):
        if not self.keep.isChecked() or self.doc is None:
            return
        s = self.doc.size
        other, val = (self.res_h, round(v * s.height() / s.width())) if which == "w" else \
            (self.res_w, round(v * s.width() / s.height()))
        other.blockSignals(True)
        other.setValue(max(1, val))
        other.blockSignals(False)

    # ------------------------------------------------------------------ guardar y exportar
    def save(self):
        if self.doc is None:
            return
        if self.project_path:
            self.doc.save_project(self.project_path)
            self._sync_title()
            return
        box = QMessageBox(QMessageBox.Icon.Question, "Guardar",
                          "¿Cómo quieres guardar los cambios?\n\nEl original se conserva salvo que elijas "
                          "sobrescribirlo.", parent=self)
        copy = box.addButton(tr("Guardar una copia…"), QMessageBox.ButtonRole.AcceptRole)
        proj = box.addButton(tr("Proyecto editable…"), QMessageBox.ButtonRole.ActionRole)
        over = box.addButton(tr("Sobrescribir el original"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(copy)
        box.exec()
        b = box.clickedButton()
        if b is copy:
            self.save_as()
        elif b is proj:
            self.save_as(project=True)
        elif b is over:
            self._overwrite()

    def _overwrite(self):
        if self.doc is None:
            return
        sure = QMessageBox.warning(self, tr("Sobrescribir el original"),
                                   tr("Se reemplazará «{v0}» por la versión editada. Esta acción no se puede deshacer desde AERO Player.\n\n¿Continuar?", v0=Path(self.path).name),
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.No)
        if sure == QMessageBox.StandardButton.Yes:
            ext = Path(self.path).suffix.lower().lstrip(".")
            fmt = "jpg" if ext in ("jpeg", "jfif") else ext
            if fmt not in dict((v, k) for k, v in FORMATS):
                QMessageBox.information(self, tr("Guardar"), tr("Este formato no se puede escribir; guarda una copia."))
                return
            self.export_to(self.path, fmt, 92, 1.0)

    def save_as(self, project: bool = False):
        if self.doc is None:
            return
        base = Path(self.path)
        if project:
            f, _ = QFileDialog.getSaveFileName(self, tr("Guardar proyecto"), str(base.with_suffix(PROJECT_EXT)),
                                               f"Proyecto de AERO Player (*{PROJECT_EXT})")
            if f:
                self.doc.save_project(f)
                self.project_path = f
                self._sync_title()
            return
        filters = ";;".join(f"{n} (*.{e})" for n, e in FORMATS) + f";;Proyecto editable (*{PROJECT_EXT})"
        f, chosen = QFileDialog.getSaveFileName(self, tr("Guardar como"), str(base.with_name(base.stem + " (editada).png")),
                                                filters)
        if not f:
            return
        if f.lower().endswith(PROJECT_EXT):
            self.doc.save_project(f)
            self.project_path = f
            self._sync_title()
            return
        ext = Path(f).suffix.lower().lstrip(".")
        fmt = {"jpeg": "jpg", "tif": "tiff"}.get(ext, ext)
        if fmt not in [e for _n, e in FORMATS]:
            fmt = "png"
            f += ".png"
        self.export_to(f, fmt, 92, 1.0)

    def export_dialog(self):
        if self.doc is None:
            return
        dlg = ExportDialog(self, self.doc)
        if dlg.exec():
            self.export_to(dlg.target, dlg.fmt(), dlg.quality.value(), dlg.scale())

    def export_to(self, path: str, fmt: str, quality: int, scale: float):
        """Exporta en segundo plano (cola de tareas pesadas) sin bloquear la edición."""
        from aero.core.tasks import tasks

        snap = _snapshot(self.doc)
        self.info.setText(tr("Exportando {v0}…", v0=Path(path).name))

        version = self.doc.version

        def done(n):
            if self.doc.version == version:
                self.doc.dirty = False  # lo guardado coincide con lo que se ve
            self._exported = path
            self._sync_title()
            self.info.setText(tr("Guardado {v0} · {v1}", v0=Path(path).name, v1=human_size(n)))

        tasks().submit(lambda: _export_job(snap, path, fmt, quality, scale), "heavy", done,
                       lambda e: QMessageBox.warning(self, tr("Exportar"), tr("No se pudo guardar: {e}", e=e)), self)

    def closeEvent(self, e):
        if self.doc is not None and self.doc.dirty:
            r = QMessageBox.question(self, tr("Cerrar el editor"), tr("Hay cambios sin guardar. ¿Cerrar de todos modos?"),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
        super().closeEvent(e)
        self.closed.emit()
        if self.controller is not None:
            self.controller.editor_closed(self)


class ExportDialog(TrDialog):
    """Formato, calidad, tamaño y peso estimado (calculado en segundo plano) antes de guardar una copia."""

    def __init__(self, parent: EditorWindow, doc: ImageDocument):
        super().__init__(parent)
        self.setWindowTitle(tr("Exportar"))
        self.doc = doc
        self.target = ""
        self.format = QComboBox()
        for n, e in FORMATS:
            self.format.addItem(n, e)
        self.format.setCurrentIndex(1)
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(10, 100)
        self.quality.setValue(85)
        self.q_lbl = label("85", "caption")
        self.size_pct = QSpinBox()
        self.size_pct.setRange(5, 400)
        self.size_pct.setValue(100)
        self.size_pct.setSuffix(" %")
        self.dims = label("", "caption")
        self.est = label(tr("Calculando…"), "caption")
        form = QFormLayout()
        form.addRow(tr("Formato"), self.format)
        form.addRow(tr("Calidad"), h_layout(self.quality, self.q_lbl, spacing=8))
        form.addRow(tr("Tamaño"), h_layout(self.size_pct, self.dims, spacing=8))
        form.addRow(tr("Peso estimado"), self.est)
        ok = QPushButton(tr("Exportar…"))
        ok.setProperty("kind", "primary")
        ok.clicked.connect(self._choose)
        cancel = QPushButton(tr("Cancelar"))
        cancel.clicked.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addLayout(form)
        lay.addWidget(label(tr("Se guarda una copia; el archivo original no cambia."), "caption"))
        lay.addLayout(h_layout(None, cancel, ok))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._estimate)
        for sig in (self.format.currentIndexChanged, self.quality.valueChanged, self.size_pct.valueChanged):
            sig.connect(self._changed)
        self._changed()

    def fmt(self) -> str:
        return self.format.currentData()

    def scale(self) -> float:
        return self.size_pct.value() / 100

    def _changed(self, *_):
        self.q_lbl.setText(str(self.quality.value()))
        self.quality.setEnabled(self.fmt() in ("jpg", "webp"))
        s = self.doc.size
        self.dims.setText(tr("{v0} × {v1} px", v0=round(s.width() * self.scale()), v1=round(s.height() * self.scale())))
        self.est.setText(tr("Calculando…"))
        self._timer.start()

    def _estimate(self):
        from aero.core.tasks import tasks

        snap, fmt, q, sc = _snapshot(self.doc), self.fmt(), self.quality.value(), self.scale()
        key = (fmt, q, sc)
        self._key = key
        tasks().submit(lambda: len(encode(snap.render(sc), fmt, q)), "interactive",
                       lambda n: self._key == key and self.est.setText("≈ " + human_size(n)),
                       lambda _e: self.est.setText("—"), self)

    def _choose(self):
        base = Path(self.parent().path)
        f, _ = QFileDialog.getSaveFileName(self, tr("Exportar"), str(base.with_name(f"{base.stem} (editada).{self.fmt()}")),
                                           f"{self.format.currentText()} (*.{self.fmt()})")
        if f:
            if not f.lower().endswith("." + self.fmt()):
                f += "." + self.fmt()
            self.target = f
            self.accept()


def open_editor(path: str, controller=None) -> EditorWindow:
    w = EditorWindow(path, controller)
    w.resize(1280, 820)
    w.show()
    w.raise_()
    w.activateWindow()
    return w

