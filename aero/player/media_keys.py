"""Teclas multimedia del teclado (reproducir/pausa, siguiente, anterior, detener).

* Con la ventana activa, Qt ya las recibe como teclas (Windows, Linux y macOS): `install_shortcuts`.
* En Windows, para que funcionen también con AERO Player en segundo plano, se registran como atajos globales
  (RegisterHotKey: no lee el teclado, solo recibe esas teclas). Para no quitárselas a otras aplicaciones
  (el navegador, otro reproductor), solo se registran mientras hay algo cargado en AERO Player y se sueltan
  al detener. Si otra aplicación ya las tiene, simplemente no se registran.
"""

from __future__ import annotations

import ctypes
import os
import threading

from PySide6.QtCore import QThread, Signal

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000
KEYS = {1: (0xB3, "play_pause"), 2: (0xB0, "next"), 3: (0xB1, "previous"), 4: (0xB2, "stop")}


class MediaKeysThread(QThread):
    """Hilo con su propia cola de mensajes de Windows: emite el nombre de la tecla pulsada."""

    pressed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tid = 0
        self._ready = threading.Event()      # la cola de mensajes ya existe: se le puede pedir que pare
        self.registered: list[str] = []

    def run(self):
        if os.name != "nt":
            self._ready.set()
            return
        from ctypes import wintypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        msg = wintypes.MSG()
        # PostThreadMessage falla si el hilo aún no tiene cola de mensajes: PeekMessage la crea antes de avisar
        user32.PeekMessageW(ctypes.byref(msg), None, 0x0400, 0x0400, 0)
        self._tid = kernel32.GetCurrentThreadId()
        self._ready.set()
        ok = []
        for hid, (vk, name) in KEYS.items():
            if user32.RegisterHotKey(None, hid, MOD_NOREPEAT, vk):
                ok.append(hid)
                self.registered.append(name)
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in KEYS:
                self.pressed.emit(KEYS[msg.wParam][1])
        for hid in ok:
            user32.UnregisterHotKey(None, hid)

    def stop(self):
        # Si se para justo después de arrancar (reproducir y detener al instante), se espera a que tenga cola
        if self.isRunning() or not self.isFinished():
            self._ready.wait(3)
        if self._tid and os.name == "nt":
            ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self.wait(3000)


class MediaKeys:
    """Activa o suelta las teclas globales según haya o no algo en reproducción."""

    def __init__(self, on_key, parent=None):
        self.on_key = on_key
        self.parent = parent
        self.thread: MediaKeysThread | None = None

    def set_active(self, active: bool) -> None:
        if os.name != "nt":
            return
        if active and self.thread is None:
            self.thread = MediaKeysThread(self.parent)
            self.thread.pressed.connect(self.on_key)
            self.thread.start()
        elif not active and self.thread is not None:
            t, self.thread = self.thread, None
            t.stop()
            t.deleteLater()

    @property
    def active(self) -> bool:
        return self.thread is not None


def install_shortcuts(widget, on_key) -> list:
    """Teclas multimedia mientras la ventana tiene el foco (todas las plataformas)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence, QShortcut

    keys = {Qt.Key.Key_MediaTogglePlayPause: "play_pause", Qt.Key.Key_MediaPlay: "play_pause",
            Qt.Key.Key_MediaPause: "play_pause", Qt.Key.Key_MediaNext: "next",
            Qt.Key.Key_MediaPrevious: "previous", Qt.Key.Key_MediaStop: "stop"}
    out = []
    for key, name in keys.items():
        sc = QShortcut(QKeySequence(key), widget)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(lambda n=name: on_key(n))
        out.append(sc)
    return out
