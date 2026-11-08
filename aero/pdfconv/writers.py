"""Salida del documento reconstruido: DOCX (python-docx), ODT (odfpy), TXT y HTML (vista de comparación)."""

from __future__ import annotations

import html
import io

from aero.pdfconv.model import Document, Image, Paragraph, Table

PT_PER_INCH = 72.0
FALLBACK_FONT = "Calibri"


# --------------------------------------------------------------------------- DOCX
def to_docx(doc: Document, path: str) -> None:
    from docx import Document as Docx
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    align = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
             "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}
    d = Docx()
    first = True
    for page in doc.pages:
        if first:
            sec = d.sections[0]
        else:
            sec = d.add_section(WD_SECTION.NEW_PAGE)
        sec.page_width, sec.page_height = Pt(page.width), Pt(page.height)
        ml, mt, mr, mb = page.margins
        sec.left_margin, sec.top_margin, sec.right_margin, sec.bottom_margin = (Pt(min(v, 144)) for v in
                                                                                 (ml, mt, mr, mb))
        cols = sec._sectPr.find(qn("w:cols"))
        if cols is None:
            from docx.oxml import OxmlElement

            cols = OxmlElement("w:cols")
            sec._sectPr.append(cols)
        cols.set(qn("w:num"), str(page.columns))
        cols.set(qn("w:space"), "425")
        first = False
        usable = page.width - min(ml, 144) - min(mr, 144)
        prev_col = None
        for b in page.blocks:
            if isinstance(b, Paragraph):
                if page.columns > 1 and prev_col == 1 and b.column == 2:
                    run = d.add_paragraph().add_run()
                    run.add_break(WD_BREAK.COLUMN)  # pasa a la segunda columna
                prev_col = b.column or prev_col
                if b.heading:
                    p = d.add_heading(level=min(3, b.heading))
                else:
                    p = d.add_paragraph()
                p.alignment = align.get(b.align, WD_ALIGN_PARAGRAPH.LEFT)
                p.paragraph_format.space_after = Pt(4)
                for r in b.runs:
                    if not r.text:
                        continue
                    run = p.add_run(r.text)
                    run.font.size = Pt(max(4.0, r.size))
                    run.font.bold = r.bold
                    run.font.italic = r.italic
                    run.font.name = r.font or FALLBACK_FONT
                    run.element.rPr.rFonts.set(qn("w:eastAsia"), r.font or FALLBACK_FONT)
                    if r.color and r.color.lower() not in ("#000000", "#000"):
                        run.font.color.rgb = RGBColor.from_string(r.color.lstrip("#").upper()[:6])
            elif isinstance(b, Image):
                w_pt = min(b.x1 - b.x0, usable / (page.columns or 1))
                d.add_picture(io.BytesIO(b.png), width=Pt(max(8.0, w_pt)))
            elif isinstance(b, Table):
                cols_n = max(len(r) for r in b.rows)
                t = d.add_table(rows=len(b.rows), cols=cols_n)
                t.style = "Table Grid"
                for i, row in enumerate(b.rows):
                    for j, cell in enumerate(row):
                        t.cell(i, j).text = cell
    d.save(path)


# --------------------------------------------------------------------------- ODT
def to_odt(doc: Document, path: str) -> None:
    from odf.draw import Frame
    from odf.draw import Image as DrawImage
    from odf.opendocument import OpenDocumentText
    from odf.style import (GraphicProperties, PageLayout, PageLayoutProperties, ParagraphProperties, Style,
                           TableColumnProperties, TextProperties)
    from odf.table import Table as OTable
    from odf.table import TableCell, TableColumn, TableRow
    from odf.text import H, P, Span

    od = OpenDocumentText()
    if doc.pages:
        pg = doc.pages[0]
        pl = PageLayout(name="Pagina")
        pl.addElement(PageLayoutProperties(pagewidth=f"{pg.width}pt", pageheight=f"{pg.height}pt",
                                           marginleft=f"{min(pg.margins[0], 144)}pt",
                                           margintop=f"{min(pg.margins[1], 144)}pt",
                                           marginright=f"{min(pg.margins[2], 144)}pt",
                                           marginbottom=f"{min(pg.margins[3], 144)}pt"))
        od.automaticstyles.addElement(pl)
        from odf.style import MasterPage

        od.masterstyles.addElement(MasterPage(name="Standard", pagelayoutname=pl))
    styles: dict[tuple, Style] = {}

    def run_style(r) -> Style:
        key = (r.size, r.bold, r.italic, r.font or FALLBACK_FONT, r.color)
        if key not in styles:
            st = Style(name=f"T{len(styles)}", family="text")
            st.addElement(TextProperties(fontsize=f"{r.size}pt", fontweight="bold" if r.bold else "normal",
                                         fontstyle="italic" if r.italic else "normal",
                                         fontname=r.font or FALLBACK_FONT, fontfamily=r.font or FALLBACK_FONT,
                                         color=r.color or "#000000"))
            od.automaticstyles.addElement(st)
            styles[key] = st
        return styles[key]

    pstyles: dict[str, Style] = {}

    def par_style(al: str, page_break: bool) -> Style:
        key = f"{al}{'-br' if page_break else ''}"
        if key not in pstyles:
            st = Style(name=f"P{len(pstyles)}", family="paragraph")
            props = {"textalign": {"justify": "justify", "center": "center", "right": "end"}.get(al, "start"),
                     "marginbottom": "4pt"}
            if page_break:
                props["breakbefore"] = "page"
            st.addElement(ParagraphProperties(**props))
            od.automaticstyles.addElement(st)
            pstyles[key] = st
        return pstyles[key]

    img_style = Style(name="fr1", family="graphic")
    img_style.addElement(GraphicProperties(wrap="none", anchortype="paragraph"))
    od.automaticstyles.addElement(img_style)
    col_style = Style(name="col1", family="table-column")
    col_style.addElement(TableColumnProperties(columnwidth="1.6in"))
    od.automaticstyles.addElement(col_style)
    n_img = 0
    for pi, page in enumerate(doc.pages):
        first_block = True
        for b in page.blocks:
            brk = pi > 0 and first_block
            first_block = False
            if isinstance(b, Paragraph):
                el = H(outlinelevel=b.heading, stylename=par_style(b.align, brk)) if b.heading else \
                    P(stylename=par_style(b.align, brk))
                for r in b.runs:
                    if r.text:
                        el.addElement(Span(stylename=run_style(r), text=r.text))
                od.text.addElement(el)
            elif isinstance(b, Image):
                n_img += 1
                href = od.addPicture(f"Pictures/img{n_img}.png", "image/png", b.png)
                holder = P(stylename=par_style("center", brk))
                fr = Frame(stylename=img_style, width=f"{b.x1 - b.x0}pt", height=f"{b.y1 - b.y0}pt",
                           anchortype="paragraph")
                fr.addElement(DrawImage(href=href))
                holder.addElement(fr)
                od.text.addElement(holder)
            elif isinstance(b, Table):
                t = OTable(name=f"Tabla{pi}")
                t.addElement(TableColumn(numbercolumnsrepeated=max(len(r) for r in b.rows), stylename=col_style))
                for row in b.rows:
                    tr = TableRow()
                    for cell in row:
                        tc = TableCell()
                        tc.addElement(P(text=cell))
                        tr.addElement(tc)
                    t.addElement(tr)
                od.text.addElement(t)
    od.save(path)


# --------------------------------------------------------------------------- TXT y HTML
def to_text(doc: Document) -> str:
    out = []
    for page in doc.pages:
        for b in page.blocks:
            if isinstance(b, Paragraph):
                out.append(b.text.strip())
            elif isinstance(b, Table):
                out.append("\n".join("\t".join(r) for r in b.rows))
        out.append("\f")
    return "\n\n".join(out).replace("\n\n\f\n\n", "\n\n\f\n\n").rstrip("\f\n ") + "\n"


def to_txt(doc: Document, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_text(doc))


def to_html(doc: Document, page_index: int | None = None, image_dir: str | None = None) -> str:
    """HTML de vista previa (estilos en línea; las imágenes como datos incrustados)."""
    import base64

    pages = doc.pages if page_index is None else doc.pages[page_index:page_index + 1]
    parts = []
    for page in pages:
        if page.columns > 1:
            parts.append("<p style='color:#888'><i>[dos columnas]</i></p>")
        for b in page.blocks:
            if isinstance(b, Paragraph):
                al = {"justify": "justify", "center": "center", "right": "right"}.get(b.align, "left")
                tag = f"h{b.heading}" if b.heading else "p"
                spans = []
                for r in b.runs:
                    st = f"font-size:{r.size}pt;"
                    if r.bold:
                        st += "font-weight:bold;"
                    if r.italic:
                        st += "font-style:italic;"
                    if r.font:
                        st += f"font-family:'{html.escape(r.font)}';"
                    if r.color and r.color.lower() != "#000000":
                        st += f"color:{r.color};"
                    spans.append(f"<span style=\"{st}\">{html.escape(r.text)}</span>")
                parts.append(f"<{tag} style='text-align:{al}; margin:0 0 6px 0'>{''.join(spans)}</{tag}>")
            elif isinstance(b, Image):
                data = base64.b64encode(b.png).decode()
                parts.append(f"<p align='center'><img width='{int(min(500, b.x1 - b.x0))}' "
                             f"src='data:image/png;base64,{data}'></p>")
            elif isinstance(b, Table):
                rows = "".join("<tr>" + "".join(f"<td style='border:1px solid #999;padding:3px'>{html.escape(c)}</td>"
                                                for c in r) + "</tr>" for r in b.rows)
                parts.append(f"<table cellspacing='0' style='border-collapse:collapse'>{rows}</table>")
        parts.append("<hr>")
    return "<html><body style='color:#111;background:#fff'>" + "".join(parts) + "</body></html>"


WRITERS = {"docx": to_docx, "odt": to_odt, "txt": to_txt}
