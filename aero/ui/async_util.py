"""Ejecutar trabajo en segundo plano y recibir el resultado en el hilo de la interfaz."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Relay(QObject):
    done = Signal(object)
    failed = Signal(object)


_live: set[_Relay] = set()


class _Job(QRunnable):
    def __init__(self, fn, relay):
        super().__init__()
        self.fn, self.relay = fn, relay

    def run(self):
        # Se sueltan la función y el relé al empezar: PySide puede conservar el objeto Python del QRunnable después
        # de ejecutarse y, con él, todo lo que capturaban (una ventana cerrada con su imagen de decenas de MB).
        fn, relay = self.fn, self.relay
        self.fn = self.relay = None
        try:
            res = fn()
        except BaseException as e:  # noqa: BLE001 - se reenvía a la interfaz
            relay.failed.emit(e)
        else:
            relay.done.emit(res)


def run_async(fn: Callable[[], Any], on_done: Callable[[Any], None],
              on_error: Callable[[BaseException], None] | None = None, owner: QObject | None = None) -> _Relay:
    """Ejecuta `fn` en el pool global. Si `owner` se destruye antes, el resultado se descarta."""
    relay = _Relay()
    _live.add(relay)
    alive = [True]
    if owner is not None:
        owner.destroyed.connect(lambda *_: alive.__setitem__(0, False))

    def ok(res):
        _live.discard(relay)
        if alive[0]:
            on_done(res)

    def bad(err):
        _live.discard(relay)
        if alive[0] and on_error:
            on_error(err)

    relay.done.connect(ok)
    relay.failed.connect(bad)
    QThreadPool.globalInstance().start(_Job(fn, relay))
    return relay


def shutdown(timeout_ms: int = 4000) -> bool:
    """Cierre ordenado: descarta lo pendiente y espera a las tareas en marcha.

    Si el intérprete termina mientras un hilo del pool aún ejecuta Python, el proceso aborta al salir
    (0xC0000409). Devuelve False si alguna tarea no terminó a tiempo.
    """
    pool = QThreadPool.globalInstance()
    pool.clear()
    return pool.waitForDone(timeout_ms)
