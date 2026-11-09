"""Recolección de ciclos solo en el hilo principal.

El recolector automático de Python se dispara en el hilo que esté reservando memoria en ese momento: una descarga,
una tarea del pool, el escáner… Si en ese ciclo cae un objeto de Qt (una ventana cerrada, un reproductor), se
destruye desde un hilo que no es el suyo y Qt no puede quitar sus temporizadores. El siguiente evento de temporizador
llega a un objeto ya destruido y la aplicación se cierra de golpe (visto en las pruebas: `sendTimerEvent` →
`notifyInternal2` sobre memoria liberada).

Aquí se desactiva el recolector automático y un temporizador del hilo principal hace lo mismo con los mismos
umbrales. Coste: una comprobación de contadores por segundo.
"""

from __future__ import annotations

import gc
import time

from PySide6.QtCore import QObject, QTimer

INTERVAL_MS = 1000
FULL_EVERY = 10          # recolecciones de la generación 1 entre dos completas
FULL_MIN_S = 30.0


class MainThreadGC(QObject):
    def __init__(self, parent: QObject | None = None, interval_ms: int = INTERVAL_MS):
        super().__init__(parent)
        self.threshold = gc.get_threshold()
        self._gen1 = 0
        self._last_full = time.monotonic()
        gc.disable()
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.check)
        self._timer.start()

    def check(self) -> int:
        """Recoge la generación que toque según los contadores (como haría Python solo). Devuelve la generación o -1.

        La generación 2 (todo el montón, la cara) no sigue el tercer umbral: en Python 3.14 vale 0 y haría una
        recolección completa cada segundo (24 % de CPU en reposo). Como Python, solo de vez en cuando: tras 10
        recolecciones de la generación 1 y como mucho una vez cada 30 s."""
        counts = gc.get_count()
        if counts[0] <= self.threshold[0]:
            return -1
        gen = 0
        if len(counts) > 1 and counts[1] >= max(1, self.threshold[1]):
            gen = 1
            self._gen1 += 1
            now = time.monotonic()
            if self._gen1 >= FULL_EVERY and now - self._last_full >= FULL_MIN_S:
                gen, self._gen1, self._last_full = 2, 0, now
        gc.collect(gen)
        return gen

    def stop(self) -> None:
        self._timer.stop()
        gc.enable()


_guard: MainThreadGC | None = None


def install(app: QObject) -> MainThreadGC:
    """Una vez por proceso, con la aplicación de Qt como dueña."""
    global _guard
    if _guard is None:
        _guard = MainThreadGC(app)
    return _guard
