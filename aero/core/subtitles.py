"""Analizador de subtítulos externos (SRT, WebVTT, ASS/SSA) con búsqueda por tiempo."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from pathlib import Path

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_TAG = re.compile(r"<[^>]+>")
_ASS_TAG = re.compile(r"\{[^}]*\}")


@dataclass(slots=True)
class Cue:
    start: int  # ms
    end: int
    text: str


def _ms(m: re.Match) -> int:
    h = int(m.group(1) or 0)
    frac = m.group(4).ljust(3, "0")
    return ((h * 60 + int(m.group(2))) * 60 + int(m.group(3))) * 1000 + int(frac)


def read_text(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16"):
        try:
            if enc == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1252", "replace")


def parse_srt_vtt(text: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in re.split(r"\r?\n\s*\r?\n", text.replace("\r\n", "\n")):
        lines = [ln for ln in block.strip().split("\n")]
        for i, ln in enumerate(lines):
            if "-->" in ln:
                a, _, b = ln.partition("-->")
                ma, mb = _TS.search(a), _TS.search(b)
                if not (ma and mb):
                    break
                body = "\n".join(_TAG.sub("", t) for t in lines[i + 1:]).strip()
                if body:
                    cues.append(Cue(_ms(ma), _ms(mb), body))
                break
    return cues


def parse_ass(text: str) -> list[Cue]:
    cues: list[Cue] = []
    fmt: list[str] = []
    in_events = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_events = s.lower() == "[events]"
            continue
        if not in_events:
            continue
        if s.lower().startswith("format:"):
            fmt = [f.strip().lower() for f in s[7:].split(",")]
        elif s.lower().startswith("dialogue:") and fmt:
            parts = s[9:].split(",", len(fmt) - 1)
            if len(parts) < len(fmt):
                continue
            d = dict(zip(fmt, parts))
            ma, mb = _TS.search(d.get("start", "")), _TS.search(d.get("end", ""))
            if not (ma and mb):
                continue
            body = _ASS_TAG.sub("", d.get("text", "")).replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
            if body.strip():
                cues.append(Cue(_ms(ma), _ms(mb), body.strip()))
    return cues


class SubtitleTrack:
    def __init__(self, cues: list[Cue], name: str = ""):
        self.cues = sorted(cues, key=lambda c: c.start)
        self._starts = [c.start for c in self.cues]
        self.name = name

    @classmethod
    def load(cls, path: str | Path) -> "SubtitleTrack":
        text = read_text(path)
        ext = Path(path).suffix.lower()
        cues = parse_ass(text) if ext in (".ass", ".ssa") else parse_srt_vtt(text)
        if not cues:
            raise ValueError("El archivo no contiene subtítulos reconocibles.")
        return cls(cues, Path(path).name)

    def text_at(self, ms: int) -> str:
        i = bisect.bisect_right(self._starts, ms)
        out = []
        # Pueden solaparse varias líneas: revisar unas pocas hacia atrás.
        for c in self.cues[max(0, i - 4):i]:
            if c.start <= ms < c.end:
                out.append(c.text)
        return "\n".join(out)


def find_sidecar(media_path: str | Path) -> Path | None:
    """Busca un subtítulo con el mismo nombre que el vídeo (pelicula.srt, pelicula.es.srt...)."""
    p = Path(media_path)
    try:
        for cand in sorted(p.parent.iterdir()):
            if cand.suffix.lower() in (".srt", ".vtt", ".ass", ".ssa") and cand.stem.split(".")[0] == p.stem.split(".")[0]:
                return cand
    except OSError:
        return None
    return None
