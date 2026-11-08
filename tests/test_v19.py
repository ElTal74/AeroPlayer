"""1.9: auditoría de rendimiento y errores (reposo del fondo animado y correcciones)."""

import time


def pump(app, s=0.2):
    end = time.time() + s
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def test_idle_seconds_is_sane():
    from aero.ui.perf import idle_seconds, on_battery

    assert idle_seconds() >= 0
    assert isinstance(on_battery(), bool)


def test_background_rests_when_idle_or_on_battery(controller, qapp):
    """Sin usar el equipo 3 minutos, o con batería, el fondo se queda quieto; al volver, se anima otra vez."""
    from aero.ui.perf import REST_AFTER, auto_tuner

    s = controller.settings
    s.set("background_motion", "on")
    s.set("theme", "burbuja")
    win = controller.show_main()
    pump(qapp, 0.6)
    bd = win.backdrop
    tuner = auto_tuner()
    try:
        s.set("motion_rest", True)
        pump(qapp, 0.1)
        assert tuner.rest_enabled and tuner._rest_timer.isActive(), "solo se vigila si hay un fondo animado"
        assert not tuner.check_rest(idle=1.0, battery=False)
        pump(qapp, 0.1)
        assert bd._motion.isActive()
        assert tuner.check_rest(idle=REST_AFTER + 1, battery=False)
        pump(qapp, 0.1)
        assert not bd._motion.isActive(), "en reposo el fondo no se anima"
        assert tuner._rest_timer.isActive(), "en reposo se sigue vigilando para despertar"
        assert not tuner.check_rest(idle=0.5, battery=False)
        pump(qapp, 0.1)
        assert bd._motion.isActive(), "al volver a usar el equipo el fondo se mueve"
        assert tuner.check_rest(idle=0.5, battery=True)
        pump(qapp, 0.1)
        assert not bd._motion.isActive(), "con batería se ahorra energía"
        s.set("motion_rest", False)
        pump(qapp, 0.1)
        assert not tuner.resting and bd._motion.isActive(), "desactivar el ajuste despierta el fondo"
        win.showMinimized()
        pump(qapp, 0.4)
        assert not tuner._rest_timer.isActive()
    finally:
        tuner.set_rest_enabled(False)
        win.showNormal()
        pump(qapp, 0.2)


def wait_for(app, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_paint_undo_shares_untouched_layers():
    """Deshacer no duplica las capas que no cambian: QImage comparte los píxeles hasta que se pinta."""
    from PySide6.QtGui import QColor

    from aero.editors.paint.document import PaintDocument

    doc = PaintDocument(64, 64)
    doc.add_layer("Arriba")
    before = [ly.image.constBits() for ly in doc.layers]
    doc.checkpoint("Trazo")
    saved = doc.undo_stack[-1][1]
    assert [ly.image.constBits() for ly in saved] == before, "la copia de deshacer comparte memoria"
    from PySide6.QtGui import QPainter

    p = QPainter(doc.layers[1].image)
    p.fillRect(0, 0, 10, 10, QColor("#ff0000"))
    p.end()
    assert saved[1].image.pixelColor(2, 2) != QColor("#ff0000"), "pintar no cambia la copia de deshacer"
    assert doc.layers[0].image.constBits() == saved[0].image.constBits(), "la capa sin tocar sigue compartida"
    assert doc.undo()
    assert doc.layers[1].image.pixelColor(2, 2) != QColor("#ff0000")


def test_paint_draft_in_background_and_only_when_changed(qapp, controller, tmp_path):
    from PySide6.QtGui import QColor

    w = controller.open_paint("")
    pump(qapp, 0.2)
    a = w.autosaver
    w.doc.checkpoint("Trazo")
    w.doc.layers[0].image.fill(QColor("#00ff00"))
    w.canvas._drag = ("stroke",)
    assert not a.tick(), "a mitad de un trazo no se guarda"
    w.canvas._drag = None
    assert a.tick() and a.writing
    assert not a.tick(), "no se lanzan dos escrituras a la vez"
    assert wait_for(qapp, lambda: not a.writing)
    assert a.draft.path.exists() and a.draft.meta_path.exists()
    stamp = a.draft.path.stat().st_mtime_ns
    assert not a.tick(), "sin cambios nuevos no se reescribe"
    assert a.draft.path.stat().st_mtime_ns == stamp
    # Si se guarda (o se cierra) mientras se escribe, la escritura en curso no deja un borrador
    w.doc.checkpoint("Otro")
    assert a.tick()
    a.discard()
    assert wait_for(qapp, lambda: not a.writing)
    assert not a.draft.path.exists() and not list(a.draft.path.parent.glob("*.part*"))
    w.doc.dirty = False
    w.close()
    pump(qapp, 0.2)


def test_image_editor_draft(qapp, controller, media, tmp_path):
    import shutil

    from aero.core import drafts
    from aero.editors.image.document import ImageDocument

    src = tmp_path / "foto.png"
    shutil.copy(media / "img.png", src)
    ed = controller.open_image_editor(str(src))
    assert wait_for(qapp, lambda: ed.doc is not None)
    ed.set_adjust("brightness", 0.3)
    assert ed.doc.dirty
    assert ed.autosaver.tick()
    assert wait_for(qapp, lambda: not ed.autosaver.writing)
    d = ed.autosaver.draft
    back = ImageDocument.load_project(str(d.path))
    assert abs(back.adjust.get("brightness", 0) - 0.3) < 1e-6
    assert [x.id for x in drafts.all_drafts()] == [d.id]
    ed.doc.dirty = False
    ed.close()
    pump(qapp, 0.2)
    assert drafts.all_drafts() == []


def test_browser_thumbnails_match_their_files(qapp, tmp_path):
    """Varias miniaturas a la vez: cada una es la de su archivo (antes podían salir cambiadas)."""
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QWidget

    from aero.files.browser import ThumbCache

    colors = {}
    for i, c in enumerate(["#ff0000", "#00ff00", "#0000ff", "#ffff00", "#00ffff", "#ff00ff"]):
        p = tmp_path / f"f{i}.png"
        img = QImage(40, 40, QImage.Format.Format_RGB32)
        img.fill(QColor(c))
        img.save(str(p))
        colors[str(p)] = QColor(c)
    ready = []
    owner = QWidget()
    cache = ThumbCache(owner, lambda p: ready.append(p))
    for p in colors:
        cache.get(p)
    assert wait_for(qapp, lambda: len(ready) == len(colors))
    for p, c in colors.items():
        pm = cache.get(p)
        assert pm is not None
        got = pm.toImage().pixelColor(pm.width() // 2, pm.height() // 2)
        assert abs(got.red() - c.red()) < 8 and abs(got.green() - c.green()) < 8 and abs(got.blue() - c.blue()) < 8
    owner.deleteLater()


def test_doc_editor_does_not_add_page_numbers(qapp, tmp_path):
    """Abrir y guardar un DOCX sin números de página no se los añade (antes se forzaban siempre)."""
    from docx import Document

    from aero.office.doc_editor import DocumentEditor

    src = tmp_path / "carta.docx"
    d = Document()
    d.add_paragraph("Hola")
    d.sections[0].footer.paragraphs[0].text = "Pie"
    d.save(str(src))
    ed = DocumentEditor(str(src))
    assert ed.page_numbers is False and ed.footer == "Pie"
    ed.text.document().setModified(False)
    ed.close()


def test_new_visible_texts_are_translated():
    from aero.i18n import catalog

    for code in ("en", "de", "it", "pt-BR", "ru", "zh-CN"):
        cat = catalog(code)
        for key in ("Optimización automática", "Renombrar capa", "Exportar como", "Insertar tabla",
                    "Detener el fondo tras 3 minutos sin usar el equipo y con batería (ahorra energía)",
                    "Datos: {a} · Caché: {b}", "{n} palabra"):
            assert key in cat, (code, key)


def test_wrapped_texts_follow_language(qapp):
    from aero.i18n import set_language, tr

    try:
        set_language("en")
        assert tr("Guardar proyecto") == "Save project"
        assert tr("Save project") == "Save project", "traducir dos veces no cambia nada"
    finally:
        set_language("es-ES")
