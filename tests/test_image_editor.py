"""Editor de imágenes (fase B): operaciones reales, historial, ajustes, capas, proyecto y exportación."""

import hashlib
import time

import pytest


def wait_until(qapp, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture()
def doc(qapp):
    from PySide6.QtGui import QColor, QImage, QPainter

    from aero.editors.image.document import ImageDocument

    img = QImage(400, 200, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#3070c0"))
    p = QPainter(img)
    p.fillRect(0, 0, 100, 100, QColor("#ff0000"))      # esquina superior izquierda roja
    p.fillRect(300, 100, 100, 100, QColor("#00ff00"))  # esquina inferior derecha verde
    p.end()
    return ImageDocument.from_image(img, "x.png")


def px(img, x, y):
    return img.pixelColor(x, y).name()


def test_crop_resize_rotate_flip_and_undo(doc):
    from PySide6.QtCore import QRect

    doc.crop(QRect(0, 0, 200, 100))
    assert (doc.size.width(), doc.size.height()) == (200, 100)
    assert px(doc.background.image, 10, 10) == "#ff0000"
    doc.rotate90(True)
    assert (doc.size.width(), doc.size.height()) == (100, 200)
    assert px(doc.background.image, 90, 10) == "#ff0000", "la esquina roja pasa arriba a la derecha"
    doc.flip(True)
    assert px(doc.background.image, 10, 10) == "#ff0000"
    doc.resize(50, 100)
    assert (doc.size.width(), doc.size.height()) == (50, 100)
    for _ in range(4):
        doc.undo()
    assert (doc.size.width(), doc.size.height()) == (400, 200), "deshacer vuelve al original"
    doc.redo()
    assert (doc.size.width(), doc.size.height()) == (200, 100)


def test_straighten_margins_pixelate_and_low_res(doc):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor

    doc.straighten(5)
    w, h = doc.size.width(), doc.size.height()
    assert w < 400 and h < 200 and abs(w / h - 2) < 0.05, "endereza y recorta sin esquinas vacías"
    assert doc.background.image.pixelColor(0, 0).alpha() == 255
    doc.undo()
    doc.add_margins(10, 20, 10, 20, QColor("#ffffff"))
    assert (doc.size.width(), doc.size.height()) == (420, 240)
    assert px(doc.background.image, 2, 2) == "#ffffff" and px(doc.background.image, 15, 25) == "#ff0000"
    doc.undo()
    before = doc.background.image.copy()
    doc.pixelate(QRect(90, 90, 40, 40), 20)       # los bloques cruzan el borde rojo/azul
    after = doc.background.image
    assert after != before
    block = {after.pixelColor(x, y).name() for x in range(90, 110) for y in range(90, 110)}
    assert len(block) == 1, "cada bloque de píxeles es de un solo color"
    assert px(after, 10, 10) == "#ff0000", "fuera de la zona no cambia nada"
    doc.low_resolution(8)
    doc.mosaic(QRect(0, 0, 100, 100), 10)
    doc.blur_region(QRect(250, 50, 100, 100), 6)
    assert len(doc.undo_stack) == 4


def test_adjustments_are_non_destructive(doc):
    from aero.editors.image import adjust

    original = doc.background.image.copy()
    doc.checkpoint("Ajustes")
    doc.adjust.update({"brightness": 0.5, "saturation": -1.0})
    out = doc.render()
    c = out.pixelColor(10, 10)
    assert c.red() == c.green() == c.blue() or abs(c.red() - c.green()) < 3, "saturación −100 % → gris"
    assert doc.background.image == original, "los ajustes no tocan los píxeles del fondo"
    doc.undo()
    assert adjust.is_neutral(doc.adjust)
    for name, preset in adjust.PRESETS.items():
        a = dict(adjust.NEUTRAL)
        a.update(preset)
        assert not adjust.apply(original, a).isNull(), name


def test_layers_and_drawing(doc):
    from PySide6.QtGui import QColor, QImage

    sticker = QImage(50, 50, QImage.Format.Format_ARGB32_Premultiplied)
    sticker.fill(QColor("#ffff00"))
    doc.add_image_layer(sticker, "Pegatina")
    ly = doc.current
    ly.x, ly.y, ly.scale, ly.opacity = 200, 100, 1.0, 1.0
    out = doc.render()
    assert px(out, 200, 100) == "#ffff00"
    ly.visible = False
    assert px(doc.render(), 200, 100) != "#ffff00", "ocultar capa"
    ly.visible = True
    doc.duplicate_layer(doc.active)
    assert len(doc.layers) == 3
    doc.move_layer(2, -1)
    assert doc.layers[1].name.endswith("(copia)")
    doc.remove_layer(1)
    assert len(doc.layers) == 2
    doc.move_layer(1, -1)
    assert doc.layers[0].background, "el fondo siempre queda debajo"
    d = doc.drawing_layer()
    assert d.image.size() == doc.size and doc.current is d


def test_project_roundtrip(doc, tmp_path):
    from PySide6.QtGui import QColor, QImage

    from aero.editors.image.document import ImageDocument

    sticker = QImage(30, 30, QImage.Format.Format_ARGB32_Premultiplied)
    sticker.fill(QColor("#ffff00"))
    doc.add_image_layer(sticker, "Pegatina")
    doc.current.angle, doc.current.opacity = 30.0, 0.5
    doc.adjust["contrast"] = 0.3
    p = tmp_path / "trabajo.aeroimg"
    doc.save_project(str(p))
    back = ImageDocument.load_project(str(p))
    assert [ly.name for ly in back.layers] == ["Fondo", "Pegatina"]
    assert back.layers[1].angle == 30.0 and back.layers[1].opacity == 0.5 and back.adjust["contrast"] == 0.3
    assert back.render().pixelColor(5, 5) == doc.render().pixelColor(5, 5)


def test_editor_window_export_keeps_original(qapp, media, tmp_path, controller):
    import shutil

    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage

    src = tmp_path / "foto.png"
    shutil.copy(media / "img.png", src)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    ed = controller.open_image_editor(str(src))
    assert wait_until(qapp, lambda: ed.doc is not None)
    w0 = ed.doc.size.width()
    ed.doc.crop(QRect(0, 0, w0 // 2, ed.doc.size.height()))
    ed.set_adjust("brightness", 0.2)
    out = tmp_path / "copia.webp"
    ed.export_to(str(out), "webp", 80, 1.0)
    assert wait_until(qapp, lambda: out.exists() and out.stat().st_size > 0)
    img = QImage(str(out))
    assert img.width() == w0 // 2
    assert hashlib.sha256(src.read_bytes()).hexdigest() == digest, "el original no se modifica"
    ed.doc.dirty = False
    ed.close()
