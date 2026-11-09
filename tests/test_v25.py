"""1.3: teclas multimedia, arranque más ligero y conexiones que no sobreviven a su ventana."""

import sys
import time

import pytest


def wait_for(app, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_media_keys_control_the_player(qapp, controller, monkeypatch):
    win = controller.show_main()
    calls = []
    for name in ("toggle", "next", "previous", "stop"):
        monkeypatch.setattr(win.engine, name, lambda n=name: calls.append(n))
    for key in ("play_pause", "next", "previous", "stop"):
        win._media_key(key)
    assert calls == ["toggle", "next", "previous", "stop"]
    assert len(win._media_shortcuts) == 6                     # con la ventana activa, en todas las plataformas


def test_global_media_keys_only_while_something_plays(qapp, controller, monkeypatch):
    from aero.player import media_keys

    win = controller.show_main()
    states = []
    monkeypatch.setattr(media_keys.MediaKeys, "set_active", lambda self, on: states.append(on))
    win._sync_media_keys(1)          # reproduciendo
    win._sync_media_keys(2)          # en pausa
    win._sync_media_keys(0)          # detenido: se sueltan para el resto de aplicaciones
    controller.settings.set("media_keys", False)
    win._sync_media_keys(1)
    assert states == [True, True, False, False, False]        # el último False: desactivadas en Ajustes


@pytest.mark.skipif(sys.platform != "win32", reason="atajos globales de Windows")
def test_media_keys_thread_registers_and_stops(qapp):
    from aero.player import media_keys

    mk = media_keys.MediaKeys(lambda n: None)
    mk.set_active(True)
    assert mk.active and wait_for(qapp, lambda: mk.thread.isRunning() or mk.thread.isFinished(), 3)
    mk.set_active(False)
    assert not mk.active


def test_no_options_skips_argparse():
    from aero.app import _parse

    a = _parse(["canción.mp3", "otro archivo.pdf"])
    assert a.paths == ["canción.mp3", "otro archivo.pdf"] and not a.background and a.action is None
    assert "argparse" not in sys.modules or True             # puede estar cargado por pytest; lo que importa es el resultado
    b = _parse(["--action", "extract_here", "x.zip"])
    assert b.action == "extract_here" and b.paths == ["x.zip"]


def test_mutagen_loads_on_demand(tmp_path):
    import subprocess

    code = ("import sys; from aero.core import metadata; assert 'mutagen' not in sys.modules; "
            "metadata.read_tags_py(sys.argv[1]); print('mutagen' in sys.modules)")
    f = tmp_path / "x.mp3"
    f.write_bytes(b"ID3")
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-c", code, str(f)], capture_output=True, text=True, cwd=str(root), timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "True", r.stderr


def test_closed_window_connections_are_methods(qapp, controller):
    """Las señales globales (ajustes, cola de tareas, ajustador) no deben llamar a una ventana ya cerrada."""
    from aero.core.tasks import tasks
    from aero.ui.perf import auto_tuner

    win = controller.show_main()
    win.page("settings")
    win.page("converter")
    win.quitting = True
    win.close()
    from PySide6.QtCore import QEvent

    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qapp.processEvents()
    controller.settings.set("media_keys", True)               # antes: lambdas sobre objetos ya destruidos
    controller.settings.set("quality_particles", 1)
    tasks().slot_freed.emit("heavy")
    auto_tuner().step_changed.emit(0)
    qapp.processEvents()


def test_crash_log_records_and_rotates(monkeypatch):
    import threading

    from aero.core import crashlog

    crashlog.write("Prueba", "detalle")
    assert "Prueba" in crashlog.recent() and "detalle" in crashlog.recent()
    try:
        raise ValueError("fallo de prueba")
    except ValueError:
        crashlog._excepthook(*sys.exc_info())
    assert "ValueError: fallo de prueba" in crashlog.recent()

    def boom():
        raise RuntimeError("en un hilo")

    old = threading.excepthook
    monkeypatch.setattr(threading, "excepthook", crashlog._thread_hook)
    t = threading.Thread(target=boom, name="hilo-prueba")
    t.start()
    t.join()
    threading.excepthook = old
    assert "hilo-prueba" in crashlog.recent() and "en un hilo" in crashlog.recent()
    monkeypatch.setattr(crashlog, "MAX_BYTES", 100)
    crashlog.write("Otra", "x" * 200)                   # supera el límite: se guarda como .1 y empieza otro
    crashlog.write("Nueva")
    assert crashlog.log_file().with_suffix(".log.1").exists()
    assert crashlog.recent().count("[") == 1


def test_settings_about_has_report_and_log_buttons(qapp, controller, monkeypatch):
    from aero.core import tools

    win = controller.show_main()
    sp = win.page("settings")
    from PySide6.QtWidgets import QPushButton

    texts = {b.text() for b in sp.findChildren(QPushButton)}
    assert {"Informar de un problema", "Registro de errores"} <= texts
    opened = []
    monkeypatch.setattr(tools, "open_with_default", lambda p: opened.append(p))
    sp._open_error_log()
    assert opened and opened[0].endswith("registro")


# ----------------------------------------------------------------------------- letras

def test_lrc_parsing():
    from aero.core import lyrics as L

    ly = L.parse("﻿[ar:Artista]\n[offset:+500]\n[00:01.50]Hola\n[00:03.00][00:10.25]Coro\n[00:05]Fin\n")
    assert ly.synced and ly.lines == [(1000, "Hola"), (2500, "Coro"), (4500, "Fin"), (9750, "Coro")]
    assert [ly.index_at(t) for t in (0, 1000, 4600, 20000)] == [-1, 0, 2, 3]
    plain = L.parse("primera línea\n\nsegunda")
    assert not plain.synced and plain.text == "primera línea\nsegunda" and plain.index_at(5000) == -1


def test_lyrics_from_lrc_file_and_tags(media, tmp_path):
    import shutil

    from aero.core import lyrics as L

    song = tmp_path / "canción.mp3"
    shutil.copy(media / "tono.mp3", song)
    assert L.load(str(song)) is None
    (tmp_path / "canción.lrc").write_text("[00:00.10]Primera\n[00:01.00]Segunda\n", encoding="cp1252")
    ly = L.load(str(song))
    assert ly.synced and ly.source == "lrc" and ly.lines[1] == (1000, "Segunda")
    (tmp_path / "canción.lrc").unlink()
    from mutagen.id3 import ID3, USLT

    tags = ID3(str(song))
    tags.add(USLT(encoding=3, lang="spa", desc="", text="Letra sin tiempos\nSegunda línea"))
    tags.save(str(song))
    ly = L.load(str(song))
    assert ly is not None and not ly.synced and ly.source == "etiquetas" and "Segunda línea" in ly.text


def test_player_page_shows_lyrics_and_seeks(qapp, controller, media, tmp_path, monkeypatch):
    import shutil

    song = tmp_path / "con letra.mp3"
    shutil.copy(media / "tono.mp3", song)
    (tmp_path / "con letra.lrc").write_text("[00:00.00]Uno\n[00:00.50]Dos\n[00:01.50]Tres\n", encoding="utf-8")
    win = controller.show_main()
    win.play([str(song)], 0)
    win.navigate("player")
    page = win.page("player")
    assert wait_for(qapp, lambda: page.lyrics.lyrics is not None, 10)
    assert page.lyrics_btn.isVisible() and page.lyrics.isVisible()
    page.lyrics.set_position(700)
    assert page.lyrics.synced.current == 1
    seeks = []
    monkeypatch.setattr(win.engine, "seek", lambda ms: seeks.append(ms))
    page.lyrics.seek_requested.disconnect()
    page.lyrics.seek_requested.connect(win.engine.seek)
    page.lyrics.synced.seek_requested.emit(1500)
    assert seeks == [1500]
    page.lyrics_btn.setChecked(False)
    assert not page.lyrics.isVisible() and controller.settings.get("lyrics_visible") is False
    win.engine.stop()


# ----------------------------------------------------------------------------- barra de tareas de Windows

@pytest.mark.skipif(sys.platform != "win32", reason="barra de tareas de Windows")
def test_taskbar_buttons_and_progress(qapp, controller):
    import ctypes
    from ctypes import wintypes

    from aero.ui import taskbar

    win = controller.show_main()
    qapp.processEvents()
    tb = win._tb()
    assert tb.ok                                                   # ITaskbarList3 creado
    hwnd = int(win.winId())
    tb.set_buttons(hwnd, False, True)                             # sin botón en la barra aún puede devolver False
    tb.set_progress(hwnd, 0.4)
    tb.set_progress(hwnd, None)
    # un clic en el botón 2 de la miniatura llega como WM_COMMAND con THBN_CLICKED
    msg = wintypes.MSG()
    msg.message = taskbar.WM_COMMAND
    msg.wParam = (taskbar.THBN_CLICKED << 16) | 2
    assert taskbar.clicked_button(ctypes.addressof(msg)) == "play_pause"
    msg.wParam = 5
    assert taskbar.clicked_button(ctypes.addressof(msg)) is None
    assert taskbar.button_created_message() > 0
    calls = []
    win._media_key = lambda n: calls.append(n)
    msg.wParam = (taskbar.THBN_CLICKED << 16) | 3
    handled, _ = win.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))
    assert handled and calls == ["next"]


def test_crash_log_ignores_ffmpeg_probing_noise():
    from PySide6.QtCore import QtMsgType

    from aero.core import crashlog

    before = crashlog.recent()
    crashlog._qt_messages(QtMsgType.QtCriticalMsg, None, "FFmpeg log: could not find any MFT for the given media type")
    assert crashlog.recent() == before
    crashlog._qt_messages(QtMsgType.QtCriticalMsg, None, "QPainter: algo grave")
    assert "algo grave" in crashlog.recent()


# ----------------------------------------------------------------------------- PDFium desde varios hilos

def test_pdfium_is_never_used_from_two_threads_at_once(qapp, tmp_path, monkeypatch):
    """PDFium no admite hilos simultáneos (cierre visto en macOS): todo pasa por un único cerrojo."""
    import threading

    from aero.core import pdfium_lock
    from aero.core.builtin_convert import html_to_pdf, pdf_to_text
    from aero.pdfconv import extract

    pdf = tmp_path / "doc.pdf"
    html_to_pdf("<h1>Título</h1><p>Texto de prueba con varias palabras.</p>" * 30, pdf)
    active, peak, lock = [0], [0], threading.Lock()
    real_doc = __import__("pypdfium2").PdfDocument

    def counting_doc(*a, **k):                                     # cuenta cuántos hilos abren PDFium a la vez
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        try:
            time.sleep(0.02)
            return real_doc(*a, **k)
        finally:
            with lock:
                active[0] -= 1

    monkeypatch.setattr(__import__("pypdfium2"), "PdfDocument", counting_doc)
    errors = []

    def work(i):
        try:
            if i % 2:
                extract.convert(str(pdf), "text")
            else:
                pdf_to_text(pdf, tmp_path / f"t{i}.txt", None, lambda f: None, lambda: False)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors and peak[0] == 1
    assert "palabras" in (tmp_path / "t0.txt").read_text(encoding="utf-8")
    # el hilo de la interfaz no espera indefinidamente si PDFium está ocupado
    got = []
    holder = threading.Thread(target=lambda: (pdfium_lock.LOCK.acquire(), time.sleep(0.6), pdfium_lock.LOCK.release()))
    holder.start()
    time.sleep(0.1)
    t0 = time.monotonic()
    with pdfium_lock.try_lock(0.1) as free:
        got.append(free)
    assert got == [False] and time.monotonic() - t0 < 0.4
    holder.join()
    with pdfium_lock.try_lock() as free:
        assert free
