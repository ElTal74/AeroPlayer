"""Optimización automática: rebaja los efectos si el equipo va justo y los recupera poco a poco.

* Solo mide mientras algo se anima (fondo con movimiento o visualizador): en reposo no hay temporizador.
* Una lectura de `GetSystemTimes` cada 3 s (coste despreciable): optimizar no debe consumir más de lo que
  ahorra.
* Histéresis: baja un nivel tras dos lecturas seguidas por encima del 85 % de carga y sube un nivel tras cinco
  seguidas por debajo del 50 % (15 s). Entre cambios hay al menos 10 s: la interfaz no «parpadea».
* Solo toca fotogramas, elementos móviles, partículas y detalle del visualizador; nunca funciones.
* Reposo: si nadie toca el teclado ni el ratón en 3 minutos, o el equipo funciona con batería, el fondo animado
  se queda quieto (el visualizador sigue). Se comprueba cada 5 s solo mientras hay un fondo que quiere moverse.
"""

from __future__ import annotations

import time
import weakref

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from aero.core.hardware import CpuLoad
from aero.core.quality import AUTO_STEPS

HIGH, LOW = 0.85, 0.50
DOWN_AFTER, UP_AFTER = 2, 5
COOLDOWN = 10.0
INTERVAL_MS = 3000
REST_AFTER = 180.0
REST_CHECK_MS = 5000


def idle_seconds() -> float:
    """Segundos desde la última pulsación o movimiento del ratón en todo el equipo (0 si no se sabe)."""
    import os

    if os.name != "nt":
        return 0.0
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return 0.0
    now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((now - li.dwTime) & 0xFFFFFFFF) / 1000.0


def on_battery() -> bool:
    from aero.core.sysinfo import battery

    try:
        b = battery()
    except Exception:  # noqa: BLE001 - sin datos de energía se asume corriente
        return False
    return b is not None and not b.plugged


class AutoTuner(QObject):
    step_changed = Signal(int)
    rest_changed = Signal(bool)
    _inst: "AutoTuner | None" = None

    def __init__(self):
        super().__init__()
        self.step = 0
        self.enabled = False
        self.settings = None
        self._animators: "weakref.WeakSet[QObject]" = weakref.WeakSet()
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVAL_MS)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._sample)
        self._load = CpuLoad()
        self._hot = self._cool = 0
        self._last_change = 0.0
        self.last_load = 0.0
        self.resting = False
        self.rest_enabled = True
        self._movers: "weakref.WeakSet[QObject]" = weakref.WeakSet()
        self._rest_timer = QTimer(self)
        self._rest_timer.setInterval(REST_CHECK_MS)
        self._rest_timer.setTimerType(Qt.TimerType.VeryCoarseTimer)
        self._rest_timer.timeout.connect(self.check_rest)

    @classmethod
    def instance(cls) -> "AutoTuner":
        if cls._inst is None:
            cls._inst = AutoTuner()
        return cls._inst

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if not on and self.step:
            self._set_step(0)
        self._sync()

    def animating(self, who: QObject, on: bool) -> None:
        """Los widgets animados avisan al empezar y al parar; sin ninguno, no se mide nada."""
        if on:
            self._animators.add(who)
        else:
            self._animators.discard(who)
        self._sync()

    # ------------------------------------------------------------------ reposo
    def wants_motion(self, who: QObject, on: bool) -> None:
        """Un fondo animado avisa de que querría moverse (aunque ahora esté en reposo)."""
        if on:
            self._movers.add(who)
        else:
            self._movers.discard(who)
        try:
            if self._movers and self.rest_enabled:
                if not self._rest_timer.isActive():
                    self._rest_timer.start()
            else:
                self._rest_timer.stop()
                if self.resting:
                    self._set_rest(False)
        except RuntimeError:
            pass

    def set_rest_enabled(self, on: bool) -> None:
        self.rest_enabled = on
        if not on and self.resting:
            self._set_rest(False)
        self.wants_motion(self, False)

    def check_rest(self, idle: float | None = None, battery: bool | None = None) -> bool:
        idle = idle_seconds() if idle is None else idle
        battery = on_battery() if battery is None else battery
        self._set_rest(self.rest_enabled and (idle >= REST_AFTER or battery))
        return self.resting

    def _set_rest(self, on: bool) -> None:
        if on != self.resting:
            self.resting = on
            # En reposo se mira más a menudo: al volver a tocar el ratón el fondo se anima enseguida.
            self._rest_timer.setInterval(1500 if on else REST_CHECK_MS)
            self.rest_changed.emit(on)

    def _sync(self) -> None:
        try:
            self._sync_timer()
        except RuntimeError:  # al cerrar el programa Qt destruye el temporizador antes que las ventanas
            pass

    def _sync_timer(self) -> None:
        run = self.enabled and len(self._animators) > 0
        if run and not self._timer.isActive():
            self._load.sample()  # punto de partida
            self._hot = self._cool = 0
            self._timer.start()
        elif not run:
            self._timer.stop()

    def feed(self, load: float, now: float | None = None) -> None:
        """Procesa una lectura de carga (0–1). Separado de la medición para poder probarlo."""
        now = time.monotonic() if now is None else now
        self.last_load = load
        if load >= HIGH:
            self._hot += 1
            self._cool = 0
        elif load <= LOW:
            self._cool += 1
            self._hot = 0
        else:
            self._hot = self._cool = 0
        if now - self._last_change < COOLDOWN:
            return
        if self._hot >= DOWN_AFTER and self.step < len(AUTO_STEPS) - 1:
            self._set_step(self.step + 1, now)
        elif self._cool >= UP_AFTER and self.step > 0:
            self._set_step(self.step - 1, now)

    def _sample(self) -> None:
        self.feed(self._load.sample())

    def _set_step(self, step: int, now: float | None = None) -> None:
        self.step = step
        self._hot = self._cool = 0
        self._last_change = time.monotonic() if now is None else now
        if self.settings is not None:
            from aero.ui.main_window import apply_quality

            apply_quality(self.settings)
        self.step_changed.emit(step)


def auto_tuner() -> AutoTuner:
    return AutoTuner.instance()
