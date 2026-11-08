"""Proyecto del editor de vídeo (sin interfaz): pistas, clips, edición y guardado.

Edición no lineal: cada clip apunta a su archivo original con un punto de entrada y de salida; nada se
modifica en disco. El proyecto se guarda como JSON (`.aerovid`) con rutas absolutas; al abrirlo se marcan
los medios que ya no existen.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field

from aero.editors.video.effects import TRANSITIONS as _FX_TRANSITIONS

PROJECT_EXT = ".aerovid"
TRANSITIONS = {"none": "Ninguna", **{k: t.name for k, t in _FX_TRANSITIONS.items()}}
ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:3": (1440, 1080),
           "21:9": (2560, 1080)}


@dataclass
class Clip:
    src: str = ""
    kind: str = "video"            # video | audio | image | text
    start: float = 0.0             # posición en la línea de tiempo (s)
    in_s: float = 0.0              # entrada en el archivo original (s)
    out_s: float = 5.0             # salida en el archivo original (s); en imágenes y textos, duración
    speed: float = 1.0
    volume: float = 1.0
    muted: bool = False
    fade_in: float = 0.0
    fade_out: float = 0.0
    transition: str = "none"       # entrada del clip
    transition_d: float = 0.6
    brightness: float = 0.0        # −1…1
    contrast: float = 1.0          # 0…2
    saturation: float = 1.0        # 0…3
    gamma: float = 1.0
    rotation: int = 0              # 0, 90, 180, 270
    scale: float = 1.0             # sobre el encaje en el lienzo
    pos_x: float = 0.0             # desplazamiento desde el centro (−1…1 = medio lienzo a cada lado)
    pos_y: float = 0.0
    angle: float = 0.0             # giro libre en grados (además de `rotation`)
    opacity: float = 1.0           # 0…1
    sx: float = 1.0                # estiramiento horizontal sobre scale (escala X = scale·sx)
    sy: float = 1.0                # estiramiento vertical (escala Y = scale·sy)
    anchor_x: float = 0.0          # punto de anclaje (−1…1 sobre el propio elemento; 0 = centro): giro y escala
    anchor_y: float = 0.0
    src_w: int = 0                 # tamaño del medio original (para colocar igual en el visor y al exportar)
    src_h: int = 0
    effects: list = field(default_factory=list)   # [{"id", "on", "params"}] (aero.editors.video.effects)
    crop: list = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])   # izq., arr., der., abajo (fracciones)
    text: str = ""
    text_size: int = 72
    text_color: str = "#ffffff"
    text_pos: str = "center"       # top | center | bottom
    has_audio: bool = True
    src_duration: float = 0.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    @property
    def duration(self) -> float:
        span = max(0.04, self.out_s - self.in_s)
        return span / self.speed if self.kind in ("video", "audio") else span

    @property
    def end(self) -> float:
        return self.start + self.duration

    def missing(self) -> bool:
        return self.kind != "text" and not os.path.exists(self.src)


@dataclass
class Track:
    kind: str = "video"            # video | audio
    name: str = "V1"
    muted: bool = False
    hidden: bool = False
    clips: list[Clip] = field(default_factory=list)
    locked: bool = False           # bloqueada: sus clips no se mueven, recortan ni transforman

    def sort(self):
        self.clips.sort(key=lambda c: c.start)


@dataclass
class Project:
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    tracks: list[Track] = field(default_factory=lambda: [Track("video", "V2"), Track("video", "V1"),
                                                         Track("audio", "A1"), Track("audio", "A2")])
    export: dict = field(default_factory=lambda: {"format": "mp4", "codec": "h264", "quality": 23,
                                                  "audio_kbps": 192, "folder": ""})
    path: str = ""

    # ------------------------------------------------------------------ consultas
    @property
    def duration(self) -> float:
        return max((c.end for t in self.tracks for c in t.clips), default=0.0)

    def all_clips(self):
        for t in self.tracks:
            for c in t.clips:
                yield t, c

    def find(self, clip_id: str) -> tuple[Track, Clip] | tuple[None, None]:
        for t, c in self.all_clips():
            if c.id == clip_id:
                return t, c
        return None, None

    def video_tracks_bottom_up(self) -> list[Track]:
        return list(reversed([t for t in self.tracks if t.kind == "video"]))

    def top_clip_at(self, t: float) -> Clip | None:
        """Clip de vídeo/imagen visible en el instante t (la pista superior manda)."""
        for tr in (x for x in self.tracks if x.kind == "video" and not x.hidden):
            for c in tr.clips:
                if c.kind in ("video", "image") and c.start <= t < c.end:
                    return c
        return None

    def missing_media(self) -> list[str]:
        return sorted({c.src for _t, c in self.all_clips() if c.missing()})

    # ------------------------------------------------------------------ edición
    def add_clip(self, track: Track, clip: Clip, at: float | None = None) -> Clip:
        clip.start = max(0.0, track.clips[-1].end if at is None and track.clips else (at or 0.0))
        track.clips.append(clip)
        track.sort()
        return clip

    def split(self, clip_id: str, t: float) -> Clip | None:
        """Divide un clip en el instante t de la línea de tiempo. Devuelve la segunda mitad."""
        track, c = self.find(clip_id)
        if c is None or not (c.start + 0.04 < t < c.end - 0.04):
            return None
        offset = (t - c.start) * (c.speed if c.kind in ("video", "audio") else 1.0)
        second = Clip(**{**asdict(c), "id": uuid.uuid4().hex[:10]})
        second.in_s = c.in_s + offset
        second.start = t
        second.fade_in, second.transition = 0.0, "none"
        c.out_s = c.in_s + offset
        c.fade_out = 0.0
        track.clips.append(second)
        track.sort()
        return second

    def trim(self, clip_id: str, edge: str, t: float) -> None:
        """Recorta el principio («in») o el final («out») hasta el instante t de la línea de tiempo."""
        _tr, c = self.find(clip_id)
        if c is None or _tr.locked:
            return
        k = c.speed if c.kind in ("video", "audio") else 1.0
        limit = c.src_duration if c.kind in ("video", "audio") and c.src_duration else None
        if edge == "in":
            t = min(t, c.end - 0.1)
            new_in = c.in_s + (t - c.start) * k
            if new_in < 0:
                t -= new_in / k
                new_in = 0.0
            c.in_s, c.start = new_in, max(0.0, t)
        else:
            new_out = c.in_s + max(0.1, t - c.start) * k
            c.out_s = min(new_out, limit) if limit else new_out

    def move(self, clip_id: str, start: float, track: Track | None = None) -> None:
        tr, c = self.find(clip_id)
        if c is None or tr.locked:
            return   # pista bloqueada: sus clips no se mueven
        c.start = max(0.0, start)
        if track is not None and track is not tr and track.kind == tr.kind and not track.locked:
            tr.clips.remove(c)
            track.clips.append(c)
            tr = track
        tr.sort()

    def set_duration(self, clip_id: str, seconds: float) -> None:
        """Duración en la línea de tiempo (imágenes y textos; en vídeo y audio, ajusta la salida)."""
        _tr, c = self.find(clip_id)
        if c is None:
            return
        seconds = max(0.1, seconds)
        if c.kind in ("video", "audio"):
            out = c.in_s + seconds * c.speed
            c.out_s = min(out, c.src_duration) if c.src_duration else out
        else:
            c.out_s = c.in_s + seconds

    def to_layer(self, clip_id: str, delta: int) -> Track | None:
        """Sube (delta < 0, más arriba = encima) o baja el clip a la pista vecina del mismo tipo; si no hay,
        crea una. Devuelve la pista de destino."""
        tr, c = self.find(clip_id)
        if c is None:
            return None
        same = [t for t in self.tracks if t.kind == tr.kind]
        i = same.index(tr) + (-1 if delta < 0 else 1)
        if 0 <= i < len(same):
            dest = same[i]
        else:
            n = len(same) + 1
            dest = Track(tr.kind, f"{'V' if tr.kind == 'video' else 'A'}{n}")
            pos = self.tracks.index(same[0]) if i < 0 else self.tracks.index(same[-1]) + 1
            self.tracks.insert(pos, dest)
        tr.clips.remove(c)
        dest.clips.append(c)
        dest.sort()
        return dest

    def move_track(self, track: Track, delta: int) -> None:
        """Reordena una pista entre las de su tipo (las de vídeo de arriba tapan a las de abajo)."""
        same = [t for t in self.tracks if t.kind == track.kind]
        i = same.index(track)
        j = max(0, min(len(same) - 1, i + delta))
        if i == j:
            return
        a, b = self.tracks.index(same[i]), self.tracks.index(same[j])
        self.tracks[a], self.tracks[b] = self.tracks[b], self.tracks[a]

    def remove_track(self, track: Track) -> bool:
        if sum(1 for t in self.tracks if t.kind == track.kind) <= 1:
            return False  # siempre queda al menos una pista de cada tipo
        self.tracks.remove(track)
        return True

    def delete(self, clip_ids: list[str]) -> None:
        for t in self.tracks:
            t.clips = [c for c in t.clips if c.id not in clip_ids]

    def ripple_delete_range(self, a: float, b: float) -> None:
        """Elimina el fragmento [a, b] de todas las pistas y junta lo que queda detrás."""
        if b <= a:
            return
        for t in self.tracks:
            for c in list(t.clips):
                if c.end <= a:
                    continue
                if c.start >= b:
                    c.start -= b - a
                    continue
                if c.start < a < c.end:
                    second = self.split(c.id, a)
                    if second is not None and second.end > b:
                        self.split(second.id, b)
            for c in list(t.clips):
                if a <= c.start and c.end <= b + 1e-6:
                    t.clips.remove(c)
            for c in t.clips:
                if c.start >= b - 1e-6:
                    c.start -= b - a
            t.sort()

    def set_aspect(self, key: str, height: int | None = None) -> None:
        w, h = ASPECTS[key]
        if height:
            w, h = int(round(w * height / max(w, h) if w > h else w * height / h)), height
            w -= w % 2
        self.width, self.height = w, h

    # ------------------------------------------------------------------ guardado
    def to_json(self) -> str:
        data = {"format": "aero_video_project", "version": 1, "width": self.width, "height": self.height,
                "fps": self.fps, "export": self.export,
                "tracks": [{"kind": t.kind, "name": t.name, "muted": t.muted, "hidden": t.hidden, "locked": t.locked,
                            "clips": [asdict(c) for c in t.clips]} for t in self.tracks]}
        return json.dumps(data, ensure_ascii=False, indent=1)

    def save(self, path: str) -> None:
        tmp = path + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())
        os.replace(tmp, path)
        self.path = path

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("format") != "aero_video_project":
            raise ValueError("No es un proyecto de vídeo de AERO Player.")
        fields = set(Clip.__dataclass_fields__)
        tracks = [Track(t["kind"], t["name"], t.get("muted", False), t.get("hidden", False),
                        [Clip(**{k: v for k, v in c.items() if k in fields}) for c in t["clips"]],
                        bool(t.get("locked", False)))
                  for t in data["tracks"]]
        p = cls(int(data["width"]), int(data["height"]), float(data["fps"]), tracks,
                {**cls().export, **data.get("export", {})}, path)
        return p


# --------------------------------------------------------------------------- medios
def media_info(path: str) -> dict:
    """Duración, dimensiones, fps y si tiene audio/vídeo (ffprobe). Las imágenes no necesitan ffprobe."""
    from aero.core import tools
    from aero.core.formats import kind_of

    k = kind_of(path)
    if k == "image":
        from PySide6.QtGui import QImageReader

        s = QImageReader(path).size()
        return {"kind": "image", "duration": 5.0, "width": s.width(), "height": s.height(), "fps": 0,
                "has_audio": False, "has_video": True}
    info = tools.probe(path) or {}
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get(
        "attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = float(info.get("format", {}).get("duration") or (v or a or {}).get("duration") or 0)
    fps = 0.0
    if v and v.get("avg_frame_rate", "0/0") != "0/0":
        n, d = v["avg_frame_rate"].split("/")
        fps = float(n) / float(d) if float(d) else 0.0
    vw, vh = (int(v["width"]), int(v["height"])) if v else (0, 0)
    if v and any(abs(int(float(d.get("rotation", 0)))) % 180 == 90 for d in v.get("side_data_list", [])):
        vw, vh = vh, vw   # vídeo de móvil girado por metadatos: FFmpeg lo endereza al decodificar
    return {"kind": "video" if v else "audio", "duration": dur, "width": vw,
            "height": vh, "fps": fps, "has_audio": a is not None, "has_video": v is not None}


def clip_from_media(path: str, info: dict) -> Clip:
    kind = info["kind"]
    dur = info["duration"] or 5.0
    return Clip(src=os.path.abspath(path), kind=kind, in_s=0.0, out_s=dur, has_audio=info.get("has_audio", False),
                src_duration=dur if kind in ("video", "audio") else 0.0, src_w=int(info.get("width") or 0),
                src_h=int(info.get("height") or 0))
