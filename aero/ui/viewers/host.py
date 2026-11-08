"""Contenedor universal de visores: elige el visor según el tipo, carga en segundo plano y gestiona errores."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from aero.core import tools
from aero.core.formats import KIND_LABELS, NEEDS_OFFICE, human_size, kind_of
from aero.core.paths import cache_dir
from aero.ui import icons
from aero.ui.async_util import run_async
from aero.ui.glass import IconButton, Spinner, h_layout, label, tm, v_layout
from aero.ui.viewers.doc_viewers import (PresentationWindow, RichViewer, SheetViewer, SlidesViewer,
                                        TextViewer, load_sheets, prepare_rich_html, render_pptx)
from aero.ui.viewers.image_viewer import ImageViewer, load_qimage
from aero.ui.viewers.pdf_viewer import PdfViewer

from aero.ui.icons import KIND_ICONS  # noqa: E402,F401 - reexportado
from aero.i18n import tr


def office_to_pdf(path: str) -> Path:
    """Convierte con LibreOffice a PDF (en caché) para vistas previas de alta fidelidad."""
    soffice = tools.find_tool("soffice")
    if not soffice:
        raise RuntimeError("LibreOffice no está instalado.")
    p = Path(path)
    st = p.stat()
    key = hashlib.sha1(f"{p.resolve()}|{st.st_mtime}|{st.st_size}".encode()).hexdigest()[:20]
    out_dir = cache_dir() / "office_pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{key}.pdf"
    if target.exists():
        return target
    tmp = tempfile.mkdtemp(prefix="aero_prev_", dir=cache_dir())
    try:
        profile = (cache_dir() / "lo_profile_preview").as_uri()
        r = tools.run_quiet([soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
                             "--convert-to", "pdf", "--outdir", tmp, str(p)], timeout=180)
        produced = list(Path(tmp).glob("*.pdf"))
        if r.returncode != 0 or not produced:
            raise RuntimeError("LibreOffice no pudo generar la vista previa.")
        shutil.move(str(produced[0]), str(target))
        return target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class ViewerHost(QWidget):
    convert_requested = Signal(str)
    edit_requested = Signal(str)
    pdf_convert_requested = Signal(str)
    media_requested = Signal(str)
    close_requested = Signal()
    file_opened = Signal(str, str)

    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self.compact = compact
        self.path = ""
        self._token = 0

        self.kind_icon = QLabel()
        self.kind_icon.setFixedSize(26, 26)
        self.title = label("", "h2")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.subtitle = label("", "caption")
        self.tool_slot = QStackedWidget()
        self.tool_slot.setSizePolicy(self.tool_slot.sizePolicy().horizontalPolicy(), self.tool_slot.sizePolicy().verticalPolicy())
        self.btn_hifi = QPushButton(tr("Alta fidelidad"))
        self.btn_hifi.setProperty("kind", "flat")
        self.btn_hifi.setToolTip(tr("Renderizar con LibreOffice para respetar el formato original"))
        self.btn_hifi.clicked.connect(self._open_hifi)
        self.btn_edit = QPushButton(tr("Editar"))
        self.btn_edit.setIcon(tm().icon("edit", 18))
        self.btn_edit.setToolTip(tr("Abrir en el editor"))
        self.btn_edit.clicked.connect(lambda: self.path and self.edit_requested.emit(self.path))
        self.btn_edit.hide()
        self.btn_back = IconButton("back", tr("Volver a la carpeta"), 18)
        self.btn_back.clicked.connect(self._go_back)
        self.btn_back.hide()
        self.btn_ext = IconButton("external", tr("Abrir con la aplicación predeterminada"), 18)
        self.btn_reveal = IconButton("folder", tr("Mostrar en el Explorador"), 18)
        self.btn_convert = IconButton("convert", tr("Convertir este archivo…"), 18)
        self.btn_ext.clicked.connect(lambda: self.path and tools.open_with_default(self.path))
        self.btn_reveal.clicked.connect(lambda: self.path and tools.reveal_in_explorer(self.path))
        self.btn_convert.clicked.connect(lambda: self.path and self.convert_requested.emit(self.path))
        if compact:
            self.btn_convert.hide()

        titles = v_layout(self.title, self.subtitle, spacing=0)
        header = h_layout(self.btn_back, self.kind_icon, spacing=10)
        header.addLayout(titles, 1)
        header.addWidget(self.btn_edit)
        header.addWidget(self.btn_hifi)
        header.addWidget(self.btn_convert)
        header.addWidget(self.btn_reveal)
        header.addWidget(self.btn_ext)
        self.btn_close = IconButton("close", tr("Cerrar y volver"), 18)
        self.btn_close.clicked.connect(self.close_requested.emit)
        header.addWidget(self.btn_close)
        self.btn_hifi.hide()

        self.stack = QStackedWidget()
        # Páginas de estado
        self.empty = self._state_page("viewer", "Suelta un archivo aquí", "")
        self.loading = QWidget()
        sp = Spinner(42)
        self.loading.setLayout(v_layout(None, h_layout(None, sp, None), label("", "muted"), None))
        self.loading.layout().itemAt(2).widget().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_title = label("", "h3")
        self.error_text = label("", "muted", wrap=True)
        self.error_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ext_btn = QPushButton(tr("Abrir con…"))
        ext_btn.clicked.connect(lambda: self.path and tools.open_with_default(self.path))
        self.error = QWidget()
        self.error.setLayout(v_layout(None, self.error_title, self.error_text, 8, h_layout(None, ext_btn, None), None,
                                      margins=(40, 0, 40, 0)))

        self.image = ImageViewer()
        self.pdf = PdfViewer()
        self.text = TextViewer()
        self.rich = RichViewer()
        self.sheet = SheetViewer()
        self.slides = SlidesViewer()
        from aero.files.browser import FolderBrowser

        self.archive = FolderBrowser()
        self.archive.open_requested.connect(self._open_from_browser)
        self._back: tuple[str, str] | None = None   # carpeta o comprimido al que volver
        self.slides.present_requested.connect(self._present)
        for w in (self.empty, self.loading, self.error, self.image, self.pdf, self.text, self.rich, self.sheet,
                  self.slides, self.archive):
            self.stack.addWidget(w)

        # Herramientas de imagen
        self.zoom_label = label("100 %", "caption")
        self.zoom_label.setMinimumWidth(48)
        img_bar = QWidget()
        b_prev = IconButton("left", tr("Imagen anterior (←)"), 18)
        b_next = IconButton("right", tr("Imagen siguiente (→)"), 18)
        b_zo = IconButton("zoom_out", "Alejar", 18)
        b_zi = IconButton("zoom_in", "Acercar", 18)
        b_fit = IconButton("fit", tr("Ajustar a la ventana"), 18)
        b_one = QPushButton("1:1")
        b_one.setProperty("kind", "flat")
        b_one.setToolTip(tr("Tamaño real"))
        b_rl = IconButton("rotate_left", tr("Girar a la izquierda"), 18)
        b_rr = IconButton("rotate", tr("Girar a la derecha"), 18)
        b_fh = IconButton("flip_h", tr("Voltear en horizontal"), 18)
        b_fv = IconButton("flip_v", tr("Voltear en vertical"), 18)
        b_fh.clicked.connect(lambda: self.image.flip(True))
        b_fv.clicked.connect(lambda: self.image.flip(False))
        b_edit = QPushButton(tr("Editar"))
        b_edit.setIcon(tm().icon("edit", 18))
        b_edit.setToolTip(tr("Abrir en el editor de imágenes (E)"))
        b_edit.clicked.connect(lambda: self.path and self.edit_requested.emit(self.path))
        img_bar.setLayout(h_layout(b_prev, b_next, 10, b_zo, self.zoom_label, b_zi, b_fit, b_one, 10, b_rl, b_rr, b_fh, b_fv, 14,
                                   b_edit, spacing=2))
        b_prev.clicked.connect(lambda: self._sibling(-1))
        b_next.clicked.connect(lambda: self._sibling(1))
        b_zo.clicked.connect(lambda: self.image.zoom(1 / 1.25))
        b_zi.clicked.connect(lambda: self.image.zoom(1.25))
        b_fit.clicked.connect(self.image.fit)
        b_one.clicked.connect(self.image.actual_size)
        b_rl.clicked.connect(lambda: self.image.rotate_by(-90))
        b_rr.clicked.connect(lambda: self.image.rotate_by(90))
        self.image.zoom_changed.connect(lambda z: self.zoom_label.setText(f"{z * 100:.0f} %"))
        b_editable = QPushButton(tr("Convertir a editable"))
        b_editable.setIcon(tm().icon("convert", 18))
        b_editable.setToolTip(tr("Reconstruir el PDF como documento de Word u OpenDocument (con OCR si está escaneado)"))
        b_editable.clicked.connect(lambda: self.path and self.pdf_convert_requested.emit(self.path))
        self.pdf.toolbar.layout().addSpacing(14)
        self.pdf.toolbar.layout().addWidget(b_editable)
        self._toolbars = {}
        for key, bar in (("none", QWidget()), ("image", img_bar), ("pdf", self.pdf.toolbar), ("text", self.text.toolbar),
                         ("rich", self.rich.toolbar), ("sheet", self.sheet.toolbar), ("slides", self.slides.toolbar),
                         ):
            if bar.layout() is not None:
                bar.layout().addStretch(1)  # alinear a la izquierda aunque otra barra sea más ancha
            self._toolbars[key] = bar
            self.tool_slot.addWidget(bar)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16 if not compact else 12, 12, 16 if not compact else 12, 12)
        lay.setSpacing(10)
        lay.addLayout(header)
        lay.addLayout(h_layout(self.tool_slot, None))
        lay.addWidget(self.stack, 1)
        self.stack.setCurrentWidget(self.empty)
        self._set_toolbar("none")

        QShortcut(QKeySequence.StandardKey.Find, self, activated=self._focus_search,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        tm().changed.connect(self._refresh_icon)

    def _state_page(self, ic: str, title: str, text: str) -> QWidget:
        w = QWidget()
        icl = QLabel()
        icl.setPixmap(icons.pixmap(ic, tm().theme.text2, 56))
        icl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = label(title, "h3")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s = label(text, "muted", wrap=True)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        w.setLayout(v_layout(None, icl, t, s, None))
        return w

    def _refresh_icon(self):
        from aero.core.filetypes import by_extension
        from aero.ui import file_icons

        cat = by_extension(self.path, os.path.isdir(self.path)) if self.path else "unknown"
        self.kind_icon.setPixmap(file_icons.pixmap(cat, 26, self.devicePixelRatioF(), tm().theme.dark))

    def _set_toolbar(self, key: str):
        self.tool_slot.setCurrentWidget(self._toolbars[key])
        self.tool_slot.setVisible(key != "none")

    def _focus_search(self):
        w = self.stack.currentWidget()
        if hasattr(w, "focus_search"):
            w.focus_search()

    # ------------------------------------------------------------------ apertura
    def open(self, path: str, _keep_back: bool = False) -> None:
        path = os.path.abspath(path)
        if not _keep_back:
            self._back = None
        self.btn_back.setVisible(self._back is not None)
        kind = "folder" if os.path.isdir(path) else kind_of(path)
        if kind in ("audio", "video"):
            self.media_requested.emit(path)
            return
        self._token += 1
        token = self._token
        self.pdf.unload()
        self.image.clear()
        self.path = path
        p = Path(path)
        self.title.setText(p.name)
        try:
            size = "" if kind == "folder" else human_size(p.stat().st_size)
        except OSError:
            self._fail("No se puede acceder al archivo", "Comprueba que existe y que tienes permiso para leerlo.")
            return
        self.subtitle.setText(f"{tr(KIND_LABELS.get(kind, 'Archivo'))} · {size}")
        self.btn_edit.setVisible(kind in ("document", "sheet", "slides", "text"))
        self.subtitle.setToolTip(str(p.parent))
        self._refresh_icon()
        self.btn_hifi.setVisible(False)
        self.file_opened.emit(path, kind)
        self.stack.setCurrentWidget(self.loading)
        self._set_toolbar("none")
        ext = p.suffix.lower()
        office = tools.find_tool("soffice") is not None

        def done(fn):
            def wrapper(res):
                if token != self._token:
                    return
                try:
                    fn(res)
                except Exception as e:  # noqa: BLE001
                    self._fail("No se pudo mostrar el archivo", str(e))
            return wrapper

        def failed(err):
            if token == self._token:
                self._fail("No se pudo abrir el archivo", _friendly(err))

        if kind == "image":
            run_async(lambda: load_qimage(path), done(self._show_image), failed, self)
        elif kind == "pdf":
            try:
                self.pdf.load(path)
                self.stack.setCurrentWidget(self.pdf)
                self._set_toolbar("pdf")
            except Exception as e:  # noqa: BLE001
                self._fail("No se pudo abrir el PDF", str(e))
        elif ext in NEEDS_OFFICE or (kind == "slides" and ext in (".odp",) and office):
            if not office:
                self._fail("Este formato necesita LibreOffice",
                           "Los archivos .doc y .ppt antiguos se muestran mediante LibreOffice (gratuito). "
                           "Instálalo desde libreoffice.org y AERO Player lo detectará automáticamente.")
                return
            run_async(lambda: office_to_pdf(path), done(self._show_pdf_preview), failed, self)
        elif kind == "slides":
            if office:
                run_async(lambda: office_to_pdf(path), done(self._show_pdf_preview), failed, self)
            elif ext == ".odp":
                self._fail("Este formato necesita LibreOffice", "Las presentaciones ODP se muestran mediante LibreOffice.")
            else:
                run_async(lambda: render_pptx(path), done(self._show_slides), failed, self)
        elif kind == "document" and ext != ".epub":
            self.btn_hifi.setVisible(office and ext in (".docx", ".odt", ".rtf"))
            run_async(lambda: prepare_rich_html(path), done(self._show_rich), failed, self)
        elif kind == "sheet":
            run_async(lambda: load_sheets(path), done(self._show_sheet), failed, self)
        elif kind in ("archive", "folder"):
            # Navegación por dentro sin extraer; al abrir un elemento se extrae solo ese (seguro).
            if self.archive.root != path or self._back is not None or not _keep_back:
                self.archive.set_root(path)
            self.stack.setCurrentWidget(self.archive)
        else:
            # Texto o desconocido: intentar como texto si no parece binario.
            run_async(lambda: _text_or_binary(path), done(self._show_text), failed, self)

    def _open_from_browser(self, path: str):
        self._back = self.archive.location()
        self.open(path, _keep_back=True)

    def _go_back(self):
        if self._back is not None:
            root, cwd = self._back
            self._back = None
            self.open(root, _keep_back=True)
            self.archive.restore(root, cwd)

    def _show_image(self, img):
        self.stack.setCurrentWidget(self.image)
        self.image.set_image(self.path, img)
        self.subtitle.setText(self.subtitle.text().split(" · ")[0] + tr(" · {v0}×{v1} px · ", v0=img.width(), v1=img.height())
                              + " · ".join(self.subtitle.text().split(" · ")[1:]))
        self._set_toolbar("image")
        self.image.setFocus()

    def _show_pdf_preview(self, pdf_path: Path):
        self.pdf.load(str(pdf_path))
        self.stack.setCurrentWidget(self.pdf)
        self._set_toolbar("pdf")

    def _show_slides(self, slides):
        self.slides.show_slides(slides)
        self.stack.setCurrentWidget(self.slides)
        self._set_toolbar("slides")
        self.slides.setFocus()

    def _show_rich(self, html_text: str):
        self.rich.show_html(html_text)
        self.stack.setCurrentWidget(self.rich)
        self._set_toolbar("rich")

    def _show_sheet(self, sheets):
        self.sheet.show_sheets(sheets)
        self.stack.setCurrentWidget(self.sheet)
        self._set_toolbar("sheet")

    def _show_text(self, data):
        if data is None:
            self._fail("Vista previa no disponible",
                       "Este tipo de archivo no se puede previsualizar. Puedes abrirlo con su aplicación habitual.")
            return
        self.text.show_text(self.path, data)
        self.stack.setCurrentWidget(self.text)
        self._set_toolbar("text")

    def _open_hifi(self):
        path, token = self.path, self._token
        self.stack.setCurrentWidget(self.loading)
        self.btn_hifi.hide()

        def ok(pdf):
            if token == self._token:
                self._show_pdf_preview(pdf)

        run_async(lambda: office_to_pdf(path), ok,
                  lambda e: token == self._token and self._fail("LibreOffice falló", _friendly(e)), self)

    def _fail(self, title: str, text: str):
        self.error_title.setText(title)
        self.error_text.setText(text)
        self.stack.setCurrentWidget(self.error)
        self._set_toolbar("none")

    def _sibling(self, step: int):
        nxt = self.image.neighbor(step)
        if nxt:
            self.open(nxt)

    def _present(self):
        if self.slides.slides:
            w = PresentationWindow(self.slides.slides, max(0, self.slides.thumbs.currentRow()))
            w.showFullScreen()
            w.activateWindow()

    def clear(self):
        self._token += 1
        self.archive.cleanup()
        self.pdf.unload()
        self.image.clear()
        self.path = ""
        self.title.setText("")
        self.subtitle.setText("")
        self.stack.setCurrentWidget(self.empty)
        self._set_toolbar("none")

    def keyPressEvent(self, e):
        if self.stack.currentWidget() is self.image and e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._sibling(-1 if e.key() == Qt.Key.Key_Left else 1)
            return
        super().keyPressEvent(e)


def _text_or_binary(path: str):
    with open(path, "rb") as fh:
        head = fh.read(8192)
    if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return None
    return TextViewer.prepare(path)


def _friendly(err: BaseException) -> str:
    if isinstance(err, PermissionError):
        return "No tienes permiso para leer este archivo."
    if isinstance(err, FileNotFoundError):
        return "El archivo ya no existe."
    if isinstance(err, MemoryError):
        return "El archivo es demasiado grande para mostrarlo."
    msg = str(err) or err.__class__.__name__
    if "zip" in msg.lower() or "BadZipFile" in err.__class__.__name__:
        return "El archivo está dañado o no tiene el formato esperado."
    return msg
