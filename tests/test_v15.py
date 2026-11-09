"""1.5.0: temas espaciales y Frutiger Metro, tutorial de bienvenida e instalador propio."""

import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest


def pump(app, ms):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


# ---------------------------------------------------------------------------------------------- temas
def test_new_themes_render_their_decorations(qapp):
    from aero.ui.glass import render_background
    from aero.ui.theme import PRESETS, theme_from_spec

    for key in ("espacio_negro", "cosmos", "nebulosa", "orbita", "tropical", "tropical_atardecer"):
        assert key in PRESETS
        spec = json.loads(json.dumps(PRESETS[key]))
        img = render_background(theme_from_spec(key, spec), 320, 200, 1.0)
        assert not img.isNull()
    # Espacio Negro: fondo casi negro con estrellas brillantes
    img = render_background(theme_from_spec("espacio_negro", PRESETS["espacio_negro"]), 400, 250, 1.0)
    lum = [img.pixelColor(x, y).lightness() for x in range(0, 400, 4) for y in range(0, 250, 4)]
    assert sorted(lum)[len(lum) // 2] < 30          # la mayoría es negro
    assert max(lum) > 120                            # hay estrellas
    # Las decoraciones nuevas cambian la imagen
    spec = json.loads(json.dumps(PRESETS["tropical"]))
    with_tiles = render_background(theme_from_spec("x", spec), 300, 200, 1.0)
    spec["deco"]["tropical"]["on"] = False
    without = render_background(theme_from_spec("x", spec), 300, 200, 1.0)
    assert with_tiles != without


def test_old_user_theme_without_new_keys_still_loads():
    from aero.ui.theme import DECO_KEYS, normalize_spec

    old = {"name": "Mío", "bg1": "#123456", "deco": {"bubbles": {"on": True, "amount": 0.3, "size": 1.0}}}
    s = normalize_spec(old)
    assert all(k in s["deco"] for k in DECO_KEYS)
    assert s["deco"]["stars"]["on"] is False and s["orb"] == 1.0


def test_theme_studio_lists_new_decorations(qapp):
    from aero.ui.pages.theme_studio import ThemeEditor
    from aero.ui.theme import PRESETS

    ed = ThemeEditor(json.loads(json.dumps(PRESETS["cosmos"])))
    from PySide6.QtWidgets import QCheckBox

    labels = {cb.text() for cb in ed.findChildren(QCheckBox)}
    assert {"Estrellas", "Nebulosa", "Planeta", "Playa y palmeras"} <= labels
    ed.deleteLater()


# ---------------------------------------------------------------------------------------------- tutorial
def test_tutorial_runs_on_first_start_and_can_be_skipped(controller, qapp):
    controller.settings.set("tutorial_done", False)
    win = controller.show_main()
    pump(qapp, 1200)
    tut = win.tutorial
    assert tut is not None and tut.isVisible()
    assert tut.index == 0
    pages = set()
    for _ in range(len(tut.steps) - 1):
        tut.next()
        pump(qapp, 150)
        pages.add(win.current_page())
        assert tut.card.geometry().right() <= win.width() and tut.card.y() >= 0
    assert {"library", "player", "files", "converter", "settings"} <= pages | {"home"}
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(tut, Qt.Key.Key_Escape)
    pump(qapp, 100)
    assert win.tutorial is None
    assert controller.settings.get("tutorial_done") is True
    # Desde Ajustes se puede volver a ver
    win.page("settings").tutorial.emit()
    pump(qapp, 200)
    assert win.tutorial is not None
    win.tutorial.close_tutorial(True)
    pump(qapp, 100)


def test_tutorial_not_shown_when_opening_files(controller, qapp, media):
    controller.settings.set("tutorial_done", False)
    win = controller.show_main([str(media / "img.png")])
    pump(qapp, 1200)
    assert getattr(win, "tutorial", None) is None


def test_tutorial_theme_picker_changes_theme(controller, qapp):
    from aero.ui.glass import tm
    from aero.ui.tutorial import ThemePicker

    picked = []
    p = ThemePicker("burbuja", picked.append)
    p.buttons["nebulosa"].click()
    assert picked == ["nebulosa"]
    controller.settings.set("theme", "nebulosa")
    pump(qapp, 100)
    assert tm().theme.key == "nebulosa"
    controller.settings.set("theme", "burbuja")


# ---------------------------------------------------------------------------------------------- instalador
def _payload(tmp: Path, files: dict[str, bytes], version="9.9.9") -> Path:
    src = tmp / "src"
    for rel, data in files.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(data)
    out = tmp / f"payload-{version}"
    out.mkdir()
    with tarfile.open(out / "payload.tar.xz", "w:xz", preset=0) as tar:
        for rel in files:
            tar.add(src / rel, arcname=rel)
    (out / "manifest.json").write_text(json.dumps({"version": version, "files": [
        {"path": rel, "size": len(d)} for rel, d in files.items()]}))
    import shutil

    shutil.rmtree(src)
    return out


def test_install_upgrade_and_manifest(tmp_path):
    from aero.installer import core

    dest = tmp_path / "AeroPlayer"
    p1 = core.Payload.load(_payload(tmp_path, {"AeroPlayer.exe": b"MZ1", "lib/a.dll": b"a", "lib/old.dll": b"o"},
                                    "1.0.0"))
    steps = []
    core.install(p1, core.Options(target=dest), lambda f, t: steps.append(f), integrate=False)
    assert (dest / "lib" / "old.dll").read_bytes() == b"o"
    assert steps[-1] == 1.0 and steps == sorted(steps)
    (dest / "notas-del-usuario.txt").write_text("mío")
    p2 = core.Payload.load(_payload(tmp_path, {"AeroPlayer.exe": b"MZ2", "lib/a.dll": b"a2", "lib/new.dll": b"n"},
                                    "2.0.0"))
    core.install(p2, core.Options(target=dest), lambda f, t: None, integrate=False)
    assert (dest / "AeroPlayer.exe").read_bytes() == b"MZ2"
    assert not (dest / "lib" / "old.dll").exists()          # restos de la versión anterior fuera
    assert (dest / "notas-del-usuario.txt").exists()        # lo que no es nuestro no se toca
    m = json.loads((dest / core.MANIFEST).read_text())
    assert m["version"] == "2.0.0" and sorted(m["files"]) == ["AeroPlayer.exe", "lib/a.dll", "lib/new.dll"]
    core.remove_files(dest, core.read_manifest(dest))
    assert not (dest / "lib").exists() and (dest / "notas-del-usuario.txt").exists()


def test_install_never_writes_outside_target(tmp_path):
    from aero.installer import core

    src = tmp_path / "evil.txt"
    src.write_bytes(b"x")
    out = tmp_path / "pl"
    out.mkdir()
    with tarfile.open(out / "payload.tar.xz", "w:xz", preset=0) as tar:
        tar.add(src, arcname="../../fuera.txt")
        tar.add(src, arcname="dentro.txt")
    (out / "manifest.json").write_text(json.dumps({"version": "1", "files": [{"path": "dentro.txt", "size": 1}]}))
    dest = tmp_path / "a" / "b" / "AeroPlayer"
    core.extract(core.Payload.load(out), dest, lambda f, t: None)
    assert (dest / "dentro.txt").exists()
    assert not (tmp_path / "a" / "fuera.txt").exists()


def test_safe_target_uses_subfolder_for_busy_folders(tmp_path):
    from aero.installer import core

    busy = tmp_path / "Documentos"
    busy.mkdir()
    (busy / "algo.txt").write_text("x")
    assert core.safe_target(busy) == busy / "AeroPlayer"
    empty = tmp_path / "Vacia"
    empty.mkdir()
    assert core.safe_target(empty) == empty
    assert core.safe_target(tmp_path / "AeroPlayer") == tmp_path / "AeroPlayer"


def test_initial_theme_is_merged_into_settings(tmp_path, monkeypatch):
    from aero.installer import core

    monkeypatch.setenv("AERO_DATA_DIR", str(tmp_path / "d"))
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "settings.json").write_text(json.dumps({"volume": 0.3, "theme": "aero"}))
    assert core.current_theme() == "aero"
    core.set_initial_theme("cosmos")
    data = json.loads((tmp_path / "d" / "settings.json").read_text())
    assert data == {"volume": 0.3, "theme": "cosmos"}


@pytest.mark.skipif(sys.platform != "win32", reason="solo Windows")
def test_scheduled_removal_deletes_only_installed_files(tmp_path):
    from aero.installer import core

    dest = tmp_path / "AeroPlayer"
    (dest / "sub").mkdir(parents=True)
    for rel in ("AeroPlayer.exe", "sub/x.dll"):
        (dest / rel).write_bytes(b"1")
    (dest / "ajeno.txt").write_text("no borrar")
    (dest / core.MANIFEST).write_text(json.dumps({"files": ["AeroPlayer.exe", "sub/x.dll"]}))
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    core.schedule_removal(dest, done.pid)
    for _ in range(150):
        if not (dest / "AeroPlayer.exe").exists() and not (dest / "sub").exists():
            break
        time.sleep(0.2)
    assert not (dest / "AeroPlayer.exe").exists() and not (dest / "sub").exists()
    assert (dest / "ajeno.txt").read_text() == "no borrar"


def test_installer_window_pages(qapp, tmp_path, monkeypatch):
    from aero.installer import core, ui

    pl = _payload(tmp_path, {"AeroPlayer.exe": b"MZ", "x.dll": b"x" * 1000}, "1.5.0")
    monkeypatch.setattr(core, "find_existing", lambda: None)
    dest = tmp_path / "dest"
    real = core.install
    monkeypatch.setattr(core, "install", lambda payload, opts, progress, cancelled=lambda: False, integrate=True:
                        real(payload, core.Options(target=dest), progress, cancelled, integrate=False))
    w = ui.InstallerWindow(pl)
    w.show()
    pump(qapp, 200)
    assert w.install_btn.isEnabled() and w.install_btn.text() == "Instalar"
    w.start_install()
    for _ in range(200):
        pump(qapp, 30)
        if w.installed is not None:
            break
    assert w.installed == dest and (dest / "AeroPlayer.exe").exists()
    assert w.stack.currentIndex() == 3
    w.cb_launch.setChecked(False)
    w._finish()
    pump(qapp, 100)


@pytest.mark.skipif(sys.platform != "win32", reason="solo Windows (instalador, registro o DWM)")
def test_installer_without_payload_explains_problem(qapp):
    from aero.installer import ui

    w = ui.InstallerWindow(None)
    assert not w.install_btn.isEnabled()
    assert "No se puede instalar" in w.where.text()
    w.deleteLater()


def test_sheet_sort_mixed_types(qapp, tmp_path, controller):
    """Ordenar una columna con números, fechas, horas, texto y vacíos no falla (lo encontró stress_check)."""
    import datetime as dt

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Valor"])
    for v in (dt.datetime(2024, 5, 1, 10, 0), 7, "texto", dt.date(2023, 1, 2), None, 2.5, dt.time(8, 30), "Abc"):
        ws.append([v])
    src = tmp_path / "mezcla.xlsx"
    wb.save(src)
    ed = controller.open_sheet_editor(str(src))
    m = ed.model
    ed.view.setCurrentIndex(m.index(0, 0))
    ed.sort_column(False)
    ed.sort_column(True)
    ed.undo()
    ed.undo()
    ed.dirty = False
    ed.close()
