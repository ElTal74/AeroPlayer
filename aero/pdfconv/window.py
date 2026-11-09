"""Ventana «PDF a documento editable»: convertir, comparar con el original página a página y guardar.

Honestidad: la reconstrucción se presenta como aproximada cuando lo es (avisos por página) y se puede
revisar antes de guardar. Todo el trabajo pesado va a la cola de tareas; el progreso llega por una cola
de mensajes que la ventana lee con un temporizador (ningún objeto Qt viaja al hilo de trabajo).
"""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QLabel, QListWidget, QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QSpinBox, QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from aero.ui.glass import GlassPanel, h_layout, label
from aero.ui.glasswindow import DragArea, GlassWindow
from aero.i18n import tr

MODES = [("auto", "Automático (OCR solo si está escaneado)"), ("text", "Solo texto del PDF"),
         ("ocr", "Reconocer todas las páginas (OCR)")]
FORMATS = [("docx", "Word (DOCX)"), ("odt", "OpenDocument (ODT)"), ("txt", "Texto (TXT)")]


def _render_page(path: str, index: int, width_px: int):
    """Hilo de trabajo: imagen de la página original para la comparación."""
    import pypdfium2 as pdfium

    from aero.core.pdfium_lock import LOCK

    with LOCK:
        pdf = pdfium.PdfDocument(path)
        try:
            page = pdf[index]
            scale = width_px / page.get_width()
            pil = page.render(scale=scale).to_pil().convert("RGB")
            page.close()
        finally:
            pdf.close()
    from PySide6.QtGui import QImage

    data = pil.tobytes()
    return QImage(data, pil.width, pil.height, pil.width * 3, QImage.Format.Format_RGB888).copy()


class PdfConvertWindow(GlassWindow):
    def __init__(self, path: str = "", controller=None):
        super().__init__(Qt.WindowType(0), flat=True)
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("PDF a documento editable · AERO Player"))
        self.setMinimumSize(980, 640)
        self.backdrop.flat_opacity = 0.94
        self.path = ""
        self.doc = None
        self.n_pages = 0
        self._msgs: deque = deque()
        self._cancel = [False]
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._drain)

        bar = DragArea()
        self.title = label(tr("PDF a documento editable"), "h3")
        self.sub = label(tr("Elige un PDF"), "caption")
        pick = QPushButton(tr("Abrir PDF…"))
        pick.setProperty("kind", "flat")
        pick.clicked.connect(self.choose)
        self.mode = QComboBox()
        for k, t in MODES:
            self.mode.addItem(t, k)
        self.lang = QComboBox()
        self.lang.addItem(tr("Idioma de OCR: automático"), "auto")
        from aero.pdfconv.ocr import available_languages

        for tag, name in available_languages():
            self.lang.addItem(f"OCR: {name}", tag)
        self.lang.setToolTip(tr("Idiomas de reconocimiento instalados en Windows (Configuración › Hora e idioma)"))
        self.go = QPushButton(tr("Convertir"))
        self.go.setProperty("kind", "primary")
        self.go.clicked.connect(self.convert)
        bar.setLayout(h_layout(14, h_layout(self.title, 10, self.sub, spacing=0), None, pick, self.mode, self.lang,
                               self.go, 10, self.window_buttons(), spacing=6, margins=(0, 8, 10, 8)))

        # Comparación lado a lado
        self.original = QLabel()
        self.original.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        left = QScrollArea()
        left.setWidget(self.original)
        left.setWidgetResizable(True)
        self.result = QTextBrowser()
        self.result.setOpenLinks(False)
        split = QSplitter()
        split.addWidget(self._titled("Original", left))
        split.addWidget(self._titled("Documento reconstruido (vista previa)", self.result))
        self._split = split
        self._left = left

        self.page = QSpinBox()
        self.page.setRange(1, 1)
        self.page.setPrefix(tr("Página "))
        self.page.valueChanged.connect(self.show_page)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(220)
        self.progress.hide()
        self.cancel_btn = QPushButton(tr("Cancelar"))
        self.cancel_btn.setProperty("kind", "flat")
        self.cancel_btn.clicked.connect(lambda: self._cancel.__setitem__(0, True))
        self.cancel_btn.hide()
        self.format = QComboBox()
        for k, t in FORMATS:
            self.format.addItem(t, k)
        self.save_btn = QPushButton(tr("Guardar…"))
        self.save_btn.setProperty("kind", "primary")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save)
        self.warnings = QListWidget()
        self.warnings.setMaximumHeight(72)
        self.note = label(tr("La conversión reconstruye el documento a partir de lo que el PDF contiene. Tipografías "
                          "especiales, fórmulas, tablas sin bordes o páginas escaneadas pueden necesitar retoques: "
                          "revisa el resultado antes de guardarlo."), "caption", wrap=True)

        bottom = GlassPanel(radius=12, nested=True)
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.addLayout(h_layout(self.page, self.progress, self.cancel_btn, None, label(tr("Guardar como"), "muted"),
                              self.format, self.save_btn, spacing=8))
        bl.addWidget(self.warnings)
        bl.addWidget(self.note)

        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(bar)
        body = QVBoxLayout()
        body.setContentsMargins(10, 0, 10, 10)
        body.setSpacing(8)
        body.addWidget(split, 1)
        body.addWidget(bottom)
        root.addLayout(body, 1)
        if path:
            self.set_path(path)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self, lambda: self._split.setSizes([self._split.width() // 2] * 2))

    def _titled(self, text: str, w: QWidget) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(label(text, "muted"))
        lay.addWidget(w, 1)
        return box

    # ------------------------------------------------------------------ archivo
    def choose(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Elegir PDF"), str(Path(self.path).parent) if self.path else "",
                                           "PDF (*.pdf)")
        if f:
            self.set_path(f)

    def set_path(self, path: str):
        import pypdfium2 as pdfium

        self.path = os.path.abspath(path)
        self.doc = None
        self.save_btn.setEnabled(False)
        self.result.setHtml("<p style='color:#888'>Pulsa «Convertir» para reconstruir el documento.</p>")
        from aero.core.pdfium_lock import try_lock

        with try_lock() as free:
            if not free:               # otra conversión usa PDFium: no se congela la ventana esperando
                QMessageBox.information(self, "PDF", tr("Espera a que termine la conversión en curso y vuelve a "
                                                        "abrir el PDF."))
                return
            try:
                pdf = pdfium.PdfDocument(self.path)
                self.n_pages = len(pdf)
                pdf.close()
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "PDF", tr("No se pudo abrir el PDF: {e}", e=e))
                return
        self.sub.setText(tr("{v0} · {n_pages} páginas", v0=Path(path).name, n_pages=self.n_pages))
        self.page.setRange(1, max(1, self.n_pages))
        self.page.setValue(1)
        self.show_page(1)

    # ------------------------------------------------------------------ conversión
    def convert(self):
        from aero.core.tasks import tasks
        from aero.pdfconv import extract

        if not self.path:
            self.choose()
            return
        msgs, cancel = self._msgs, self._cancel
        cancel[0] = False
        path, mode, lang = self.path, self.mode.currentData(), self.lang.currentData()
        self.go.setEnabled(False)
        self.progress.setRange(0, max(1, self.n_pages))
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_btn.show()
        self._poll.start()

        def job():
            return extract.convert(path, mode, lang, progress=lambda i, n: msgs.append(("p", i)),
                                   cancelled=lambda: cancel[0])

        tasks().submit(job, "heavy", self._done, self._fail, self)

    def _drain(self):
        while self._msgs:
            kind, v = self._msgs.popleft()
            if kind == "p":
                self.progress.setValue(v)
                self.sub.setText(tr("{v0} · página {v} de {n_pages}", v0=Path(self.path).name, v=v, n_pages=self.n_pages))

    def _finish_ui(self):
        self._drain()
        self._poll.stop()
        self.progress.hide()
        self.cancel_btn.hide()
        self.go.setEnabled(True)

    def _done(self, doc):
        self._finish_ui()
        self.doc = doc
        self.save_btn.setEnabled(bool(doc.pages))
        self.warnings.clear()
        if self._cancel[0]:
            self.warnings.addItem(tr("Conversión cancelada: {v0} de {n_pages} páginas.", v0=len(doc.pages), n_pages=self.n_pages))
        for w in doc.warnings or ["Sin avisos: el PDF contenía texto con su formato."]:
            self.warnings.addItem(w)
        self.sub.setText(tr("{v0} · {v1} páginas convertidas", v0=Path(self.path).name, v1=len(doc.pages)))
        self.show_page(self.page.value())

    def _fail(self, err):
        self._finish_ui()
        QMessageBox.warning(self, tr("Convertir"), tr("No se pudo convertir: {err}", err=err))

    def show_page(self, n: int):
        from aero.core.tasks import tasks

        if not self.path:
            return
        i = n - 1
        vw = self._left.viewport().width() - 8
        path, width = self.path, max(300, int(vw * self.devicePixelRatioF()))
        tasks().submit(lambda: _render_page(path, i, min(width, 1400)), "interactive",
                       lambda img: (self.page.value() == n) and self._show_original(img), None, self)
        if self.doc is not None and i < len(self.doc.pages):
            from aero.pdfconv.writers import to_html

            self.result.setHtml(to_html(self.doc, i))

    def _show_original(self, img):
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(self.devicePixelRatioF())
        self.original.setPixmap(pm)

    def save(self):
        from aero.core.tasks import tasks
        from aero.pdfconv import writers

        if self.doc is None:
            return
        fmt = self.format.currentData()
        base = Path(self.path)
        f, _ = QFileDialog.getSaveFileName(self, tr("Guardar documento"), str(base.with_suffix("." + fmt)),
                                           f"{self.format.currentText()} (*.{fmt})")
        if not f:
            return
        if not f.lower().endswith("." + fmt):
            f += "." + fmt
        doc = self.doc
        tasks().submit(lambda: writers.WRITERS[fmt](doc, f), "heavy",
                       lambda _r: self.sub.setText(f"Guardado: {Path(f).name}"),
                       lambda e: QMessageBox.warning(self, tr("Guardar"), tr("No se pudo guardar: {e}", e=e)), self)


def open_window(path: str = "", controller=None) -> PdfConvertWindow:
    w = PdfConvertWindow(path, controller)
    w.resize(1320, 860)
    w.show()
    w.raise_()
    w.activateWindow()
    return w
