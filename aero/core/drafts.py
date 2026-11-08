"""Borradores automáticos de los editores y recuperación tras un cierre inesperado.

Cada editor con cambios sin guardar escribe cada minuto una copia en `data_dir()/drafts` (el archivo del usuario
no se toca). Al cerrar el editor con normalidad, o al guardar, el borrador se borra. Si AERO Player se cierra de
golpe, en el siguiente inicio se ofrece recuperar los borradores cuyo proceso ya no está vivo.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

KINDS = {"paint": "AERO Paint", "video": "Editor de vídeo", "image": "Editor de imágenes"}
INTERVAL_MS = 60_000


def folder() -> Path:
    from aero.core.paths import data_dir

    d = data_dir() / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Draft:
    kind: str
    ext: str
    title: str = ""
    source: str = ""            # archivo original o proyecto del usuario (vacío si no se había guardado)
    saved: float = 0.0
    pid: int = field(default_factory=os.getpid)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def path(self) -> Path:
        return folder() / f"{self.id}{self.ext}"

    @property
    def meta_path(self) -> Path:
        return folder() / f"{self.id}.json"


def pid_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes

    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def all_drafts() -> list[Draft]:
    out = []
    fields = set(Draft.__dataclass_fields__)
    base = folder()
    old = time.time() - 3600
    for part in base.glob("*.part*"):  # escrituras que se cortaron (cierre a mitad de un borrador)
        try:
            if part.stat().st_mtime < old:
                part.unlink()
        except OSError:
            pass
    for m in base.glob("*.json"):
        try:
            d = Draft(**{k: v for k, v in json.loads(m.read_text(encoding="utf-8")).items() if k in fields})
        except (OSError, ValueError, TypeError):
            continue
        if d.path.exists():
            out.append(d)
    return sorted(out, key=lambda d: d.saved, reverse=True)


def pending() -> list[Draft]:
    """Borradores que dejó una sesión que ya no está abierta (cierre inesperado)."""
    return [d for d in all_drafts() if not pid_alive(d.pid)]


def discard(d: Draft) -> None:
    for p in (d.path, d.meta_path):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


class Autosaver(QObject):
    """Guarda un borrador del editor cada minuto mientras haya cambios sin guardar.

    `dirty()` dice si hay cambios, `write(ruta)` escribe el borrador, `token()` (opcional) identifica la versión
    para no reescribir lo mismo, `title()` y `source()` describen el trabajo en la lista de recuperación y
    `busy()` (opcional) aplaza el guardado mientras el usuario está a mitad de un trazo.

    Con `background=True`, `write()` se llama en el hilo principal y devuelve una función `job(ruta)` que escribe
    una copia del documento en segundo plano: con imágenes grandes la edición no se congela cada minuto.
    """

    def __init__(self, owner: QObject, kind: str, ext: str, dirty, write, title, source, token=None,
                 settings=None, interval: int = INTERVAL_MS, busy=None, background: bool = False):
        super().__init__(owner)
        self.draft = Draft(kind, ext)
        self._dirty, self._write, self._title, self._source, self._token = dirty, write, title, source, token
        self._busy, self._background = busy, background
        self._settings = settings
        self._last = object()
        self._gen = 0              # cambia al descartar: una escritura en curso ya no debe publicarse
        self.writing = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval)
        self._timer.timeout.connect(self.tick)
        self._timer.start()

    def enabled(self) -> bool:
        return self._settings is None or bool(self._settings.get("autosave_drafts"))

    def tick(self) -> bool:
        """Escribe el borrador si hace falta. Devuelve True si lo ha escrito (o empezado a escribir)."""
        if self.writing:
            return False
        try:
            dirty = self._dirty()
            busy = bool(self._busy()) if self._busy else False
        except (AttributeError, RuntimeError):
            return False
        if not dirty or not self.enabled():
            if not dirty:
                self.discard()
            return False
        if busy:
            return False
        token = self._token() if self._token else None
        if token is not None and token == self._last and self.draft.path.exists():
            return False
        d = self.draft
        tmp = d.path.with_name(d.path.stem + ".part" + d.ext)
        try:
            title, source = self._title(), self._source() or ""
            if self._background:
                job = self._write()   # copia del documento, en el hilo principal
                gen = self._gen
                self.writing = True
                from aero.ui.async_util import run_async

                run_async(lambda: job(str(tmp)), lambda _r: self._published(tmp, title, source, token, gen),
                          lambda _e: self._failed(tmp), self)
                return True
            self._write(str(tmp))
        except Exception:  # noqa: BLE001 - un borrador fallido nunca debe interrumpir la edición
            self._failed(tmp)
            return False
        return self._published(tmp, title, source, token, self._gen)

    def _published(self, tmp: Path, title: str, source: str, token, gen: int) -> bool:
        self.writing = False
        d = self.draft
        if gen != self._gen:   # se guardó o se cerró mientras tanto: el borrador ya no sirve
            self._failed(tmp)
            return False
        try:
            os.replace(tmp, d.path)
            d.title, d.source, d.saved = title, source, time.time()
            meta_tmp = d.meta_path.with_suffix(".tmp")
            meta_tmp.write_text(json.dumps(asdict(d), ensure_ascii=False), encoding="utf-8")
            os.replace(meta_tmp, d.meta_path)
        except OSError:
            self._failed(tmp)
            return False
        self._last = token
        return True

    def _failed(self, tmp: Path) -> None:
        self.writing = False
        try:
            tmp.unlink()
        except OSError:
            pass

    def discard(self) -> None:
        self._last = object()
        self._gen += 1
        if self.draft.path.exists() or self.draft.meta_path.exists():
            discard(self.draft)

    def stop(self) -> None:
        """Cierre normal del editor: sin borrador pendiente."""
        self._timer.stop()
        self.discard()
