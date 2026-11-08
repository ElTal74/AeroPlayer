"""Centro de tareas: un registro común de las operaciones largas (extraer, comprimir, convertir, exportar…).

Cada módulo informa de sus operaciones aquí (inicio, avance, fin o error) y la interfaz las muestra juntas,
con la posibilidad de cancelar. Las terminadas pasan al historial, que se guarda en disco (las últimas 200).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal

RUNNING, DONE, ERROR, CANCELLED = "running", "done", "error", "cancelled"
STATE_LABELS = {RUNNING: "En curso", DONE: "Terminada", ERROR: "Error", CANCELLED: "Cancelada"}
KIND_LABELS = {"extract": "Extraer", "compress": "Comprimir", "convert": "Convertir", "export": "Exportar vídeo",
               "image": "Exportar imagen", "torrent": "Descarga BitTorrent", "other": "Tarea"}
HISTORY_MAX = 200


@dataclass
class Activity:
    name: str
    kind: str = "other"
    state: str = RUNNING
    progress: float | None = None     # 0–1; None = desconocido
    detail: str = ""
    result: str = ""                  # ruta del resultado (carpeta o archivo)
    error: str = ""
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    @property
    def elapsed(self) -> float:
        return (self.finished or time.time()) - self.started


class ActivityCenter(QObject):
    changed = Signal()
    _inst: "ActivityCenter | None" = None

    def __init__(self):
        super().__init__()
        self.active: dict[str, Activity] = {}
        self.history: list[Activity] = []
        self._cancel: dict[str, object] = {}
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1500)
        self._save_timer.timeout.connect(self.save)
        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.setInterval(250)   # el avance se agrupa: como mucho 4 avisos por segundo
        self._emit_timer.timeout.connect(self.changed.emit)
        self._load()

    @classmethod
    def instance(cls) -> "ActivityCenter":
        if cls._inst is None:
            cls._inst = ActivityCenter()
        return cls._inst

    # ------------------------------------------------------------------ registro
    def start(self, name: str, kind: str = "other", cancel=None) -> str:
        a = Activity(name, kind)
        self.active[a.id] = a
        if cancel is not None:
            self._cancel[a.id] = cancel
        self.changed.emit()
        return a.id

    def update(self, aid: str, progress: float | None = None, detail: str | None = None) -> None:
        a = self.active.get(aid)
        if a is None:
            return
        if progress is not None:
            a.progress = max(0.0, min(1.0, progress))
        if detail is not None:
            a.detail = detail
        if not self._emit_timer.isActive():
            self._emit_timer.start()

    def finish(self, aid: str, state: str = DONE, result: str = "", error: str = "") -> None:
        a = self.active.pop(aid, None)
        self._cancel.pop(aid, None)
        if a is None:
            return
        a.state, a.result, a.error, a.finished = state, result, error, time.time()
        if state == DONE:
            a.progress = 1.0
        self.history.insert(0, a)
        del self.history[HISTORY_MAX:]
        self._save_timer.start()
        self.changed.emit()

    def cancel(self, aid: str) -> bool:
        fn = self._cancel.get(aid)
        if fn is None:
            return False
        fn()
        return True

    def can_cancel(self, aid: str) -> bool:
        return aid in self._cancel

    def clear_history(self) -> None:
        self.history.clear()
        self.save()
        self.changed.emit()

    # ------------------------------------------------------------------ disco
    @staticmethod
    def _path():
        from aero.core.paths import data_dir

        return data_dir() / "activity.json"

    def save(self) -> None:
        path = self._path()
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(a) for a in self.history], ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass

    def _load(self) -> None:
        try:
            raw = json.loads(self._path().read_text(encoding="utf-8"))
            fields = set(Activity.__dataclass_fields__)
            self.history = [Activity(**{k: v for k, v in d.items() if k in fields}) for d in raw][:HISTORY_MAX]
        except (OSError, ValueError, TypeError):
            self.history = []


def activities() -> ActivityCenter:
    return ActivityCenter.instance()
