"""PDF a documento editable: estructura, estilos, tablas, imágenes, columnas, OCR y formatos de salida."""

import os

import pytest


def _make_pdfs(tmp_path):
    from PySide6.QtCore import QMarginsF, QRectF
    from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

    text_pdf = tmp_path / "digital.pdf"
    w = QPdfWriter(str(text_pdf))
    w.setResolution(72)  # 1 unidad = 1 punto
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                QMarginsF(0, 0, 0, 0)))
    p = QPainter(w)

    def font(size, bold=False, italic=False):
        f = QFont("Arial")
        f.setPointSizeF(size)
        f.setBold(bold)
        f.setItalic(italic)
        return f

    p.setFont(font(24, True))
    p.drawText(72, 90, "Informe anual")
    p.setFont(font(11))
    p.drawText(72, 130, "Este documento resume las ventas del")
    p.setFont(font(11, True))
    p.drawText(268, 130, "primer semestre")
    p.setFont(font(11, italic=True))
    p.drawText(72, 146, "con una nota en cursiva para la prueba.")
    # Tabla con bordes 3×2
    p.setPen(QPen(QColor("black"), 1))
    xs, ys = [72, 222, 372], [180, 205, 230, 255]
    for x in xs:
        p.drawLine(x, ys[0], x, ys[-1])
    for y in ys:
        p.drawLine(xs[0], y, xs[-1], y)
    p.setFont(font(10))
    cells = [["Mes", "Ventas"], ["Enero", "1200"], ["Febrero", "1350"]]
    for r, row in enumerate(cells):
        for c, txt in enumerate(row):
            p.drawText(xs[c] + 6, ys[r] + 17, txt)
    img = QImage(120, 80, QImage.Format.Format_RGB32)
    img.fill(QColor("#3070c0"))
    p.drawImage(QRectF(72, 290, 120, 80), img)
    w.newPage()
    # Página 2: dos columnas
    p.setFont(font(10))
    for i in range(14):
        p.drawText(72, 100 + i * 16, f"Columna izquierda línea {i + 1}")
        p.drawText(320, 100 + i * 16, f"Columna derecha línea {i + 1}")
    p.end()

    scan_pdf = tmp_path / "escaneado.pdf"
    page_img = QImage(1240, 1754, QImage.Format.Format_RGB32)  # A4 a 150 ppp
    page_img.fill(QColor("white"))
    q = QPainter(page_img)
    f = QFont("Segoe UI")
    f.setPixelSize(54)
    q.setFont(f)
    q.setPen(QColor("black"))
    q.drawText(150, 300, "Contrato de alquiler")
    f.setPixelSize(36)
    q.setFont(f)
    q.drawText(150, 420, "La vivienda se entrega en buen estado.")
    q.end()
    w2 = QPdfWriter(str(scan_pdf))
    w2.setResolution(150)
    w2.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                 QMarginsF(0, 0, 0, 0)))
    q2 = QPainter(w2)
    q2.drawImage(0, 0, page_img)
    q2.end()
    return text_pdf, scan_pdf


def test_text_pdf_reconstruction(qapp, tmp_path):
    from aero.pdfconv import extract
    from aero.pdfconv.model import Image, Paragraph, Table

    text_pdf, _ = _make_pdfs(tmp_path)
    doc = extract.convert(str(text_pdf), "auto")
    assert len(doc.pages) == 2
    p1 = doc.pages[0]
    paras = [b for b in p1.blocks if isinstance(b, Paragraph)]
    assert paras[0].text.strip() == "Informe anual" and paras[0].heading == 1, "título detectado"
    body = next(b for b in paras if "resume las ventas" in b.text)
    assert any(r.bold and "primer semestre" in r.text for r in body.runs), "negrita conservada"
    assert any(r.italic and "cursiva" in r.text for b in paras for r in b.runs), "cursiva conservada"
    assert any(abs(r.size - 11) < 0.6 for r in body.runs), "tamaño de letra conservado"
    tables = [b for b in p1.blocks if isinstance(b, Table)]
    assert tables and tables[0].rows == [["Mes", "Ventas"], ["Enero", "1200"], ["Febrero", "1350"]]
    assert any(isinstance(b, Image) for b in p1.blocks), "imagen recuperada"
    assert not any("Mes" in b.text for b in paras), "el texto de la tabla no se duplica en párrafos"
    p2 = doc.pages[1]
    assert p2.columns == 2
    text2 = " ".join(b.text for b in p2.blocks if isinstance(b, Paragraph))
    assert text2.index("izquierda línea 14") < text2.index("derecha línea 1"), "orden de lectura por columnas"
    assert any("dos columnas" in w for w in doc.warnings)


def test_scanned_pdf_uses_ocr(qapp, tmp_path):
    from aero.pdfconv import extract, ocr

    if not ocr.available_languages():
        pytest.skip("sin idiomas de OCR en Windows")
    _, scan_pdf = _make_pdfs(tmp_path)
    doc = extract.convert(str(scan_pdf), "auto")
    page = doc.pages[0]
    assert page.ocr and any("OCR" in w for w in doc.warnings), "se avisa de que es aproximado"
    text = " ".join(b.text for b in page.blocks).lower()
    assert "alquiler" in text and "vivienda" in text
    title = page.blocks[0]
    assert title.heading == 1, "el texto más grande se reconoce como título"


def test_outputs_open_and_keep_content(qapp, tmp_path):
    from docx import Document as Docx
    from odf import teletype
    from odf.opendocument import load
    from odf.text import P

    from aero.pdfconv import extract, writers

    text_pdf, _ = _make_pdfs(tmp_path)
    doc = extract.convert(str(text_pdf))
    for fmt in ("docx", "odt", "txt"):
        out = tmp_path / f"salida.{fmt}"
        writers.WRITERS[fmt](doc, str(out))
        assert out.stat().st_size > 0
    d = Docx(str(tmp_path / "salida.docx"))
    texts = [p.text for p in d.paragraphs]
    assert "Informe anual" in texts[0] and d.paragraphs[0].style.name.startswith("Heading")
    assert any(r.bold and "primer semestre" in r.text for p in d.paragraphs for r in p.runs)
    assert d.tables and d.tables[0].cell(2, 1).text == "1350"
    assert len(d.inline_shapes) == 1, "la imagen está en el DOCX"
    assert len(d.sections) == 2 and d.sections[1]._sectPr.xpath("./w:cols/@w:num") == ["2"]
    odt = load(str(tmp_path / "salida.odt"))
    otext = " ".join(teletype.extractText(p) for p in odt.getElementsByType(P))
    assert "primer semestre" in otext and "1350" in otext
    txt = (tmp_path / "salida.txt").read_text(encoding="utf-8")
    assert "Informe anual" in txt and "Enero\t1200" in txt
    assert "Informe anual" in writers.to_html(doc, 0)


def test_cancel_and_progress(qapp, tmp_path):
    from aero.pdfconv import extract

    text_pdf, _ = _make_pdfs(tmp_path)
    seen = []
    doc = extract.convert(str(text_pdf), progress=lambda i, n: seen.append((i, n)), cancelled=lambda: len(seen) >= 1)
    assert seen == [(1, 2)] and len(doc.pages) == 1, "se puede cancelar entre páginas"
    assert os.path.exists(text_pdf)


def test_convert_window_and_shared_converter(qapp, tmp_path, controller):
    import time

    from aero.core.config import Settings
    from aero.core.convert_spec import ConvertOptions, targets_for
    from aero.core.converter import DONE, ConversionManager

    text_pdf, _ = _make_pdfs(tmp_path)
    w = controller.open_pdf_convert(str(text_pdf))
    w.convert()
    end = time.monotonic() + 30
    while w.doc is None and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert w.doc is not None and len(w.doc.pages) == 2 and w.save_btn.isEnabled()
    assert "Informe anual" in w.result.toPlainText()
    assert w.warnings.count() >= 1
    w.close()
    # El conversor común usa la misma reconstrucción (sin LibreOffice)
    assert [t[0] for t in targets_for(str(text_pdf), office=False)][:3] == ["docx", "odt", "txt"]
    cm = ConversionManager(Settings())
    cm.add([(str(text_pdf), "")], ConvertOptions(target="docx"), tmp_path / "out")
    end = time.monotonic() + 30
    while cm.busy() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    job = next(iter(cm.jobs.values()))
    assert job.state == DONE, job.message
    from docx import Document as Docx

    assert "Informe anual" in Docx(str(job.outputs[0])).paragraphs[0].text
