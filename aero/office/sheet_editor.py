"""Editor de hojas de cálculo: la cuadrícula manda.

Barra de fórmulas, formato (negrita, cursiva, relleno, color, bordes, formato numérico), insertar y borrar
filas y columnas, ordenar, filtrar, varias hojas y gráficos básicos (de barras o de líneas, guardados en el
XLSX). Las fórmulas se guardan tal cual y se recalculan con el evaluador propio para mostrarlas.
"""

from __future__ import annotations

import datetime as dt
import os
from copy import copy
from pathlib import Path

from openpyxl.styles import Border, PatternFill, Side
from openpyxl.utils import get_column_letter
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox, QFileDialog, QHBoxLayout,
                               QInputDialog, QLineEdit, QMenu, QMessageBox, QPushButton, QTabBar, QTableView,
                               QVBoxLayout, QWidget)

from aero.office import sheetio
from aero.office.formula import Evaluator, a1
from aero.ui.glass import IconButton, h_layout, label, v_layout
from aero.ui.glasswindow import DragArea, GlassWindow, TrDialog
from aero.i18n import tr

NUMBER_FORMATS = [("General", "General"), ("Número (2 decimales)", "#,##0.00"), ("Entero", "#,##0"),
                  ("Porcentaje", "0.00%"), ("Moneda (€)", "#,##0.00 €"), ("Fecha", "DD/MM/YYYY")]
THIN = Side(style="thin", color="FF8A94A6")


def _argb(c: QColor) -> str:
    return "FF" + c.name()[1:].upper()


def _qcolor(argb) -> QColor | None:
    if not argb or not isinstance(argb, str) or len(argb) < 6:
        return None
    c = QColor("#" + argb[-6:])
    return c if c.isValid() else None


def format_value(v, fmt: str) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "VERDADERO" if v else "FALSO"
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%d/%m/%Y") if not isinstance(v, dt.datetime) or (v.hour, v.minute) == (0, 0) \
            else v.strftime("%d/%m/%Y %H:%M")
    if isinstance(v, (int, float)):
        f = fmt or "General"
        if "%" in f:
            dec = len(f.split(".")[1].rstrip("%")) if "." in f else 0
            return f"{v * 100:,.{dec}f} %".replace(",", " ").replace(".", ",").replace(" ", ".")
        if f != "General" and "0" in f:
            dec = len(f.split(".")[1].split(" ")[0].rstrip("€ ")) if "." in f else 0
            s = f"{v:,.{dec}f}".replace(",", " ").replace(".", ",").replace(" ", ".")
            return s + (" €" if "€" in f else "")
        if isinstance(v, float):
            if v.is_integer() and abs(v) < 1e15:
                return str(int(v))
            return f"{v:.10g}".replace(".", ",")
        return str(v)
    return str(v)


class SheetModel(QAbstractTableModel):
    """Vista sobre una hoja de openpyxl: solo se consultan las celdas visibles."""

    def __init__(self, book: sheetio.LoadedBook, ev: Evaluator, parent=None):
        super().__init__(parent)
        self.book, self.ev = book, ev
        self.ws = book.wb.active

    def set_sheet(self, name: str):
        self.beginResetModel()
        self.ws = self.book.wb[name]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else max(self.ws.max_row + 40, 100)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else max(self.ws.max_column + 8, 26)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return get_column_letter(section + 1) if orientation == Qt.Orientation.Horizontal else str(section + 1)

    def _cell(self, index):
        return self.ws.cell(index.row() + 1, index.column() + 1)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row() + 1, index.column() + 1
        if r > self.ws.max_row or c > self.ws.max_column:
            return None
        cell = self.ws.cell(r, c)
        raw = cell.value
        if role == Qt.ItemDataRole.EditRole:
            return "" if raw is None else (raw if isinstance(raw, str) else format_value(raw, "General"))
        if role == Qt.ItemDataRole.DisplayRole:
            v = self.ev.value(self.ws.title, r, c) if isinstance(raw, str) and raw.startswith("=") else raw
            return format_value(v, cell.number_format)
        if role == Qt.ItemDataRole.FontRole:
            f = cell.font
            if f is not None and (f.b or f.i or f.u):
                q = QFont()
                q.setBold(bool(f.b))
                q.setItalic(bool(f.i))
                q.setUnderline(bool(f.u))
                return q
        if role == Qt.ItemDataRole.BackgroundRole:
            fill = cell.fill
            if fill is not None and fill.fill_type == "solid":
                c = _qcolor(fill.fgColor.rgb if fill.fgColor is not None else None)
                if c is not None:
                    return QBrush(c)
        if role == Qt.ItemDataRole.ForegroundRole:
            f = cell.font
            if f is not None and f.color is not None and isinstance(f.color.rgb, str):
                c = _qcolor(f.color.rgb)
                if c is not None and c != QColor("black"):
                    return QBrush(c)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            v = self.ev.value(self.ws.title, r, c) if isinstance(raw, str) and raw.startswith("=") else raw
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole:
            return False
        cell = self._cell(index)
        v = sheetio._number(str(value)) if isinstance(value, str) else value
        if cell.value == v:
            return False
        self.parent().record(self.ws.title, [(cell.row, cell.column, cell.value)])
        cell.value = v
        self.ev.invalidate()
        self.refresh()
        return True

    def refresh(self):
        self.beginResetModel()
        self.endResetModel()


class SheetEditor(GlassWindow):
    def __init__(self, path: str = "", controller=None):
        super().__init__(Qt.WindowType(0), flat=True)
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumSize(980, 620)
        self.backdrop.flat_opacity = 0.94
        self.path = os.path.abspath(path) if path else ""
        self.dirty = False
        self._undo: list[tuple[str, list]] = []
        self._save_ok = False
        try:
            self.book = sheetio.load(self.path) if self.path else sheetio.LoadedBook(sheetio.Workbook())
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(None, tr("Hoja de cálculo"), tr("No se pudo abrir: {e}", e=e))
            self.book = sheetio.LoadedBook(sheetio.Workbook())
        self.ev = Evaluator(self.book.wb, self.book.cached)
        self.model = SheetModel(self.book, self.ev, self)

        bar = DragArea()
        self.title = label("", "h3")
        self.info = label("", "caption")
        save = IconButton("save", tr("Guardar (Ctrl+S)"), 18)
        save.clicked.connect(self.save)
        save_as = IconButton("external", tr("Guardar como…"), 18)
        save_as.clicked.connect(self.save_as)
        undo = IconButton("undo", tr("Deshacer (Ctrl+Z)"), 18)
        undo.clicked.connect(self.undo)
        bar.setLayout(h_layout(14, v_layout(self.title, self.info, spacing=0), None, undo, 8, save_as, save, 10,
                               self.window_buttons(), spacing=4, margins=(0, 8, 10, 6)))

        # Barra de formato
        self.bold = self._fmt_btn("B", "Negrita", lambda: self.toggle_font("b"))
        self.italic = self._fmt_btn("I", "Cursiva", lambda: self.toggle_font("i"))
        fill = IconButton("brush", tr("Color de relleno"), 18)
        fill.clicked.connect(self.pick_fill)
        color = IconButton("text_tool", tr("Color del texto"), 18)
        color.clicked.connect(self.pick_text_color)
        borders = IconButton("grid", "Bordes", 18)
        borders.clicked.connect(self.toggle_borders)
        self.numfmt = QComboBox()
        for t, f in NUMBER_FORMATS:
            self.numfmt.addItem(t, f)
        self.numfmt.activated.connect(lambda _i: self.set_number_format(self.numfmt.currentData()))
        rows = IconButton("plus", tr("Insertar o borrar filas y columnas"), 18)
        rows.clicked.connect(self._rows_menu)
        sort_a = IconButton("sort", tr("Ordenar por esta columna (A→Z)"), 18)
        sort_a.clicked.connect(lambda: self.sort_column(False))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("Filtrar esta columna…"))
        self.filter.setMaximumWidth(200)
        self.filter.textChanged.connect(self.apply_filter)
        chart = IconButton("visualizer", tr("Insertar gráfico de la selección"), 18)
        chart.clicked.connect(self.insert_chart)
        fmt = QWidget()
        fmt.setLayout(h_layout(self.bold, self.italic, fill, color, borders, self.numfmt, 10, rows, sort_a,
                               self.filter, chart, None, spacing=3, margins=(12, 0, 12, 6)))

        self.cell_name = QLineEdit()
        self.cell_name.setReadOnly(True)
        self.cell_name.setFixedWidth(80)
        self.formula = QLineEdit()
        self.formula.setPlaceholderText(tr("Valor o fórmula (empieza por =)"))
        self.formula.returnPressed.connect(self.commit_formula)
        fbar = QWidget()
        fbar.setLayout(h_layout(self.cell_name, label("fx", "muted"), self.formula, spacing=6, margins=(12, 0, 12, 6)))

        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.horizontalHeader().setDefaultSectionSize(96)
        self.view.verticalHeader().setDefaultSectionSize(26)
        self.view.setStyleSheet("QTableView { background: #ffffff; color: #1b1f24; gridline-color: #d6dbe3;"
                                " selection-background-color: #cfe3ff; selection-color: #000; }"
                                "QHeaderView::section { background: #eef1f6; color: #3b4452; border: none;"
                                " border-right: 1px solid #d6dbe3; border-bottom: 1px solid #d6dbe3; padding: 2px; }")
        pal = self.view.palette()
        pal.setColor(pal.ColorRole.HighlightedText, QColor("#0b1220"))  # texto legible sobre la selección clara
        pal.setColor(pal.ColorRole.Highlight, QColor("#cfe3ff"))
        self.view.setPalette(pal)
        self.view.selectionModel().currentChanged.connect(self._current)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.currentChanged.connect(self._tab)
        self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._tab_menu)
        add = IconButton("plus", tr("Nueva hoja"), 16)
        add.clicked.connect(self.add_sheet)

        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(bar)
        root.addWidget(fmt)
        root.addWidget(fbar)
        body = QVBoxLayout()
        body.setContentsMargins(12, 0, 12, 10)
        body.setSpacing(4)
        body.addWidget(self.view, 1)
        tabs_row = QHBoxLayout()
        tabs_row.addWidget(self.tabs)
        tabs_row.addWidget(add)
        tabs_row.addStretch(1)
        body.addLayout(tabs_row)
        root.addLayout(body, 1)
        for seq, fn in (("Ctrl+S", self.save), ("Ctrl+Z", self.undo), ("Ctrl+B", lambda: self.toggle_font("b")),
                        ("Ctrl+I", lambda: self.toggle_font("i")), ("Delete", self.clear_cells)):
            QShortcut(QKeySequence(seq), self, activated=fn)
        self._fill_tabs()
        self._sync_title()
        if self.book.unsupported:
            self.info.setText(tr("Aviso: {x}", x="; ".join(self.book.unsupported)))

    def _fmt_btn(self, text, tip, fn):
        from PySide6.QtWidgets import QToolButton

        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setFixedSize(32, 32)
        f = QFont(b.font())
        f.setBold(text == "B")
        f.setItalic(text == "I")
        b.setFont(f)
        b.clicked.connect(fn)
        return b

    # ------------------------------------------------------------------ hojas
    def _fill_tabs(self):
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for name in self.book.wb.sheetnames:
            self.tabs.addTab(name)
        self.tabs.setCurrentIndex(self.book.wb.sheetnames.index(self.model.ws.title))
        self.tabs.blockSignals(False)

    def _tab(self, i: int):
        if i >= 0:
            self.model.set_sheet(self.book.wb.sheetnames[i])
            self.book.wb.active = i
            self.filter.clear()

    def add_sheet(self):
        n = len(self.book.wb.sheetnames) + 1
        name = f"Hoja{n}"
        while name in self.book.wb.sheetnames:
            n += 1
            name = f"Hoja{n}"
        self.book.wb.create_sheet(name)
        self.model.set_sheet(name)
        self._fill_tabs()
        self._mark()

    def _tab_menu(self, pos):
        i = self.tabs.tabAt(pos)
        if i < 0:
            return
        name = self.book.wb.sheetnames[i]
        m = QMenu(self)
        m.addAction(tr("Cambiar nombre…"), lambda: self.rename_sheet(name))
        if len(self.book.wb.sheetnames) > 1:
            m.addAction(tr("Eliminar hoja"), lambda: self.delete_sheet(name))
        m.exec(self.tabs.mapToGlobal(pos))

    def rename_sheet(self, name: str):
        new, ok = QInputDialog.getText(self, tr("Cambiar nombre"), tr("Nombre de la hoja:"), text=name)
        new = new.strip()[:31]
        if ok and new and new not in self.book.wb.sheetnames:
            self.book.wb[name].title = new
            self._fill_tabs()
            self._mark()

    def delete_sheet(self, name: str):
        if QMessageBox.question(self, tr("Eliminar hoja"), tr("¿Eliminar la hoja «{name}»?", name=name)) \
                == QMessageBox.StandardButton.Yes:
            self.book.wb.remove(self.book.wb[name])
            self.model.set_sheet(self.book.wb.sheetnames[0])
            self._fill_tabs()
            self._mark()

    # ------------------------------------------------------------------ edición
    def record(self, sheet: str, cells: list):
        """Guarda el estado anterior de unas celdas para deshacer."""
        self._undo.append((sheet, cells))
        del self._undo[:-200]
        self._mark()

    def undo(self):
        if not self._undo:
            return
        sheet, cells = self._undo.pop()
        ws = self.book.wb[sheet]
        for r, c, v in cells:
            ws.cell(r, c).value = v
        self.ev.invalidate()
        self.model.refresh()

    def _mark(self):
        self.dirty = True
        self._sync_title()

    def _current(self, cur, _prev):
        if not cur.isValid():
            return
        self.cell_name.setText(a1(cur.row() + 1, cur.column() + 1))
        self.formula.setText(str(self.model.data(cur, Qt.ItemDataRole.EditRole) or ""))
        cell = self.model._cell(cur)
        i = self.numfmt.findData(cell.number_format)
        self.numfmt.setCurrentIndex(max(0, i))

    def commit_formula(self):
        idx = self.view.currentIndex()
        if idx.isValid():
            self.model.setData(idx, self.formula.text())
            self.view.setCurrentIndex(self.model.index(idx.row() + 1, idx.column()))
            self.view.setFocus()

    def _selected_cells(self):
        idxs = self.view.selectionModel().selectedIndexes() or [self.view.currentIndex()]
        ws = self.model.ws
        return [ws.cell(i.row() + 1, i.column() + 1) for i in idxs if i.isValid()]

    def clear_cells(self):
        cells = self._selected_cells()
        if not self.view.hasFocus() or not cells:
            return
        self.record(self.model.ws.title, [(c.row, c.column, c.value) for c in cells])
        for c in cells:
            c.value = None
        self.ev.invalidate()
        self.model.refresh()

    def toggle_font(self, attr: str):
        cells = self._selected_cells()
        if not cells:
            return
        on = not bool(getattr(cells[0].font, attr))
        for c in cells:
            f = copy(c.font)
            setattr(f, attr, on)
            c.font = f
        self._mark()
        self.model.refresh()

    def pick_fill(self):
        c = QColorDialog.getColor(QColor("#fff2a8"), self, "Color de relleno")
        if c.isValid():
            for cell in self._selected_cells():
                cell.fill = PatternFill("solid", fgColor=_argb(c))
            self._mark()
            self.model.refresh()

    def pick_text_color(self):
        c = QColorDialog.getColor(QColor("#c01010"), self, "Color del texto")
        if c.isValid():
            for cell in self._selected_cells():
                f = copy(cell.font)
                f.color = _argb(c)
                cell.font = f
            self._mark()
            self.model.refresh()

    def toggle_borders(self):
        cells = self._selected_cells()
        on = not (cells and cells[0].border is not None and cells[0].border.left is not None
                  and cells[0].border.left.style)
        for cell in cells:
            cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN) if on else Border()
        self._mark()
        self.model.refresh()

    def set_number_format(self, fmt: str):
        for cell in self._selected_cells():
            cell.number_format = fmt
        self._mark()
        self.model.refresh()

    def _rows_menu(self):
        idx = self.view.currentIndex()
        r, c = (idx.row() + 1, idx.column() + 1) if idx.isValid() else (1, 1)
        ws = self.model.ws
        m = QMenu(self)
        m.addAction(tr("Insertar fila encima"), lambda: self._struct(lambda: ws.insert_rows(r)))
        m.addAction(tr("Insertar columna a la izquierda"), lambda: self._struct(lambda: ws.insert_cols(c)))
        m.addSeparator()
        m.addAction(tr("Borrar fila"), lambda: self._struct(lambda: ws.delete_rows(r)))
        m.addAction(tr("Borrar columna"), lambda: self._struct(lambda: ws.delete_cols(c)))
        m.exec(self.mapToGlobal(self.rect().center()))

    def _struct(self, fn):
        fn()
        self._undo.clear()  # los cambios de estructura no se deshacen celda a celda
        self.ev.invalidate()
        self._mark()
        self.model.refresh()

    def sort_column(self, descending: bool, header: bool = True):
        """Ordena las filas usadas por la columna actual (la primera fila se trata como encabezado)."""
        idx = self.view.currentIndex()
        col = idx.column() + 1 if idx.isValid() else 1
        ws = self.model.ws
        first = 2 if header else 1
        if ws.max_row < first:
            return
        rows = [[ws.cell(r, c).value for c in range(1, ws.max_column + 1)] for r in range(first, ws.max_row + 1)]
        formulas = any(isinstance(v, str) and v.startswith("=") for row in rows for v in row)

        def key(row):
            # Columnas mezcladas (números, fechas, texto): se agrupan por tipo para que nunca se comparen
            # valores incomparables; vacíos y fórmulas al final.
            import datetime as dt

            v = row[col - 1]
            if v is None or (isinstance(v, str) and v.startswith("=")):
                return (4, 0)
            if isinstance(v, (int, float)):
                return (0, float(v))
            if isinstance(v, dt.datetime):
                return (1, v.replace(tzinfo=None))
            if isinstance(v, dt.date):
                return (1, dt.datetime.combine(v, dt.time()))
            if isinstance(v, dt.time):
                return (2, v.hour * 3600 + v.minute * 60 + v.second + v.microsecond / 1e6)
            return (3, str(v).lower())

        self.record(ws.title, [(r, c, ws.cell(r, c).value) for r in range(first, ws.max_row + 1)
                               for c in range(1, ws.max_column + 1)])
        rows.sort(key=key, reverse=descending)
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                ws.cell(first + i, j + 1).value = v
        self.ev.invalidate()
        self.model.refresh()
        if formulas:
            self.info.setText(tr("Aviso: al ordenar, las fórmulas conservan sus referencias originales"))

    def apply_filter(self, text: str):
        idx = self.view.currentIndex()
        col = idx.column() + 1 if idx.isValid() else 1
        t = text.strip().lower()
        ws = self.model.ws
        for r in range(2, self.model.rowCount() + 1):
            if not t:
                self.view.setRowHidden(r - 1, False)
                continue
            v = self.model.data(self.model.index(r - 1, col - 1))
            self.view.setRowHidden(r - 1, r > ws.max_row or t not in str(v or "").lower())
        if t:
            ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"

    def insert_chart(self, kind: str | None = None, preview: bool = True):
        """Gráfico de barras o de líneas con la selección (primera fila: títulos de serie)."""
        from openpyxl.chart import BarChart, LineChart, Reference

        idxs = self.view.selectionModel().selectedIndexes()
        if len(idxs) < 2:
            QMessageBox.information(self, tr("Gráfico"), tr("Selecciona primero los datos (con una fila de títulos)."))
            return
        r0, r1 = min(i.row() for i in idxs) + 1, max(i.row() for i in idxs) + 1
        c0, c1 = min(i.column() for i in idxs) + 1, max(i.column() for i in idxs) + 1
        if kind is None:
            kind, ok = QInputDialog.getItem(self, tr("Gráfico"), tr("Tipo:"), ["Barras", "Líneas"], 0, False)
            if not ok:
                return
        ws = self.model.ws
        ch = BarChart() if kind == "Barras" else LineChart()
        ch.title = "Gráfico"
        first_data_col = c0 + 1 if c1 > c0 else c0
        data = Reference(ws, min_col=first_data_col, max_col=c1, min_row=r0, max_row=r1)
        ch.add_data(data, titles_from_data=True)
        if c1 > c0:
            ch.set_categories(Reference(ws, min_col=c0, max_col=c0, min_row=r0 + 1, max_row=r1))
        ws.add_chart(ch, f"{get_column_letter(c1 + 2)}{r0}")
        self._mark()
        if preview:
            ChartPreview(self, ws, kind, r0, r1, c0, c1, self.ev).exec()

    # ------------------------------------------------------------------ guardar
    def _sync_title(self):
        name = Path(self.path).name if self.path else "Libro nuevo"
        self.title.setText(name + (" •" if self.dirty else ""))
        self.setWindowTitle(tr("{name} · Hoja de cálculo · AERO Player", name=name))

    def save(self):
        if not self.path or Path(self.path).suffix.lower() not in (".xlsx", ".xlsm", ".csv", ".ods"):
            self.save_as()
            return
        if not self._save_ok:
            lost = self.book.unsupported
            msg = f"¿Guardar los cambios en «{Path(self.path).name}»?"
            if lost:
                msg += "\n\n" + tr("Aviso: {x}. Se recomienda guardar una copia.", x="; ".join(lost))
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
        base = Path(self.path) if self.path else Path.home() / "Libro.xlsx"
        filters = ";;".join(f"{t} (*.{e})" for e, t in sheetio.WRITE_FORMATS.items())
        f, _ = QFileDialog.getSaveFileName(self, tr("Guardar como"), str(base.with_suffix(".xlsx")), filters)
        if f:
            if not Path(f).suffix:
                f += ".xlsx"
            self.save_to(f)
            self.path = os.path.abspath(f)
            self._save_ok = True
            self._sync_title()

    def save_to(self, path: str):
        tmp = path + ".part" + Path(path).suffix
        try:
            sheetio.save(self.book, tmp, self.model.ws.title, self.ev)
            os.replace(tmp, path)
        except Exception as e:  # noqa: BLE001
            if os.path.exists(tmp):
                os.remove(tmp)
            QMessageBox.warning(self, tr("Guardar"), tr("No se pudo guardar: {e}", e=e))
            return
        self.dirty = False
        self.info.setText(f"Guardado: {Path(path).name}")
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


class ChartPreview(TrDialog):
    """Vista previa del gráfico que se guarda en el XLSX (dibujada con los mismos datos)."""

    def __init__(self, parent, ws, kind, r0, r1, c0, c1, ev):
        super().__init__(parent)
        self.setWindowTitle(tr("Gráfico insertado"))
        self.resize(560, 380)
        self.kind = kind
        cats = [str(ws.cell(r, c0).value or "") for r in range(r0 + 1, r1 + 1)] if c1 > c0 else \
            [str(i) for i in range(1, r1 - r0 + 1)]
        first = c0 + 1 if c1 > c0 else c0
        self.series = []
        for c in range(first, c1 + 1):
            name = str(ws.cell(r0, c).value or get_column_letter(c))
            vals = []
            for r in range(r0 + 1, r1 + 1):
                v = ws.cell(r, c).value
                if isinstance(v, str) and v.startswith("="):
                    v = ev.value(ws.title, r, c)
                vals.append(float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0)
            self.series.append((name, vals))
        self.cats = cats
        ok = QPushButton(tr("Aceptar"))
        ok.clicked.connect(self.accept)
        lay = QVBoxLayout(self)
        self.canvas = QWidget()
        self.canvas.paintEvent = self._paint
        lay.addWidget(self.canvas, 1)
        lay.addWidget(label(tr("El gráfico se guarda en el archivo XLSX junto a los datos."), "caption"))
        lay.addLayout(h_layout(None, ok))

    def _paint(self, e):
        p = QPainter(self.canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.canvas.width(), self.canvas.height()
        p.fillRect(0, 0, w, h, QColor("white"))
        if not self.series or not self.cats:
            return
        top = max(1e-9, max(max(v) for _n, v in self.series))
        left, bottom, right, tp = 40, h - 30, w - 12, 14
        p.setPen(QPen(QColor("#9aa4b2"), 1))
        p.drawLine(left, bottom, right, bottom)
        p.drawLine(left, tp, left, bottom)
        colors = ["#2f7ed8", "#f28f43", "#2bb3c0", "#8f7ae0", "#e0675a"]
        n = len(self.cats)
        slot = (right - left) / n
        for si, (_name, vals) in enumerate(self.series):
            col = QColor(colors[si % len(colors)])
            if self.kind == "Barras":
                bw = slot * 0.7 / len(self.series)
                for i, v in enumerate(vals):
                    bh = (bottom - tp) * v / top
                    p.fillRect(int(left + i * slot + slot * 0.15 + si * bw), int(bottom - bh), int(bw), int(bh), col)
            else:
                p.setPen(QPen(col, 2))
                pts = [(left + (i + 0.5) * slot, bottom - (bottom - tp) * v / top) for i, v in enumerate(vals)]
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    p.drawLine(int(x0), int(y0), int(x1), int(y1))
        p.setPen(QColor("#3b4452"))
        for i, c in enumerate(self.cats):
            p.drawText(int(left + i * slot), bottom + 4, int(slot), 20, Qt.AlignmentFlag.AlignHCenter, c[:10])


def open_editor(path: str = "", controller=None) -> SheetEditor:
    w = SheetEditor(path, controller)
    w.resize(1240, 820)
    w.show()
    w.raise_()
    w.activateWindow()
    return w

