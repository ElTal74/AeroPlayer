"""Editor de documentos: lectura y escritura de DOCX conservando sus elementos, otros formatos y PDF."""

import hashlib
import io
import time


def _sample_docx(path):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    d = Document()
    d.add_heading("Plan de proyecto", level=1)
    p = d.add_paragraph("Texto normal, ")
    r = p.add_run("negrita")
    r.bold = True
    p.add_run(" y ")
    r = p.add_run("cursiva roja")
    r.italic = True
    r.font.color.rgb = RGBColor(0xC0, 0x10, 0x10)
    r.font.size = Pt(14)
    c = d.add_paragraph("Párrafo centrado")
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for t in ("Primero", "Segundo"):
        d.add_paragraph(t, style="List Bullet")
    for t in ("Paso uno", "Paso dos"):
        d.add_paragraph(t, style="List Number")
    t = d.add_table(rows=2, cols=2)
    for i, row in enumerate([["Clave", "Valor"], ["A", "1"]]):
        for j, v in enumerate(row):
            t.cell(i, j).text = v
    img = QImage(60, 40, QImage.Format.Format_RGB32)
    img.fill(QColor("#2080d0"))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    d.add_picture(io.BytesIO(bytes(ba.data())))
    d.sections[0].header.paragraphs[0].text = "Empresa S.A."
    d.sections[0].footer.paragraphs[0].text = "Confidencial"
    d.save(str(path))


def test_docx_roundtrip_keeps_elements(qapp, tmp_path):
    from docx import Document

    from aero.office import docio

    src = tmp_path / "plan.docx"
    _sample_docx(src)
    ld = docio.load(str(src))
    text = ld.doc.toPlainText()
    for s in ("Plan de proyecto", "negrita", "cursiva roja", "Primero", "Paso dos", "Clave", "Valor"):
        assert s in text
    assert ld.header == "Empresa S.A." and ld.footer == "Confidencial"
    assert ld.unsupported == []
    out = tmp_path / "plan2.docx"
    docio.save(ld.doc, str(out), ld.header, ld.footer, page_numbers=True)
    d = Document(str(out))
    pars = d.paragraphs
    assert pars[0].text == "Plan de proyecto" and pars[0].style.name == "Heading 1"
    runs = {r.text: r for p in pars for r in p.runs}
    assert runs["negrita"].bold
    assert runs["cursiva roja"].italic and str(runs["cursiva roja"].font.color.rgb) == "C01010"
    assert runs["cursiva roja"].font.size.pt == 14
    assert next(p for p in pars if p.text == "Párrafo centrado").alignment == 1
    assert [p.style.name for p in pars if p.text in ("Primero", "Segundo")] == ["List Bullet"] * 2
    assert [p.style.name for p in pars if p.text in ("Paso uno", "Paso dos")] == ["List Number"] * 2
    assert d.tables[0].cell(1, 1).text == "1"
    assert len(d.inline_shapes) == 1, "la imagen se conserva"
    assert d.sections[0].header.paragraphs[0].text == "Empresa S.A."
    assert "PAGE" in d.sections[0].footer.paragraphs[0]._p.xml, "número de página"


def test_other_formats_and_pdf(qapp, tmp_path):
    import pypdfium2 as pdfium
    from PySide6.QtGui import QTextCursor

    from aero.office import docio

    src = tmp_path / "plan.docx"
    _sample_docx(src)
    ld = docio.load(str(src))
    for ext in ("odt", "md", "html", "txt"):
        out = tmp_path / f"plan.{ext}"
        docio.save(ld.doc, str(out))
        back = docio.load(str(out))
        assert "Plan de proyecto" in back.doc.toPlainText(), ext
    cur = QTextCursor(ld.doc)
    cur.movePosition(QTextCursor.MoveOperation.End)
    for i in range(120):
        cur.insertBlock()
        cur.insertText(f"Línea de relleno {i}")
    pdf = tmp_path / "plan.pdf"
    n = docio.export_pdf(ld.doc, str(pdf), "Empresa S.A.", "Confidencial", True)
    assert n >= 2
    doc = pdfium.PdfDocument(str(pdf))
    assert len(doc) == n
    t = doc[1].get_textpage().get_text_range()
    assert "Empresa S.A." in t and f"Página 2 de {n}" in t


def test_unsupported_elements_are_reported(qapp, tmp_path):
    from docx import Document
    from docx.oxml import parse_xml

    from aero.office import docio

    d = Document()
    p = d.add_paragraph("Con campo ")
    p._p.append(parse_xml('<w:fldSimple xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
                          'w:instr="DATE"><w:r><w:t>hoy</w:t></w:r></w:fldSimple>'))
    path = tmp_path / "campos.docx"
    d.save(str(path))
    assert "campos" in docio.load(str(path)).unsupported


def test_document_editor_window(qapp, tmp_path, controller):
    from PySide6.QtGui import QTextCursor

    src = tmp_path / "plan.docx"
    _sample_docx(src)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    ed = controller.open_document_editor(str(src))
    end = time.monotonic() + 10
    while ed.loaded is None and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert "Plan de proyecto" in ed.text.toPlainText()
    # Editar: añadir texto en negrita, buscar y sustituir
    cur = ed.text.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    ed.text.setTextCursor(cur)
    ed.bold.setChecked(True)
    ed.text.insertPlainText(" Añadido")
    n = ed.replace_all("Segundo", "Segunda")
    assert n == 1 and "Segunda" in ed.text.toPlainText()
    out = tmp_path / "copia.docx"
    ed.save_to(str(out))
    from docx import Document

    d = Document(str(out))
    assert any(p.text == "Segunda" for p in d.paragraphs)
    assert any(r.bold and "Añadido" in r.text for p in d.paragraphs for r in p.runs)
    assert hashlib.sha256(src.read_bytes()).hexdigest() == digest, "guardar como no toca el original"
    ed.text.document().setModified(False)
    ed.close()


def test_contextual_opening_from_windows(qapp, tmp_path, media, controller):
    """Al recibir un archivo desde Windows se abre su experiencia, sin la ventana principal."""
    import zipfile

    from openpyxl import Workbook
    from pptx import Presentation

    from aero.office.doc_editor import DocumentEditor
    from aero.office.sheet_editor import SheetEditor
    from aero.office.slides_editor import SlidesEditor

    docx = tmp_path / "a.docx"
    _sample_docx(docx)
    xlsx = tmp_path / "b.xlsx"
    Workbook().save(str(xlsx))
    pptx = tmp_path / "c.pptx"
    Presentation().save(str(pptx))
    zpath = tmp_path / "d.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("x.txt", "x")
    for path, cls in ((docx, DocumentEditor), (xlsx, SheetEditor), (pptx, SlidesEditor)):
        controller.open_files([str(path)])
        assert isinstance(controller.editors[-1], cls)
    controller.open_files([str(zpath)])
    assert controller.media_windows[-1].kind == "archive"
    assert controller.main is None, "no se abre la interfaz completa"
    for e in list(controller.editors):
        if hasattr(e, "dirty"):
            e.dirty = False
        if hasattr(e, "text"):
            e.text.document().setModified(False)
        e.close()


def test_compatibility_matrix_only_registers_what_opens(qapp, tmp_path):
    """Cada extensión que se registra en Windows tiene un módulo que la abre de verdad."""
    import os

    from aero.core import associations, compat
    from aero.core.formats import kind_of

    rows = {r.ext: r for r in compat.matrix()}
    for cat in associations.CATEGORIES:
        for ext in cat.exts:
            assert ext in rows, f"{ext} se registra pero no está en la matriz"
            assert rows[ext].status in ("Completo", "Parcial"), f"{ext}: {rows[ext].status}"
            assert kind_of("x" + ext) != "unknown" or ext in (".aerovid", ".aeroimg", ".torrent")
    assert not rows[".doc"].default_app and rows[".doc"].status == "Requiere LibreOffice"
    if os.name == "nt":
        base = r"Software\AeroPlayerTests\Compat"
        reg = associations.Registry(base)
        try:
            reg.set(r"Software\Classes\.pdf\OpenWithProgids", "AeroPlayer.Document", "")
            associations.register(reg)
            assert reg.get(r"Software\Classes\.pdf\OpenWithProgids", "AeroPlayer.Document") is None, \
                "se limpia la asociación antigua"
            assert reg.get(rf"{associations.CAPS_KEY}\FileAssociations", ".rar") == "AeroPlayer.Archive"
            assert reg.get(rf"{associations.CAPS_KEY}\FileAssociations", ".xlsx") == "AeroPlayer.Sheet"
            assert reg.get(r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\UserChoice",
                           "ProgId") is None, "nunca UserChoice"
        finally:
            reg.delete_tree("")
            associations.Registry(r"Software\AeroPlayerTests").delete_tree("")
