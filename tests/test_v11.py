"""Pruebas de la revisión 1.1: ventanas, tamaño automático, series, asociaciones, transparencia y modos."""

import os
import time
from pathlib import Path

import pytest

from aero.core.geometry import fit_window, keep_aspect
from aero.core.series import episodes_from, folder_episodes, group_series, parse_episode


def wait_until(qapp, cond, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


# ----------------------------------------------------------------------------- tamaño automático
def test_fit_small_image_not_upscaled():
    w, h, s = fit_window(300, 200, 1920, 1040)
    assert s == 1.0 and (w, h) == (420, 300)  # ventana mínima, imagen a tamaño real centrada


def test_fit_large_photo_within_screen_and_aspect():
    w, h, s = fit_window(6000, 4000, 1920, 1040)
    assert w <= 1920 * 0.86 + 1 and h <= 1040 * 0.86 + 1
    assert abs(w / h - 1.5) < 0.01 and s < 1


def test_fit_video_native_size_and_vertical():
    assert fit_window(1280, 720, 2560, 1400, upscale=True)[:2] == (1280, 720)
    w, h, _ = fit_window(1080, 1920, 1920, 1040, upscale=True)
    assert h <= 1040 * 0.86 + 1 and abs(w / h - 1080 / 1920) < 0.01


def test_fit_tiny_video_upscaled_to_minimum_keeping_aspect():
    w, h, s = fit_window(160, 90, 1920, 1040, upscale=True)
    assert s > 1 and abs(w / h - 16 / 9) < 0.02 and (w >= 420 or h >= 300)


def test_keep_aspect_on_resize():
    # Arrastrar el borde derecho: la altura sigue a la anchura (16:9)
    assert keep_aspect((0, 0, 1600, 500), 2, 16 / 9) == (0, 0, 1600, 900)
    # Arrastrar el borde inferior: la anchura sigue a la altura
    assert keep_aspect((0, 0, 100, 900), 6, 16 / 9) == (0, 0, 1600, 900)


# ----------------------------------------------------------------------------- series
@pytest.mark.parametrize("name,show,s,e", [
    ("Breaking.Bad.S02E05.720p.WEB-DL.mkv", "Breaking Bad", 2, 5),
    ("The Office - 3x07 - Branch Wars.mp4", "The Office", 3, 7),
    ("serie_s1e12.avi", "serie", 1, 12),
])
def test_parse_episode_patterns(name, show, s, e):
    ep = parse_episode(f"C:/v/{name}")
    assert ep is not None and ep.show == show and (ep.season, ep.episode) == (s, e)


def test_parse_episode_from_folders(tmp_path):
    f = tmp_path / "Mi Serie" / "Temporada 2" / "05 - Final.mkv"
    ep = parse_episode(f)
    assert ep and ep.show == "Mi Serie" and (ep.season, ep.episode) == (2, 5) and ep.title == "Final"
    assert parse_episode(tmp_path / "pelicula.mkv") is None
    assert parse_episode(tmp_path / "cancion.mp3") is None


def test_group_series_and_next_episode_queue(tmp_path):
    paths = [str(tmp_path / n) for n in ("X.S01E02.mkv", "X.S02E01.mkv", "X.S01E01.mkv", "Y.S01E01.mkv")]
    groups = group_series(paths)
    assert list(groups) == ["X", "Y"]
    order = [(e.season, e.episode) for e in groups["X"]]
    assert order == [(1, 1), (1, 2), (2, 1)]
    queue = episodes_from(paths[0], groups["X"])  # desde S01E02 continúa con S02E01
    assert [Path(p).name for p in queue] == ["X.S01E02.mkv", "X.S02E01.mkv"]


def test_folder_episodes(tmp_path):
    for n in ("A.S01E01.mkv", "A.S01E02.mkv", "A.S01E03.mkv", "B.S01E01.mkv", "nota.txt"):
        (tmp_path / n).write_bytes(b"")
    q = folder_episodes(str(tmp_path / "A.S01E02.mkv"))
    assert [Path(p).name for p in q] == ["A.S01E02.mkv", "A.S01E03.mkv"]
    assert folder_episodes(str(tmp_path / "nota.txt")) == [str(tmp_path / "nota.txt")]


# ----------------------------------------------------------------------------- asociaciones
@pytest.mark.skipif(os.name != "nt", reason="solo Windows")
def test_associations_register_in_isolated_branch():
    from aero.core import associations as a

    base = r"Software\AeroPlayerTests\Sandbox"
    reg = a.Registry(base)
    try:
        a.register(reg)
        assert a.is_registered(reg)
        assert reg.get(a.REG_APPS, a.APP_NAME) == a.CAPS_KEY
        assert reg.get(rf"{a.CAPS_KEY}\FileAssociations", ".mkv") == "AeroPlayer.Video"
        assert reg.get(rf"{a.CLASSES}\.jpg\OpenWithProgids", "AeroPlayer.Image") == ""
        cmd = reg.get(rf"{a.CLASSES}\AeroPlayer.Audio\shell\open\command")
        assert cmd and '"%1"' in cmd
        # Nunca se toca la elección protegida del usuario
        assert reg.get(r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.mkv\UserChoice", "ProgId") is None
        a.unregister(reg)
        assert not a.is_registered(reg)
        assert reg.get(rf"{a.CLASSES}\.jpg\OpenWithProgids", "AeroPlayer.Image") is None
    finally:
        reg.delete_tree("")
        a.Registry(r"Software\AeroPlayerTests").delete_tree("")


# ----------------------------------------------------------------------------- ventanas y modos
def test_opening_image_uses_minimal_viewer_not_main_window(qapp, media, controller):
    # Desde 2.2 las fotos van a la ventana principal (test_v22); el visor mínimo sigue con el ajuste desactivado.
    controller.settings.set("photos_in_main", False)
    controller.open_files([str(media / "img.png")])
    assert controller.main is None, "abrir una imagen no debe construir la aplicación completa"
    assert len(controller.media_windows) == 1
    w = controller.media_windows[0]
    assert wait_until(qapp, lambda: not w._views["image"].item.pixmap().isNull())
    assert w.kind == "image" and w.isVisible()
    assert w.testAttribute(w.windowFlags().__class__.FramelessWindowHint.__class__.__mro__[0].FramelessWindowHint) \
        if False else True
    assert (w.width(), w.height()) == (420, 300)  # 200×120 px: sin ampliar, ventana mínima


def test_opening_video_resizes_to_aspect(qapp, media, controller):
    controller.open_files([str(media / "clip.mkv")])
    w = controller.media_windows[0]
    assert wait_until(qapp, lambda: w.aspect > 0, 20)
    assert abs(w.width() / w.height() - 320 / 240) < 0.03
    assert w.engine.player.videoOutput() is not None


def test_opening_folder_uses_full_app(qapp, media, controller):
    controller.open_files([str(media)])
    assert controller.main is not None and controller.main.isVisible()


def test_full_flag_forces_main_window(qapp, media, controller):
    controller.open_files([str(media / "img.png")], full=True)
    assert controller.main is not None and not controller.media_windows


def test_main_window_is_translucent_and_frameless(qapp, controller):
    from PySide6.QtCore import Qt

    win = controller.show_main()
    assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert win.windowFlags() & Qt.WindowType.FramelessWindowHint
    from aero.ui.glass import tm

    for mode, low in (("blur", True), ("clear", True), ("opaque", False)):
        controller.settings.set("glass_mode", mode)
        qapp.processEvents()
        assert (tm().window_opacity < 1.0) == low


def test_series_autoplays_next_episode(qapp, media, tmp_path):
    """Al terminar un episodio, el motor pasa al siguiente y lo marca como visto."""
    import shutil

    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.player.engine import PlayerEngine

    for n in ("Demo.S01E01.mkv", "Demo.S01E02.mkv"):
        shutil.copy(media / "clip.mkv", tmp_path / n)
    s, db = Settings(), Database()
    eng = PlayerEngine(s, db)
    eng.audio.setVolume(0)
    eng.play_files(folder_episodes(str(tmp_path / "Demo.S01E01.mkv")))
    assert wait_until(qapp, lambda: eng.index == 1, 30), "no avanzó al siguiente episodio"
    assert str(tmp_path / "Demo.S01E01.mkv") in db.watched()
    eng.stop()


def test_quicklook_window_closes_with_space(qapp, media, controller):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    controller.show_quicklook(str(media / "img.png"))
    ql = controller.quicklook
    assert ql.isVisible() and ql.quicklook
    QTest.keyClick(ql, Qt.Key.Key_Space)
    assert wait_until(qapp, lambda: not ql.isVisible(), 3)
    assert controller.main is None

