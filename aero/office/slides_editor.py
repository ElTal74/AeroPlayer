"""Editor de presentaciones (PPTX; ODP y PPT a través de LibreOffice si está instalado).

Diapositivas a la izquierda, la diapositiva en grande en el centro y las propiedades del elemento elegido a
la derecha. Se puede crear, duplicar, eliminar y reordenar diapositivas; añadir y editar texto, imágenes y
formas; mover y redimensionar elementos; cambiar fondos y colores; presentar a pantalla completa y exportar
a PDF. python-pptx conserva el resto del archivo (diseños, notas, animaciones) aunque el editor no lo muestre.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Pt
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QColorDialog, QFileDialog, QFormLayout, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout,
                               QWidget)

from aero.ui.glass import GlassPanel, IconButton, h_layout, label, v_layout
from aero.ui.glasswindow import DragArea, GlassWindow
from aero.i18n import tr

RENDER_W = 1280
THUMB_W = 176
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


# --------------------------------------------------------------------------- operaciones (sin interfaz)
def blank_layout(prs):
    """Diseño «en blanco»: el de nombre conocido o el que tiene menos marcadores de contenido."""
    from pptx.enum.shapes import PP_PLACEHOLDER

    meta = {PP_PLACEHOLDER.DATE, PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.SLIDE_NUMBER}
    for layout in prs.slide_layouts:
        if layout.name.strip().lower() in ("blank", "en blanco", "vacía", "vacio", "vacío"):
            return layout
    return min(prs.slide_layouts,
               key=lambda lay: sum(1 for ph in lay.placeholders if ph.placeholder_format.type not in meta))


def add_slide(prs, index: int | None = None, title: str = ""):
    layout = prs.slide_layouts[1] if title and len(prs.slide_layouts) > 1 else blank_layout(prs)
    s = prs.slides.add_slide(layout)
    if title and s.shapes.title is not None:
        s.shapes.title.text = title
    elif not title:
        for ph in list(s.placeholders):
            if not ph.has_text_frame or not ph.text_frame.text.strip():
                ph._element.getparent().remove(ph._element)  # diapositiva realmente en blanco
    if index is not None:
        move_slide(prs, len(prs.slides) - 1, index)
    return s


def move_slide(prs, old: int, new: int):
    lst = prs.slides._sldIdLst
    items = list(lst)
    el = items[old]
    lst.remove(el)
    lst.insert(max(0, min(new, len(items) - 1)), el)


def delete_slide(prs, index: int):
    lst = prs.slides._sldIdLst
    el = list(lst)[index]
    prs.part.drop_rel(el.rId)
    lst.remove(el)


def duplicate_slide(prs, index: int):
    src = prs.slides[index]
    dst = prs.slides.add_slide(src.slide_layout)
    for ph in list(dst.placeholders):
        ph._element.getparent().remove(ph._element)
    for el in src.shapes._spTree.iterchildren():
        if el.tag.endswith(("}nvGrpSpPr", "}grpSpPr")):
            continue
        new = copy.deepcopy(el)
        for blip in new.iter(f"{A_NS}blip"):
            rid = blip.get(R_EMBED)
            if rid and rid in src.part.rels:
                rel = src.part.rels[rid]
                blip.set(R_EMBED, dst.part.relate_to(rel._target, rel.reltype))
        dst.shapes._spTree.append(new)
    try:
        if src.background.fill.type == 1:
            dst.background.fill.solid()
            dst.background.fill.fore_color.rgb = src.background.fill.fore_color.rgb
    except Exception:  # noqa: BLE001
        pass
    move_slide(prs, len(prs.slides) - 1, index + 1)
    return dst


def set_text(shape, text: str):
    """Cambia el texto conservando el formato del primer tramo."""
    tf = shape.text_frame
    fmt = None
    for p in tf.paragraphs:
        if p.runs:
            f = p.runs[0].font
            fmt = (f.size, f.bold, f.italic, f.color.rgb if f.color and f.color.type is not None else None)
            break
    tf.text = text
    if fmt:
        for p in tf.paragraphs:
            for r in p.runs:
                r.font.size, r.font.bold, r.font.italic = fmt[0], fmt[1], fmt[2]
                if fmt[3] is not None:
                    r.font.color.rgb = fmt[3]


def style_text(shape, size: float | None = None, bold: bool | None = None, color: QColor | None = None):
    for p in shape.text_frame.paragraphs:
        for r in p.runs:
            if size:
                r.font.size = Pt(size)
            if bold is not None:
                r.font.bold = bold
            if color is not None:
                r.font.color.rgb = RGBColor(color.red(), color.green(), color.blue())


def delete_shape(shape):
    shape._element.getparent().remove(shape._element)


# --------------------------------------------------------------------------- lienzo de la diapositiva
class SlideCanvas(QWidget):
    selected = Signal(object)
    edited = Signal()
    text_requested = Signal(object)

    def __init__(self, editor: "SlidesEditor"):
        super().__init__()
        self.ed = editor
        self.img = None
        self.shape = None
        self._drag = None
        self.setMouseTracking(True)
        self.setMinimumSize(480, 300)

    def slide_rect(self) -> QRectF:
        prs = self.ed.prs
        ar = prs.slide_width / prs.slide_height
        w = min(self.width() - 32, (self.height() - 32) * ar)
        h = w / ar
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _k(self) -> float:
        return self.slide_rect().width() / self.ed.prs.slide_width

    def shape_rect(self, sh) -> QRectF:
        r, k = self.slide_rect(), self._k()
        return QRectF(r.left() + (sh.left or 0) * k, r.top() + (sh.top or 0) * k, (sh.width or 0) * k,
                      (sh.height or 0) * k)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.slide_rect()
        p.fillRect(r.translated(0, 3), QColor(0, 0, 0, 60))
        if self.img is not None:
            p.drawImage(r, self.img)
        if self.shape is not None:
            sr = self.shape_rect(self.shape)
            p.setPen(QPen(QColor("#2f8fff"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sr)
            p.setBrush(QColor("white"))
            for c in (sr.topLeft(), sr.topRight(), sr.bottomLeft(), sr.bottomRight()):
                p.drawEllipse(c, 4.5, 4.5)

    def _hit(self, pos: QPointF):
        for sh in reversed(list(self.ed.slide.shapes)):
            if sh.width is not None and self.shape_rect(sh).contains(pos):
                return sh
        return None

    def _corner(self, pos: QPointF):
        if self.shape is None:
            return None
        sr = self.shape_rect(self.shape)
        for name, c in (("tl", sr.topLeft()), ("tr", sr.topRight()), ("bl", sr.bottomLeft()),
                        ("br", sr.bottomRight())):
            if (pos - c).manhattanLength() < 12:
                return name
        return None

    def mousePressEvent(self, e):
        pos = e.position()
        corner = self._corner(pos)
        if corner is None:
            self.shape = self._hit(pos)
            self.selected.emit(self.shape)
        if self.shape is not None:
            sh = self.shape
            self.ed.checkpoint()
            self._drag = (corner or "move", pos, (sh.left, sh.top, sh.width, sh.height))
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is None:
            c = self._corner(pos)
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if c in ("tl", "br") else
                           Qt.CursorShape.SizeBDiagCursor if c in ("tr", "bl") else
                           Qt.CursorShape.SizeAllCursor if self._hit(pos) is not None else Qt.CursorShape.ArrowCursor)
            return
        mode, start, (x, y, w, h) = self._drag
        k = self._k()
        dx, dy = int((pos.x() - start.x()) / k), int((pos.y() - start.y()) / k)
        sh = self.shape
        if mode == "move":
            sh.left, sh.top = Emu(x + dx), Emu(y + dy)
        else:
            nx, ny, nw, nh = x, y, w, h
            if "l" in mode:
                nx, nw = x + dx, w - dx
            if "r" in mode:
                nw = w + dx
            if "t" in mode:
                ny, nh = y + dy, h - dy
            if "b" in mode:
                nh = h + dy
            if nw > 20000 and nh > 20000:
                sh.left, sh.top, sh.width, sh.height = Emu(nx), Emu(ny), Emu(nw), Emu(nh)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.edited.emit()

    def mouseDoubleClickEvent(self, e):
        sh = self._hit(e.position())
        if sh is not None and getattr(sh, "has_text_frame", False) and sh.has_text_frame:
            self.shape = sh
            self.text_requested.emit(sh)


class SlidesEditor(GlassWindow):
    def __init__(self, path: str = "", controller=None):
        super().__init__(Qt.WindowType(0), flat=True)
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumSize(1000, 640)
        self.backdrop.flat_opacity = 0.94
        self.path = os.path.abspath(path) if path else ""
        self.dirty = False
        self._history: list[bytes] = []
        self._save_ok = False
        try:
            self.prs = self._open(self.path)
        except Exception as e:  # noqa: BLE001 - archivo dañado o formato no compatible: se avisa y se abre vacío
            QMessageBox.warning(None, tr("Presentación"), tr("No se pudo abrir «{v0}»: {e}", v0=Path(path).name, e=e))
            self.prs = Presentation()
            self.path = ""
        self.index = 0

        bar = DragArea()
        self.title = label("", "h3")
        self.info = label("", "caption")
        acts = []
        for ic, tip, fn in (("plus", "Nueva diapositiva", self.new_slide),
                            ("list_add", "Duplicar diapositiva", self.dup_slide),
                            ("trash", "Eliminar diapositiva", self.del_slide),
                            ("text_tool", "Añadir cuadro de texto", self.add_text),
                            ("image", "Añadir imagen", self.add_image),
                            ("rect", "Añadir forma", self.add_shape_menu),
                            ("brush", "Color de fondo de la diapositiva", self.pick_background),
                            ("undo", "Deshacer (Ctrl+Z)", self.undo)):
            b = IconButton(ic, tip, 18)
            b.clicked.connect(fn)
            acts.append(b)
        present = QPushButton(tr("Presentar"))
        present.setIcon(IconButton("play", "", 16).icon())
        present.clicked.connect(self.present)
        pdf = IconButton("pdf", tr("Exportar a PDF"), 18)
        pdf.clicked.connect(self.export_pdf)
        save = IconButton("save", tr("Guardar (Ctrl+S)"), 18)
        save.clicked.connect(self.save)
        save_as = IconButton("external", tr("Guardar como…"), 18)
        save_as.clicked.connect(self.save_as)
        bar.setLayout(h_layout(14, v_layout(self.title, self.info, spacing=0), 18, *acts, None, present, 6, pdf,
                               save_as, save, 10, self.window_buttons(), spacing=3, margins=(0, 8, 10, 8)))

        self.thumbs = QListWidget()
        self.thumbs.setIconSize(QSize(THUMB_W, int(THUMB_W * 0.5625)))
        self.thumbs.setFixedWidth(THUMB_W + 34)
        self.thumbs.setSpacing(4)
        self.thumbs.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.thumbs.model().rowsMoved.connect(self._rows_moved)
        self.thumbs.currentRowChanged.connect(self.go)
        self.thumbs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self._thumb_menu)
        self.canvas = SlideCanvas(self)
        self.canvas.selected.connect(self._selected)
        self.canvas.edited.connect(self._edited)
        self.canvas.text_requested.connect(lambda _s: (self.props.setCurrentIndex(1), self.text_edit.setFocus()))

        # Propiedades (contextuales)
        self.props = QStackedWidget()
        slide_page = QWidget()
        slide_page.setLayout(v_layout(label(tr("Haz clic en un elemento para editarlo; doble clic en un texto para "
                                            "escribir."), "caption", wrap=True), None))
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(tr("Texto del elemento"))
        apply_text = QPushButton(tr("Aplicar texto"))
        apply_text.setProperty("kind", "primary")
        apply_text.clicked.connect(self.apply_text)
        self.size = QSpinBox()
        self.size.setRange(6, 200)
        self.size.setSuffix(tr(" pt"))
        self.size.setValue(24)
        size_ok = QPushButton(tr("Tamaño"))
        size_ok.clicked.connect(lambda: self._style(size=self.size.value()))
        bold = QPushButton(tr("Negrita"))
        bold.clicked.connect(lambda: self._style(bold=True))
        normal = QPushButton(tr("Normal"))
        normal.clicked.connect(lambda: self._style(bold=False))
        tcolor = QPushButton(tr("Color del texto"))
        tcolor.clicked.connect(self._text_color)
        fill = QPushButton(tr("Relleno"))
        fill.clicked.connect(self._fill_color)
        remove = QPushButton(tr("Eliminar elemento"))
        remove.clicked.connect(self.delete_selected)
        form = QFormLayout()
        form.addRow(h_layout(self.size, size_ok, spacing=4))
        shape_page = QWidget()
        shape_page.setLayout(v_layout(self.text_edit, apply_text, form, h_layout(bold, normal, spacing=4), tcolor,
                                      fill, None, remove, spacing=6))
        self.props.addWidget(slide_page)
        self.props.addWidget(shape_page)
        side = GlassPanel(radius=12, nested=True)
        side.setFixedWidth(270)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 12, 14, 12)
        self.prop_title = label("Diapositiva", "h3")
        sl.addWidget(self.prop_title)
        sl.addWidget(self.props, 1)

        body = h_layout(self.thumbs, self.canvas, side, spacing=10, margins=(10, 0, 10, 10))
        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(bar)
        root.addLayout(body, 1)
        for seq, fn in (("Ctrl+S", self.save), ("Ctrl+Z", self.undo), ("F5", self.present),
                        ("Delete", self.delete_selected)):
            QShortcut(QKeySequence(seq), self, activated=fn)
        self.refresh_all()

    # ------------------------------------------------------------------ archivo
    def _open(self, path: str):
        if not path:
            return Presentation()
        ext = Path(path).suffix.lower()
        if ext in (".odp", ".ppt"):
            from aero.core import tools

            soffice = tools.find_tool("soffice")
            if not soffice:
                raise RuntimeError("Para editar ODP o PPT hace falta LibreOffice (se convierte a PPTX).")
            import tempfile

            out = tempfile.mkdtemp(prefix="aero_pptx_")
            tools.run_quiet([soffice, "--headless", "--convert-to", "pptx", "--outdir", out, path], timeout=180)
            conv = next(Path(out).glob("*.pptx"), None)
            if conv is None:
                raise RuntimeError("LibreOffice no pudo convertir la presentación.")
            self.path = str(Path(path).with_suffix(".pptx"))
            return Presentation(str(conv))
        return Presentation(path)

    @property
    def slide(self):
        return self.prs.slides[self.index]

    # ------------------------------------------------------------------ historial
    def checkpoint(self):
        import io

        buf = io.BytesIO()
        self.prs.save(buf)
        self._history.append(buf.getvalue())
        del self._history[:-30]
        self.dirty = True

    def undo(self):
        import io

        if not self._history:
            return
        self.prs = Presentation(io.BytesIO(self._history.pop()))
        self.index = min(self.index, len(self.prs.slides) - 1)
        self.canvas.shape = None
        self.refresh_all()

    # ------------------------------------------------------------------ dibujo
    def render(self, i: int):
        from aero.ui.viewers.doc_viewers import render_pptx

        imgs = render_pptx(self.prs, RENDER_W, only=i)
        return imgs[0] if imgs else None

    def refresh_all(self):
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        for i in range(len(self.prs.slides)):
            img = self.render(i)
            it = QListWidgetItem(QIcon(QPixmap.fromImage(img.scaledToWidth(THUMB_W * 2,
                                                                          Qt.TransformationMode.SmoothTransformation))),
                                 str(i + 1))
            self.thumbs.addItem(it)
        self.thumbs.blockSignals(False)
        if len(self.prs.slides) == 0:
            add_slide(self.prs)
            self.refresh_all()
            return
        self.index = max(0, min(self.index, len(self.prs.slides) - 1))
        self.thumbs.setCurrentRow(self.index)
        self.go(self.index)
        self._sync_title()

    def refresh_current(self):
        img = self.render(self.index)
        self.canvas.img = img
        it = self.thumbs.item(self.index)
        if it is not None and img is not None:
            it.setIcon(QIcon(QPixmap.fromImage(img.scaledToWidth(THUMB_W * 2, Qt.TransformationMode.SmoothTransformation))))
        self.canvas.update()
        self._sync_title()

    def go(self, i: int):
        if i < 0 or i >= len(self.prs.slides):
            return
        self.index = i
        self.canvas.shape = None
        self.canvas.img = self.render(i)
        self._selected(None)
        self.canvas.update()

    def _sync_title(self):
        name = Path(self.path).name if self.path else tr("Presentación nueva")
        self.title.setText(name + (" •" if self.dirty else ""))
        self.info.setText(f"{len(self.prs.slides)} diapositivas")
        self.setWindowTitle(tr("{name} · Presentación · AERO Player", name=name))

    # ------------------------------------------------------------------ diapositivas
    def new_slide(self):
        self.checkpoint()
        add_slide(self.prs, self.index + 1)
        self.index += 1
        self.refresh_all()

    def dup_slide(self):
        self.checkpoint()
        duplicate_slide(self.prs, self.index)
        self.index += 1
        self.refresh_all()

    def del_slide(self):
        if len(self.prs.slides) <= 1:
            return
        self.checkpoint()
        delete_slide(self.prs, self.index)
        self.index = max(0, self.index - 1)
        self.refresh_all()

    def _rows_moved(self, _parent, start, _end, _dest, row):
        new = row if row < start else row - 1
        self.checkpoint()
        move_slide(self.prs, start, new)
        self.index = new
        self.refresh_all()

    def _thumb_menu(self, pos):
        m = QMenu(self)
        m.addAction(tr("Nueva diapositiva"), self.new_slide)
        m.addAction(tr("Duplicar"), self.dup_slide)
        m.addAction(tr("Subir"), lambda: self._move(-1))
        m.addAction(tr("Bajar"), lambda: self._move(1))
        m.addSeparator()
        m.addAction(tr("Eliminar"), self.del_slide)
        m.exec(self.thumbs.mapToGlobal(pos))

    def _move(self, step: int):
        j = self.index + step
        if 0 <= j < len(self.prs.slides):
            self.checkpoint()
            move_slide(self.prs, self.index, j)
            self.index = j
            self.refresh_all()

    def pick_background(self):
        c = QColorDialog.getColor(QColor("#ffffff"), self, "Fondo de la diapositiva")
        if c.isValid():
            self.checkpoint()
            f = self.slide.background.fill
            f.solid()
            f.fore_color.rgb = RGBColor(c.red(), c.green(), c.blue())
            self.refresh_current()

    # ------------------------------------------------------------------ elementos
    def _center_box(self, w_frac=0.6, h_frac=0.2):
        sw, sh = self.prs.slide_width, self.prs.slide_height
        return Emu(int(sw * (1 - w_frac) / 2)), Emu(int(sh * (1 - h_frac) / 2)), Emu(int(sw * w_frac)), \
            Emu(int(sh * h_frac))

    def add_text(self, text: str = "Escribe aquí"):
        self.checkpoint()
        tb = self.slide.shapes.add_textbox(*self._center_box())
        tb.text_frame.text = text
        tb.text_frame.word_wrap = True
        style_text(tb, size=28)
        self.canvas.shape = tb
        self._selected(tb)
        self.refresh_current()

    def add_image(self, path: str = ""):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("Añadir imagen"), "", "Imágenes (*.png *.jpg *.jpeg *.gif *.bmp)")
        if not path:
            return
        self.checkpoint()
        x, y, w, _h = self._center_box(0.4, 0.4)
        pic = self.slide.shapes.add_picture(path, x, y, width=w)
        self.canvas.shape = pic
        self._selected(pic)
        self.refresh_current()

    def add_shape_menu(self):
        m = QMenu(self)
        for text, kind in (("Rectángulo", MSO_SHAPE.RECTANGLE), ("Rectángulo redondeado", MSO_SHAPE.ROUNDED_RECTANGLE),
                           ("Elipse", MSO_SHAPE.OVAL)):
            m.addAction(text, lambda k=kind: self.add_shape(k))
        m.exec(self.cursor().pos())

    def add_shape(self, kind=MSO_SHAPE.RECTANGLE, color: QColor | None = None):
        self.checkpoint()
        sh = self.slide.shapes.add_shape(kind, *self._center_box(0.3, 0.3))
        c = color or QColor("#2bb3c0")
        sh.fill.solid()
        sh.fill.fore_color.rgb = RGBColor(c.red(), c.green(), c.blue())
        sh.line.fill.background()
        self.canvas.shape = sh
        self._selected(sh)
        self.refresh_current()
        return sh

    def _selected(self, sh):
        is_text = sh is not None and getattr(sh, "has_text_frame", False) and sh.has_text_frame
        self.props.setCurrentIndex(1 if sh is not None else 0)
        self.prop_title.setText(tr("Elemento") if sh is not None else f"Diapositiva {self.index + 1}")
        self.text_edit.setEnabled(bool(is_text))
        self.text_edit.setPlainText(sh.text_frame.text if is_text else "")

    def _edited(self):
        self.refresh_current()

    def apply_text(self):
        sh = self.canvas.shape
        if sh is not None and getattr(sh, "has_text_frame", False) and sh.has_text_frame:
            self.checkpoint()
            set_text(sh, self.text_edit.toPlainText())
            self.refresh_current()

    def _style(self, **kw):
        sh = self.canvas.shape
        if sh is not None and getattr(sh, "has_text_frame", False) and sh.has_text_frame:
            self.checkpoint()
            style_text(sh, **kw)
            self.refresh_current()

    def _text_color(self):
        c = QColorDialog.getColor(QColor("#1b2533"), self, "Color del texto")
        if c.isValid():
            self._style(color=c)

    def _fill_color(self):
        sh = self.canvas.shape
        if sh is None or not hasattr(sh, "fill"):
            return
        c = QColorDialog.getColor(QColor("#2bb3c0"), self, "Relleno")
        if c.isValid():
            self.checkpoint()
            sh.fill.solid()
            sh.fill.fore_color.rgb = RGBColor(c.red(), c.green(), c.blue())
            self.refresh_current()

    def delete_selected(self):
        sh = self.canvas.shape
        if sh is None or not self.canvas.hasFocus() and not self.isActiveWindow():
            return
        self.checkpoint()
        delete_shape(sh)
        self.canvas.shape = None
        self._selected(None)
        self.refresh_current()

    # ------------------------------------------------------------------ presentar y exportar
    def all_images(self):
        from aero.ui.viewers.doc_viewers import render_pptx

        return render_pptx(self.prs, 1920)

    def present(self):
        from aero.ui.viewers.doc_viewers import PresentationWindow

        w = PresentationWindow(self.all_images(), self.index)
        w.showFullScreen()
        w.activateWindow()
        self._presenting = w

    def export_pdf(self, path: str = ""):
        from PySide6.QtCore import QMarginsF, QSizeF
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter

        if not path:
            base = Path(self.path) if self.path else Path.home() / "Presentación.pptx"
            path, _ = QFileDialog.getSaveFileName(self, tr("Exportar a PDF"), str(base.with_suffix(".pdf")), "PDF (*.pdf)")
        if not path:
            return
        imgs = self.all_images()
        w = QPdfWriter(path)
        size = QSizeF(self.prs.slide_width / 12700, self.prs.slide_height / 12700)
        w.setPageLayout(QPageLayout(QPageSize(size, QPageSize.Unit.Point), QPageLayout.Orientation.Portrait,
                                    QMarginsF(0, 0, 0, 0)))
        w.setResolution(144)
        p = QPainter(w)
        for i, img in enumerate(imgs):
            if i:
                w.newPage()
            p.drawImage(QRectF(0, 0, w.width(), w.height()), img)
        p.end()
        self.info.setText(tr("PDF exportado · {v0} páginas (aproximado)", v0=len(imgs)))

    # ------------------------------------------------------------------ guardar
    def save(self):
        if not self.path or Path(self.path).suffix.lower() != ".pptx":
            self.save_as()
            return
        if not self._save_ok:
            r = QMessageBox.question(self, tr("Guardar"), tr("¿Guardar los cambios en «{v0}»?", v0=Path(self.path).name))
            if r != QMessageBox.StandardButton.Yes:
                return
            self._save_ok = True
        self.save_to(self.path)

    def save_as(self):
        base = Path(self.path) if self.path else Path.home() / "Presentación.pptx"
        f, _ = QFileDialog.getSaveFileName(self, tr("Guardar como"), str(base.with_suffix(".pptx")),
                                           "PowerPoint (*.pptx)")
        if f:
            if not f.lower().endswith(".pptx"):
                f += ".pptx"
            self.save_to(f)
            self.path = os.path.abspath(f)
            self._save_ok = True
            self._sync_title()

    def save_to(self, path: str):
        tmp = path + ".part.pptx"
        try:
            self.prs.save(tmp)
            os.replace(tmp, path)
        except Exception as e:  # noqa: BLE001
            if os.path.exists(tmp):
                os.remove(tmp)
            QMessageBox.warning(self, tr("Guardar"), tr("No se pudo guardar: {e}", e=e))
            return
        self.dirty = False
        self._sync_title()

    def closeEvent(self, e):
        if self.dirty:
            r = QMessageBox.question(self, tr("Cerrar"), tr("Hay cambios sin guardar. ¿Cerrar de todos modos?"),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
        super().closeEvent(e)
        if self.controller is not None:
            self.controller.editor_closed(self)


def open_editor(path: str = "", controller=None) -> SlidesEditor:
    w = SlidesEditor(path, controller)
    w.resize(1320, 820)
    w.show()
    w.raise_()
    w.activateWindow()
    return w
