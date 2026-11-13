"""1.6: esquinas uniformes, cursor de bordes, compresión fiable y demás mejoras de usabilidad."""

import sys
import time

import pytest

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout


def pump(app, s=0.2):
    end = time.time() + s
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _move(widget, gpos: QPoint):
    local = widget.mapFromGlobal(gpos)
    ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(local), QPointF(gpos), Qt.MouseButton.NoButton,
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)


def test_edge_cursor_is_per_window_and_never_sticks(qapp, monkeypatch):
    from aero.ui import glasswindow
    from aero.ui.glasswindow import GlassWindow

    a, b = GlassWindow(), GlassWindow()
    for w in (a, b):
        child = QLabel("contenido")
        QVBoxLayout(w.backdrop).addWidget(child)
        w.resize(500, 400)
        w.show()
    b.move(a.x() + 700, a.y())
    pump(qapp, 0.3)
    child_a = a.backdrop.findChild(QLabel)
    pos = {"p": a.mapToGlobal(QPoint(a.width() - 2, 200))}
    monkeypatch.setattr(glasswindow.QCursor, "pos", staticmethod(lambda: pos["p"]))
    _move(child_a, pos["p"])
    assert a.cursor().shape() == Qt.CursorShape.SizeHorCursor
    assert QApplication.overrideCursor() is None          # nada global que pueda quedarse puesto
    pos["p"] = a.mapToGlobal(QPoint(250, 200))
    _move(child_a, pos["p"])
    assert a.cursor().shape() == Qt.CursorShape.ArrowCursor
    # Borde, y luego el ratón pasa directamente a otra ventana: el cursor de la primera se quita
    pos["p"] = a.mapToGlobal(QPoint(a.width() - 1, a.height() - 1))
    _move(child_a, pos["p"])
    assert a.cursor().shape() == Qt.CursorShape.SizeFDiagCursor
    pos["p"] = b.mapToGlobal(QPoint(250, 200))
    _move(b.backdrop.findChild(QLabel), pos["p"])
    assert a.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert b.cursor().shape() == Qt.CursorShape.ArrowCursor
    a.close()
    b.close()


@pytest.mark.skipif(sys.platform != "win32", reason="solo Windows (instalador, registro o DWM)")
def test_every_window_gets_rounded_corners(qapp):
    import ctypes

    from PySide6.QtWidgets import QDialog, QMenu

    from aero.ui import corners

    corners.install(qapp)
    dlg = QDialog()
    dlg.show()
    menu = QMenu()
    menu.addAction("Uno")
    menu.popup(QPoint(200, 200))
    pump(qapp, 0.3)
    for w, want in ((dlg, corners.DWMWCP_ROUND), (menu, corners.DWMWCP_ROUNDSMALL)):
        v = ctypes.c_int(-1)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(int(w.winId()), 33, ctypes.byref(v), ctypes.sizeof(v))
        # Qt también pide redondeo a los menús de Windows 11; lo que importa es que nunca queden rectos.
        assert v.value in (want, corners.DWMWCP_ROUND, corners.DWMWCP_ROUNDSMALL), w
    menu.close()
    dlg.close()


def test_open_file_shows_contextual_actions(controller, qapp, media):
    """Al abrir un vídeo o una foto, «Editar» está a la vista y funciona (sin ir al menú del clic derecho)."""
    from aero.editors.image.window import EditorWindow
    from aero.editors.video.window import VideoEditor
    from aero.ui.file_actions import actions_for

    assert [a.key for a in actions_for(str(media / "clip.mkv"))][:2] == ["edit", "convert"]
    assert [a.key for a in actions_for(str(media / "img.png"))][:4] == ["edit", "crop", "paint", "convert"]
    controller.open_files([str(media / "clip.mkv")])
    pump(qapp, 1.0)
    mw = controller.media_windows[-1]
    bar = mw.actions_bar
    # la ventana de este vídeo es pequeña: la barra puede ir en modo «solo iconos» (el nombre se conserva)
    assert bar.isVisible() and bar.buttons["edit"].accessibleName() == "Editar"
    bar.buttons["edit"].click()
    pump(qapp, 1.5)
    ed = next(w for w in controller.editors if isinstance(w, VideoEditor))
    assert ed.isVisible()
    ed.close()
    mw.open(str(media / "img.png"))
    pump(qapp, 0.5)
    assert set(mw.actions_bar.buttons) >= {"edit", "crop", "convert", "reveal"}
    mw.actions_bar.buttons["crop"].click()
    pump(qapp, 1.0)
    img = next(w for w in controller.editors if isinstance(w, EditorWindow))
    assert img.canvas.tool == "crop"
    img.close()
    mw.close()
    pump(qapp, 0.3)


def test_background_really_moves_and_can_be_stopped(controller, qapp):
    """Burbujas, nubes y estrellas se animan de verdad; «reducido» y «estático» se respetan."""
    s = controller.settings
    s.set("background_motion", "on")
    s.set("theme", "cosmos")
    win = controller.show_main()
    pump(qapp, 0.8)
    bd = win.backdrop
    assert bd._motion.isActive() and bd._sprites, "con animaciones activadas el fondo debe moverse"
    stars = [sp for sp in bd._sprites if sp.kind == "stars"]
    assert stars, "las estrellas titilan"
    before = [sp.glow for sp in stars]
    pump(qapp, 0.8)
    assert [sp.glow for sp in stars] != before
    s.set("theme", "burbuja")
    pump(qapp, 0.5)
    bubbles = [sp for sp in win.backdrop._sprites if sp.kind == "bubbles"]
    y0 = [sp.y for sp in bubbles]
    pump(qapp, 0.8)
    assert [sp.y for sp in bubbles] != y0, "las burbujas flotan"
    s.set("background_motion", "reduced")
    pump(qapp, 0.4)
    assert win.backdrop._motion.isActive() and len(win.backdrop._sprites) <= 6
    s.set("background_motion", "static")
    pump(qapp, 0.4)
    assert not win.backdrop._motion.isActive()
    s.set("background_motion", "on")
    pump(qapp, 0.4)
    assert win.backdrop._motion.isActive()
    win.showMinimized()
    pump(qapp, 0.5)
    assert not win.backdrop._motion.isActive(), "minimizada no se anima"
    win.showNormal()
    pump(qapp, 0.3)


def test_settings_have_sections_and_search(controller, qapp):
    win = controller.show_main()
    win.navigate("settings")
    sp = win.page("settings")
    pump(qapp, 0.3)
    titles = [sp.nav.item(i).text() for i in range(sp.nav.count())]
    for t in ("General", "Apariencia", "Temas", "Animaciones y fondos", "Reproducción", "Biblioteca",
              "Archivos y asociaciones", "Conversión", "Compresión", "Editores", "Rendimiento", "Privacidad",
              "Atajos de teclado", "Sistema y almacenamiento", "Acerca de"):
        assert t in titles
    sp.open_category("archive")
    assert sp.stack.currentIndex() == titles.index("Compresión")
    sp.search.setText("bandeja")
    visible = [sp.nav.item(i).text() for i in range(sp.nav.count()) if not sp.nav.item(i).isHidden()]
    assert visible == ["General"] and sp.stack.currentIndex() == 0
    sp.search.setText("animacion")  # sin tilde también encuentra
    assert "Animaciones y fondos" in [sp.nav.item(i).text() for i in range(sp.nav.count())
                                       if not sp.nav.item(i).isHidden()]
    sp.search.clear()
    assert all(not sp.nav.item(i).isHidden() for i in range(sp.nav.count()))


def test_home_widgets_customize_and_persist(controller, qapp):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QDropEvent

    from aero.ui.home_widgets import MIME, HardwareService, WidgetBoard

    win = controller.show_main()
    win.navigate("home")
    home = win.page("home")
    board = home.widgets.board
    pump(qapp, 3.0)
    svc = HardwareService.instance()
    assert svc.static is not None and svc.live is not None, "datos reales del equipo"
    assert svc.static.cpu_model and svc.live.ram_total > 0
    kinds = [c["type"] for c in board.visible_conf()]
    assert kinds[:3] == ["cpu", "gpu", "ram"]
    # Reordenar arrastrando la RAM sobre la CPU
    mime = QMimeData()
    mime.setData(MIME, b"ram")
    target = board.cards["cpu"].geometry().center()
    ev = QDropEvent(QPointF(target), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    board.dropEvent(ev)
    assert [c["type"] for c in board.visible_conf()][:2] == ["ram", "cpu"]
    board.set_size("cpu", "wide")
    board.hide_widget("os")
    board.remove("board")
    board.toggle_field("cpu", "temp")
    assert board.cards["cpu"].width() > board.cards["gpu"].width()
    # Se conserva al volver a abrir
    again = WidgetBoard(controller.settings)
    conf = {c["type"]: c for c in again.layout_conf}
    assert [c["type"] for c in again.visible_conf()][:2] == ["ram", "cpu"]
    assert conf["cpu"]["size"] == "wide" and conf["os"]["hidden"] and "board" not in conf
    assert "temp" not in conf["cpu"]["fields"]
    again.deleteLater()
    board.add("board")
    assert "board" in board.cards
    board.reset()
    assert [c["type"] for c in board.visible_conf()][:3] == ["cpu", "gpu", "ram"]
    # Sin Inicio a la vista no se consulta el hardware
    win.navigate("library")
    pump(qapp, 0.6)
    assert not any(w.isVisible() for w in svc._users)


def test_video_editor_full_flow(controller, qapp, media, tmp_path):
    """Abrir un vídeo → Editar, dos vídeos en la línea de tiempo, una foto encima, un audio independiente,
    mover y recortar clips, posición/opacidad de la foto y exportar un MP4 que se reproduce sin errores."""
    import json
    import shutil
    import subprocess

    from aero.editors.video.window import ExportDialog, VideoEditor

    v1, v2 = tmp_path / "toma1.mkv", tmp_path / "toma2.mkv"
    shutil.copy(media / "clip.mkv", v1)
    shutil.copy(media / "clip.mkv", v2)
    img, mus = tmp_path / "foto.png", tmp_path / "musica.mp3"
    shutil.copy(media / "img.png", img)
    shutil.copy(media / "tono.mp3", mus)
    # 1) Desde el visor: «Editar»
    controller.open_files([str(v1)])
    pump(qapp, 1.0)
    mw = controller.media_windows[-1]
    mw.actions_bar.buttons["edit"].click()
    pump(qapp, 1.5)
    ed = next(w for w in controller.editors if isinstance(w, VideoEditor))
    mw.close()
    p = ed.project
    base = [t for t in p.tracks if t.kind == "video"][-1]
    assert len(base.clips) == 1
    # 2) Segundo vídeo a continuación, en la misma pista
    ed.import_paths([str(v2), str(img), str(mus)])
    ed.add_to_timeline(str(v2))
    assert len(base.clips) == 2 and base.clips[1].start == pytest_approx(base.clips[0].end)
    # 3) Foto encima del vídeo y 4) audio independiente desde el principio
    ed.add_to_timeline(str(img), at=0.5)
    _tr, photo = next((t, c) for t, c in p.all_clips() if c.kind == "image")
    upper = [t for t in p.tracks if t.kind == "video"]
    assert upper.index(_tr) < upper.index(base), "la foto queda en una pista por encima del vídeo"
    ed.add_to_timeline(str(mus), at=0.0)
    _atr, music = next((t, c) for t, c in p.all_clips() if c.kind == "audio")
    assert _atr.kind == "audio" and music.start == 0.0
    # Ajustes de la foto desde el inspector: duración, posición, escala y opacidad
    ed.timeline.selected = {photo.id}
    ed._load_inspector()
    assert ed.sections["frame"].isVisibleTo(ed.inspector) and not ed.sections["audio"].isVisibleTo(ed.inspector)
    ed.f_dur.setValue(1.2)
    ed.f_px.setValue(40)
    ed.f_scale.setValue(40)
    ed.f_opacity.setValue(80)
    assert (photo.duration, photo.pos_x, photo.scale, photo.opacity) == (pytest_approx(1.2), 0.4, 0.4, 0.8)
    # Vista previa: la foto y el vídeo a la vez
    ed.seek(0.8)
    pump(qapp, 0.3)
    assert photo.id in ed.preview.layers and ed.preview.video.isVisible()
    assert ed.preview.layers[photo.id].zValue() > ed.preview.video.zValue()
    # 5) Mover y recortar
    p.move(music.id, 0.3)
    second = base.clips[1]
    p.trim(second.id, "in", second.start + 0.5)
    p.trim(second.id, "out", second.end - 0.3)
    assert music.start == 0.3 and abs(second.duration - 1.2) < 0.1
    ed.undo()
    ed.redo()
    # 6) Exportar y comprobar que se reproduce
    out = tmp_path / "montaje.mp4"
    dlg = ExportDialog(ed)
    dlg.start(str(out))
    end = time.time() + 120
    while not hasattr(dlg, "result_code") and time.time() < end:
        pump(qapp, 0.2)
    assert getattr(dlg, "result_code", None) == 0, dlg.status.text()
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                                      "-show_streams", str(out)], capture_output=True, encoding="utf-8",
                                     errors="replace").stdout)
    kinds = {s["codec_type"] for s in info["streams"]}
    assert kinds == {"video", "audio"}
    assert abs(float(info["format"]["duration"]) - ed.project.duration) < 0.3
    dec = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "null", "-"], capture_output=True,
                         encoding="utf-8", errors="replace")
    assert dec.returncode == 0 and not dec.stderr.strip(), dec.stderr[-500:]
    ed.dirty = False
    ed.close()


def pytest_approx(v):
    import pytest

    return pytest.approx(v, abs=0.05)
