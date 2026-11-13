"""1.3.1: la cabecera de la vista rápida se adapta al ancho (los botones no se montan ni se recortan)."""

import os
import time


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _check_header(mw):
    """Ningún botón visible está recortado ni pisa a otro, y todo cabe dentro de la ventana."""
    bar = mw.actions_bar
    shown = [b for b in bar.buttons.values() if not b.isHidden()]
    assert shown, "siempre queda al menos una acción a la vista"
    prev_right = None
    for b in shown:
        need = bar.ICON_W if bar.compact else b.sizeHint().width()
        assert b.width() >= need, (b.accessibleName(), b.width(), need)
        left = b.mapTo(mw.shade, b.rect().topLeft()).x()
        if prev_right is not None:
            assert left >= prev_right, "los botones no se solapan"
        prev_right = left + b.width()
    # las acciones terminan antes de los botones de la derecha, y estos dentro de la ventana
    app_left = mw.btn_app.mapTo(mw.shade, mw.btn_app.rect().topLeft()).x()
    assert prev_right <= app_left
    win_right = mw.winbtns.mapTo(mw.shade, mw.winbtns.rect().topRight()).x()
    assert win_right <= mw.shade.width()
    if mw._titles.isVisible():      # el nombre no invade las acciones
        t_right = mw._titles.mapTo(mw.shade, mw._titles.rect().topRight()).x()
        first = shown[0].mapTo(mw.shade, shown[0].rect().topLeft()).x()
        assert t_right <= first


def test_quicklook_header_never_collapses(controller, qapp, media, tmp_path):
    """Con una foto pequeña la ventana es estrecha: las acciones pasan a ser solo iconos, sin recortes."""
    from PySide6.QtGui import QImage

    small = tmp_path / "89e62473a57525be84619ed85d649641.jpg"      # nombre largo, como una descarga
    img = QImage(563, 563, QImage.Format.Format_RGB32)
    img.fill(0x335577)
    assert img.save(str(small))
    controller.show_quicklook(str(small))
    pump(qapp, 1.0)
    mw = controller.quicklook
    bar = mw.actions_bar
    assert set(bar.buttons) >= {"edit", "crop", "paint", "convert", "reveal"}

    mw.resize(1200, 700)
    pump(qapp, 0.3)
    assert not bar.compact and bar.buttons["edit"].text() == "Editar"
    _check_header(mw)

    for width in (760, 560, 480, 400, 340):
        mw.resize(width, 420)
        pump(qapp, 0.3)
        _check_header(mw)
    edit = bar.buttons["edit"]
    if os.name == "nt":      # con las fuentes reales los textos no caben a 340 px (en «offscreen» no hay fuentes)
        assert bar.compact
    bar.fit(bar.compact_width())                                  # el modo «solo iconos», sea cual sea la fuente
    assert bar.compact and edit.width() == bar.ICON_W
    assert edit.text() == "" and "Editar" in edit.toolTip()      # el texto pasa a la descripción emergente
    assert not edit.icon().isNull()
    assert bar.fit(bar.ICON_W) == bar.ICON_W                      # sin sitio queda una sola acción, entera
    assert [k for k, b in bar.buttons.items() if not b.isHidden()] == ["edit"]
    assert mw.name.text() == small.name                           # el nombre completo se conserva (se pinta con «…»)

    mw.resize(1200, 700)                                          # y al ensanchar vuelven los textos
    pump(qapp, 0.3)
    assert not bar.compact and bar.buttons["reveal"].text() == "Carpeta"
    _check_header(mw)
    out = os.environ.get("AERO_SHOT_DIR")
    if out:                                                       # capturas para revisar a ojo
        from shot_util import window_image

        for width in (1200, 560, 400):
            mw.resize(width, 600 if width > 600 else 420)
            pump(qapp, 0.4)
            window_image(mw.overlay).save(os.path.join(out, f"cabecera_{width}.png"))
    mw.close()
