"""2.0: perfiles que se aplican, Paint en la barra lateral, explorador con iconos y programas, manipulación directa
en el editor de vídeo, traducción completa con inglés por defecto y memoria."""

import gc
import os
import subprocess
import time
import weakref
from pathlib import Path

import pytest


def pump(app, s=0.2):
    end = time.time() + s
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_for(app, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


# ----------------------------------------------------------------------------- perfiles de rendimiento

def test_first_run_applies_recommended_profile(qapp, monkeypatch):
    """Antes el perfil recomendado se guardaba pero no se aplicaba hasta el siguiente arranque."""
    from aero.core import hardware
    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.ui.controller import AppController
    from aero.ui.glass import tm
    from aero.ui.main_window import apply_theme

    monkeypatch.setattr(hardware, "recommend", lambda hw: ("high", "x"))
    s = Settings()
    s.set("tutorial_done", True)
    s.set("quicklook_enabled", False)
    s.set("language", "es-ES")
    s.set("quality_profile", "")
    apply_theme(qapp, s)            # como al arrancar: perfil vacío = Equilibrado (20 fps)
    AppController(qapp, s, Database())
    assert s.get("quality_profile") == "high" and tm().quality["fps"] == 30


def test_profiles_create_edit_duplicate_rename_delete_and_persist(qapp, controller, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from aero.core import quality
    from aero.core.config import Settings
    from aero.ui.glass import tm
    from aero.ui.pages.perf_settings import PerformanceSettings

    assert set(quality.PROFILE_NAMES) == {"ultra", "balanced", "performance", "high", "custom"}
    s = controller.settings
    ps = PerformanceSettings(s)
    names = iter(["Lento", "Lento (copia)", "Rápido"])
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (next(names), True)))
    ps._choose("balanced")
    ps.spins["fps"].setValue(8)
    assert s.get("quality_profile") == "custom" and tm().quality["fps"] == 8
    ps._save_as()
    assert s.get("quality_profile") == "user:Lento" and "Lento" in ps.active.text()
    ps._duplicate()
    assert s.get("quality_profile") == "user:Lento (copia)"
    ps.spins["fps"].setValue(12)                    # editar la copia no cambia el original
    assert s.get("quality_user")["Lento"]["fps"] == 8 and s.get("quality_user")["Lento (copia)"]["fps"] == 12
    ps._rename()
    assert "Rápido" in s.get("quality_user") and "Lento (copia)" not in s.get("quality_user")
    ps._choose("user:Lento")
    assert tm().quality["fps"] == 8 and not any(b.isChecked() for b in ps.buttons.values())
    ps._choose("performance")
    assert tm().quality["fps"] == 30 and ps.buttons["performance"].isChecked()
    from aero.core.tasks import tasks

    assert tasks().limits["background"] == quality.PROFILES["performance"]["background"]
    ps._choose("user:Rápido")
    ps._delete()
    assert "Rápido" not in s.get("quality_user") and s.get("quality_profile") == "custom"
    assert quality.resolve(s)["fps"] == 12          # lo borrado se sigue viendo igual, ahora como Personalizado
    s.save_now()
    again = Settings()
    assert again.get("quality_profile") == "custom" and "Lento" in again.get("quality_user")
    ps.deleteLater()


def test_profile_controls_thumbnails_and_proxies(qapp, controller):
    from aero.files.browser import ThumbCache
    from aero.ui.glass import tm

    controller.settings.set("quality_profile", "ultra")
    assert ThumbCache.limits() == (96, 120, 1)
    w = controller.open_video_editor()
    pump(qapp, 0.2)
    assert w.use_proxies and w.proxy_box.isChecked() and tm().quality["proxies"]
    w.dirty = False
    w.close()
    controller.settings.set("quality_profile", "high")
    assert ThumbCache.limits() == (256, 600, 3)


# ----------------------------------------------------------------------------- Paint y decoraciones

def test_paint_in_sidebar_and_as_window(qapp, controller):
    from aero.editors.paint.window import PaintEditor, PaintWindow
    from aero.ui.main_window import PAGE_KEYS

    assert "paint" in PAGE_KEYS
    win = controller.show_main()
    win.navigate("paint")
    pump(qapp, 0.3)
    page = win.pages["paint"]
    assert isinstance(page, PaintEditor) and win.current_page() == "paint" and page.embedded
    win.navigate("files")
    win.navigate("paint")
    assert win.pages["paint"] is page, "se conserva el dibujo al volver"
    w = controller.open_paint("")
    assert isinstance(w, PaintWindow) and isinstance(w.editor, PaintEditor) and w.doc is w.editor.doc
    w.close()
    pump(qapp, 0.2)


def test_no_seasonal_decorations(qapp, controller):
    import datetime as dt

    from aero.ui.pages import home_page

    assert not hasattr(home_page, "SeasonArt")
    win = controller.show_main()
    home = win.page("home")
    home.refresh(dt.datetime(2026, 12, 25, 10, 0))
    assert "Navidad" not in home.greet.text() and "Christmas" not in home.greet.text()


# ----------------------------------------------------------------------------- explorador

def _shortcut(path: Path, target: str):
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{path}'); $s.TargetPath='{target}'; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows")
def test_explorer_icons_shortcuts_and_safe_run(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from aero.files import shell
    from aero.files.browser import FolderBrowser

    exe = tmp_path / "Programa de prueba.exe"
    exe.write_bytes(Path(r"C:\Windows\System32\where.exe").read_bytes())
    bat = tmp_path / "script ñ.bat"
    bat.write_text("@echo hola", encoding="ascii")
    with open(str(bat) + ":Zone.Identifier", "w", encoding="ascii") as fh:
        fh.write("[ZoneTransfer]\nZoneId=3\n")
    sub = tmp_path / "Carpeta con espacios"
    sub.mkdir()
    _shortcut(tmp_path / "a carpeta.lnk", str(sub))
    _shortcut(tmp_path / "a programa.lnk", str(exe))
    assert shell.resolve_shortcut(str(tmp_path / "a carpeta.lnk")).is_dir
    assert shell.resolve_shortcut(str(tmp_path / "a programa.lnk")).runnable
    assert shell.from_internet(str(bat)) and not shell.from_internet(str(exe))
    assert shell.type_name(str(exe)) == "Aplicación · EXE" and shell.type_name(str(bat)) == "Script · BAT"
    b = FolderBrowser()
    b.resize(800, 500)
    b.show()
    b.set_root(str(tmp_path))
    assert wait_for(qapp, lambda: len(b.model.rows) == 5)
    assert wait_for(qapp, lambda: not b.shell_icons.queue)
    assert all(v is not None for v in b.shell_icons.icons.values()), "iconos reales de Windows"
    asked, launched = [], []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: asked.append(self.informativeText()) or 0)
    monkeypatch.setattr(shell, "run", lambda p, admin=False: launched.append(p))
    b.open_entry(str(exe))
    b.open_entry(str(bat))
    b.open_entry(str(tmp_path / "a programa.lnk"))
    assert len(asked) == 3 and launched == [], "nada se ejecuta sin confirmar"
    assert "Internet" in asked[1]
    b.open_entry(str(tmp_path / "a carpeta.lnk"))
    assert b.cwd == str(sub)
    b.deleteLater()


# ----------------------------------------------------------------------------- editor de vídeo

def _red_png(path: Path, w=200, h=100):
    from PySide6.QtGui import QColor, QImage

    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#ff0000"))
    img.save(str(path))


def _red_box(png: Path):
    from PySide6.QtGui import QImage

    fr = QImage(str(png))
    xs, ys = [], []
    for y in range(0, fr.height(), 2):
        for x in range(0, fr.width(), 2):
            c = fr.pixelColor(x, y)
            if c.red() > 150 and c.green() < 90:
                xs.append(x)
                ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def test_viewer_direct_manipulation_matches_export(qapp, tmp_path):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest

    from aero.editors.video import export as vexport
    from aero.editors.video import geometry
    from aero.editors.video.window import VideoEditor

    src = tmp_path / "rojo.png"
    _red_png(src)
    ed = VideoEditor()
    ed.resize(1300, 860)
    ed.show()
    pump(qapp, 0.4)
    ed.project.width, ed.project.height = 640, 360
    ed.preview.resize_scene()
    ed.import_paths([str(src)], add=True)
    pump(qapp, 0.3)
    c = next(c for _t, c in ed.project.all_clips())
    ed.seek(1.0)
    pump(qapp, 0.2)
    vp = ed.preview.viewport()
    center = ed.preview.mapFromScene(QPointF(320, 180))
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    pump(qapp, 0.1)
    assert ed.selected_clip() is c, "un clic en el visor selecciona el clip"
    k = ed.preview.scale_k()
    n_undo = len(ed._undo)
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    for i in range(1, 6):
        QTest.mouseMove(vp, center + QPoint(int(20 * k * i), int(10 * k * i)))
        pump(qapp, 0.02)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       center + QPoint(int(100 * k), int(50 * k)))
    pump(qapp, 0.1)
    assert abs(c.pos_x - 100 / 320) < 0.02 and abs(c.pos_y - 50 / 180) < 0.02
    assert len(ed._undo) == n_undo + 1 and abs(ed.f_px.value() - c.pos_x * 100) < 0.2
    # Escala, estiramiento, anclaje, recorte y giro con valores exactos
    ed.f_scale.setValue(30)
    ed.f_sx.setValue(150)
    ed.f_ax.setValue(50)
    ed.f_angle.setValue(30)
    c.crop = [0.1, 0.0, 0.0, 0.2]
    ed._show_frame()
    pump(qapp, 0.1)
    pl = ed.preview.placed[c.id][2]
    poly = geometry.corners(pl)
    view_box = (min(poly[i].x() for i in range(4)), min(poly[i].y() for i in range(4)),
                max(poly[i].x() for i in range(4)), max(poly[i].y() for i in range(4)))
    out = tmp_path / "f.png"
    args, _t, temps = vexport.build_command(ed.project, str(out), start=1.0, end=2.0, still=True)
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]
    got = _red_box(out)
    assert all(abs(a - b) <= 4 for a, b in zip(got, view_box)), (got, view_box)
    # Guardar y volver a abrir conserva la transformación
    proj = tmp_path / "p.aerovideo"
    ed.project.save(str(proj))
    from aero.editors.video.project import Project

    c2 = next(x for _t, x in Project.load(str(proj)).all_clips())
    assert (c2.sx, c2.anchor_x, c2.angle, c2.src_w) == (c.sx, c.anchor_x, c.angle, 200)
    # Pista bloqueada: ni se mueve ni muestra tiradores
    trk, _c = ed.project.find(c.id)
    trk.locked = True
    before = c.pos_x
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     ed.preview.mapFromScene(pl.center))
    QTest.mouseMove(vp, ed.preview.mapFromScene(pl.center) + QPoint(60, 0))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       ed.preview.mapFromScene(pl.center) + QPoint(60, 0))
    assert c.pos_x == before
    ed.project.move(c.id, 3.0)
    assert c.start == 0.0, "una pista bloqueada no deja mover clips en la línea de tiempo"
    ed.dirty = False
    ed.close()


def test_titles_are_transformable_in_export(qapp, tmp_path):
    from aero.editors.video import export as vexport
    from aero.editors.video import geometry
    from aero.editors.video.project import Clip, Project, Track
    from aero.editors.video.titles import render_title

    t = Clip(kind="text", text="AERO", text_color="#ff0000", text_size=60, out_s=3.0, pos_x=0.5, pos_y=-0.4,
             angle=20.0, scale=1.5)
    p = Project(640, 360, 30.0, [Track("video", "V1", clips=[t]), Track("audio", "A1")])
    img = render_title(t)
    pl = geometry.place(640, 360, img.width(), img.height(), t)
    poly = geometry.corners(pl)
    out = tmp_path / "t.png"
    args, _tot, temps = vexport.build_command(p, str(out), start=1.0, end=2.0, still=True)
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]
    x0, y0, x1, y1 = _red_box(out)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    assert abs(cx - pl.center.x()) < 12 and abs(cy - pl.center.y()) < 12, ((cx, cy), pl.center)
    assert x1 <= max(poly[i].x() for i in range(4)) + 4
    for f in temps:
        os.unlink(f)


# ----------------------------------------------------------------------------- idiomas

def test_english_is_default_language():
    from aero import i18n

    assert i18n.DEFAULT_LANGUAGE == "en"
    src = (Path(__file__).resolve().parents[1] / "aero" / "app.py").read_text(encoding="utf-8")
    assert "or DEFAULT_LANGUAGE" in src and "system_language()" not in src


def test_all_code_keys_translated_in_every_language():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import i18n_keys

    keys = i18n_keys.collect()
    from aero.i18n import catalog

    for code in i18n_keys.FULL:
        cat = catalog(code)
        missing = [k for k in keys if k not in cat]
        assert not missing, (code, missing[:10])


def test_translation_safety_net_on_widgets(qapp):
    from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget

    from aero.i18n import set_language
    from aero.i18n.widgets import translate_tree

    w = QWidget()
    lay = QVBoxLayout(w)
    b = QPushButton("Guardar proyecto")
    b.setToolTip("Canciones guardadas")
    lb = QLabel("rojo.png")             # dato del usuario: no es una clave, no se toca
    cb = QComboBox()
    cb.addItems(["Ninguna", "Fundido a negro"])
    for x in (b, lb, cb):
        lay.addWidget(x)
    try:
        set_language("de")
        assert translate_tree(w) >= 4
        assert b.text() == "Projekt speichern" and b.toolTip() == "Gespeicherte Titel"
        assert lb.text() == "rojo.png" and cb.itemText(0) == "Keine"
        assert translate_tree(w) == 0, "idempotente"
    finally:
        set_language("es-ES")
    w.deleteLater()


# ----------------------------------------------------------------------------- memoria

def test_closed_editors_release_memory(qapp, controller, tmp_path):
    from PySide6.QtGui import QColor, QImage

    img = QImage(1200, 800, QImage.Format.Format_RGB32)
    img.fill(QColor("#335577"))
    png = tmp_path / "f.png"
    img.save(str(png))
    ed = controller.open_image_editor(str(png))
    assert wait_for(qapp, lambda e=ed: e.doc is not None)
    ref = weakref.ref(ed.doc)
    ed.doc.dirty = False
    ed.close()
    del ed
    pump(qapp, 0.5)
    gc.collect()
    pump(qapp, 0.2)
    gc.collect()
    assert ref() is None, "el editor cerrado no deja su imagen en memoria"


def test_finished_tasks_drop_their_callbacks(qapp):
    from aero.core.tasks import tasks

    class Big:
        pass

    big = Big()
    ref = weakref.ref(big)
    t = tasks().submit(lambda: 1, "interactive", lambda _r, b=big: None)
    del big
    assert wait_for(qapp, lambda: t.fn is None)
    gc.collect()
    assert ref() is None and t.on_done is None
