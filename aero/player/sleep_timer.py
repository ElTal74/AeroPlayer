"""Temporizador de apagado: detiene la reproducción tras un tiempo o al terminar la pista actual.

Al cumplirse, baja el volumen poco a poco (unos 8 s) para no despertar a nadie, pausa y devuelve el volumen a
su valor. No toca la configuración guardada (el volumen se cambia directamente en la salida de audio).
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

FADE_MS = 8000
STEPS = 40
CHOICES = (15, 30, 45, 60, 90, 120)       # minutos


class SleepTimer(QObject):
    changed = Signal()          # se activó, se canceló o cambió el tiempo restante
    fired = Signal()            # la reproducción se ha detenido

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.deadline = 0.0             # time.time() en el que se detiene (0 = sin tiempo)
        self.end_of_track = False
        self._track = None
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._check)
        self._fade = QTimer(self)
        self._fade.setInterval(FADE_MS // STEPS)
        self._fade.timeout.connect(self._fade_step)
        self._fade_left = 0
        self._vol0 = 1.0
        engine.track_changed.connect(self._on_track)

    @property
    def active(self) -> bool:
        return bool(self.deadline) or self.end_of_track

    def remaining(self) -> float | None:
        return max(0.0, self.deadline - time.time()) if self.deadline else None

    def start(self, minutes: float) -> None:
        self.cancel(quiet=True)
        self.deadline = time.time() + minutes * 60
        self._tick.start()
        self.changed.emit()

    def start_end_of_track(self) -> None:
        self.cancel(quiet=True)
        self.end_of_track = True
        self._track = getattr(self.engine.current, "path", None)
        self.changed.emit()

    def cancel(self, quiet: bool = False) -> None:
        if self._fade.isActive():
            self._fade.stop()
            self._restore()
        self.deadline, self.end_of_track, self._track = 0.0, False, None
        self._tick.stop()
        if not quiet:
            self.changed.emit()

    def _check(self):
        rem = self.remaining()
        if rem is None:
            return
        if rem <= FADE_MS / 1000 and not self._fade.isActive():
            self._begin_fade()
        self.changed.emit()

    def _on_track(self, info):
        """«Al terminar esta pista»: cuando empieza la siguiente, se detiene enseguida (sin desvanecer)."""
        if not self.end_of_track:
            return
        path = getattr(info, "path", None)
        if self._track is None:
            self._track = path
            return
        if path != self._track:
            self.engine.player.pause()
            self.cancel(quiet=True)
            self.fired.emit()
            self.changed.emit()

    def _begin_fade(self):
        self._vol0 = self.engine.audio.volume()
        self._fade_left = STEPS
        self._fade.start()

    def _fade_step(self):
        self._fade_left -= 1
        self.engine.audio.setVolume(self._vol0 * max(0, self._fade_left) / STEPS)
        if self._fade_left <= 0:
            self._fade.stop()
            if self.engine.playing:
                self.engine.player.pause()
            self._restore()
            self.deadline = 0.0
            self._tick.stop()
            self.fired.emit()
            self.changed.emit()

    def _restore(self):
        self.engine.audio.setVolume(self._vol0)
