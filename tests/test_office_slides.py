"""Presentaciones: diapositivas, texto, imágenes, formas, fondos, orden, guardar y reabrir, PDF."""

from pptx import Presentation
from pptx.util import Inches


def _deck(path, media):
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Bienvenida"
    s.placeholders[1].text = "Primera diapositiva"
    s2 = prs.slides.add_slide(prs.slide_layouts[6])
    s2.shapes.add_picture(str(media / "img.png"), Inches(1), Inches(1), width=Inches(3))
    s2.notes_slide.notes_text_frame.text = "Nota del orador"
    prs.save(str(path))


def test_slide_operations_and_roundtrip(qapp, tmp_path, media, controller):
    import pypdfium2 as pdfium
    from PySide6.QtGui import QColor

    src = tmp_path / "charla.pptx"
    _deck(src, media)
    ed = controller.open_slides_editor(str(src))
    assert len(ed.prs.slides) == 2 and ed.thumbs.count() == 2
    assert ed.canvas.img is not None and not ed.canvas.img.isNull()
    # Nueva diapositiva con texto, forma y fondo
    ed.go(1)
    ed.new_slide()
    assert ed.index == 2 and len(ed.prs.slides) == 3
    ed.add_text("Conclusiones")
    tb = ed.canvas.shape
    ed.text_edit.setPlainText("Conclusiones finales")
    ed.apply_text()
    assert tb.text_frame.text == "Conclusiones finales"
    old_left = tb.left
    tb.left = old_left + 500000
    ed._edited()
    shape = ed.add_shape(color=QColor("#ff8800"))
    assert str(shape.fill.fore_color.rgb) == "FF8800"
    ed.slide.background.fill.solid()
    # Duplicar la diapositiva con imagen y reordenar
    ed.go(1)
    ed.dup_slide()
    assert len(ed.prs.slides) == 4
    pics = [sh for sh in ed.prs.slides[2].shapes if sh.shape_type == 13]
    assert pics and pics[0].image.blob, "la imagen se copia al duplicar"
    from aero.office.slides_editor import move_slide

    move_slide(ed.prs, 3, 0)
    assert any(sh.has_text_frame and sh.text_frame.text == "Conclusiones finales" for sh in ed.prs.slides[0].shapes)
    # Deshacer el último cambio (reordenar no pasa por el historial: se deshace el duplicado)
    n = len(ed.prs.slides)
    ed.undo()
    assert len(ed.prs.slides) == n - 1
    ed.redo_check = True
    out = tmp_path / "charla2.pptx"
    ed.save_to(str(out))
    back = Presentation(str(out))
    texts = [sh.text_frame.text for s in back.slides for sh in s.shapes if sh.has_text_frame]
    assert "Bienvenida" in texts and "Conclusiones finales" in texts
    assert back.slides[1].has_notes_slide and "Nota del orador" in back.slides[1].notes_slide.notes_text_frame.text, \
        "lo que el editor no muestra (notas) se conserva"
    pdf = tmp_path / "charla.pdf"
    ed.export_pdf(str(pdf))
    assert len(pdfium.PdfDocument(str(pdf))) == len(ed.prs.slides)
    ed.dirty = False
    ed.close()


def test_delete_slide_and_shape(qapp, tmp_path, media, controller):
    src = tmp_path / "charla.pptx"
    _deck(src, media)
    ed = controller.open_slides_editor(str(src))
    ed.go(1)
    pic = next(iter(ed.slide.shapes))
    ed.canvas.shape = pic
    ed.canvas.setFocus()
    ed.activateWindow()
    from aero.office.slides_editor import delete_shape

    delete_shape(pic)
    assert len(list(ed.slide.shapes)) == 0
    ed.del_slide()
    assert len(ed.prs.slides) == 1
    out = tmp_path / "corta.pptx"
    ed.save_to(str(out))
    assert len(Presentation(str(out)).slides) == 1
    ed.dirty = False
    ed.close()


def test_damaged_pptx_opens_empty_with_warning(qapp, tmp_path, controller, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a)))
    bad = tmp_path / "roto.pptx"
    bad.write_bytes(b"\x00\x01\x02")
    ed = controller.open_slides_editor(str(bad))
    assert warned and len(ed.prs.slides) >= 1 and ed.path == ""
    ed.dirty = False
    ed.close()
