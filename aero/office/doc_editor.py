"""Editor de documentos (DOCX, ODT, RTF, TXT, Markdown, HTML).

Prioriza la lectura y la escritura: una hoja centrada sobre el cristal, una sola barra de formato y la
búsqueda solo cuando se pide (Ctrl+F / Ctrl+H). Guardar sobre un DOCX con elementos que el editor no
conserva (notas al pie, comentarios, cambios…) avisa antes y propone una copia.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QKeySequence, QShortcut, QTextCharFormat,
                           QTextCursor, QTextDocument, QTextImageFormat, QTextListFormat,
                           QTextTableFormat)
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFileDialog, QFontComboBox, QHBoxLayout,
                               QInputDialog, QLineEdit, QMessageBox, QSpinBox, QTextEdit, QVBoxLayout, QWidget)

from aero.office import docio
from aero.ui.glass import IconButton, h_layout, label, v_layout
from aero.ui.glasswindow import DragArea, GlassWindow
from aero.i18n import ntr, tr

PAPER_W = 816  # ancho de la hoja en píxeles a 96 ppp (Carta/A4 aproximado)
STYLES = [("Normal", 0), ("Título 1", 1), ("Título 2", 2), ("Título 3", 3)]


class Paper(QTextEdit):
    """La hoja: blanca, con márgenes de documento y ancho de página fijo."""

    def __init__(self):
        super().__init__()
        self.setAcceptRichText(True)
        self.document().setDocumentMargin(72)
        self.setFixedWidth(PAPER_W)
        self.setStyleSheet("QTextEdit { background: #ffffff; color: #1b1f24; border: 1px solid rgba(0,0,0,40);"
                           " border-radius: 4px; selection-background-color: #9cc8ff; selection-color: #000; }")
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

    def insertFromMimeData(self, source):
        if source.hasImage():
            img = QImage(source.imageData())
            if not img.isNull():
                self.window().insert_image_object(img)
                return
        super().insertFromMimeData(source)


class DocumentEditor(GlassWindow):
    def __init__(self, path: str = "", controller=None):
        super().__init__(Qt.WindowType(0), flat=True)
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumSize(900, 600)
        self.backdrop.flat_opacity = 0.94
        self.path = os.path.abspath(path) if path else ""
        self.loaded: docio.LoadedDoc | None = None
        self.header, self.footer, self.page_numbers = "", "", True
        self._save_ok = False   # se confirmó guardar sobre el original
        self._n_img = 0

        self.text = Paper()
        self.text.currentCharFormatChanged.connect(self._sync_format)
        self.text.cursorPositionChanged.connect(self._sync_block)
        self.text.textChanged.connect(self._sync_title)

        # ---------------------------------------------------------- barra superior y formato
        bar = DragArea()
        self.title = label("Documento", "h3")
        self.info = label("", "caption")
        save = IconButton("save", tr("Guardar (Ctrl+S)"), 18)
        save.clicked.connect(self.save)
        save_as = IconButton("external", tr("Guardar como… (Ctrl+Mayús+S)"), 18)
        save_as.clicked.connect(self.save_as)
        pdf = IconButton("pdf", tr("Exportar a PDF"), 18)
        pdf.clicked.connect(self.export_pdf)
        undo = IconButton("undo", tr("Deshacer (Ctrl+Z)"), 18)
        undo.clicked.connect(self.text.undo)
        redo = IconButton("redo", tr("Rehacer (Ctrl+Y)"), 18)
        redo.clicked.connect(self.text.redo)
        find = IconButton("search", tr("Buscar y sustituir (Ctrl+H)"), 18)
        find.clicked.connect(lambda: self.toggle_find(True))
        bar.setLayout(h_layout(14, v_layout(self.title, self.info, spacing=0), None, undo, redo, 8, find, 8, pdf,
                               save_as, save, 10, self.window_buttons(), spacing=4, margins=(0, 8, 10, 6)))

        self.style_box = QComboBox()
        for name, lvl in STYLES:
            self.style_box.addItem(name, lvl)
        self.style_box.activated.connect(lambda _i: self.set_heading(self.style_box.currentData()))
        self.font_box = QFontComboBox()
        self.font_box.setMaximumWidth(180)
        self.font_box.currentFontChanged.connect(lambda f: self._merge(families=[f.family()]))
        self.size_box = QSpinBox()
        self.size_box.setRange(6, 96)
        self.size_box.setValue(11)
        self.size_box.setSuffix(tr(" pt"))
        self.size_box.valueChanged.connect(lambda v: self._merge(size=v))
        self.bold = self._toggle("B", "Negrita (Ctrl+B)", lambda on: self._merge(bold=on), bold=True)
        self.italic = self._toggle("I", "Cursiva (Ctrl+I)", lambda on: self._merge(italic=on), italic=True)
        self.underline = self._toggle("S", "Subrayado (Ctrl+U)", lambda on: self._merge(underline=on), under=True)
        color = IconButton("brush", tr("Color del texto"), 18)
        color.clicked.connect(self.pick_color)
        mark = IconButton("highlight", "Resaltar", 18)
        mark.clicked.connect(self.toggle_highlight)
        self.align_btns = {}
        al_row = []
        for key, tip, flag in (("left", "Izquierda", Qt.AlignmentFlag.AlignLeft),
                               ("center", "Centrado", Qt.AlignmentFlag.AlignHCenter),
                               ("right", "Derecha", Qt.AlignmentFlag.AlignRight),
                               ("justify", "Justificado", Qt.AlignmentFlag.AlignJustify)):
            b = IconButton(f"align_{key}", tip, 18)
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, f=flag: self.set_align(f))
            self.align_btns[key] = (b, flag)
            al_row.append(b)
        bullets = IconButton("list", tr("Lista con viñetas"), 18)
        bullets.clicked.connect(lambda: self.set_list(QTextListFormat.Style.ListDisc))
        numbers = IconButton("list_num", tr("Lista numerada"), 18)
        numbers.clicked.connect(lambda: self.set_list(QTextListFormat.Style.ListDecimal))
        table = IconButton("sheet", tr("Insertar tabla"), 18)
        table.clicked.connect(self.insert_table)
        image = IconButton("image", tr("Insertar imagen"), 18)
        image.clicked.connect(self.insert_image)
        hf = IconButton("text_tool", tr("Encabezado, pie y números de página"), 18)
        hf.clicked.connect(self.edit_header_footer)
        fmt = QWidget()
        fmt.setLayout(h_layout(self.style_box, self.font_box, self.size_box, 8, self.bold, self.italic,
                               self.underline, color, mark, 8, *al_row, 8, bullets, numbers, 8, table, image, hf,
                               None, spacing=3, margins=(12, 0, 12, 6)))

        # Buscar y sustituir (oculto hasta pedirlo)
        self.find_text = QLineEdit()
        self.find_text.setPlaceholderText(tr("Buscar"))
        self.find_text.returnPressed.connect(self.find_next)
        self.repl_text = QLineEdit()
        self.repl_text.setPlaceholderText(tr("Sustituir por"))
        self.case = QCheckBox(tr("Mayúsculas"))
        nxt = IconButton("down", tr("Siguiente (Intro)"), 18)
        nxt.clicked.connect(self.find_next)
        one = IconButton("check", "Sustituir", 18)
        one.clicked.connect(self.replace_one)
        allb = IconButton("refresh", tr("Sustituir todo"), 18)
        allb.clicked.connect(lambda: self.info.setText(f"{self.replace_all(self.find_text.text(), self.repl_text.text())}"
                                                      " sustituciones"))
        close = IconButton("close", tr("Cerrar búsqueda (Esc)"), 16)
        close.clicked.connect(lambda: self.toggle_find(False))
        self.find_bar = QWidget()
        self.find_bar.setLayout(h_layout(self.find_text, nxt, self.repl_text, one, allb, self.case, None, close,
                                         spacing=4, margins=(12, 0, 12, 6)))
        self.find_bar.hide()

        page_row = QHBoxLayout()
        page_row.addStretch(1)
        page_row.addWidget(self.text)
        page_row.addStretch(1)
        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(bar)
        root.addWidget(fmt)
        root.addWidget(self.find_bar)
        root.addLayout(page_row, 1)
        root.addSpacing(10)

        for seq, fn in (("Ctrl+S", self.save), ("Ctrl+Shift+S", self.save_as), ("Ctrl+F", lambda: self.toggle_find(True)),
                        ("Ctrl+H", lambda: self.toggle_find(True)), ("Ctrl+B", lambda: self.bold.click()),
                        ("Ctrl+I", lambda: self.italic.click()), ("Ctrl+U", lambda: self.underline.click()),
                        ("Esc", lambda: self.toggle_find(False))):
            QShortcut(QKeySequence(seq), self, activated=fn)
        if self.path:
            self._load()
        else:
            self.loaded = docio.LoadedDoc(QTextDocument())
            self._attach(self.loaded.doc)

    def _toggle(self, text, tip, fn, bold=False, italic=False, under=False):
        from PySide6.QtWidgets import QToolButton

        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(True)
        b.setFixedSize(32, 32)
        f = QFont(b.font())
        f.setBold(bold)
        f.setItalic(italic)
        f.setUnderline(under)
        b.setFont(f)
        b.toggled.connect(lambda on: not self._syncing and fn(on))
        return b

    _syncing = False

    # ------------------------------------------------------------------ carga
    def _load(self):
        self.info.setText(tr("Abriendo…"))
        path = self.path
        # QTextDocument se construye en el hilo de la interfaz (no es seguro moverlo entre hilos)
        try:
            ld = docio.load(path)
        except Exception as e:  # noqa: BLE001
            self.info.setText(tr("No se pudo abrir: {e}", e=e))
            QMessageBox.warning(self, tr("Abrir"), tr("No se pudo abrir el documento: {e}", e=e))
            return
        self.loaded = ld
        self.header, self.footer, self.page_numbers = ld.header, ld.footer, ld.page_numbers  # abrir y guardar no añade números
        self._attach(ld.doc)

    def _attach(self, doc: QTextDocument):
        doc.setDocumentMargin(72)
        self.text.setDocument(doc)
        doc.setModified(False)
        self._sync_title()
        self._warned = bool(self.loaded and self.loaded.unsupported)
        if self._warned:
            self.info.setText(tr("Aviso: {x} no se conservarán al guardar", x=", ".join(self.loaded.unsupported)))

    # ------------------------------------------------------------------ formato
    def _merge(self, families=None, size=None, bold=None, italic=None, underline=None, color=None, bg=None):
        if self._syncing:
            return
        f = QTextCharFormat()
        if families is not None:
            f.setFontFamilies(families)
        if size is not None:
            f.setFontPointSize(size)
        if bold is not None:
            f.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        if italic is not None:
            f.setFontItalic(italic)
        if underline is not None:
            f.setFontUnderline(underline)
        if color is not None:
            f.setForeground(color)
        if bg is not None:
            f.setBackground(bg)
        cur = self.text.textCursor()
        if not cur.hasSelection() and families is None and size is None and color is None and bg is None:
            self.text.mergeCurrentCharFormat(f)  # escribe con este formato a partir de aquí
        else:
            cur.mergeCharFormat(f)
            self.text.mergeCurrentCharFormat(f)
        self.text.setFocus()

    def pick_color(self):
        c = QColorDialog.getColor(self.text.currentCharFormat().foreground().color(), self, "Color del texto")
        if c.isValid():
            self._merge(color=c)

    def toggle_highlight(self):
        cur = self.text.textCursor()
        has = cur.charFormat().background().style() != Qt.BrushStyle.NoBrush
        self._merge(bg=QBrush(Qt.BrushStyle.NoBrush) if has else QBrush(QColor(255, 236, 64)))

    def set_align(self, flag):
        self.text.setAlignment(flag)
        self._sync_block()

    def set_heading(self, level: int):
        cur = self.text.textCursor()
        cur.beginEditBlock()
        bf = cur.blockFormat()
        bf.setHeadingLevel(level)
        cur.setBlockFormat(bf)
        cur.select(QTextCursor.SelectionType.BlockUnderCursor)
        f = QTextCharFormat()
        f.setFontWeight(QFont.Weight.Bold if level else QFont.Weight.Normal)
        f.setFontPointSize(docio.HEADING_SIZES.get(level, 11.0))
        cur.mergeCharFormat(f)
        cur.endEditBlock()

    def set_list(self, style):
        cur = self.text.textCursor()
        lst = cur.currentList()
        if lst is not None and lst.format().style() == style:
            # Quitar de la lista
            lst.remove(cur.block())
            bf = cur.blockFormat()
            bf.setIndent(0)
            cur.setBlockFormat(bf)
            return
        lf = QTextListFormat()
        lf.setStyle(style)
        cur.createList(lf)

    def insert_table(self):
        rows, ok = QInputDialog.getInt(self, tr("Insertar tabla"), tr("Filas:"), 3, 1, 200)
        if not ok:
            return
        cols, ok = QInputDialog.getInt(self, tr("Insertar tabla"), tr("Columnas:"), 3, 1, 30)
        if not ok:
            return
        tf = QTextTableFormat()
        tf.setBorder(1)
        tf.setCellPadding(4)
        tf.setCellSpacing(0)
        from PySide6.QtGui import QTextFrameFormat

        tf.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
        self.text.textCursor().insertTable(rows, cols, tf)

    def insert_image(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Insertar imagen"), str(Path(self.path).parent) if self.path else "",
                                           "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if f:
            img = QImage(f)
            if not img.isNull():
                self.insert_image_object(img)

    def insert_image_object(self, img: QImage):
        self._n_img += 1
        name = f"aero-img-{self._n_img}"
        self.text.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), img)
        fmt = QTextImageFormat()
        fmt.setName(name)
        max_w = PAPER_W - 2 * 72 - 8
        w = min(img.width(), max_w)
        fmt.setWidth(w)
        fmt.setHeight(img.height() * w / max(1, img.width()))
        self.text.textCursor().insertImage(fmt)

    def edit_header_footer(self):
        from PySide6.QtWidgets import QDialog, QFormLayout, QPushButton

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Encabezado y pie de página"))
        h, f = QLineEdit(self.header), QLineEdit(self.footer)
        pn = QCheckBox(tr("Números de página"))
        pn.setChecked(self.page_numbers)
        form = QFormLayout(dlg)
        form.addRow(tr("Encabezado"), h)
        form.addRow(tr("Pie"), f)
        form.addRow(pn)
        ok = QPushButton(tr("Aceptar"))
        ok.setProperty("kind", "primary")
        ok.clicked.connect(dlg.accept)
        form.addRow(ok)
        if dlg.exec():
            self.header, self.footer, self.page_numbers = h.text(), f.text(), pn.isChecked()
            self.text.document().setModified(True)
            self._sync_title()

    # ------------------------------------------------------------------ sincronización
    def _sync_format(self, f: QTextCharFormat):
        self._syncing = True
        self.bold.setChecked(f.fontWeight() >= QFont.Weight.DemiBold.value)
        self.italic.setChecked(f.fontItalic())
        self.underline.setChecked(f.fontUnderline())
        if f.fontPointSize() > 0:
            self.size_box.setValue(int(round(f.fontPointSize())))
        fams = f.fontFamilies()
        if fams:
            self.font_box.setCurrentFont(QFont(fams[0] if isinstance(fams, list) else str(fams)))
        self._syncing = False

    def _sync_block(self):
        bf = self.text.textCursor().blockFormat()
        a = self.text.alignment()
        for _k, (b, flag) in self.align_btns.items():
            b.setChecked(bool(a & flag) if flag != Qt.AlignmentFlag.AlignLeft else
                         not (a & (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignRight |
                                   Qt.AlignmentFlag.AlignJustify)))
        i = self.style_box.findData(bf.headingLevel())
        self.style_box.setCurrentIndex(max(0, i))

    def _sync_title(self):
        name = Path(self.path).name if self.path else tr("Documento nuevo")
        mod = self.text.document().isModified()
        self.title.setText(name + (" •" if mod else ""))
        self.setWindowTitle(tr("{name} · Documento · AERO Player", name=name))
        words = len(self.text.toPlainText().split())
        if not getattr(self, "_warned", False):
            self.info.setText(ntr("{n} palabra", "{n} palabras", words))

    # ------------------------------------------------------------------ buscar y sustituir
    def toggle_find(self, on: bool):
        self.find_bar.setVisible(on)
        if on:
            sel = self.text.textCursor().selectedText()
            if sel:
                self.find_text.setText(sel)
            self.find_text.setFocus()
            self.find_text.selectAll()
        else:
            self.text.setFocus()

    def _flags(self):
        return QTextDocument.FindFlag.FindCaseSensitively if self.case.isChecked() else QTextDocument.FindFlag(0)

    def find_next(self) -> bool:
        t = self.find_text.text()
        if not t:
            return False
        if self.text.find(t, self._flags()):
            return True
        cur = self.text.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.Start)
        self.text.setTextCursor(cur)
        return self.text.find(t, self._flags())

    def replace_one(self):
        cur = self.text.textCursor()
        if cur.hasSelection() and cur.selectedText() == self.find_text.text():
            cur.insertText(self.repl_text.text())
        self.find_next()

    def replace_all(self, find: str, repl: str) -> int:
        if not find:
            return 0
        doc = self.text.document()
        n = 0
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        while True:
            cur = doc.find(find, cur, self._flags())
            if cur.isNull():
                break
            cur.insertText(repl)
            n += 1
        cur.endEditBlock()
        return n

    # ------------------------------------------------------------------ guardar
    def save(self):
        if not self.path or Path(self.path).suffix.lower() not in (".docx", ".odt", ".md", ".markdown", ".html",
                                                                   ".htm", ".txt"):
            self.save_as()
            return
        if not self._save_ok:
            lost = list(self.loaded.unsupported) if self.loaded else []
            msg = f"¿Guardar los cambios en «{Path(self.path).name}»?"
            if lost and any(x for x in lost if not x.startswith(("El formato", "RTF"))):
                msg += ("\n\nEste documento contiene elementos que el editor no conserva: " + ", ".join(lost) +
                        ". Si guardas sobre el original se perderán; se recomienda guardar una copia.")
            box = QMessageBox(QMessageBox.Icon.Question, "Guardar", msg, parent=self)
            over = box.addButton(tr("Guardar"), QMessageBox.ButtonRole.AcceptRole)
            copy = box.addButton(tr("Guardar una copia…"), QMessageBox.ButtonRole.ActionRole)
            box.addButton(tr("Cancelar"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(copy if lost else over)
            box.exec()
            if box.clickedButton() is copy:
                self.save_as()
                return
            if box.clickedButton() is not over:
                return
            self._save_ok = True
        self.save_to(self.path)

    def save_as(self):
        base = Path(self.path) if self.path else Path.home() / "Documento.docx"
        filters = ";;".join(f"{t} (*.{e})" for e, t in docio.WRITE_FORMATS.items())
        f, chosen = QFileDialog.getSaveFileName(self, tr("Guardar como"), str(base.with_suffix(".docx")), filters)
        if f:
            if not Path(f).suffix:
                f += ".docx"
            self.save_to(f)
            self.path = os.path.abspath(f)
            self._save_ok = True
            self._sync_title()

    def save_to(self, path: str):
        tmp = path + ".part" + Path(path).suffix
        try:
            docio.save(self.text.document(), tmp, self.header, self.footer, self.page_numbers)
            os.replace(tmp, path)
        except Exception as e:  # noqa: BLE001
            if os.path.exists(tmp):
                os.remove(tmp)
            QMessageBox.warning(self, tr("Guardar"), tr("No se pudo guardar: {e}", e=e))
            return
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(self.path or ""):
            self.text.document().setModified(False)
        self.info.setText(f"Guardado: {Path(path).name}")
        self._sync_title()

    def export_pdf(self):
        base = Path(self.path) if self.path else Path.home() / "Documento.pdf"
        f, _ = QFileDialog.getSaveFileName(self, tr("Exportar a PDF"), str(base.with_suffix(".pdf")), "PDF (*.pdf)")
        if f:
            n = docio.export_pdf(self.text.document(), f, self.header, self.footer, self.page_numbers)
            self.info.setText(tr("PDF exportado · {n} páginas", n=n))

    def closeEvent(self, e):
        if self.text.document().isModified():
            r = QMessageBox.question(self, tr("Cerrar"), tr("Hay cambios sin guardar. ¿Cerrar de todos modos?"),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
        super().closeEvent(e)
        if self.controller is not None:
            self.controller.editor_closed(self)


def open_editor(path: str = "", controller=None) -> DocumentEditor:
    w = DocumentEditor(path, controller)
    w.resize(1100, 860)
    w.show()
    w.raise_()
    w.activateWindow()
    return w

