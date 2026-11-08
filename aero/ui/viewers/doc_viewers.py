"""Visores de texto, documentos enriquecidos, hojas de cálculo, presentaciones y ZIP."""

from __future__ import annotations

import datetime as dt
import hashlib
import html
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontDatabase, QImage, QPainter, QPen, QPixmap,
                           QTextCursor, QTextDocument)
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QSplitter, QTabBar, QTableView, QTextBrowser, QVBoxLayout, QWidget)

from aero.core.builtin_convert import read_text_file
from aero.core.paths import cache_dir
from aero.ui.glass import IconButton, h_layout, label, tm
from aero.i18n import tr

TEXT_LIMIT = 16 * 1024 * 1024


# --------------------------------------------------------------------------- búsqueda común

class FindBar(QWidget):
    def __init__(self, target, parent=None):
        super().__init__(parent)
        self.target = target
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("Buscar"))
        self.edit.setClearButtonEnabled(True)
        self.edit.setFixedWidth(220)
        self.info = label("", "caption")
        prev = IconButton("left", "Anterior", 16)
        nxt = IconButton("right", "Siguiente", 16)
        self.setLayout(h_layout(self.edit, prev, nxt, self.info, spacing=4))
        self.edit.returnPressed.connect(lambda: self.find(False))
        self.edit.textChanged.connect(lambda _t: self.find(False, restart=True))
        nxt.clicked.connect(lambda: self.find(False))
        prev.clicked.connect(lambda: self.find(True))

    def find(self, backward: bool, restart: bool = False):
        text = self.edit.text()
        if not text:
            self.info.setText("")
            return
        if restart:
            c = self.target.textCursor()
            c.movePosition(QTextCursor.MoveOperation.Start)
            self.target.setTextCursor(c)
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        ok = self.target.find(text, flags)
        if not ok:
            c = self.target.textCursor()
            c.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
            self.target.setTextCursor(c)
            ok = self.target.find(text, flags)
        self.info.setText("" if ok else tr("Sin resultados"))

    def focus(self):
        self.edit.setFocus()
        self.edit.selectAll()


# --------------------------------------------------------------------------- texto plano

class TextViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.edit = QPlainTextEdit()
        self.edit.setReadOnly(True)
        self.edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.find_bar = FindBar(self.edit)
        self.wrap = IconButton("text", tr("Ajuste de línea"), 18, checkable=True)
        self.wrap.setChecked(True)
        self.wrap.toggled.connect(lambda on: self.edit.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if on else QPlainTextEdit.LineWrapMode.NoWrap))
        self.note = label("", "caption")
        self.toolbar = QWidget()
        self.toolbar.setLayout(h_layout(self.find_bar, self.wrap, self.note, spacing=6))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.addWidget(self.edit)

    @staticmethod
    def prepare(path: str) -> tuple[str, bool]:
        size = Path(path).stat().st_size
        return read_text_file(Path(path), TEXT_LIMIT if size > TEXT_LIMIT else None), size > TEXT_LIMIT

    def show_text(self, path: str, data: tuple[str, bool]) -> None:
        text, truncated = data
        code = Path(path).suffix.lower() not in (".txt", ".log", ".nfo", ".md")
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont) if code else QFont("Segoe UI", 11)
        if code:
            font.setPointSize(10)
        self.edit.setFont(font)
        self.edit.setPlainText(text)
        lines = text.count("\n") + 1
        self.note.setText(f"{lines:,} líneas".replace(",", ".") + (tr(" · mostrando los primeros 16 MB") if truncated else ""))

    def focus_search(self):
        self.find_bar.focus()


# --------------------------------------------------------------------------- documento enriquecido

def prepare_rich_html(path: str) -> str:
    """HTML para QTextBrowser. Las imágenes de DOCX se extraen a la caché (QTextBrowser no carga data:)."""
    from aero.core.builtin_convert import DOC_CSS, document_to_html

    p = Path(path)
    if p.suffix.lower() != ".docx":
        return document_to_html(p)
    import mammoth

    key = hashlib.sha1(f"{p}{p.stat().st_mtime}".encode()).hexdigest()[:16]
    img_dir = cache_dir() / "docx_img" / key
    img_dir.mkdir(parents=True, exist_ok=True)
    counter = [0]

    def save_image(image):
        counter[0] += 1
        ext = (image.content_type or "image/png").split("/")[-1].replace("jpeg", "jpg").replace("x-emf", "emf")
        out = img_dir / f"img{counter[0]}.{ext}"
        with image.open() as src:
            out.write_bytes(src.read())
        attrs = {"src": QUrl.fromLocalFile(str(out)).toString()}
        img = QImage(str(out))
        if not img.isNull() and img.width() > 680:
            attrs["width"] = "680"
        return attrs

    with open(p, "rb") as fh:
        from aero.core.builtin_convert import STYLE_MAP

        body = mammoth.convert_to_html(fh, style_map=STYLE_MAP,
                                       convert_image=mammoth.images.img_element(save_image)).value
    return f"<html><head><meta charset='utf-8'><style>{DOC_CSS}</style></head><body>{body}</body></html>"


class RichViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._link)
        self.browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.find_bar = FindBar(self.browser)
        self.toolbar = QWidget()
        self.toolbar.setLayout(h_layout(self.find_bar, spacing=6))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.browser)

    def _link(self, url: QUrl):
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
        elif url.fragment():
            self.browser.scrollToAnchor(url.fragment())

    def show_html(self, html_text: str) -> None:
        # Página clara tipo «papel» sobre el cristal para máxima legibilidad.
        dark = tm().theme.dark
        self.browser.setStyleSheet(
            "QTextBrowser { background: rgba(255,255,255,%d); color: #12202e; border-radius: 12px; padding: 24px; }"
            % (240 if dark else 250))
        self.browser.document().setDefaultStyleSheet("body { color: #12202e; } a { color: #0a6fc2; }")
        self.browser.setHtml(html_text)

    def focus_search(self):
        self.find_bar.focus()


# --------------------------------------------------------------------------- hojas de cálculo

def col_name(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


class SheetModel(QAbstractTableModel):
    def __init__(self, rows: list[list], parent=None):
        super().__init__(parent)
        self.rows = rows
        self.cols = max((len(r) for r in rows), default=0)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.cols

    def data(self, idx, role=Qt.ItemDataRole.DisplayRole):
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.TextAlignmentRole, Qt.ItemDataRole.ToolTipRole):
            return None
        row = self.rows[idx.row()]
        v = row[idx.column()] if idx.column() < len(row) else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter) if isinstance(v, (int, float)) \
                else int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return fmt_cell(v)

    def headerData(self, s, o, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return col_name(s) if o == Qt.Orientation.Horizontal else str(s + 1)


def fmt_cell(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "VERDADERO" if v else "FALSO"
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:,.6g}".replace(",", " ")
    if isinstance(v, dt.datetime):
        return v.strftime("%d/%m/%Y %H:%M") if (v.hour or v.minute) else v.strftime("%d/%m/%Y")
    if isinstance(v, dt.date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, dt.timedelta):
        return str(v)
    return str(v)


MAX_SHEET_ROWS = 300_000


def load_sheets(path: str) -> list[tuple[str, list[list], bool]]:
    p = Path(path)
    if p.suffix.lower() in (".csv", ".tsv"):
        import csv

        text = read_text_file(p)
        try:
            dialect = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel_tab if p.suffix.lower() == ".tsv" else csv.excel
        rows = []
        for i, r in enumerate(csv.reader(text.splitlines(), dialect)):
            if i >= MAX_SHEET_ROWS:
                return [(p.name, rows, True)]
            rows.append(r)
        return [(p.name, rows, False)]
    from python_calamine import CalamineWorkbook

    wb = CalamineWorkbook.from_path(str(p))
    out = []
    for name in wb.sheet_names:
        rows = wb.get_sheet_by_name(name).to_python(skip_empty_area=False, nrows=MAX_SHEET_ROWS + 1)
        out.append((name, rows[:MAX_SHEET_ROWS], len(rows) > MAX_SHEET_ROWS))
    return out


class SheetViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(120)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setWordWrap(False)
        self.info = label("", "caption")
        self.toolbar = QWidget()
        self.toolbar.setLayout(h_layout(self.info, spacing=6))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 4)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.tabs)
        self.sheets: list = []
        self.tabs.currentChanged.connect(self._show)

    def show_sheets(self, sheets) -> None:
        self.sheets = sheets
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for name, _rows, _t in sheets:
            self.tabs.addTab(name)
        self.tabs.blockSignals(False)
        self.tabs.setVisible(len(sheets) > 1)
        self._show(0)

    def _show(self, i: int) -> None:
        if not (0 <= i < len(self.sheets)):
            return
        name, rows, truncated = self.sheets[i]
        self.table.setModel(SheetModel(rows, self.table))
        cols = max((len(r) for r in rows), default=0)
        self.info.setText(f"{len(rows):,} filas × {cols} columnas".replace(",", ".")
                          + (f" · mostrando las primeras {MAX_SHEET_ROWS:,}".replace(",", ".") if truncated else ""))
        # Ajustar el ancho de las primeras columnas según contenido de una muestra
        fm = self.table.fontMetrics()
        for c in range(min(cols, 40)):
            sample = [fmt_cell(r[c]) for r in rows[:200] if c < len(r)]
            w = max([fm.horizontalAdvance(s) for s in sample] + [40]) + 24
            self.table.setColumnWidth(c, min(320, w))


# --------------------------------------------------------------------------- presentaciones

def _emu(v) -> float:
    return float(v or 0)


def render_pptx(path, width: int = 1280, only: int | None = None) -> list[QImage]:
    """Render aproximado de PPTX: fondos, imágenes, formas con relleno, texto y tablas.

    `path` puede ser una ruta o una presentación ya abierta (editor); `only` dibuja solo esa diapositiva."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
    from pptx.enum.text import PP_ALIGN

    prs = Presentation(path) if isinstance(path, (str, bytes)) or hasattr(path, "__fspath__") else path
    sw, sh = _emu(prs.slide_width) or 9144000, _emu(prs.slide_height) or 6858000
    scale = width / sw
    height = int(sh * scale)
    out = []

    def rgb(color_fmt, default=None):
        try:
            if color_fmt is not None and color_fmt.type is not None:
                return QColor("#" + str(color_fmt.rgb))
        except Exception:
            pass
        return default

    def draw_text(p, frame, rect, default_pt=18):
        parts = []
        for para in frame.paragraphs:
            align = {PP_ALIGN.CENTER: "center", PP_ALIGN.RIGHT: "right", PP_ALIGN.JUSTIFY: "justify"}.get(
                para.alignment, "left")
            spans = []
            for run in para.runs:
                f = run.font
                size = (f.size.pt if f.size else default_pt) * 12700 * scale
                col = rgb(f.color if f.color and f.color.type else None, None)
                style = f"font-size:{size:.1f}px;"
                if f.bold:
                    style += "font-weight:600;"
                if f.italic:
                    style += "font-style:italic;"
                if col is not None:
                    style += f"color:{col.name()};"
                spans.append(f"<span style='{style}'>{html.escape(run.text)}</span>")
            if not spans:
                spans.append("&nbsp;")
            bullet = "• " if para.level > 0 else ""
            parts.append(f"<p align='{align}' style='margin:0 0 {max(1, 50800 * scale):.0f}px {para.level * 18}px'>{bullet}{''.join(spans)}</p>")
        doc = QTextDocument()
        doc.setDefaultStyleSheet("p { color: #1b2533; font-family: 'Segoe UI'; }")
        doc.setHtml("".join(parts))
        doc.setTextWidth(rect.width())
        p.save()
        p.translate(rect.topLeft())
        top = 0.0
        try:
            from pptx.enum.text import MSO_ANCHOR

            if frame.vertical_anchor == MSO_ANCHOR.MIDDLE:
                top = max(0.0, (rect.height() - doc.size().height()) / 2)
            elif frame.vertical_anchor == MSO_ANCHOR.BOTTOM:
                top = max(0.0, rect.height() - doc.size().height())
        except Exception:
            pass
        p.translate(0, top)
        doc.drawContents(p, QRectF(0, -top, rect.width(), rect.height()))
        p.restore()

    def draw_shapes(p, shapes, ox=0.0, oy=0.0, sx=1.0, sy=1.0):
        for sh_ in shapes:
            try:
                if sh_.left is None or sh_.width is None:
                    continue
                r = QRectF(ox + _emu(sh_.left) * sx * scale, oy + _emu(sh_.top) * sy * scale,
                           _emu(sh_.width) * sx * scale, _emu(sh_.height) * sy * scale)
                st = sh_.shape_type
                if st == MSO_SHAPE_TYPE.GROUP:
                    # Coordenadas hijas relativas al rectángulo hijo del grupo
                    xfrm = sh_._element.grpSpPr.find(
                        "{http://schemas.openxmlformats.org/drawingml/2006/main}xfrm")
                    ch_off = xfrm.find("{http://schemas.openxmlformats.org/drawingml/2006/main}chOff")
                    ch_ext = xfrm.find("{http://schemas.openxmlformats.org/drawingml/2006/main}chExt")
                    cx, cy = float(ch_off.get("x")), float(ch_off.get("y"))
                    cw, ch = float(ch_ext.get("cx")) or 1, float(ch_ext.get("cy")) or 1
                    nsx, nsy = _emu(sh_.width) / cw * sx, _emu(sh_.height) / ch * sy
                    draw_shapes(p, sh_.shapes, r.left() - cx * nsx * scale, r.top() - cy * nsy * scale, nsx, nsy)
                    continue
                if st == MSO_SHAPE_TYPE.PICTURE or hasattr(sh_, "image"):
                    try:
                        img = QImage.fromData(sh_.image.blob)
                        if not img.isNull():
                            p.drawImage(r, img)
                    except Exception:
                        pass
                fill = getattr(sh_, "fill", None)
                try:
                    if fill is not None and fill.type == 1:  # MSO_FILL.SOLID
                        c = rgb(fill.fore_color)
                        if c is not None:
                            kind = sh_.auto_shape_type if st == MSO_SHAPE_TYPE.AUTO_SHAPE else None
                            p.setPen(Qt.PenStyle.NoPen)
                            p.setBrush(c)
                            if kind == MSO_SHAPE.OVAL:
                                p.drawEllipse(r)
                            elif kind == MSO_SHAPE.ROUNDED_RECTANGLE:
                                rad = min(r.width(), r.height()) * 0.16
                                p.drawRoundedRect(r, rad, rad)
                            else:
                                p.fillRect(r, c)
                            p.setBrush(Qt.BrushStyle.NoBrush)
                except Exception:
                    pass
                if getattr(sh_, "has_table", False) and sh_.has_table:
                    tbl = sh_.table
                    nrows, ncols = len(tbl.rows), len(tbl.columns)
                    cw, chh = r.width() / max(1, ncols), r.height() / max(1, nrows)
                    p.setPen(QPen(QColor("#9aa9b8"), 1))
                    f = p.font()
                    f.setPixelSize(max(8, int(chh * 0.4)))
                    p.setFont(f)
                    for ri, row in enumerate(tbl.rows):
                        for ci, cell in enumerate(row.cells):
                            cr = QRectF(r.left() + ci * cw, r.top() + ri * chh, cw, chh)
                            p.drawRect(cr)
                            p.setPen(QColor("#1b2533"))
                            p.drawText(cr.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                                       cell.text)
                            p.setPen(QPen(QColor("#9aa9b8"), 1))
                elif getattr(sh_, "has_chart", False) and sh_.has_chart:
                    p.setPen(QPen(QColor("#7d8fa3"), 1, Qt.PenStyle.DashLine))
                    p.drawRect(r)
                    p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Gráfico")
                if getattr(sh_, "has_text_frame", False) and sh_.has_text_frame and sh_.text_frame.text.strip():
                    default_pt = 18
                    if getattr(sh_, "is_placeholder", False):
                        try:
                            from pptx.enum.shapes import PP_PLACEHOLDER

                            kind = sh_.placeholder_format.type
                            if kind in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE):
                                default_pt = 40
                            elif kind == PP_PLACEHOLDER.SUBTITLE:
                                default_pt = 28
                            else:
                                default_pt = 22
                        except Exception:
                            pass
                    draw_text(p, sh_.text_frame, r.adjusted(91440 * scale, 45720 * scale, -91440 * scale, 0), default_pt)
            except Exception:
                continue

    slides = list(prs.slides)
    if only is not None:
        slides = slides[only:only + 1]
    for slide in slides:
        img = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        bg = QColor("#ffffff")
        try:
            f = slide.background.fill
            if f.type == 1:
                bg = rgb(f.fore_color, bg)
        except Exception:
            pass
        img.fill(bg)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        try:
            draw_shapes(p, slide.shapes)
        finally:
            p.end()
        out.append(img)
    return out


class SlidesViewer(QWidget):
    present_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.ViewMode.ListMode)
        self.thumbs.setIconSize(QSize(160, 90))
        self.thumbs.setFixedWidth(200)
        self.thumbs.setSpacing(4)
        self.stage = QLabel()
        self.stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stage.setMinimumSize(200, 120)
        split = QSplitter()
        split.addWidget(self.thumbs)
        split.addWidget(self.stage)
        split.setStretchFactor(1, 1)
        self.present_btn = IconButton("fullscreen", tr("Presentar (F5)"), 18)
        self.info = label("", "caption")
        self.toolbar = QWidget()
        self.toolbar.setLayout(h_layout(self.present_btn, self.info, spacing=6))
        self.present_btn.clicked.connect(self.present_requested)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 8)
        lay.addWidget(split)
        self.slides: list[QImage] = []
        self.thumbs.currentRowChanged.connect(self._show)

    def show_slides(self, slides: list[QImage], note: str = "") -> None:
        self.slides = slides
        self.thumbs.clear()
        for i, img in enumerate(slides):
            it = QListWidgetItem(QPixmap.fromImage(img.scaled(320, 180, Qt.AspectRatioMode.KeepAspectRatio,
                                                              Qt.TransformationMode.SmoothTransformation)), f"{i + 1}")
            self.thumbs.addItem(it)
        self.info.setText(f"{len(slides)}")
        self.info.setToolTip(note or "Vista aproximada · instala LibreOffice para máxima fidelidad")
        if slides:
            self.thumbs.setCurrentRow(0)

    def _show(self, i: int) -> None:
        if 0 <= i < len(self.slides):
            pm = QPixmap.fromImage(self.slides[i])
            self.stage.setPixmap(pm.scaled(self.stage.size() * 0.96, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._show(self.thumbs.currentRow())

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_PageDown, Qt.Key.Key_Down):
            self.thumbs.setCurrentRow(min(self.thumbs.count() - 1, self.thumbs.currentRow() + 1))
        elif e.key() in (Qt.Key.Key_Left, Qt.Key.Key_PageUp, Qt.Key.Key_Up):
            self.thumbs.setCurrentRow(max(0, self.thumbs.currentRow() - 1))
        elif e.key() == Qt.Key.Key_F5:
            self.present_requested.emit()
        else:
            super().keyPressEvent(e)


class PresentationWindow(QWidget):
    """Modo presentación a pantalla completa: flechas/clic para avanzar, Esc para salir."""

    def __init__(self, slides: list[QImage], start: int = 0):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.slides, self.i = slides, start
        self.setStyleSheet("background: black;")
        self.setCursor(Qt.CursorShape.BlankCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("black"))
        if self.slides:
            img = self.slides[self.i]
            sz = img.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            r = QRectF((self.width() - sz.width()) / 2, (self.height() - sz.height()) / 2, sz.width(), sz.height())
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(r, img)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Escape, Qt.Key.Key_F5):
            self.close()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Space, Qt.Key.Key_PageDown, Qt.Key.Key_Down, Qt.Key.Key_Return):
            self.i = min(len(self.slides) - 1, self.i + 1)
            self.update()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_PageUp, Qt.Key.Key_Up, Qt.Key.Key_Backspace):
            self.i = max(0, self.i - 1)
            self.update()

    def mousePressEvent(self, e):
        self.i = min(len(self.slides) - 1, self.i + (1 if e.button() == Qt.MouseButton.LeftButton else -1))
        self.i = max(0, self.i)
        self.update()
