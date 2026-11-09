"""Letras de canciones: archivo .lrc junto a la canción o letra incrustada en las etiquetas.

* `.lrc` con el mismo nombre (también «cancion.mp3.lrc»): líneas `[mm:ss.xx] texto`, varias marcas por línea,
  `[offset:±ms]`; se ignoran las cabeceras `[ar:]`, `[ti:]`…
* Etiquetas: ID3 USLT (MP3), LYRICS / UNSYNCEDLYRICS (FLAC, OGG, Opus) y ©lyr (M4A). Si su texto trae marcas
  LRC, se sincroniza igual.
* Sin marcas de tiempo, la letra se muestra entera sin seguir la canción.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from pathlib import Path

_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_OFFSET = re.compile(r"\[offset:\s*([+-]?\d+)\]", re.I)
_HEADER = re.compile(r"^\[[a-z]+:.*\]$", re.I)
MAX_BYTES = 512 * 1024


@dataclass
class Lyrics:
    lines: list[tuple[int, str]] = field(default_factory=list)   # (ms, texto); ms = -1 si no está sincronizada
    synced: bool = False
    source: str = ""                                              # «lrc» o «etiquetas»

    def __post_init__(self):
        self._times = [t for t, _ in self.lines]      # se consulta varias veces por segundo: lista ya hecha

    def index_at(self, ms: int) -> int:
        """Línea que suena en `ms` (-1 antes de la primera)."""
        if not self.synced or not self.lines:
            return -1
        return bisect.bisect_right(self._times, ms) - 1

    @property
    def text(self) -> str:
        return "\n".join(t for _, t in self.lines)


def parse(text: str) -> Lyrics:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    m = _OFFSET.search(text)
    offset = int(m.group(1)) if m else 0
    timed: list[tuple[int, str]] = []
    plain: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        stamps = list(_TAG.finditer(line))
        if stamps and stamps[0].start() == 0:
            body = _TAG.sub("", line).strip()
            for s in stamps:
                mm, ss, frac = int(s.group(1)), int(s.group(2)), s.group(3) or "0"
                ms = (mm * 60 + ss) * 1000 + int(frac.ljust(3, "0")[:3])
                timed.append((max(0, ms - offset), body))
        elif line and not _HEADER.match(line):
            plain.append(line)
    if timed:
        timed.sort(key=lambda x: x[0])
        return Lyrics(timed, True)
    return Lyrics([(-1, t) for t in plain], False)


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def lrc_candidates(song: Path) -> list[Path]:
    return [song.with_suffix(".lrc"), song.with_suffix(".LRC"), Path(str(song) + ".lrc")]


def from_tags(song: Path) -> str | None:
    """Texto de la letra incrustada (o None)."""
    from aero.core.metadata import _mg

    mg = _mg()
    if mg is None:
        return None
    try:
        f = mg.File(str(song))
    except Exception:  # noqa: BLE001 - archivo dañado o formato raro: sin letra
        return None
    tags = getattr(f, "tags", None)
    if not tags:
        return None
    try:
        if hasattr(tags, "getall"):                              # ID3
            frames = tags.getall("USLT")
            if frames:
                return str(frames[0].text)
            return None
        for key in ("LYRICS", "UNSYNCEDLYRICS", "lyrics", "unsyncedlyrics", "\xa9lyr"):
            if key in tags:
                v = tags[key]
                return str(v[0] if isinstance(v, list) and v else v)
    except Exception:  # noqa: BLE001
        return None
    return None


def load(path: str) -> Lyrics | None:
    """Letra de la canción o None. Lee disco: llamar en un hilo."""
    song = Path(path)
    for cand in lrc_candidates(song):
        if cand.is_file():
            text = _read_text(cand)
            if text:
                ly = parse(text)
                if ly.lines:
                    ly.source = "lrc"
                    return ly
    text = from_tags(song)
    if text and text.strip():
        ly = parse(text)
        if ly.lines:
            ly.source = "etiquetas"
            return ly
    return None
