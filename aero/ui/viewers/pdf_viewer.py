"""Visor PDF basado en QtPdf (PDFium): páginas, zoom, ajuste a ancho/página y búsqueda de texto."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtPdf import QPdfDocument, QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import QInputDialog, QLineEdit, QSpinBox, QVBoxLayout, QWidget

from aero.ui.glass import IconButton, h_layout, label
from aero.i18n import tr


class PdfViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = QPdfDocument(self)
        self.view = QPdfView(self)
        self.view.setDocument(self.doc)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.setPageSpacing(14)
        self.view.setStyleSheet("QPdfView { background: transparent; border: none; }")
        pal = self.view.palette()
        for role in (QPalette.ColorRole.Dark, QPalette.ColorRole.Window, QPalette.ColorRole.Base):
            pal.setColor(role, QColor(0, 0, 0, 0))
        self.view.setPalette(pal)
        self.view.viewport().setAutoFillBackground(False)
        self.view.setFrameShape(QPdfView.Shape.NoFrame)
        self.search_model = QPdfSearchModel(self)
        self.search_model.setDocument(self.doc)
        self.view.setSearchModel(self.search_model)
        self._result = -1

        # Barra de herramientas propia (la incrusta ViewerHost)
        self.toolbar = QWidget()
        self.prev_btn = IconButton("up", tr("Página anterior"), 18)
        self.next_btn = IconButton("down", tr("Página siguiente"), 18)
        self.page_box = QSpinBox()
        self.page_box.setMinimum(1)
        self.page_box.setFixedWidth(64)
        self.page_box.setAccessibleName(tr("Número de página"))
        self.page_total = label("/ 0", "muted")
        self.zoom_out = IconButton("zoom_out", "Alejar", 18)
        self.zoom_in = IconButton("zoom_in", "Acercar", 18)
        self.fit_w = IconButton("fit", tr("Ajustar al ancho"), 18, checkable=True)
        self.fit_p = IconButton("viewer", tr("Página completa"), 18, checkable=True)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Buscar"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(200)
        self.search_info = label("", "caption")
        self.s_prev = IconButton("left", tr("Resultado anterior"), 16)
        self.s_next = IconButton("right", tr("Resultado siguiente"), 16)
        self.toolbar.setLayout(h_layout(self.prev_btn, self.next_btn, self.page_box, self.page_total, 12,
                                        self.zoom_out, self.zoom_in, self.fit_w, self.fit_p, 12, self.search,
                                        self.s_prev, self.s_next, self.search_info, spacing=4))
        self.fit_w.setChecked(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)

        nav = self.view.pageNavigator()
        nav.currentPageChanged.connect(lambda p: self._sync_page(p))
        self.prev_btn.clicked.connect(lambda: self.goto(nav.currentPage() - 1))
        self.next_btn.clicked.connect(lambda: self.goto(nav.currentPage() + 1))
        self.page_box.editingFinished.connect(lambda: self.goto(self.page_box.value() - 1))
        self.zoom_in.clicked.connect(lambda: self._zoom(1.2))
        self.zoom_out.clicked.connect(lambda: self._zoom(1 / 1.2))
        self.fit_w.clicked.connect(lambda: self._mode(QPdfView.ZoomMode.FitToWidth))
        self.fit_p.clicked.connect(lambda: self._mode(QPdfView.ZoomMode.FitInView))
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._do_search)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.search.returnPressed.connect(lambda: self._step_result(1))
        self.s_next.clicked.connect(lambda: self._step_result(1))
        self.s_prev.clicked.connect(lambda: self._step_result(-1))
        self.search_model.rowsInserted.connect(lambda *_: self._update_search_info())
        self.search_model.modelReset.connect(self._update_search_info)

    def load(self, path: str) -> None:
        self.doc.close()
        err = self.doc.load(path)
        if err == QPdfDocument.Error.IncorrectPassword:
            pwd, ok = QInputDialog.getText(self, tr("PDF protegido"), tr("Este PDF tiene contraseña:"), QLineEdit.EchoMode.Password)
            if not ok:
                raise ValueError("El PDF está protegido con contraseña.")
            self.doc.setPassword(pwd)
            err = self.doc.load(path)
        if err != QPdfDocument.Error.None_:
            raise ValueError({
                QPdfDocument.Error.FileNotFound: "No se encontró el archivo.",
                QPdfDocument.Error.InvalidFileFormat: "El archivo no es un PDF válido o está dañado.",
                QPdfDocument.Error.IncorrectPassword: "Contraseña incorrecta.",
                QPdfDocument.Error.UnsupportedSecurityScheme: "Esquema de seguridad no compatible.",
            }.get(err, "No se pudo abrir el PDF."))
        n = self.doc.pageCount()
        self.page_box.setMaximum(max(1, n))
        self.page_total.setText(f"/ {n}")
        self.search.clear()
        self._mode(QPdfView.ZoomMode.FitToWidth)
        self.goto(0)

    def unload(self) -> None:
        self.doc.close()

    def goto(self, page: int) -> None:
        n = self.doc.pageCount()
        if n == 0:
            return
        page = max(0, min(n - 1, page))
        self.view.pageNavigator().jump(page, QPointF(), self.view.zoomFactor())

    def _sync_page(self, p: int) -> None:
        self.page_box.blockSignals(True)
        self.page_box.setValue(p + 1)
        self.page_box.blockSignals(False)

    def _zoom(self, f: float) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(0.1, min(8.0, self.view.zoomFactor() * f)))
        self.fit_w.setChecked(False)
        self.fit_p.setChecked(False)

    def _mode(self, m) -> None:
        self.view.setZoomMode(m)
        self.fit_w.setChecked(m == QPdfView.ZoomMode.FitToWidth)
        self.fit_p.setChecked(m == QPdfView.ZoomMode.FitInView)

    def _do_search(self) -> None:
        self._result = -1
        self.search_model.setSearchString(self.search.text())
        QTimer.singleShot(150, self._update_search_info)

    def _update_search_info(self, *_):
        n = self.search_model.rowCount(QModelIndex())
        if not self.search.text():
            self.search_info.setText("")
        else:
            self.search_info.setText(f"{self._result + 1 if self._result >= 0 else 0}/{n}" if n else tr("Sin resultados"))

    def _step_result(self, d: int) -> None:
        n = self.search_model.rowCount(QModelIndex())
        if n == 0:
            return
        self._result = (self._result + d) % n
        self.view.setCurrentSearchResultIndex(self._result)
        link = self.search_model.resultAtIndex(self._result)
        self.view.pageNavigator().jump(link)
        self._update_search_info()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_PageDown,):
            self.goto(self.view.pageNavigator().currentPage() + 1)
        elif k in (Qt.Key.Key_PageUp,):
            self.goto(self.view.pageNavigator().currentPage() - 1)
        elif k == Qt.Key.Key_Home:
            self.goto(0)
        elif k == Qt.Key.Key_End:
            self.goto(self.doc.pageCount() - 1)
        else:
            super().keyPressEvent(e)
