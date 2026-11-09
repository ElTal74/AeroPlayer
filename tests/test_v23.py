"""1.1: actualizaciones desde GitHub, esquinas redondeadas en todas las ventanas y autoría."""

import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


def wait_for(app, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if app is not None:
            app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


# ----------------------------------------------------------------------------- servidor que imita a GitHub

class FakeGitHub:
    def __init__(self, version="9.9.0", setup=b"MZ" + b"instalador" * 5000, sums_ok=True, with_assets=True):
        self.version, self.setup = version, setup
        digest = hashlib.sha256(setup).hexdigest() if sums_ok else "0" * 64
        self.name = f"AeroPlayer-{version}-setup.exe"
        self.sums = f"﻿{digest}  {self.name}\n{'1' * 64}  AeroPlayer-{version}-portable.zip\n".encode()
        self.hits = []
        self.fail = {}               # ruta -> cuántas veces responder 504 antes de servirla
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append(self.path)
                key = "/repos/" if self.path.startswith("/repos/") else self.path
                if outer.fail.get(key, 0) > 0:
                    outer.fail[key] -= 1
                    self.send_response(504)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path.startswith("/repos/"):
                    base = f"http://127.0.0.1:{outer.port}"
                    assets = [{"name": outer.name, "size": len(outer.setup), "browser_download_url": f"{base}/setup",
                               "url": f"{base}/api/setup"},
                              {"name": "SHA256SUMS.txt", "size": len(outer.sums), "browser_download_url": f"{base}/sums",
                               "url": f"{base}/api/sums"}]
                    body = json.dumps({"tag_name": f"v{outer.version}", "body": "## Novedades\n- Todo mejor",
                                       "html_url": f"{base}/page", "assets": assets if with_assets else []}).encode()
                elif self.path in ("/setup", "/sums") or (
                        self.path in ("/api/setup", "/api/sums")
                        and self.headers.get("Accept") == "application/octet-stream"):
                    body = outer.setup if self.path.endswith("setup") else outer.sums
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_port
        self.api = f"http://127.0.0.1:{self.port}/repos/{{repo}}/releases/latest"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture()
def gh():
    g = FakeGitHub()
    yield g
    g.close()


def test_version_comparison():
    from aero.core import updater

    assert updater.parse_version("v1.2.10") == (1, 2, 10)
    assert updater.is_newer("1.1.0", "1.0.0") and updater.is_newer("v1.0.10", "1.0.9")
    assert not updater.is_newer("1.0.0", "1.0.0") and not updater.is_newer("1.0", "1.0.0")
    assert not updater.is_newer("0.9.9", "1.0.0") and updater.is_newer("2", "1.9.9")
    assert updater.parse_version("1.1.0-beta") == (1, 1, 0)


def test_latest_release_and_check(gh, monkeypatch):
    from aero.core import updater

    monkeypatch.setattr(updater, "RETRY_WAIT", 0)

    rel = updater.latest("ElTal74/AeroPlayer", gh.api)
    assert rel.version == "9.9.0" and rel.setup_name == gh.name and rel.setup_size == len(gh.setup)
    assert "Novedades" in rel.notes and rel.sums_url.endswith("/sums")
    assert updater.check("ElTal74/AeroPlayer", gh.api).version == "9.9.0"
    old = FakeGitHub(version="0.1.0")
    try:
        assert updater.check("x/y", old.api) is None                 # no es más nueva: nada que hacer
    finally:
        old.close()
    empty = FakeGitHub(with_assets=False)
    try:
        assert updater.latest("x/y", empty.api) is None             # sin instalador publicado
    finally:
        empty.close()
    with pytest.raises(updater.UpdateError):
        updater.latest("x/y", "http://127.0.0.1:9/repos/{repo}/releases/latest")


def test_transient_github_errors_are_retried(gh, tmp_path, monkeypatch):
    """GitHub a veces responde 504 un momento (pasó de verdad al publicar 1.1.0): se reintenta."""
    from aero.core import updater

    monkeypatch.setattr(updater, "RETRY_WAIT", 0)
    gh.fail = {"/repos/": 1, "/sums": 2, "/setup": 1}
    rel = updater.latest("x/y", gh.api)
    assert rel.version == "9.9.0"
    assert updater.download(rel, folder=tmp_path).read_bytes() == gh.setup
    assert gh.fail == {"/repos/": 0, "/sums": 0, "/setup": 0}
    # github.com caído (pasó al publicar 1.1.0: 504 en todo github.com con la API funcionando): se usa la API
    gh.fail = {"/sums": 99, "/setup": 99}
    assert updater.download(rel, folder=tmp_path / "api").read_bytes() == gh.setup
    assert "/api/sums" in gh.hits and "/api/setup" in gh.hits
    gh.fail = {"/sums": 99, "/api/sums": 99}                            # si nada responde: error claro
    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.download(rel, folder=tmp_path / "otra")


def test_download_verifies_sha256(gh, tmp_path):
    from aero.core import updater

    rel = updater.latest("x/y", gh.api)
    seen = []
    path = updater.download(rel, lambda d, t: seen.append((d, t)), folder=tmp_path)
    assert path.read_bytes() == gh.setup and seen[-1] == (len(gh.setup), len(gh.setup))
    hits = len(gh.hits)
    assert updater.download(rel, folder=tmp_path) == path               # ya comprobado: no se baja otra vez
    assert len(gh.hits) == hits + 1                                     # solo se vuelve a leer SHA256SUMS
    bad = FakeGitHub(sums_ok=False)
    try:
        brel = updater.latest("x/y", bad.api)
        with pytest.raises(updater.UpdateError, match="SHA-256"):
            updater.download(brel, folder=tmp_path / "malo")
        assert not any((tmp_path / "malo").glob("*"))                  # no queda nada que se pueda ejecutar
    finally:
        bad.close()


def test_download_can_be_cancelled(gh, tmp_path):
    from aero.core import updater

    rel = updater.latest("x/y", gh.api)
    with pytest.raises(updater.UpdateError):
        updater.download(rel, cancelled=lambda: True, folder=tmp_path)
    assert not any(tmp_path.glob("*.part")) and not (tmp_path / gh.name).exists()


def test_due_once_a_day_and_respects_setting():
    from aero.core import updater
    from aero.core.config import Settings

    s = Settings()
    s.set("update_check", True)
    s.set("update_last_check", 0.0)
    assert updater.due(s)
    s.set("update_last_check", time.time())
    assert not updater.due(s)
    s.set("update_last_check", 0.0)
    s.set("update_check", False)
    assert not updater.due(s)


def test_update_dialog_downloads_and_launches_installer(qapp, gh, tmp_path, monkeypatch):
    from aero.core import updater
    from aero.core.config import Settings
    from aero.ui import update_ui

    rel = updater.latest("x/y", gh.api)
    launched, quit_calls = [], []
    monkeypatch.setattr(updater, "can_install", lambda: True)
    monkeypatch.setattr(updater, "updates_dir", lambda: tmp_path)
    monkeypatch.setattr(updater, "launch_installer", lambda p: launched.append(p))

    class Ctl:
        settings = Settings()

        def quit(self):
            quit_calls.append(1)

    dlg = update_ui.UpdateDialog(rel, Ctl.settings, Ctl())
    dlg.show()
    assert "9.9.0" in dlg.findChildren(type(dlg.status))[0].text()
    dlg._update()
    assert wait_for(qapp, lambda: launched and quit_calls, 15)
    assert launched[0].read_bytes() == gh.setup
    dlg.close()


def test_update_dialog_skip_and_dev_mode(qapp, gh, monkeypatch):
    from aero.core import tools, updater
    from aero.core.config import Settings
    from aero.ui import update_ui

    rel = updater.latest("x/y", gh.api)
    s = Settings()
    dlg = update_ui.UpdateDialog(rel, s)
    assert dlg.btn_update.text() == "Ir a la descarga"                 # desde el código no se autoinstala
    opened = []
    monkeypatch.setattr(tools, "open_with_default", lambda p: opened.append(p))
    dlg._update()
    assert opened == [rel.page]
    dlg2 = update_ui.UpdateDialog(rel, s)
    dlg2._skip()
    assert s.get("update_skip") == "9.9.0"


def test_startup_check_shows_dialog_and_respects_skip(qapp, controller, gh, monkeypatch):
    from aero.core import updater
    from aero.ui import update_ui

    monkeypatch.setattr(updater, "API", gh.api)
    real_check = updater.check
    monkeypatch.setattr(updater, "check", lambda: real_check("x/y", gh.api))
    controller.settings.set("update_check", True)
    controller.settings.set("update_last_check", 0.0)
    controller.show_main()
    update_ui.startup_check(controller)
    assert wait_for(qapp, lambda: update_ui._open, 10)
    d = update_ui._open[0]
    assert d.rel.version == "9.9.0" and controller.settings.get("update_last_check") > 0
    d.reject()
    qapp.processEvents()
    controller.settings.set("update_skip", "9.9.0")
    controller.settings.set("update_last_check", 0.0)
    update_ui.startup_check(controller)
    time.sleep(1.0)
    qapp.processEvents()
    assert not update_ui._open                                         # versión omitida: no molesta


def test_installer_update_keeps_options(monkeypatch, tmp_path):
    from aero.core import associations, shellmenu
    from aero.installer import core

    monkeypatch.setattr(associations, "is_registered", lambda reg=None: False)
    monkeypatch.setattr(shellmenu, "is_registered", lambda reg=None: True)
    monkeypatch.setattr(core, "shortcut_paths", lambda: {"programs": tmp_path / "p.lnk", "desktop": tmp_path / "d.lnk"})
    (tmp_path / "d.lnk").write_text("x")
    opts = core.options_for_update(core.Existing("aero", tmp_path / "AeroPlayer", "1.0.0"))
    assert opts.target == tmp_path / "AeroPlayer" and opts.desktop and not opts.start_menu
    assert opts.context_menu and not opts.associations and opts.theme == "" and opts.language == ""


def test_setup_entry_point_has_update_mode():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "packaging" / "setup_main.py").read_text(encoding="utf-8")
    assert '"--update"' in src and "main_update" in src


# ----------------------------------------------------------------------------- esquinas y autoría

def test_media_windows_have_rounded_content(qapp, controller, media):
    w = controller.open_media_window(str(media / "img.png"))
    assert wait_for(qapp, lambda: w.isVisible() and not w._views["image"].item.pixmap().isNull(), 10)
    w._round_content()
    qapp.processEvents()
    img = w.grab().toImage()
    for x, y in ((0, 0), (img.width() - 1, 0), (0, img.height() - 1), (img.width() - 1, img.height() - 1)):
        assert img.pixelColor(x, y).alpha() < 40, (x, y)
    w.showMaximized()
    qapp.processEvents()
    w._round_content()
    assert w.stack.mask().isEmpty()                                     # maximizada: recta, como en Windows
    w.close()


def test_author_and_copyright():
    import aero

    assert aero.AUTHOR == "David Seva Gonzalvez" and "David Seva Gonzalvez" in aero.COPYRIGHT
    assert aero.UPDATE_REPO == "ElTal74/AeroPlayer"


# ----------------------------------------------------------------------------- temporizador, novedades, portable

def test_sleep_timer_fades_and_pauses(qapp, monkeypatch):
    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.player import sleep_timer
    from aero.player.engine import PlayerEngine

    monkeypatch.setattr(sleep_timer, "FADE_MS", 400)
    e = PlayerEngine(Settings(), Database())
    st = sleep_timer.SleepTimer(e)
    st._fade.setInterval(10)
    e.audio.setVolume(0.8)
    paused, fired = [], []
    monkeypatch.setattr(type(e), "playing", property(lambda self: True))
    monkeypatch.setattr(e.player, "pause", lambda: paused.append(1))
    st.fired.connect(lambda: fired.append(1))
    st.start(1)
    assert st.active and 59 <= st.remaining() <= 60
    st.deadline = sleep_timer.time.time() + 0.2           # que se cumpla ya
    st._check()
    assert wait_for(qapp, lambda: fired, 5)
    assert paused and not st.active and abs(e.audio.volume() - 0.8) < 0.01   # volumen devuelto
    st.start(30)
    st.cancel()
    assert not st.active


def test_sleep_timer_end_of_track(qapp, monkeypatch):
    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.player.engine import PlayerEngine, TrackInfo
    from aero.player.sleep_timer import SleepTimer

    e = PlayerEngine(Settings(), Database())
    st = SleepTimer(e)
    paused = []
    monkeypatch.setattr(e.player, "pause", lambda: paused.append(1))
    e.current = TrackInfo("a.mp3", "audio")
    st.start_end_of_track()
    e.track_changed.emit(TrackInfo("a.mp3", "audio"))      # la misma: nada
    assert not paused
    e.track_changed.emit(TrackInfo("b.mp3", "audio"))      # empieza la siguiente: se detiene
    assert paused and not st.active


def test_player_bar_has_sleep_timer(qapp, controller):
    win = controller.show_main()
    bar = win.bar
    bar._build_sleep_menu()
    texts = [a.text() for a in bar.sleep_menu.actions() if a.text()]
    assert texts[0] == "Desactivado" and "Al terminar esta pista" in texts and "1 hora" in texts
    bar.sleep.start(15)
    assert bar.sleep_btn.isChecked() and "Se detendrá en" in bar.sleep_btn.toolTip()
    bar.sleep.cancel()
    assert not bar.sleep_btn.isChecked()


def test_whats_new_only_after_update(qapp, monkeypatch):
    import aero
    from aero.core.config import Settings
    from aero.ui import update_ui

    class Ctl:
        settings = Settings()
        main = None

    c = Ctl()
    c.settings.set("seen_version", "")
    assert update_ui.whats_new(c) is None                        # primera instalación: no molesta
    assert c.settings.get("seen_version") == aero.__version__
    c.settings.set("seen_version", "0.9.0")
    dlg = update_ui.whats_new(c)
    assert dlg is not None and aero.__version__ in dlg.findChildren(type(dlg.layout().itemAt(0).widget()))[0].text()
    dlg.close()
    assert update_ui.whats_new(c) is None                        # una sola vez


def test_portable_copy_does_not_run_installer(monkeypatch, tmp_path):
    import sys

    from aero.core import updater
    from aero.installer import core

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "portable" / "AeroPlayer.exe"))
    monkeypatch.setattr(core, "find_existing", lambda: core.Existing("aero", tmp_path / "instalado", "1.0.0"))
    assert updater.is_portable() and not updater.can_install()
    monkeypatch.setattr(core, "find_existing", lambda: core.Existing("aero", tmp_path / "portable", "1.0.0"))
    assert not updater.is_portable()


def test_library_summary_and_converter_empty_states(qapp, controller, media):
    controller.settings.set("library_folders", [str(media)])       # si no, scan() pide elegir una carpeta
    win = controller.show_main()
    lib = win.page("library")
    lib.scan()
    assert wait_for(qapp, lambda: lib.summary.text().endswith(("canciones", "canción")), 20)
    conv = win.page("converter")
    assert conv.go.isEnabled() is False and not conv.table.horizontalHeader().isVisible()
    conv.add_paths([str(media / "tono.mp3")])
    assert conv.go.isEnabled() and "1 archivo" in conv.count_label.text()
    assert "\n" in conv.drop.item(0).text() and not conv.drop.item(0).icon().isNull()


# ----------------------------------------------------------------------------- visor sin QtPdf

_NO_QTPDF = r'''
import os, sys, time
sys.modules["PySide6.QtPdf"] = None          # como una compilación sin el paquete PySide6_Pdf
sys.modules["PySide6.QtPdfWidgets"] = None
from PySide6.QtWidgets import QApplication
app = QApplication([])
from aero.ui.viewers.host import ViewerHost
v = ViewerHost()
v.open(sys.argv[1])
end = time.time() + 15
while time.time() < end and v.stack.currentWidget() is not v.image:
    app.processEvents(); time.sleep(0.02)
assert v.stack.currentWidget() is v.image, "la foto no se abrió"
v.open(sys.argv[2])
app.processEvents()
assert v.stack.currentWidget() is v.error and "PDF" in v.error_text.text(), v.error_text.text()
print("ok", flush=True)          # os._exit no vacía la salida
os._exit(0)
'''


def test_viewer_works_without_qtpdf(qapp, tmp_path):
    """Sin QtPdf (pasó en las compilaciones de GitHub) solo fallan los PDF, con un aviso; fotos y demás, bien."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    script = tmp_path / "sin_pdf.py"
    script.write_text(_NO_QTPDF, encoding="utf-8")
    env = {**__import__("os").environ, "PYTHONPATH": str(root), "AERO_DATA_DIR": str(tmp_path / "datos")}
    from PySide6.QtGui import QColor, QImage

    img = QImage(64, 48, QImage.Format.Format_RGB32)       # archivos propios: tests/media no está en el repositorio
    img.fill(QColor("#3a8ee6"))
    photo = tmp_path / "foto.png"
    assert img.save(str(photo))
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    r = subprocess.run([sys.executable, str(script), str(photo), str(pdf)], capture_output=True, text=True,
                       timeout=120, env=env, cwd=str(root))
    assert r.returncode == 0 and "ok" in r.stdout, r.stdout + r.stderr


# ----------------------------------------------------------------------------- recolección en el hilo principal

def test_cycles_are_collected_only_on_the_main_thread(qapp):
    """Un objeto de Qt en un ciclo de referencias se destruye en el hilo principal, nunca en un hilo secundario."""
    import gc
    import threading
    import weakref

    from PySide6.QtCore import QObject, QThread, QTimer

    from aero.ui import gc_guard

    guard = gc_guard.install(qapp)
    assert not gc.isenabled()
    destroyed_in = []

    class Holder:
        pass

    def make():
        h = Holder()
        h.obj = QObject()
        h.obj.timer = QTimer(h.obj)
        h.obj.timer.start(50)
        h.self = h                                           # ciclo: solo lo libera el recolector
        main = QThread.currentThread()
        h.obj.destroyed.connect(lambda *_: destroyed_in.append(QThread.currentThread() is main))
        return weakref.ref(h)

    ref = make()

    def allocate():                                          # mucha basura en otro hilo: antes disparaba el recolector aquí
        junk = [[] for _ in range(200_000)]
        del junk
    t = threading.Thread(target=allocate)
    t.start()
    t.join()
    assert ref() is not None                                 # el hilo secundario no recogió nada
    gc.collect()                                             # lo que hace el temporizador del hilo principal
    assert ref() is None and destroyed_in == [True]
    assert guard.check() in (-1, 0, 1, 2)
