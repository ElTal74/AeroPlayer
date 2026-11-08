"""1.4: menú contextual del Explorador, acciones agrupadas, ventanas de extraer/comprimir y conversión rápida."""

import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _wait(qapp, cond, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


# ----------------------------------------------------------------------------- registro del menú
@pytest.mark.skipif(os.name != "nt", reason="solo Windows")
def test_context_menu_register_in_isolated_branch():
    from aero.core import associations as a
    from aero.core import shellmenu as m

    base = r"Software\AeroPlayerTests\Menu"
    reg = a.Registry(base)
    try:
        m.sync(True, reg, refresh_only=True)
        assert not m.is_present(reg), "al arrancar no se crea si el usuario no lo pidió"
        m.register(reg)
        assert m.is_registered(reg)
        assert reg.get(m.ROOT_FILES, "MUIVerb") == "AERO Player"
        assert reg.get(m.ROOT_FILES, "SubCommands") == ""
        assert reg.get(m.ROOT_DIRS, "MUIVerb") == "AERO Player"
        here = rf"{m.ROOT_FILES}\shell\10extract_here"
        assert ".rar" in reg.get(here, "AppliesTo") and ".7z" in reg.get(here, "AppliesTo")
        assert ".mp3" not in reg.get(here, "AppliesTo"), "extraer solo en comprimidos"
        assert reg.get(rf"{m.ROOT_FILES}\shell\20compress_zip", "AppliesTo") is None, "comprimir en todo"
        assert ".png" in reg.get(rf"{m.ROOT_FILES}\shell\30convert", "AppliesTo")
        cmd = reg.get(rf"{here}\command")
        assert '--action extract_here "%1"' in cmd
        assert reg.get(rf"{m.ROOT_DIRS}\shell\22compress\command").endswith('--action compress "%1"')
        assert int(reg.get(rf"{m.ROOT_FILES}\shell\20compress_zip", "CommandFlags")) == m.SEPARATOR_BEFORE
        # Ruta del programa cambiada: al arrancar se actualiza
        reg.set(rf"{here}\command", None, "viejo")
        m.sync(True, reg, refresh_only=True)
        assert m.is_registered(reg)
        m.sync(False, reg)
        assert not m.is_present(reg) and reg.get(m.ROOT_DIRS, "MUIVerb") is None
        assert all(a in m.ACTIONS for a in ("extract_here", "extract_to", "compress", "convert", "compress_7z"))
    finally:
        reg.delete_tree("")
        a.Registry(r"Software\AeroPlayerTests").delete_tree("")


def test_applies_to_syntax():
    from aero.core import shellmenu as m

    s = m.applies_to({".zip", ".7z"})
    assert s == "System.FileExtension:=.7z OR System.FileExtension:=.zip"


# ----------------------------------------------------------------------------- acciones del controlador
def test_actions_are_grouped(controller, qapp, tmp_path):
    calls = []
    controller._do_action = lambda a, p: calls.append((a, list(p)))
    files = []
    for i in range(3):
        f = tmp_path / f"f{i}.txt"
        f.write_text("x")
        files.append(str(f))
        controller.run_action("compress_zip", [str(f)])
    controller.run_action("compress_zip", [files[0]])  # repetido: no se duplica
    controller.run_action("extract_here", [str(tmp_path / "no-existe.zip")])
    assert _wait(qapp, lambda: calls, 5)
    assert calls == [("compress_zip", files)]


def test_compress_and_extract_actions(controller, qapp, tmp_path, monkeypatch):
    from aero.archive import ui

    monkeypatch.setattr(ui, "AUTO_CLOSE_S", 1)
    src = tmp_path / "Carpeta ñ"
    src.mkdir()
    for n in ("a.txt", "b 😀.txt"):
        (src / n).write_text(n * 100, encoding="utf-8")
    controller._do_action("compress_7z", [str(src)])
    out = tmp_path / "Carpeta ñ.7z"
    assert _wait(qapp, lambda: out.exists() and not any(isinstance(w, ui.ProgressWindow) for w in controller.editors))
    controller._do_action("extract_folder", [str(out)])
    dest = tmp_path / "Carpeta ñ (2)"  # la carpeta original existe y no está vacía: no se mezcla
    assert _wait(qapp, lambda: (dest / "Carpeta ñ" / "b 😀.txt").exists())
    assert _wait(qapp, lambda: not controller.editors), "las ventanas de progreso se cierran solas al terminar bien"


def test_extract_asks_password_and_retries(controller, qapp, tmp_path, monkeypatch):
    from aero.archive import ops, ui

    src = tmp_path / "s.txt"
    src.write_text("secreto", encoding="utf-8")
    z = tmp_path / "c.zip"
    ops.compress([str(src)], str(z), "zip", 5, "clave")
    asked = []

    def fake(*a, **k):
        asked.append(1)
        return ("clave", True)

    monkeypatch.setattr(ui.QInputDialog, "getText", fake)
    ui.run_extract(controller, str(z), str(tmp_path / "out"))
    assert _wait(qapp, lambda: (tmp_path / "out" / "s.txt").exists())
    assert asked == [1]
    for w in list(controller.editors):
        w.close()


def test_progress_window_cancel(controller, qapp, tmp_path):
    from aero.archive import ui

    src = tmp_path / "grande"
    src.mkdir()
    for i in range(300):
        (src / f"{i}.bin").write_bytes(os.urandom(20000))
    w = ui.run_compress(controller, [str(src)], str(tmp_path / "g.zip"), "zip", 9)
    w.cancel()
    assert _wait(qapp, lambda: w.ok is not None)
    assert w.ok is False and not (tmp_path / "g.zip").exists()
    w.close()


def test_archive_manager_and_add(controller, qapp, tmp_path):
    from aero.archive import ui

    z = tmp_path / "m.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("uno.txt", "1")
    w = ui.open_manager(str(z), controller)
    assert _wait(qapp, lambda: w.browser.archive is not None and w.browser.entries)
    extra = tmp_path / "dos.txt"
    extra.write_text("2")
    w.add_files([str(extra)])
    with zipfile.ZipFile(z) as f:
        assert set(f.namelist()) == {"uno.txt", "dos.txt"}
    assert not Path(str(z) + ".bak").exists()
    rar = tmp_path / "x.tar.gz"
    rar.write_bytes(b"")
    with pytest.raises(ui.ArchiveError):
        ui.add_to_archive(str(rar), [str(extra)])
    w.close()


def test_dialogs_build(qapp, tmp_path):
    from aero.archive import ui

    f = tmp_path / "foto.png"
    f.write_bytes(b"x")
    d = ui.CompressDialog([str(f)])
    d.format.setCurrentIndex(d.format.findData("7z"))
    assert d.output().endswith("foto.7z")
    d.format.setCurrentIndex(d.format.findData("tar.gz"))
    assert d.output().endswith("foto.tar.gz") and not d.password.isEnabled()
    e = ui.ExtractDialog(str(tmp_path / "a.tar.gz"))
    assert e.dest.text().endswith("a")


def test_quick_convert(controller, qapp, media, tmp_path):
    from aero.ui.quick_convert import QuickConvert, common_targets

    keys = [k for k, _ in common_targets([str(media / "img.png")])]
    assert "jpg" in keys or "webp" in keys
    assert common_targets([str(media / "img.png"), str(media / "tono.mp3")]) == []
    w = QuickConvert([str(media / "img.png")], controller)
    w.folder.setText(str(tmp_path))
    w.target.setCurrentIndex(max(0, w.target.findData("jpg")))
    target = w.target.currentData()
    w.start()
    assert _wait(qapp, lambda: not w.cm.busy() and w.ids, 60)
    assert list(tmp_path.glob(f"img*.{target}")), list(tmp_path.iterdir())
    w2 = QuickConvert([str(media / "img.png"), str(media / "tono.mp3")], controller)
    assert not w2.go.isEnabled()
    w.close()
    w2.close()


# ----------------------------------------------------------------------------- de punta a punta
@pytest.mark.skipif(os.name != "nt", reason="solo Windows")
def test_explorer_multiselect_one_archive(tmp_path):
    """El Explorador lanza un proceso por archivo seleccionado: deben acabar en UN solo ZIP."""
    files = []
    for i in range(3):
        f = tmp_path / f"doc{i}.txt"
        f.write_text(f"texto {i}", encoding="utf-8")
        files.append(f)
    env = dict(os.environ, AERO_DATA_DIR=str(tmp_path / "data"), AERO_INSTANCE=f"-test{os.getpid()}")
    procs = [subprocess.Popen([sys.executable, "-m", "aero", "--action", "compress_zip", str(f)], cwd=ROOT, env=env)
             for f in files]
    try:
        for p in procs:
            p.wait(timeout=90)
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
    zips = list(tmp_path.glob("*.zip"))
    assert len(zips) == 1, zips
    with zipfile.ZipFile(zips[0]) as z:
        assert sorted(z.namelist()) == ["doc0.txt", "doc1.txt", "doc2.txt"]


def test_home_create_menu(controller, qapp, monkeypatch, tmp_path):
    from aero.ui import main_window as mw

    win = controller.show_main()
    home = win.page("home")
    win.resize(860, 560)
    qapp.processEvents()
    assert win.width() <= 900, "seis baldosas no ensanchan la ventana mínima"
    assert [k for k in (i[2] for i in home.CREATE_MENU if i)] == [
        "paint", "new_document", "new_sheet", "new_slides", "new_video", "edit_image", "pdf_convert", "compress", "open_archive"]
    before = len(controller.editors)
    for key in ("new_document", "new_sheet", "new_slides", "new_video"):
        home.tool.emit(key)
        qapp.processEvents()
    assert len(controller.editors) == before + 4
    called = []
    controller.run_action = lambda a, p: called.append((a, p))
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileNames", lambda *a, **k: ([str(tmp_path)], ""))
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileName", lambda *a, **k: (str(tmp_path / "x.zip"), ""))
    home.tool.emit("compress")
    home.tool.emit("open_archive")
    assert called == [("compress", [str(tmp_path)]), ("open_archive", [str(tmp_path / "x.zip")])]
    for e in list(controller.editors):
        for attr in ("dirty",):
            if hasattr(e, attr):
                setattr(e, attr, False)
        e.close()


def test_files_browser_context_menu(qapp, tmp_path):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    from aero.files.browser import ENTRY_ROLE, FolderBrowser

    (tmp_path / "foto.png").write_bytes(b"x")
    with zipfile.ZipFile(tmp_path / "c.zip", "w") as z:
        z.writestr("dentro.txt", "1")
    from PySide6.QtCore import QTimer

    shown = []

    def grab_menu():
        pop = qapp.activePopupWidget()
        if isinstance(pop, QMenu):
            shown.append([x.text() for x in pop.actions() if x.text()])
            pop.close()
        else:
            QTimer.singleShot(50, grab_menu)

    def menu_at(pos):
        QTimer.singleShot(50, grab_menu)
        b._context_menu(pos)

    b = FolderBrowser()
    b.resize(600, 400)
    b.set_root(str(tmp_path))
    assert _wait(qapp, lambda: b.model.rowCount() == 2)
    got = []
    b.action_requested.connect(lambda a, p: got.append((a, p)))
    for name in ("c.zip", "foto.png"):
        b.view.clearSelection()
        idx = next(b.model.index(i) for i in range(2) if b.model.index(i).data(ENTRY_ROLE).name == name)
        b.view.setCurrentIndex(idx)
        menu_at(b.view.visualRect(idx).center())
    assert "Extraer aquí" in shown[0] and "Convertir…" not in shown[0]
    assert "Convertir…" in shown[1] and "Editar" in shown[1] and "Extraer aquí" not in shown[1]
    b.set_root(str(tmp_path / "c.zip"))
    assert _wait(qapp, lambda: b.archive is not None and b.model.rowCount() == 1)
    b.view.setCurrentIndex(b.model.index(0))
    menu_at(b.view.visualRect(b.model.index(0)).center())
    assert shown[-1] == ["Abrir", "Extraer los seleccionados en…"]
    b._context_menu(QPoint(-5, -5))
    b.cleanup()
