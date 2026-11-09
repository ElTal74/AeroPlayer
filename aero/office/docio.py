"""Lectura y escritura de documentos para el editor (sobre `QTextDocument`).

Formatos: DOCX (python-docx, lectura y escritura propias), ODT (escritura con Qt, lectura vía HTML),
RTF (solo lectura del texto), Markdown, HTML y TXT. Exportación a PDF con encabezado, pie y números de
página.

Se conserva: párrafos, alineación, títulos (1–3), negrita, cursiva, subrayado, tachado, tamaño, fuente,
color, resaltado, listas con viñetas o numeradas, tablas e imágenes, encabezado y pie de página.
No se conserva al guardar un DOCX (y se avisa antes): notas al pie, comentarios, control de cambios,
campos, cuadros de texto, formas, varias secciones con distinta orientación.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QRectF, QSizeF, Qt, QUrl
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter,
                           QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextDocumentWriter,
                           QTextFormat, QTextFrameFormat, QTextImageFormat, QTextListFormat, QTextTableFormat)

EMU_PER_PX = 9525  # a 96 ppp
READ_FORMATS = {".docx", ".odt", ".rtf", ".md", ".markdown", ".txt", ".html", ".htm"}
WRITE_FORMATS = {"docx": "Word (DOCX)", "odt": "OpenDocument (ODT)", "md": "Markdown (MD)", "html": "Página web (HTML)",
                 "txt": "Texto (TXT)"}
HEADING_SIZES = {1: 20.0, 2: 16.0, 3: 13.0}


@dataclass
class LoadedDoc:
    doc: QTextDocument
    header: str = ""
    footer: str = ""
    page_numbers: bool = False
    unsupported: list[str] = field(default_factory=list)   # elementos que no se conservarán al guardar


# --------------------------------------------------------------------------- lectura
def load(path: str) -> LoadedDoc:
    ext = Path(path).suffix.lower()
    if ext == ".docx":
        return load_docx(path)
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Calibri", 11))
    if ext in (".md", ".markdown"):
        doc.setMarkdown(Path(path).read_text(encoding="utf-8", errors="replace"))
    elif ext in (".html", ".htm"):
        doc.setHtml(Path(path).read_text(encoding="utf-8", errors="replace"))
    elif ext == ".odt":
        from aero.ui.viewers.doc_viewers import prepare_rich_html

        doc.setHtml(prepare_rich_html(path))
        return LoadedDoc(doc, unsupported=["El formato ODT se abre a través de HTML: algunos estilos de página "
                                           "pueden simplificarse."])
    elif ext == ".rtf":
        from striprtf.striprtf import rtf_to_text

        doc.setPlainText(rtf_to_text(Path(path).read_text(encoding="latin-1", errors="replace")))
        return LoadedDoc(doc, unsupported=["RTF: se abre el texto sin formato. Guárdalo como DOCX u ODT para "
                                           "conservar los cambios con formato."])
    else:
        from aero.core.builtin_convert import read_text_file

        doc.setPlainText(read_text_file(Path(path)))
    return LoadedDoc(doc)


def _char_format(run, para_size: float | None = None) -> QTextCharFormat:
    f = QTextCharFormat()
    font = run.font
    if run.bold:
        f.setFontWeight(QFont.Weight.Bold)
    if run.italic:
        f.setFontItalic(True)
    if run.underline:
        f.setFontUnderline(True)
    if font.strike:
        f.setFontStrikeOut(True)
    size = font.size.pt if font.size is not None else para_size
    if size:
        f.setFontPointSize(float(size))
    if font.name:
        f.setFontFamilies([font.name])
    try:
        if font.color is not None and font.color.rgb is not None:
            f.setForeground(QBrush(QColor("#" + str(font.color.rgb))))
    except (AttributeError, ValueError):
        pass
    if font.highlight_color is not None:
        f.setBackground(QBrush(QColor(255, 235, 59)))
    return f


def _style_size(style) -> float | None:
    while style is not None:
        if style.font is not None and style.font.size is not None:
            return style.font.size.pt
        style = style.base_style
    return None


def _heading_level(par) -> int:
    name = (par.style.name if par.style is not None else "") or ""
    low = name.lower()
    for key in ("heading ", "título ", "titulo "):
        if low.startswith(key) and low[len(key):].strip().isdigit():
            return min(3, int(low[len(key):].strip()))
    return 1 if low in ("title", "título", "titulo") else 0


def _list_kind(par, numbering_fmts: dict) -> str:
    """'' | 'bullet' | 'number'"""
    p_pr = par._p.pPr
    num_pr = p_pr.numPr if p_pr is not None else None
    name = (par.style.name if par.style is not None else "").lower()
    if num_pr is None or num_pr.numId is None:
        if "list bullet" in name or "viñeta" in name:
            return "bullet"
        if "list number" in name:
            return "number"
        return ""
    fmt = numbering_fmts.get(str(num_pr.numId.val), "bullet")
    return "number" if fmt not in ("bullet", "none") else "bullet"


def _numbering_formats(d) -> dict:
    out = {}
    try:
        numbering = d.part.numbering_part.element
    except (KeyError, AttributeError, NotImplementedError):
        return out
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    abstract = {}
    for a in numbering.findall(f"{ns}abstractNum"):
        lvl = a.find(f"{ns}lvl")
        fmt = lvl.find(f"{ns}numFmt") if lvl is not None else None
        abstract[a.get(f"{ns}abstractNumId")] = fmt.get(f"{ns}val") if fmt is not None else "bullet"
    for n in numbering.findall(f"{ns}num"):
        ref = n.find(f"{ns}abstractNumId")
        if ref is not None:
            out[n.get(f"{ns}numId")] = abstract.get(ref.get(f"{ns}val"), "bullet")
    return out


def load_docx(path: str) -> LoadedDoc:
    from docx import Document as Docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = Docx(path)
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Calibri", 11))
    cur = QTextCursor(doc)
    numbering = _numbering_formats(d)
    unsupported = _scan_unsupported(d)
    first = True
    current_list = None
    current_kind = ""
    n_img = 0

    def add_runs(par, cursor: QTextCursor, heading: int):
        nonlocal n_img
        psize = _style_size(par.style) if par.style is not None else None
        for child in par._p.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "hyperlink":
                runs = [r for r in child.iterchildren() if r.tag.endswith("}r")]
            elif tag == "r":
                runs = [child]
            else:
                continue
            for r_el in runs:
                from docx.text.run import Run

                run = Run(r_el, par)
                for blip in r_el.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
                    rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                    try:
                        blob = par.part.related_parts[rid].blob
                    except KeyError:
                        continue
                    img = QImage.fromData(blob)
                    if img.isNull():
                        continue
                    n_img += 1
                    name = f"docx-img-{n_img}"
                    doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), img)
                    ext = next(r_el.iter("{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
                                         "extent"), None)
                    fmt = QTextImageFormat()
                    fmt.setName(name)
                    if ext is not None:
                        fmt.setWidth(int(ext.get("cx")) / EMU_PER_PX)
                        fmt.setHeight(int(ext.get("cy")) / EMU_PER_PX)
                    cursor.insertImage(fmt)
                if run.text:
                    f = _char_format(run, psize)
                    if heading:
                        f.setFontWeight(QFont.Weight.Bold)
                        if not f.hasProperty(QTextFormat.Property.FontPointSize) or run.font.size is None:
                            f.setFontPointSize(HEADING_SIZES[heading])
                    cursor.insertText(run.text.replace("\t", "    "), f)

    def block_format(par, heading: int) -> QTextBlockFormat:
        bf = QTextBlockFormat()
        al = par.alignment
        if al is not None:
            v = int(al)
            bf.setAlignment({1: Qt.AlignmentFlag.AlignHCenter, 2: Qt.AlignmentFlag.AlignRight,
                             3: Qt.AlignmentFlag.AlignJustify}.get(v, Qt.AlignmentFlag.AlignLeft))
        if heading:
            bf.setHeadingLevel(heading)
            bf.setTopMargin(10)
        bf.setBottomMargin(6)
        return bf

    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            par = Paragraph(el, d)
            heading = _heading_level(par)
            kind = _list_kind(par, numbering)
            if first:
                cur.setBlockFormat(block_format(par, heading))
                first = False
            else:
                cur.insertBlock(block_format(par, heading))
            if kind:
                if current_list is None or kind != current_kind:
                    lf = QTextListFormat()
                    lf.setStyle(QTextListFormat.Style.ListDisc if kind == "bullet" else
                                QTextListFormat.Style.ListDecimal)
                    current_list = cur.createList(lf)
                    current_kind = kind
                else:
                    current_list.add(cur.block())
            else:
                current_list, current_kind = None, ""
            add_runs(par, cur, heading)
        elif tag == "tbl":
            table = Table(el, d)
            rows, cols = len(table.rows), max((len(r.cells) for r in table.rows), default=0)
            if rows and cols:
                if first:
                    first = False
                tf = QTextTableFormat()
                tf.setBorder(1)
                tf.setCellPadding(4)
                tf.setCellSpacing(0)
                tf.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
                qt_table = cur.insertTable(rows, cols, tf)
                for i, row in enumerate(table.rows):
                    for j, cell in enumerate(row.cells[:cols]):
                        cc = qt_table.cellAt(i, j).firstCursorPosition()
                        for k, p in enumerate(cell.paragraphs):
                            if k:
                                cc.insertBlock()
                            add_runs(p, cc, 0)
                cur.movePosition(QTextCursor.MoveOperation.End)
            current_list = None
    sec = d.sections[0] if d.sections else None
    header = "\n".join(p.text for p in sec.header.paragraphs).strip() if sec is not None else ""
    footer_pars = sec.footer.paragraphs if sec is not None else []
    footer = "\n".join(p.text for p in footer_pars).strip()
    has_page = any("PAGE" in (instr.text or "") for p in footer_pars
                   for instr in p._p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}instrText"))
    doc.setModified(False)
    return LoadedDoc(doc, header, footer, has_page, unsupported)


def _scan_unsupported(d) -> list[str]:
    body = d.element.body
    xml = body.xml if hasattr(body, "xml") else ""
    found = []
    checks = [("w:footnoteReference", "notas al pie"), ("w:commentReference", "comentarios"),
              ("w:ins ", "control de cambios"), ("w:del ", "control de cambios"), ("w:fldSimple", "campos"),
              ("wps:txbx", "cuadros de texto"), ("wps:wsp", "formas"), ("mc:AlternateContent", "objetos avanzados"),
              ("m:oMath", "ecuaciones")]
    for key, label in checks:
        if key in xml and label not in found:
            found.append(label)
    if len(d.sections) > 1:
        found.append("varias secciones")
    return found


# --------------------------------------------------------------------------- escritura
def _png(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba.data())


def _resource_image(doc: QTextDocument, name: str) -> QImage:
    res = doc.resource(QTextDocument.ResourceType.ImageResource, QUrl(name))
    if isinstance(res, QImage):
        return res
    from PySide6.QtGui import QPixmap

    if isinstance(res, QPixmap):
        return res.toImage()
    img = QImage(name)
    return img


def save(doc: QTextDocument, path: str, header: str = "", footer: str = "", page_numbers: bool = False) -> None:
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "docx":
        save_docx(doc, path, header, footer, page_numbers)
    elif ext == "odt":
        w = QTextDocumentWriter(path, QByteArray(b"odf"))
        if not w.write(doc):
            raise OSError("No se pudo escribir el ODT.")
    elif ext in ("md", "markdown"):
        Path(path).write_text(doc.toMarkdown(), encoding="utf-8")
    elif ext in ("html", "htm"):
        Path(path).write_text(doc.toHtml(), encoding="utf-8")
    elif ext == "txt":
        Path(path).write_text(doc.toPlainText(), encoding="utf-8")
    else:
        raise ValueError(f"No se puede guardar en formato {ext.upper()}.")


def _write_runs(d, par, block, doc: QTextDocument):
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_COLOR_INDEX

    it = block.begin()
    while not it.atEnd():
        frag = it.fragment()
        it += 1
        if not frag.isValid():
            continue
        cf = frag.charFormat()
        if cf.isImageFormat():
            imf = cf.toImageFormat()
            img = _resource_image(doc, imf.name())
            if img.isNull():
                continue
            w = imf.width() or img.width()
            par.add_run().add_picture(io.BytesIO(_png(img)), width=Pt(w * 0.75))
            continue
        text = frag.text().replace(" ", "\n").replace("￼", "")
        if not text:
            continue
        run = par.add_run(text)
        f = run.font
        if cf.fontWeight() >= QFont.Weight.DemiBold.value:
            f.bold = True
        if cf.fontItalic():
            f.italic = True
        if cf.fontUnderline():
            f.underline = True
        if cf.fontStrikeOut():
            f.strike = True
        if cf.hasProperty(QTextFormat.Property.FontPointSize) and cf.fontPointSize() > 0:
            f.size = Pt(cf.fontPointSize())
        fams = cf.fontFamilies()
        if fams:
            f.name = fams[0] if isinstance(fams, list) else str(fams)
        if cf.hasProperty(QTextFormat.Property.ForegroundBrush):
            c = cf.foreground().color()
            if c.isValid() and c != QColor("black"):
                f.color.rgb = RGBColor(c.red(), c.green(), c.blue())
        if cf.hasProperty(QTextFormat.Property.BackgroundBrush) and cf.background().style() != Qt.BrushStyle.NoBrush:
            f.highlight_color = WD_COLOR_INDEX.YELLOW


def save_docx(doc: QTextDocument, path: str, header: str = "", footer: str = "", page_numbers: bool = False):
    from docx import Document as Docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    d = Docx()
    body = d.element.body
    for p in list(body.iterchildren()):
        if p.tag.endswith("}p"):
            body.remove(p)
    align = {Qt.AlignmentFlag.AlignHCenter: WD_ALIGN_PARAGRAPH.CENTER, Qt.AlignmentFlag.AlignRight:
             WD_ALIGN_PARAGRAPH.RIGHT, Qt.AlignmentFlag.AlignJustify: WD_ALIGN_PARAGRAPH.JUSTIFY}

    def add_block(block, container=d):
        bf = block.blockFormat()
        level = bf.headingLevel()
        lst = block.textList()
        if level:
            par = container.add_paragraph(style=f"Heading {min(3, level)}")
        elif lst is not None:
            st = lst.format().style()
            numbered = st in (QTextListFormat.Style.ListDecimal, QTextListFormat.Style.ListLowerAlpha,
                              QTextListFormat.Style.ListUpperAlpha, QTextListFormat.Style.ListLowerRoman,
                              QTextListFormat.Style.ListUpperRoman)
            par = container.add_paragraph(style="List Number" if numbered else "List Bullet")
        else:
            par = container.add_paragraph()
        a = bf.alignment() & Qt.AlignmentFlag.AlignHorizontal_Mask
        for k, v in align.items():
            if a == k or (k == Qt.AlignmentFlag.AlignHCenter and a == Qt.AlignmentFlag.AlignCenter):
                par.alignment = v
        _write_runs(d, par, block, doc)

    frame = doc.rootFrame()
    it = frame.begin()
    while not it.atEnd():
        child = it.currentFrame()
        block = it.currentBlock()
        if child is not None:
            from PySide6.QtGui import QTextTable

            if isinstance(child, QTextTable):
                t = d.add_table(rows=child.rows(), cols=child.columns())
                t.style = "Table Grid"
                for i in range(child.rows()):
                    for j in range(child.columns()):
                        cell = child.cellAt(i, j)
                        dc = t.cell(i, j)
                        dc.paragraphs[0]._p.getparent().remove(dc.paragraphs[0]._p)
                        b = cell.firstCursorPosition().block()
                        end = cell.lastCursorPosition().block()
                        while b.isValid():
                            add_block(b, dc)
                            if b == end:
                                break
                            b = b.next()
        elif block.isValid():
            add_block(block)
        it += 1
    sec = d.sections[0]
    if header:
        sec.header.paragraphs[0].text = header
    if footer or page_numbers:
        p = sec.footer.paragraphs[0]
        p.text = footer + ("  ·  " if footer and page_numbers else "")
        if page_numbers:
            _add_page_field(p)
    d.save(path)


def _add_page_field(par):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = par.add_run()
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


# --------------------------------------------------------------------------- PDF
def export_pdf(doc: QTextDocument, path: str, header: str = "", footer: str = "", page_numbers: bool = True,
               page: QPageSize.PageSizeId = QPageSize.PageSizeId.A4) -> int:
    """PDF paginado con encabezado, pie y «Página n de N». Devuelve el número de páginas."""
    writer = QPdfWriter(path)
    writer.setResolution(96)
    writer.setPageLayout(QPageLayout(QPageSize(page), QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0)))
    full = writer.pageLayout().fullRectPixels(96)
    margin, band = 72, 28
    body = QRectF(margin, margin + band, full.width() - 2 * margin, full.height() - 2 * margin - 2 * band)
    d = doc.clone()
    d.setPageSize(QSizeF(body.width(), body.height()))
    d.setDocumentMargin(0)
    pages = d.pageCount()
    p = QPainter(writer)
    small = QFont("Calibri", 9)
    for i in range(pages):
        if i:
            writer.newPage()
        p.save()
        p.translate(body.left(), body.top() - i * body.height())
        d.drawContents(p, QRectF(0, i * body.height(), body.width(), body.height()))
        p.restore()
        p.setFont(small)
        p.setPen(QColor(90, 90, 90))
        if header:
            p.drawText(QRectF(margin, margin - 4, body.width(), band), Qt.AlignmentFlag.AlignLeft |
                       Qt.AlignmentFlag.AlignVCenter, header)
        foot = footer
        if page_numbers:
            from aero.i18n import tr

            foot = (foot + "    " if foot else "") + tr("Página {n} de {total}", n=i + 1, total=pages)
        if foot:
            p.drawText(QRectF(margin, body.bottom() + 6, body.width(), band), Qt.AlignmentFlag.AlignHCenter |
                       Qt.AlignmentFlag.AlignVCenter, foot)
    p.end()
    return pages
