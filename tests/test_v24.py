"""1.2: «Usar AERO Player para todo» (Ajustes e instalador) y piezas de Linux y macOS."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_linux_desktop_file_lists_the_same_types():
    from aero.core import defaults

    text = (ROOT / "packaging" / "linux" / "aero-player.desktop").read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if x.startswith("MimeType="))
    assert tuple(m for m in line[len("MimeType="):].split(";") if m) == defaults.LINUX_MIME_TYPES
    assert "mp3" in defaults.extensions() and "pdf" in defaults.extensions() and "torrent" in defaults.extensions()


def test_windows_registers_and_opens_settings(monkeypatch):
    from aero.core import associations, defaults

    calls = []
    monkeypatch.setattr(defaults.sys, "platform", "win32")
    monkeypatch.setattr(associations, "register", lambda: calls.append("register"))
    monkeypatch.setattr(associations, "open_default_apps_settings", lambda: calls.append("settings"))
    assert defaults.make_default_everywhere() == defaults.SETTINGS
    assert calls == ["register", "settings"]                  # nunca se escribe UserChoice: confirma el usuario


def test_linux_uses_xdg_mime(monkeypatch, tmp_path):
    from aero.core import defaults

    runs = []

    class R:
        returncode = 0

    monkeypatch.setattr(defaults.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(defaults.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(defaults.subprocess, "run", lambda args, **kw: runs.append(args) or R())
    assert defaults.make_default_everywhere() == defaults.DONE
    desktop = tmp_path / "applications" / "aero-player.desktop"
    assert desktop.exists() and "MimeType=audio/mpeg;" in desktop.read_text(encoding="utf-8")
    xdg = next(r for r in runs if r[0].endswith("xdg-mime"))
    assert xdg[1:3] == ["default", "aero-player.desktop"] and "application/pdf" in xdg
    monkeypatch.setattr(defaults.shutil, "which", lambda n: None)          # sin xdg-mime: a mano
    assert defaults.make_default_everywhere() == defaults.MANUAL


def test_mac_needs_the_app_bundle(monkeypatch):
    from aero.core import defaults

    monkeypatch.setattr(defaults.sys, "platform", "darwin")
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert defaults.make_default_everywhere() == defaults.MANUAL


def test_settings_button_uses_everything(qapp, controller, monkeypatch):
    from aero.core import defaults

    win = controller.show_main()
    sp = win.page("settings")
    called, msgs = [], []
    monkeypatch.setattr(defaults, "make_default_everywhere", lambda: called.append(1) or defaults.DONE)
    sp.message.connect(lambda text, kind: msgs.append((text, kind)))
    assert sp.btn_default_all.text() == "Usar AERO Player para todos mis archivos"
    sp.btn_default_all.click()
    assert called and msgs[-1][1] == "ok"


@pytest.mark.skipif(sys.platform != "win32", reason="solo Windows (instalador, registro o DWM)")
def test_installer_offers_default_for_everything(qapp, monkeypatch):
    from aero.core import associations
    from aero.installer import ui

    w = ui.InstallerWindow(None)
    assert w.cb_default.text() == "Usar AERO Player para todos mis archivos"
    opened = []
    monkeypatch.setattr(associations, "open_default_apps_settings", lambda: opened.append(1))
    monkeypatch.setattr(ui.core, "run_app", lambda *a, **k: None)
    w.installed = Path(os.devnull)
    w.opts.associations = True
    w.cb_launch.setChecked(False)
    w.cb_default.setChecked(True)
    w._finish()
    assert opened == [1]
    w.deleteLater()


def test_autostart_files_on_linux_and_mac(monkeypatch, tmp_path):
    from aero.core import winintegration as w

    monkeypatch.setattr(w.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    for plat, rel in (("linux", ".config/autostart/aero-player.desktop"),
                      ("darwin", "Library/LaunchAgents/io.github.eltal74.aeroplayer.plist")):
        monkeypatch.setattr(w.sys, "platform", plat)
        assert w.set_autostart(True) and w.autostart_enabled()
        assert w._unix_file() == tmp_path / rel
        assert w.set_autostart(False) and not w.autostart_enabled()


def test_data_dirs_per_platform(monkeypatch, tmp_path):
    from aero.core import paths

    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "linux")
    assert paths._platform_dirs() == (tmp_path / ".local/share/AeroPlayer", tmp_path / ".cache/AeroPlayer")
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    assert paths._platform_dirs()[0] == tmp_path / "Library/Application Support/AeroPlayer"


def test_progress_window_closes_if_it_appears_under_a_still_pointer(qapp, monkeypatch):
    """En Linux la ventana aparecía bajo el puntero quieto: lo tomaba por «ratón encima» y no se cerraba nunca."""
    from PySide6 import QtGui
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QEnterEvent

    from aero.archive import ui

    pos = {"p": QPoint(500, 400)}
    monkeypatch.setattr(QtGui.QCursor, "pos", staticmethod(lambda: pos["p"]))   # sin mover el ratón de verdad
    w = ui.ProgressWindow("Prueba")
    w.show_success("Hecho", "", auto_close=True)
    ev = QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(500, 400))
    w.enterEvent(ev)
    assert not w._hover and "se cierra en" in w.detail.text()          # puntero quieto: sigue la cuenta atrás
    pos["p"] = QPoint(520, 410)                                          # el usuario mueve el ratón encima
    w.enterEvent(ev)
    assert w._hover and "apartar el ratón" in w.detail.text()
    w._close_timer.stop()
    w.close()
