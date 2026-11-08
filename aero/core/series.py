"""Detección de series, temporadas y episodios a partir del nombre del archivo y de la carpeta."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from aero.core.formats import VIDEO

_SE = re.compile(r"^(?P<show>.*?)[\s._\-\[(]*[Ss](?P<s>\d{1,2})[\s._\-]*[Ee][Pp]?(?P<e>\d{1,3})(?P<rest>.*)$")
_X = re.compile(r"^(?P<show>.*?)[\s._\-\[(]+(?P<s>\d{1,2})x(?P<e>\d{2,3})(?P<rest>.*)$")
_SEASON_DIR = re.compile(r"^(?:season|temporada|temp|staffel|saison|s|t)[\s._\-]*(?P<s>\d{1,2})$", re.I)
_EP_ONLY = re.compile(r"^(?:.*?[\s._\-])?(?:e|ep|episodio|episode|cap|capitulo|capítulo)[\s._\-]*(?P<e>\d{1,3})\b|^(?P<n>\d{1,3})(?:[\s._\-]|$)",
                      re.I)
_NOISE = re.compile(r"\b(?:\d{3,4}p|x26[45]|h\.?26[45]|hevc|web-?dl|webrip|bluray|brrip|hdtv|dvdrip|aac|ac3|dts|"
                    r"10bit|8bit|multi|dual|esp|spa|eng|lat|subs?)\b.*$", re.I)


@dataclass(frozen=True)
class Episode:
    path: str
    show: str
    season: int
    episode: int
    title: str

    @property
    def code(self) -> str:
        return f"T{self.season} · E{self.episode:02d}"


def _clean(name: str) -> str:
    name = re.sub(r"[._]+", " ", name)
    name = _NOISE.sub("", name)
    name = re.sub(r"\(\s*(19|20)\d{2}\s*\)|\[[^\]]*\]", "", name)
    return re.sub(r"\s{2,}", " ", name).strip(" -–·")


def parse_episode(path: str | os.PathLike) -> Episode | None:
    p = Path(path)
    if p.suffix.lower() not in VIDEO:
        return None
    stem = p.stem
    for rx in (_SE, _X):
        m = rx.match(stem)
        if m:
            show = _clean(m.group("show")) or _show_from_folders(p)
            if not show:
                return None
            return Episode(str(p), show, int(m.group("s")), int(m.group("e")), _clean(m.group("rest")))
    # Estructura de carpetas: Serie/Temporada 2/05 - Título.mkv
    parent = p.parent.name
    sm = _SEASON_DIR.match(parent.strip())
    if sm:
        em = _EP_ONLY.match(stem)
        if em:
            num = em.group("e") or em.group("n")
            show = _clean(p.parent.parent.name)
            if show and num:
                title = _clean(re.sub(r"^\d{1,3}[\s._\-]*", "", stem))
                return Episode(str(p), show, int(sm.group("s")), int(num), title)
    return None


def _show_from_folders(p: Path) -> str:
    parent = p.parent
    if _SEASON_DIR.match(parent.name.strip()):
        parent = parent.parent
    return _clean(parent.name)


def group_series(paths: list[str]) -> dict[str, list[Episode]]:
    """Serie → episodios ordenados por temporada y número."""
    shows: dict[str, list[Episode]] = {}
    for path in paths:
        ep = parse_episode(path)
        if ep:
            shows.setdefault(ep.show.casefold(), []).append(ep)
    out = {}
    for eps in shows.values():
        eps.sort(key=lambda e: (e.season, e.episode, e.path))
        out[eps[0].show] = eps
    return dict(sorted(out.items(), key=lambda kv: kv[0].casefold()))


def episodes_from(path: str, episodes: list[Episode]) -> list[str]:
    """Cola de reproducción desde un episodio hasta el final de la serie (siguiente episodio automático)."""
    paths = [e.path for e in episodes]
    return paths[paths.index(path):] if path in paths else [path]


def folder_episodes(path: str) -> list[str]:
    """Episodios de la misma serie en la carpeta del archivo, desde ese episodio (para abrir desde el Explorador)."""
    ep = parse_episode(path)
    if ep is None:
        return [path]
    try:
        siblings = [str(f) for f in Path(path).parent.iterdir() if f.suffix.lower() in VIDEO]
    except OSError:
        return [path]
    same = [e for e in (parse_episode(s) for s in siblings) if e and e.show.casefold() == ep.show.casefold()]
    same.sort(key=lambda e: (e.season, e.episode))
    return episodes_from(path, same)
