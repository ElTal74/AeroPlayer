"""2.2: desarrollo sin interferir (escritorio aparte), iconos AERO en el Explorador de Windows, fotos en la ventana
principal, categoría de instaladores y NumPy fuera del arranque."""

import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def wait_for(app, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if app is not None:
            app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


# ----------------------------------------------------------------------------- tareas sin interferir

@pytest.mark.skipif(os.name != "nt", reason="escritorio de Windows")
def test_devrun_runs_hidden_logs_and_stops(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import devrun

    monkeypatch.setattr(devrun, "DIR", tmp_path / ".devrun")
    monkeypatch.setenv("AERO_DEVRUN_DIR", str(tmp_path / ".devrun"))     # también para el vigilante
    code = "import ctypes,sys;h=ctypes.windll.user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId());" \
           "b=ctypes.create_unicode_buffer(64);ctypes.windll.user32.GetUserObjectInformationW(h,2,b,128,None);" \
           "print('escritorio', b.value)"
    assert devrun.run("ok", [PY, "-c", code]) == 0
    end = time.time() + 30
    while time.time() < end and devrun._read("ok").get("state") == "running":
        time.sleep(0.2)
    d = devrun._read("ok")
    log = (tmp_path / ".devrun" / "ok.log").read_text(encoding="utf-8", errors="replace")
    assert d["state"] == "done" and d["exit"] == 0, log
    assert "escritorio AeroDev" in (tmp_path / ".devrun" / "ok.log").read_text(encoding="utf-8")   # no es el tuyo
    assert devrun.run("larga", [PY, "-c", "import time; time.sleep(120)"]) == 0
    pid = devrun._read("larga")["pid"]
    assert devrun._alive(pid)
    assert devrun.stop("larga") == 0
    assert wait_for(None, lambda: not devrun._alive(pid), 10)
    assert devrun._read("larga")["state"] == "stopped"
    assert {d["name"] for d in devrun.status()} == {"ok", "larga"}


# ----------------------------------------------------------------------------- iconos .ico

def test_ico_files_have_all_sizes(qapp, tmp_path):
    from aero.ui import icon_export
    from aero.ui.file_icons import PALETTE

    files = icon_export.export(tmp_path)
    assert set(files) == set(PALETTE) and "installer" in files
    data = files["video"].read_bytes()
    _r, kind, n = struct.unpack("<HHH", data[:6])
    assert kind == 1 and n == len(icon_export.SIZES)
    sizes = []
    for i in range(n):
        w, _h, _c, _x, _p, _b, ln, off = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        sizes.append(w or 256)
        assert data[off:off + 8] == b"\x89PNG\r\n\x1a\n" and off + ln <= len(data)
    assert sizes == list(icon_export.SIZES)
    assert files["video"].read_bytes() != files["audio"].read_bytes()
    mtime = files["video"].stat().st_mtime_ns
    icon_export.export(tmp_path)                          # sin cambios no se reescribe
    assert files["video"].stat().st_mtime_ns == mtime
    for cat in PALETTE:                                    # los del paquete existen y están al día
        assert (icon_export.icons_dir() / f"{cat}.ico").read_bytes() == icon_export.ico_bytes(cat), cat


def test_installer_category():
    from aero.core import filetypes as ft

    for ext in (".msi", ".msix", ".appx", ".msixbundle"):
        assert ft.by_extension("x" + ext) == "installer"
    assert ft.by_extension("x.exe") == "app"


# ----------------------------------------------------------------------------- asociaciones con iconos

@pytest.fixture()
def branch():
    from aero.core import associations as a

    reg = a.Registry(r"Software\AeroPlayerTests22")
    reg.delete_tree("")
    yield reg
    reg.delete_tree("")


@pytest.mark.skipif(os.name != "nt", reason="registro de Windows")
def test_register_gives_each_progid_its_category_icon(qapp, branch):
    from aero.core import associations as a
    from aero.ui.icon_export import icon_path

    a.register(branch)
    for progid, cat in (("AeroPlayer.Video", "video"), ("AeroPlayer.Audio", "audio"), ("AeroPlayer.Image", "image"),
                        ("AeroPlayer.Pdf", "pdf"), ("AeroPlayer.Archive", "archive"), ("AeroPlayer.Disc", "disc"),
                        ("AeroPlayer.Torrent", "torrent"), ("AeroPlayer.Document", "document")):
        assert branch.get(rf"{a.CLASSES}\{progid}\DefaultIcon") == f'"{icon_path(cat)}",0', progid
    assert branch.get(rf"{a.CLASSES}\.iso\OpenWithProgids", "AeroPlayer.Disc") == ""
    assert branch.get(rf"{a.CLASSES}\.iso\OpenWithProgids", "AeroPlayer.Archive") is None
    assert branch.get(rf"{a.CLASSES}\.torrent\OpenWithProgids", "AeroPlayer.Torrent") == ""
    assert branch.get(rf"{a.CLASSES}\.mp4") is None                 # nunca se adueña de la extensión
    assert not any("UserChoice" in k for k in _all_keys(branch))
    a.unregister(branch)
    assert branch.get(rf"{a.CLASSES}\AeroPlayer.Video\DefaultIcon") is None


def _all_keys(reg, sub=""):
    import winreg

    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg._k(sub) if sub else reg.base) as k:
            i = 0
            while True:
                try:
                    child = winreg.EnumKey(k, i)
                except OSError:
                    break
                path = f"{sub}\\{child}" if sub else child
                out.append(path)
                out.extend(_all_keys(reg, path))
                i += 1
    except OSError:
        pass
    return out


@pytest.mark.skipif(os.name != "nt", reason="registro de Windows")
def test_foreign_icons_apply_and_restore_exactly(qapp, branch, monkeypatch):
    from aero.core import explorer_icons as ei
    from aero.core.associations import CLASSES
    from aero.ui.icon_export import icon_path

    monkeypatch.setattr(ei, "extensions", lambda: {".mp4": "video", ".mkv": "video", ".flac": "audio",
                                                   ".txt": "document", ".log": "document", ".zip": "archive"})
    branch.set(rf"{CLASSES}\.mp4", None, "VLC.mp4")
    branch.set(rf"{CLASSES}\VLC.mp4\DefaultIcon", None, r"C:\vlc.exe,1")         # valor propio previo
    branch.set(rf"{CLASSES}\.mkv", None, "VLC.mkv")                                # sin DefaultIcon en HKCU
    branch.set(rf"{CLASSES}\.flac", None, "Shared.Media")
    branch.set(rf"{CLASSES}\.txt", None, "Shared.Media")                           # mismo ProgID, otra categoría
    branch.set(rf"{CLASSES}\.log", None, "txtfile")
    branch.set(rf"{CLASSES}\.zip", None, "AeroPlayer.Archive")                     # ya es de AERO: no se toca
    plan = ei.plan(branch)
    assert set(plan) == {"VLC.mp4", "VLC.mkv", "txtfile"}
    assert ei.apply(branch) == 3
    video = f'"{icon_path("video")}",0'
    assert branch.get(rf"{CLASSES}\VLC.mp4\DefaultIcon") == video
    assert branch.get(rf"{CLASSES}\VLC.mkv\DefaultIcon") == video
    assert branch.get(rf"{CLASSES}\txtfile\DefaultIcon") == f'"{icon_path("document")}",0'
    assert branch.get(rf"{CLASSES}\Shared.Media\DefaultIcon") is None
    assert branch.get(rf"{CLASSES}\.mp4") == "VLC.mp4"                          # el programa no cambia
    assert ei.applied(branch) == 3 and ei.apply(branch) == 0                      # idempotente
    branch.set(rf"{CLASSES}\txtfile\DefaultIcon", None, r"C:\mio.ico")          # el usuario lo cambia después
    assert ei.restore(branch) == 2
    assert branch.get(rf"{CLASSES}\VLC.mp4\DefaultIcon") == r"C:\vlc.exe,1"     # vuelve el valor exacto
    assert branch.get(rf"{CLASSES}\VLC.mkv\DefaultIcon") is None                # no había nada: se quita
    assert branch.get(rf"{CLASSES}\txtfile\DefaultIcon") == r"C:\mio.ico"       # lo del usuario se respeta
    assert branch.get(ei.BACKUP, "VLC.mp4") is None


def test_scripts_and_programs_keep_their_icon():
    from aero.core import explorer_icons as ei

    ex = ei.extensions()
    for ext in (".exe", ".lnk", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".dll", ".ini", ".reg"):
        assert ext not in ex, ext
    for ext, cat in ((".mp4", "video"), (".flac", "audio"), (".png", "image"), (".pdf", "pdf"), (".zip", "archive"),
                     (".iso", "disc"), (".torrent", "torrent"), (".ttf", "font"), (".py", "code"), (".msi", "installer"),
                     (".docx", "document")):
        assert ex.get(ext) == cat, ext


STEP = r'''
import os, sys
sys.path.insert(0, sys.argv[3])
from PySide6.QtGui import QGuiApplication, QImage
app = QGuiApplication([])
from aero.core import explorer_icons as ei
from aero.core.associations import Registry, CLASSES, notify_shell
from aero.ui import file_icons
reg = Registry(); B = "\\"
EXT, PROG = ".aerotest22", "AeroTest22.Foreign"
step, f = sys.argv[1], sys.argv[2]
ei.extensions = lambda: {EXT: "video"}
if step == "setup":
    reg.set(CLASSES + B + EXT, None, PROG); reg.set(CLASSES + B + PROG, None, "Prueba")
    reg.set(CLASSES + B + PROG + B + "DefaultIcon", None, r"C:\Windows\System32\shell32.dll,3")
    notify_shell()
elif step == "apply": print(ei.apply(reg))
elif step == "restore": print(ei.restore(reg))
elif step == "clean":
    reg.delete_tree(CLASSES + B + EXT); reg.delete_tree(CLASSES + B + PROG); reg.delete_tree(ei.BACKUP); notify_shell()
else:
    a = ei.shell_icon_image(f, 48).convertToFormat(QImage.Format.Format_ARGB32)
    b = file_icons.pixmap("video", 48, 1.0, dark=False).toImage().convertToFormat(QImage.Format.Format_ARGB32)
    t = sum(abs(a.pixelColor(x, y).red() - b.pixelColor(x, y).red()) + abs(a.pixelColor(x, y).green()
            - b.pixelColor(x, y).green()) + abs(a.pixelColor(x, y).blue() - b.pixelColor(x, y).blue())
            for y in range(48) for x in range(48))
    print(round(t / (48 * 48 * 3), 1))
'''


@pytest.mark.skipif(os.name != "nt", reason="Explorador de Windows")
def test_explorer_really_shows_the_aero_icon_and_restores(tmp_path):
    """Con el Shell de verdad: cada paso en un proceso nuevo (como el Explorador, sin caché del proceso)."""
    script = tmp_path / "step.py"
    script.write_text(STEP, encoding="utf-8")
    f = tmp_path / "clip.aerotest22"
    f.write_bytes(b"x")

    def step(name):
        r = subprocess.run([PY, str(script), name, str(f), str(ROOT)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    try:
        step("setup")
        before = float(step("look"))
        assert step("apply") == "1"
        after = float(step("look"))
        assert step("restore") == "1"
        back = float(step("look"))
    finally:
        step("clean")
    assert after < before - 10, (before, after)        # el Explorador dibuja ahora el icono AERO de vídeo
    assert abs(back - before) < 1, (before, back)        # y tras restaurar, exactamente el de antes


# ----------------------------------------------------------------------------- fotos en la ventana principal

def test_photo_opens_in_main_viewer_and_quicklook_stays_separate(qapp, media, controller):
    controller.settings.set("photos_in_main", True)
    controller.open_files([str(media / "img.png")])
    assert controller.main is not None and not controller.media_windows
    win = controller.main
    assert wait_for(qapp, lambda: win.current_page() == "viewer", 5)
    v = win.page("viewer")
    assert wait_for(qapp, lambda: v.image.item.pixmap() is not None and not v.image.item.pixmap().isNull(), 10)
    assert "200×120 px" in v.subtitle.text()
    # Quick Look sigue siendo independiente
    controller.show_quicklook(str(media / "img.png"))
    assert controller.quicklook is not None and controller.quicklook.isVisible()
    controller.quicklook.close_preview()
    assert win.current_page() == "viewer"


def test_viewer_flip_zoom_rotate(qapp, tmp_path):
    from PySide6.QtGui import QColor, QImage

    from aero.ui.viewers.image_viewer import ImageViewer

    img = QImage(40, 20, QImage.Format.Format_RGB32)
    img.fill(QColor("#0000ff"))
    for y in range(20):
        for x in range(10):
            img.setPixelColor(x, y, QColor("#ff0000"))             # rojo a la izquierda
    v = ImageViewer()
    v.resize(400, 300)
    v.show()
    v.set_image(str(tmp_path / "a.png"), img)
    v.flip(True)
    pm = v.item.pixmap().toImage()
    assert pm.pixelColor(35, 5).red() > 200 and pm.pixelColor(2, 5).blue() > 200     # ahora a la derecha
    v.flip(False)
    v.flip(True)
    assert v.flipped == (False, True)
    v.zoom(2.0)
    assert not v.fit_mode and abs(v.transform().m11() - 2.0) < 0.01
    v.rotate_by(90)
    assert v.rotation == 90
    v.fit()
    assert v.fit_mode
    v.close()


def test_minimal_viewer_still_available(qapp, media, controller):
    controller.settings.set("photos_in_main", False)
    controller.open_files([str(media / "img.png")])
    assert len(controller.media_windows) == 1 and controller.main is None


# ----------------------------------------------------------------------------- rendimiento

def test_numpy_not_loaded_at_startup():
    code = "import sys; sys.path.insert(0, sys.argv[1]); import aero.ui.main_window; print('numpy' in sys.modules)"
    r = subprocess.run([PY, "-c", code, str(ROOT)], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "False", r.stderr


def test_analyzer_created_on_first_use(qapp):
    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.player.engine import PlayerEngine

    e = PlayerEngine(Settings(), Database())
    assert e._analyzer is None
    a = e.analyzer
    assert a is e.analyzer and e._analyzer is a


# ----------------------------------------------------------------------------- reparar un registro roto

@pytest.mark.skipif(os.name != "nt", reason="registro de Windows")
def test_chosen_but_missing_detects_broken_choice(monkeypatch):
    from aero.core import associations as a

    monkeypatch.setattr(a, "current_progid", lambda ext: {".mp4": "AeroPlayer.NoExiste",
                                                          ".mkv": "VLC.mkv"}.get(ext))
    assert a.chosen_but_missing() == [".mp4"]


def test_registration_upgrade_only_in_installed_app(qapp, controller, monkeypatch):
    from aero.core import associations as a

    calls = []
    monkeypatch.setattr(a, "register", lambda reg=None: calls.append("register"))
    monkeypatch.setattr(a, "is_registered", lambda reg=None: False)
    monkeypatch.setattr(a, "chosen_but_missing", lambda: [".mp4"])
    controller.settings.set("assoc_version", 0)
    controller._upgrade_registration()
    assert calls == ["register"] and controller.settings.get("assoc_version") == a.REG_VERSION
    controller._upgrade_registration()                       # una sola vez
    assert calls == ["register"]
    controller.settings.set("assoc_version", 0)
    monkeypatch.setattr(a, "chosen_but_missing", lambda: [])
    controller._upgrade_registration()                       # ni registrado ni elegido: no se registra nada
    assert calls == ["register"]
    import inspect

    src = inspect.getsource(type(controller).__init__)
    assert 'getattr(sys, "frozen", False)' in src and "_upgrade_registration" in src
