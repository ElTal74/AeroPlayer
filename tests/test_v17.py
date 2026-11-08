"""1.7: AERO Paint, biblioteca de efectos y transiciones, tareas, formato .aeroarchive, búsqueda e idiomas."""

import time

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication


def pump(app, s=0.2):
    end = time.time() + s
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _mouse(w, kind, img_pt: QPointF, button=Qt.MouseButton.LeftButton):
    c = w.canvas
    v = QPointF(c.offset.x() + img_pt.x() * c.zoom, c.offset.y() + img_pt.y() * c.zoom)
    t = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
         "release": QEvent.Type.MouseButtonRelease}[kind]
    buttons = button if kind != "release" else Qt.MouseButton.NoButton
    ev = QMouseEvent(t, v, c.mapToGlobal(v), button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(c, ev)


def _drag(w, a, b, steps=6, button=Qt.MouseButton.LeftButton):
    _mouse(w, "press", a, button)
    for i in range(1, steps + 1):
        _mouse(w, "move", QPointF(a.x() + (b.x() - a.x()) * i / steps, a.y() + (b.y() - a.y()) * i / steps), button)
    _mouse(w, "release", b, button)


def test_aero_paint_tools_layers_and_files(qapp, controller, tmp_path):
    from aero.editors.paint.document import PaintDocument

    w = controller.open_paint()
    w.resize(1200, 800)
    pump(qapp, 0.4)
    doc = w.doc
    assert doc.size.width() == 1280 and doc.render().pixelColor(5, 5) == QColor("#ffffff")
    # Pincel rojo
    w.set_color(QColor("#ff0000"))
    w.set_tool("brush")
    w.editor.size.setValue(12)
    _drag(w, QPointF(100, 100), QPointF(300, 100))
    assert doc.render().pixelColor(200, 100).red() > 200 and doc.render().pixelColor(200, 100).green() < 60
    # Rectángulo relleno con el color 2
    w.set_color(QColor("#00ff00"), 2)
    w.set_tool("rect")
    w.fill_shapes.setChecked(True)
    _drag(w, QPointF(400, 300), QPointF(600, 450))
    assert doc.render().pixelColor(500, 375) == QColor("#00ff00")
    # Relleno (cubo) de la zona blanca alrededor con azul, sin tocar el rectángulo
    w.set_color(QColor("#0000ff"))
    w.set_tool("fill")
    _mouse(w, "press", QPointF(1000, 700))
    _mouse(w, "release", QPointF(1000, 700))
    img = doc.render()
    assert img.pixelColor(1000, 700) == QColor("#0000ff") and img.pixelColor(500, 375) == QColor("#00ff00")
    # Cuentagotas
    w.set_tool("picker")
    _mouse(w, "press", QPointF(500, 375))
    assert w.canvas.primary == QColor("#00ff00")
    # Borrador en una capa nueva y opacidad de capa
    w.add_layer()
    assert len(doc.layers) == 2 and doc.active == 1
    w.set_color(QColor("#000000"))
    w.set_tool("pencil")
    _drag(w, QPointF(50, 600), QPointF(250, 600))
    assert doc.layers[1].image.pixelColor(150, 600).alpha() == 255
    w.set_tool("eraser")
    w.editor.size.setValue(30)
    _drag(w, QPointF(100, 600), QPointF(200, 600))
    assert doc.layers[1].image.pixelColor(150, 600).alpha() == 0
    # Selección rectangular y recortar
    w.set_tool("select")
    _drag(w, QPointF(380, 280), QPointF(620, 470))
    assert w.canvas.selection is not None
    w.canvas.crop_to_selection()
    assert (doc.size.width(), doc.size.height()) == (240, 190)
    # Deshacer y rehacer
    w.undo()
    assert doc.size.width() == 1280
    w.redo()
    assert doc.size.width() == 240
    # Proyecto editable y exportaciones
    proj = tmp_path / "dibujo.aeropaint"
    doc.save_project(str(proj))
    again = PaintDocument.load_project(str(proj))
    assert len(again.layers) == 2 and again.size == doc.size
    for ext in ("png", "jpg", "bmp", "webp"):
        out = tmp_path / f"dibujo.{ext}"
        doc.export(str(out))
        assert not QImage(str(out)).isNull()
    # Transparencia: lienzo transparente exportado en PNG conserva el alfa
    t = PaintDocument(40, 30, "transparent")
    t.export(str(tmp_path / "t.png"))
    assert QImage(str(tmp_path / "t.png")).pixelColor(1, 1).alpha() == 0
    doc.dirty = False
    w.close()


def _vid_project(media, tmp_path):
    import shutil

    from aero.editors.video.project import Project, clip_from_media, media_info

    v = tmp_path / "toma.mkv"
    shutil.copy(media / "clip.mkv", v)
    img = tmp_path / "foto.png"
    shutil.copy(media / "img.png", img)
    p = Project(320, 180, 25.0)
    v1 = next(t for t in p.tracks if t.name == "V1")
    a = p.add_clip(v1, clip_from_media(str(v), media_info(str(v))))
    a.out_s = 1.2   # deja material sobrante para la transición
    b = p.add_clip(v1, clip_from_media(str(v), media_info(str(v))))
    c = p.add_clip(v1, clip_from_media(str(img), media_info(str(img))))
    c.out_s = 1.0
    return p, a, b, c


def _render(p, out):
    import subprocess

    from aero.editors.video.export import build_command

    args, total, temps = build_command(p, str(out), "mp4", "h264", 30, 96)
    r = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace", timeout=180)
    return r, total


def test_every_effect_and_transition_exports(media, tmp_path):
    """Todos los efectos y transiciones de la biblioteca producen un vídeo válido con FFmpeg."""
    from aero.editors.video import effects as fx

    p, a, b, c = _vid_project(media, tmp_path)
    ids = list(fx.EFFECTS)
    # se reparten los efectos entre los clips (varios por clip) y se prueba cada transición
    for i, eid in enumerate(ids):
        target = b if fx.EFFECTS[eid].kinds == frozenset({"video"}) else (a, b, c)[i % 3]
        target.effects.append(fx.new_instance(eid))
    for tid in fx.TRANSITIONS:
        b.transition, b.transition_d = tid, 0.5
        c.transition, c.transition_d = tid, 0.4
        r, total = _render(p, tmp_path / f"t_{tid}.mp4")
        assert r.returncode == 0, (tid, r.stderr[-1200:])


def test_effects_change_the_exported_image(media, tmp_path):
    import subprocess

    from aero.editors.video import effects as fx

    p, a, b, c = _vid_project(media, tmp_path)
    for clip in (a, b, c):
        clip.effects.append(fx.new_instance("bw"))
    out = tmp_path / "bn.mp4"
    r, _t = _render(p, out)
    assert r.returncode == 0, r.stderr[-800:]
    # un fotograma del resultado debe estar en blanco y negro (sin saturación)
    frame = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", str(out), "-frames:v", "1", str(frame)],
                   check=True)
    img = QImage(str(frame))
    sats = [img.pixelColor(x, y).hsvSaturationF() for x in range(10, 310, 30) for y in range(10, 170, 30)]
    assert max(sats) < 0.12
    # desactivar el efecto devuelve el color
    for clip in (a, b, c):
        clip.effects[0]["on"] = False
    r, _t = _render(p, out)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", str(out), "-frames:v", "1", str(frame)],
                   check=True)
    img = QImage(str(frame))
    assert max(img.pixelColor(x, y).hsvSaturationF() for x in range(10, 310, 30) for y in range(10, 170, 30)) > 0.4


def _drop(widget, mime_type, value, pos):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QDropEvent

    md = QMimeData()
    md.setData(mime_type, value.encode())
    ev = QDropEvent(QPointF(pos), Qt.DropAction.CopyAction, md, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    widget.dropEvent(ev)


def test_video_effects_library_full_flow(controller, qapp, media, tmp_path):
    import shutil
    import subprocess

    from aero.editors.video.library import MIME_FX, MIME_TR
    from aero.editors.video.project import Project
    from aero.editors.video.timeline import RULER, TRACK_H

    v = tmp_path / "toma.mkv"
    shutil.copy(media / "clip.mkv", v)
    ed = controller.open_video_editor(str(v))
    ed.add_to_timeline(str(v))
    pump(qapp, 0.5)
    tl = ed.timeline
    base_i = next(i for i, t in enumerate(ed.project.tracks) if t.kind == "video" and t.clips)
    a, b = ed.project.tracks[base_i].clips
    y = RULER + base_i * TRACK_H + TRACK_H / 2
    # 1) Transición arrastrada entre los dos clips
    _drop(tl, MIME_TR, "wipe", QPointF(tl.x_of(b.start) + 2, y))
    assert b.transition == "wipe" and 0.1 <= b.transition_d <= b.duration / 2
    # 2) Duración: valor numérico desde el inspector y límite por clips cortos
    ed.timeline.selected = {b.id}
    ed._load_inspector()
    ed.f_td.setValue(0.6)
    assert abs(b.transition_d - 0.6) < 0.01
    tl.request.emit("transition_d", (b.id, 50.0))
    assert b.transition_d <= min(a.duration, b.duration) / 2 + 0.01
    # 3) Quitar la transición (Supr con la transición elegida) y volver a ponerla
    tl.selected_transition = b.id
    ed.delete()
    assert b.transition == "none" and len(ed.project.tracks[base_i].clips) == 2
    _drop(tl, MIME_TR, "dissolve", QPointF(tl.x_of(b.start) + 2, y))
    assert b.transition == "dissolve"
    # 4) Filtro arrastrado sobre el primer vídeo, parámetros, desactivar y reactivar, varios efectos
    _drop(tl, MIME_FX, "bw", QPointF(tl.x_of(a.start + a.duration / 2), y))
    _drop(tl, MIME_FX, "vignette", QPointF(tl.x_of(a.start + a.duration / 2), y))
    assert [x["id"] for x in a.effects] == ["bw", "vignette"]
    ed.timeline.selected = {a.id}
    ed._load_inspector()
    ed.fx_list.setCurrentRow(1)
    ed._fx_set(1, "strength", 1.2)
    assert a.effects[1]["params"]["strength"] == 1.2
    ed.fx_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert a.effects[0]["on"] is False
    ed.fx_list.item(0).setCheckState(Qt.CheckState.Checked)
    assert a.effects[0]["on"] is True
    # 5) Copiar los efectos al segundo clip
    ed.copy_effects()
    ed.paste_effects(b.id)
    assert [x["id"] for x in b.effects] == ["bw", "vignette"]
    # 6) Guardar, cerrar y volver a abrir: todo sigue ahí
    proj = tmp_path / "fx.aerovid"
    ed.project_path = str(proj)
    ed.save_project()
    ed.dirty = False
    ed.close()
    p = Project.load(str(proj))
    clips = [c for t in p.tracks if t.kind == "video" for c in t.clips]
    assert clips[1].transition == "dissolve" and [x["id"] for x in clips[0].effects] == ["bw", "vignette"]
    assert clips[0].effects[1]["params"]["strength"] == 1.2
    # 7) Exportar y comprobar que el efecto está en el vídeo final (blanco y negro)
    out = tmp_path / "fx.mp4"
    r, _t = _render(p, out)
    assert r.returncode == 0, r.stderr[-800:]
    frame = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", str(out), "-frames:v", "1", str(frame)],
                   check=True)
    img = QImage(str(frame))
    w, h = img.width(), img.height()
    def spread(c):  # en gris los tres canales son casi iguales (la saturación HSV falla en píxeles oscuros)
        return max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue())

    assert max(spread(img.pixelColor(x, y2)) for x in range(w // 4, 3 * w // 4, 20)
               for y2 in range(h // 4, 3 * h // 4, 20)) < 24


def test_preview_shows_effects_when_paused(controller, qapp, media, tmp_path):
    import shutil

    v = tmp_path / "toma.mkv"
    shutil.copy(media / "clip.mkv", v)
    ed = controller.open_video_editor(str(v))
    c = next(c for _t, c in ed.project.all_clips())
    ed.apply_effect(c.id, "bw")
    ed.seek(1.0)
    end = time.time() + 15
    while not ed.preview.still.isVisible() and time.time() < end:
        pump(qapp, 0.1)
    assert ed.preview.still.isVisible(), "la vista previa en pausa muestra el fotograma con efectos"
    img = ed.preview.still.pixmap().toImage()
    col = img.pixelColor(img.width() // 2, img.height() // 2)
    assert max(col.red(), col.green(), col.blue()) - min(col.red(), col.green(), col.blue()) < 24
    ed.toggle_play()
    assert not ed.preview.still.isVisible(), "al reproducir se ve el vídeo en tiempo real"
    ed.toggle_play()
    ed.dirty = False
    ed.close()


def test_aeroarchive_roundtrip_integrity_and_recovery(tmp_path):
    import zipfile

    from aero.archive import aeroformat, ops, read_archive

    src = tmp_path / "datos ñ"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("hola " * 1000, encoding="utf-8")
    (src / "sub" / "b 😀.bin").write_bytes(bytes(range(256)) * 400)
    out = tmp_path / "copia.aeroarchive"
    ops.compress([str(src)], str(out), "aeroarchive", 5)
    assert out.read_bytes()[:8] == aeroformat.MAGIC and aeroformat.is_aeroarchive(str(out))
    meta, offset = aeroformat.read_meta(str(out))
    assert meta["files"] == 2 and meta["version"] == 1 and offset > 16
    assert ops.test_archive(str(out))[0]
    assert {e.base for e in read_archive(str(out)).files} == {"a.txt", "b 😀.bin"}
    dest = tmp_path / "x"
    ops.extract(str(out), str(dest))
    assert (dest / "datos ñ" / "sub" / "b 😀.bin").read_bytes() == bytes(range(256)) * 400
    # Recuperable con cualquier herramienta ZIP (los lectores ZIP admiten datos delante)
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
    # Con contraseña
    enc = tmp_path / "secreto.aeroarchive"
    ops.compress([str(src / "a.txt")], str(enc), "aeroarchive", 5, "clave")
    assert aeroformat.read_meta(str(enc))[0]["encrypted"] is True
    ops.extract(str(enc), str(tmp_path / "y"), password="clave")
    assert (tmp_path / "y" / "a.txt").exists()
    # Daños: un byte cambiado en el contenido se detecta; una versión futura se rechaza con un mensaje claro
    data = bytearray(out.read_bytes())
    data[offset + 40] ^= 0xFF
    bad = tmp_path / "danado.aeroarchive"
    bad.write_bytes(bytes(data))
    ok, msg = ops.test_archive(str(bad))
    assert not ok and "dañado" in msg
    data = bytearray(out.read_bytes())
    data[8] = 9
    fut = tmp_path / "futuro.aeroarchive"
    fut.write_bytes(bytes(data))
    ok, msg = aeroformat.verify(str(fut))
    assert not ok and "más nueva" in msg


def test_own_format_association_only_touches_own_extension():
    import uuid

    from aero.core import associations as a

    base = rf"Software\AeroPlayerTest\{uuid.uuid4().hex[:8]}"
    reg = a.Registry(base)
    try:
        reg.set(rf"{a.CLASSES}\.zip", None, "OtroPrograma.Zip")   # asociación ajena que debe quedar intacta
        a.register(reg)
        assert reg.get(rf"{a.CLASSES}\.aeroarchive") == a.OWN_PROGID
        assert reg.get(rf"{a.CLASSES}\{a.OWN_PROGID}\DefaultIcon")
        assert "open_archive" in reg.get(rf"{a.CLASSES}\{a.OWN_PROGID}\shell\open\command")
        assert reg.get(rf"{a.CLASSES}\.zip") == "OtroPrograma.Zip"
        a.unregister(reg)
        assert reg.get(rf"{a.CLASSES}\.aeroarchive") is None
        assert reg.get(rf"{a.CLASSES}\.zip") == "OtroPrograma.Zip"
    finally:
        reg.delete_tree("")
        a.Registry().delete_tree("Software\\AeroPlayerTest")


def test_palette_and_close_media(controller, qapp, media):
    win = controller.show_main()
    win.navigate("library")
    win.open_palette()
    pal = win.cmd_palette
    pal.edit.setText("ajustes")
    pal.refresh()
    titles = [pal.list.item(i).text().split("\n")[0] for i in range(pal.list.count())]
    assert "Ajustes" in titles
    pal.edit.setText("compresion")       # sin tilde encuentra el apartado de Ajustes
    pal.refresh()
    titles = [pal.list.item(i).text().split("\n")[0] for i in range(pal.list.count())]
    assert "Compresión" in titles
    i = titles.index("Compresión")
    pal._activate(pal.list.item(i))
    assert win.current_page() == "settings"
    sp = win.page("settings")
    assert sp.nav.currentItem().text() == "Compresión"
    # Un vídeo abierto en la aplicación se cierra sin cerrar la aplicación y vuelve a donde estabas
    win.navigate("library")
    win.play([str(media / "clip.mkv")])
    pump(qapp, 0.8)
    assert win.current_page() == "player" and win.engine.current is not None
    win.page("player").close_btn.click()
    pump(qapp, 0.3)
    assert win.current_page() == "library" and win.engine.current is None and win.isVisible()


def test_languages_catalogs_are_complete_and_safe():
    import json
    import re
    from pathlib import Path

    from aero import i18n

    root = Path(i18n.__file__).with_name("locales")
    source = json.loads(Path(i18n.__file__).with_name("source_strings.json").read_text(encoding="utf-8"))
    for code in i18n.LANGUAGES:
        if code == i18n.SOURCE:
            continue
        cat = json.loads((root / f"{code}.json").read_text(encoding="utf-8"))
        cat.pop("@language", None)
        if code in i18n.FALLBACK:
            assert all(k in source and v != k for k, v in cat.items()), code   # solo diferencias reales
        else:
            missing = [k for k in source if k not in cat]
            assert not missing, (code, missing[:5])
        for k, v in cat.items():
            assert set(re.findall(r"{\w+}", k)) == set(re.findall(r"{\w+}", v if isinstance(v, str) else v[0])), (code, k)


def test_language_switch_and_plurals(controller, qapp):
    from aero import i18n

    try:
        i18n.set_language("es-419")
        assert i18n.tr("Ajustes") != "Ajustes"            # «Configuración»
        assert i18n.tr("Biblioteca") == "Biblioteca"       # heredado de es-ES
        i18n.set_language("ru")
        assert i18n.plural_index("ru", 1) == 0 and i18n.plural_index("ru", 3) == 1 and i18n.plural_index("ru", 7) == 2
        win = controller.show_main()
        controller.settings.set("language", "en")
        pump(qapp, 0.5)
        new = controller.main
        assert new is not win and new.rail.buttons["settings"].toolTip() == i18n.tr("Ajustes") != "Ajustes"
        new.navigate("settings")
        sp = new.page("settings")
        assert sp.nav.item(0).text() == i18n.catalog("en")["General"]
        assert sp.search.placeholderText() == i18n.catalog("en")["Buscar ajustes"]
    finally:
        i18n.set_language("es-ES")
        controller.settings.set("language", "es-ES")
        pump(qapp, 0.3)


def test_installer_in_other_language(qapp):
    from aero import i18n
    from aero.installer import ui

    try:
        i18n.set_language("de")
        w = ui.InstallerWindow(None)
        assert w.install_btn.text() == i18n.catalog("de")["Instalar"]
        assert w.lang.currentData() == "de"
        w.deleteLater()
    finally:
        i18n.set_language("es-ES")


def test_settings_file_with_bom_is_read(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("AERO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_bytes(b'\xef\xbb\xbf{"language": "en", "theme": "tropical"}')
    from aero.core.config import Settings

    s = Settings()
    assert s.get("language") == "en" and s.get("theme") == "tropical"
