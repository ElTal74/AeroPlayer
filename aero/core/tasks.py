"""Cola común de tareas: controla cuántas cosas se hacen a la vez para no saturar equipos modestos.

Clases de tarea:
* «interactive»: lo que el usuario está esperando (abrir un elemento, listar una carpeta). Sin cola.
* «background»: miniaturas, recuentos, tamaños de carpetas. Límite pequeño y prioridad LIFO (lo último
  pedido, que es lo visible, primero).
* «heavy»: conversiones, exportaciones, OCR, escaneos. Normalmente una a la vez; los procesos externos
  (FFmpeg, LibreOffice) reservan una plaza con `acquire()` y la liberan al terminar.

Mientras se reproduce vídeo las tareas en segundo plano bajan a una (`set_foreground_busy`): la reproducción
y la interfaz tienen prioridad. Las tareas en cola se pueden cancelar; las que ya corren se descartan al
terminar (no se interrumpe un hilo a la fuerza).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

KINDS = ("interactive", "background", "heavy")


@dataclass
class Ticket:
    kind: str
    fn: object
    on_done: object = None
    on_error: object = None
    owner: object = None
    cancelled: bool = False
    running: bool = False
    meta: dict = field(default_factory=dict)

    def cancel(self) -> None:
        self.cancelled = True


class TaskManager(QObject):
    slot_freed = Signal(str)
    changed = Signal()
    _inst: "TaskManager | None" = None

    def __init__(self):
        super().__init__()
        self.limits = {"background": 2, "heavy": 1}
        self.running = {"background": 0, "heavy": 0}
        self.held = 0                       # plazas pesadas reservadas por procesos externos
        self.pending: dict[str, deque[Ticket]] = {"background": deque(), "heavy": deque()}
        self.busy = False
        self._busy_owners: set[int] = set()

    @classmethod
    def instance(cls) -> "TaskManager":
        if cls._inst is None:
            cls._inst = TaskManager()
        return cls._inst

    # ------------------------------------------------------------------ límites
    def set_limits(self, background: int, heavy: int) -> None:
        self.limits = {"background": max(1, int(background)), "heavy": max(1, int(heavy))}
        self._pump()

    def limit(self, kind: str) -> int:
        n = self.limits.get(kind, 1)
        return 1 if (self.busy and kind == "background") else n

    def mark_busy(self, owner, on: bool) -> None:
        """Varios reproductores pueden estar activos (aplicación y vista rápida): basta con uno."""
        key = id(owner)
        if on:
            self._busy_owners.add(key)
        else:
            self._busy_owners.discard(key)
        self.set_foreground_busy(bool(self._busy_owners))

    def set_foreground_busy(self, on: bool) -> None:
        """Vídeo en reproducción u otra actividad sensible: menos trabajo en segundo plano."""
        if on != self.busy:
            self.busy = on
            self._pump()

    # ------------------------------------------------------------------ envío
    def submit(self, fn, kind: str = "background", on_done=None, on_error=None, owner=None) -> Ticket:
        """`fn` se ejecuta en un hilo y no debe capturar objetos Qt; `on_done/on_error` vuelven al hilo principal."""
        t = Ticket(kind if kind in KINDS else "background", fn, on_done, on_error, owner)
        if t.kind == "interactive":
            self._run(t)
        else:
            self.pending[t.kind].append(t)
            self._pump()
        return t

    def _pump(self) -> None:
        for kind in ("heavy", "background"):
            q = self.pending[kind]
            while q and self._free(kind) > 0:
                t = q.pop() if kind == "background" else q.popleft()
                if not t.cancelled:
                    self._run(t)
        self.changed.emit()

    def _free(self, kind: str) -> int:
        used = self.running[kind] + (self.held if kind == "heavy" else 0)
        return self.limit(kind) - used

    def _run(self, t: Ticket) -> None:
        from aero.ui.async_util import run_async

        t.running = True
        if t.kind in self.running:
            self.running[t.kind] += 1

        def finish():
            if t.kind in self.running:
                self.running[t.kind] -= 1
                self.slot_freed.emit(t.kind)
                self._pump()

        def release():
            # El ticket puede seguir referenciado (p. ej. por quien lo creó): sin función ni retrollamadas no
            # mantiene viva la ventana que lo pidió.
            t.fn = t.on_done = t.on_error = t.owner = None

        def ok(res):
            finish()
            cb = None if t.cancelled else t.on_done
            release()
            if cb:
                cb(res)

        def bad(err):
            finish()
            cb = None if t.cancelled else t.on_error
            release()
            if cb:
                cb(err)

        run_async(t.fn, ok, bad, t.owner)

    # ------------------------------------------------------------------ procesos externos pesados
    def acquire(self, kind: str = "heavy") -> bool:
        """Reserva una plaza pesada para un proceso externo (FFmpeg, LibreOffice). False si no hay."""
        if self._free(kind) <= 0:
            return False
        self.held += 1
        self.changed.emit()
        return True

    def release(self, kind: str = "heavy") -> None:
        self.held = max(0, self.held - 1)
        self.slot_freed.emit(kind)
        self._pump()

    def stats(self) -> dict:
        return {"background": (self.running["background"], len(self.pending["background"])),
                "heavy": (self.running["heavy"] + self.held, len(self.pending["heavy"]))}


def tasks() -> TaskManager:
    return TaskManager.instance()
