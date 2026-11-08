"""Lógica pura de conversión: destinos posibles, nombres de salida seguros y argumentos de FFmpeg.

Sin dependencias de interfaz para poder probarse de forma unitaria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from aero.core.formats import kind_of

PRESETS = {
    "equilibrado": "Equilibrado",
    "alta": "Alta calidad",
    "reducido": "Tamaño reducido",
    "dispositivos": "Compatible con dispositivos",
    "moviles": "Compatible con móviles",
    "windows": "Compatible con Windows",
    "conservar": "Conservar calidad (sin recomprimir si es posible)",
}

IMAGE_TARGETS = [("jpg", "JPG"), ("png", "PNG"), ("webp", "WebP"), ("avif", "AVIF"), ("bmp", "BMP"),
                 ("tiff", "TIFF"), ("gif", "GIF"), ("ico", "ICO (icono)"), ("pdf", "PDF")]
AUDIO_TARGETS = [("mp3", "MP3"), ("m4a", "AAC (M4A)"), ("flac", "FLAC (sin pérdida)"), ("wav", "WAV"),
                 ("ogg", "OGG Vorbis"), ("opus", "Opus")]
VIDEO_TARGETS = [("mp4", "MP4"), ("mkv", "MKV"), ("webm", "WebM"), ("mov", "MOV"), ("avi", "AVI"),
                 ("gif", "GIF animado")]
VIDEO_CODECS = {"auto": "Automático", "h264": "H.264 (máxima compatibilidad)", "h265": "H.265 / HEVC",
                "vp9": "VP9", "av1": "AV1 (más eficiente, más lento)"}
CONTAINER_VIDEO = {
    "mp4": ("h264", "h265", "av1"), "mov": ("h264", "h265"), "mkv": ("h264", "h265", "vp9", "av1"),
    "webm": ("vp9", "av1"), "avi": ("mpeg4",), "gif": ("gif",),
}
# Códecs (nombre de ffprobe) que pueden copiarse tal cual a cada contenedor.
REMUX_OK = {
    "mp4": ({"h264", "hevc", "av1", "mpeg4"}, {"aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"}),
    "mov": ({"h264", "hevc", "mpeg4", "prores", "mjpeg"}, {"aac", "mp3", "alac", "pcm_s16le", "pcm_s24le", "ac3"}),
    "mkv": (None, None),  # admite casi todo
    "webm": ({"vp8", "vp9", "av1"}, {"opus", "vorbis"}),
}
AUDIO_COVER_OK = {"mp3", "flac", "m4a"}

OFFICE_TARGETS = {
    "document": [("pdf", "PDF"), ("docx", "Word (DOCX)"), ("odt", "OpenDocument (ODT)"), ("rtf", "RTF"),
                 ("txt", "Texto (TXT)"), ("html", "HTML")],
    "sheet": [("pdf", "PDF"), ("xlsx", "Excel (XLSX)"), ("ods", "OpenDocument (ODS)"), ("csv", "CSV")],
    "slides": [("pdf", "PDF"), ("pptx", "PowerPoint (PPTX)"), ("odp", "OpenDocument (ODP)")],
}


@dataclass
class ConvertOptions:
    target: str
    preset: str = "equilibrado"
    video_codec: str = "auto"
    max_height: int = 0
    fps: int = 0
    audio: str = "auto"         # auto | none
    audio_bitrate: int = 0      # kbps; 0 = según preset
    hw: bool = True
    quality: int = 90           # imágenes 1-100
    max_side: int = 0           # imágenes: lado mayor máximo (0 = original)
    bg_color: str = "#ffffff"   # relleno al quitar transparencia
    strip_metadata: bool = False
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- destinos

def targets_for(path: str | Path, office: bool, pillow_avif: bool = True) -> list[tuple[str, str]]:
    ext = Path(path).suffix.lower().lstrip(".")
    kind = kind_of(path)
    if kind == "image":
        return [t for t in IMAGE_TARGETS if t[0] != ext and (pillow_avif or t[0] != "avif")]
    if kind == "audio":
        return [t for t in AUDIO_TARGETS if t[0] != ext]
    if kind == "video":
        return [t for t in VIDEO_TARGETS] + [(t[0], f"Solo audio · {t[1]}") for t in AUDIO_TARGETS]
    if kind == "pdf":
        # Documento editable reconstruido (estructura, estilos, tablas, imágenes; OCR si está escaneado)
        return [("docx", "Word editable (DOCX)"), ("odt", "OpenDocument editable (ODT)"), ("txt", "Texto (TXT)"),
                ("png", "Imágenes PNG (una por página)"), ("jpg", "Imágenes JPG (una por página)")]
    if kind in ("document", "sheet", "slides"):
        if office:
            return [t for t in OFFICE_TARGETS[kind] if t[0] != ext]
        builtin = {
            "document": [("html", "HTML"), ("txt", "Texto (TXT)"), ("pdf", "PDF (básico)")],
            "sheet": [("csv", "CSV (una hoja por archivo)")],
            "slides": [("txt", "Texto de las diapositivas")],
        }[kind]
        if ext in (".doc", "doc"):
            return []
        return [t for t in builtin if t[0] != ext]
    if kind == "text":
        return [("pdf", "PDF (básico)"), ("html", "HTML")]
    return []


def method_for(path: str | Path, target: str, office: bool) -> str:
    kind = kind_of(path)
    if kind in ("audio", "video"):
        return "ffmpeg"
    if kind == "image":
        return "image"
    if kind == "pdf":
        return "builtin"
    if kind in ("document", "sheet", "slides"):
        return "office" if office else "builtin"
    return "builtin"


# ----------------------------------------------------------------------------- rutas

def unique_path(path: Path) -> Path:
    """Devuelve una ruta libre añadiendo « (1)», « (2)»… sin sobrescribir nunca."""
    if not path.exists():
        return path
    stem, suf = path.stem, path.suffix
    for i in range(1, 10000):
        cand = path.with_name(f"{stem} ({i}){suf}")
        if not cand.exists():
            return cand
    raise OSError("No se encontró un nombre de archivo libre.")


def reserve_path(path: Path) -> Path:
    """Crea atómicamente un archivo vacío con un nombre libre; evita colisiones entre trabajos paralelos."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cand = unique_path(path)
    for _ in range(10000):
        try:
            with open(cand, "x"):
                return cand
        except FileExistsError:
            cand = unique_path(cand)
    raise OSError("No se encontró un nombre de archivo libre.")


def safe_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad or ord(c) < 32 else c for c in name).strip(" .")
    return cleaned or "archivo"


def output_path(src: str | Path, out_dir: str | Path, target: str, rel_dir: str = "") -> Path:
    src = Path(src)
    folder = Path(out_dir) / rel_dir if rel_dir else Path(out_dir)
    dst = folder / f"{safe_name(src.stem)}.{target}"
    if dst.resolve() == src.resolve():
        dst = folder / f"{safe_name(src.stem)} (convertido).{target}"
    return unique_path(dst)


# ----------------------------------------------------------------------------- FFmpeg

def _streams(info: dict | None, kind: str) -> list[dict]:
    if not info:
        return []
    return [s for s in info.get("streams", []) if s.get("codec_type") == kind
            and not (kind == "video" and s.get("disposition", {}).get("attached_pic"))]


def can_remux(info: dict | None, target: str) -> bool:
    if not info or target not in REMUX_OK:
        return False
    vok, aok = REMUX_OK[target]
    v = _streams(info, "video")
    a = _streams(info, "audio")
    if not v:
        return False
    if vok is not None and any(s.get("codec_name") not in vok for s in v[:1]):
        return False
    if aok is not None and any(s.get("codec_name") not in aok for s in a):
        return False
    return True


def choose_video_encoder(codec: str, target: str, encs: set[str] | frozenset[str], hw: bool,
                         hw_check: Callable[[str], bool]) -> tuple[str, str]:
    """Devuelve (encoder, familia). La familia decide los parámetros de calidad."""
    allowed = CONTAINER_VIDEO.get(target, ("h264",))
    if codec == "auto" or codec not in allowed:
        codec = allowed[0]
    if target == "avi":
        return ("mpeg4", "mpeg4")
    if hw and codec in ("h264", "h265", "av1"):
        prefix = {"h264": "h264", "h265": "hevc", "av1": "av1"}[codec]
        for vendor in ("nvenc", "qsv", "amf"):
            name = f"{prefix}_{vendor}"
            if name in encs and hw_check(name):
                return (name, vendor)
    software = {"h264": "libx264", "h265": "libx265", "vp9": "libvpx-vp9", "av1": "libsvtav1"}[codec]
    if software not in encs and codec == "av1" and "libaom-av1" in encs:
        software = "libaom-av1"
    if software not in encs:
        if "libx264" in encs:
            return ("libx264", "x264")
        raise ValueError(f"Tu FFmpeg no incluye el codificador {software}.")
    family = {"libx264": "x264", "libx265": "x265", "libvpx-vp9": "vp9", "libsvtav1": "svtav1",
              "libaom-av1": "aom"}[software]
    return (software, family)


_CRF = {  # alta, equilibrado, reducido, dispositivos, conservar
    "x264": (18, 22, 27, 21, 16), "x265": (20, 24, 29, 23, 18), "vp9": (24, 31, 37, 31, 20),
    "svtav1": (26, 32, 40, 32, 22), "aom": (26, 32, 40, 32, 22), "nvenc": (19, 24, 30, 23, 17),
    "qsv": (19, 24, 30, 23, 17), "amf": (19, 24, 30, 23, 17), "mpeg4": (3, 4, 7, 4, 2),
}
_PRESET_IDX = {"alta": 0, "equilibrado": 1, "reducido": 2, "dispositivos": 3, "conservar": 4,
               "moviles": 3, "windows": 1}
# Perfiles de compatibilidad: H.264 + AAC en 4:2:0, que reproducen todos los móviles y Windows sin extensiones.
COMPAT = {"dispositivos": 1080, "moviles": 1080, "windows": 2160}


def _video_quality_args(family: str, preset: str) -> list[str]:
    q = _CRF[family][_PRESET_IDX.get(preset, 1)]
    if family == "x264":
        return ["-crf", str(q), "-preset", "slow" if preset in ("alta", "conservar") else "medium"]
    if family == "x265":
        return ["-crf", str(q), "-preset", "medium", "-tag:v", "hvc1"]
    if family == "vp9":
        return ["-crf", str(q), "-b:v", "0", "-row-mt", "1", "-deadline", "good",
                "-cpu-used", "2" if preset == "alta" else "4"]
    if family == "svtav1":
        return ["-crf", str(q), "-preset", "5" if preset == "alta" else "7"]
    if family == "aom":
        return ["-crf", str(q), "-b:v", "0", "-cpu-used", "6", "-row-mt", "1"]
    if family == "nvenc":
        return ["-rc", "vbr", "-cq", str(q), "-b:v", "0", "-preset", "p5"]
    if family == "qsv":
        return ["-global_quality", str(q), "-preset", "medium"]
    if family == "amf":
        return ["-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q), "-quality", "balanced"]
    if family == "mpeg4":
        return ["-q:v", str(q)]
    return []


def _audio_args(target: str, preset: str, bitrate: int, info: dict | None) -> list[str]:
    i = _PRESET_IDX.get(preset, 1)
    if target == "mp3":
        args = ["-c:a", "libmp3lame"]
        return args + (["-b:a", f"{bitrate}k"] if bitrate else ["-q:a", str((0, 2, 5, 2, 0)[i])])
    if target in ("m4a", "aac", "mp4", "mov", "mkv"):
        return ["-c:a", "aac", "-b:a", f"{bitrate or (256, 192, 128, 192, 320)[i]}k"]
    if target in ("opus", "webm"):
        return ["-c:a", "libopus", "-b:a", f"{bitrate or (192, 128, 80, 128, 256)[i]}k"]
    if target == "ogg":
        return ["-c:a", "libvorbis"] + (["-b:a", f"{bitrate}k"] if bitrate else ["-q:a", str((8, 6, 4, 5, 9)[i])])
    if target == "flac":
        return ["-c:a", "flac", "-compression_level", "8" if preset == "alta" else "5"]
    if target == "wav":
        bits = 16
        for s in _streams(info, "audio")[:1]:
            try:
                bits = int(s.get("bits_per_raw_sample") or s.get("bits_per_sample") or 16)
            except ValueError:
                bits = 16
        return ["-c:a", "pcm_s24le" if bits > 16 and preset in ("alta", "conservar") else "pcm_s16le"]
    if target == "avi":
        return ["-c:a", "libmp3lame", "-b:a", "192k"]
    return []


def build_ffmpeg_args(ffmpeg: str, src: str, dst: str, opts: ConvertOptions, info: dict | None,
                      encs: set[str] | frozenset[str], hw_check: Callable[[str], bool] = lambda _n: False,
                      overwrite_reserved: bool = False) -> list[str]:
    target = opts.target
    src_kind = kind_of(src)
    audio_target = target in dict(AUDIO_TARGETS)
    has_audio = bool(_streams(info, "audio")) if info else True
    has_video = bool(_streams(info, "video")) if info else src_kind == "video"

    # -y solo cuando el destino es el marcador vacío reservado por este mismo trabajo.
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y" if overwrite_reserved else "-n", "-i", src]
    args += ["-map_metadata", "-1" if opts.strip_metadata else "0"]

    if audio_target:
        if not has_audio:
            raise ValueError("El archivo no contiene ninguna pista de audio.")
        args += ["-map", "0:a:0"]
        cover = (src_kind == "audio" and target in AUDIO_COVER_OK and info is not None and any(
            s.get("disposition", {}).get("attached_pic") for s in info.get("streams", [])))
        if cover:
            args += ["-map", "0:v:0", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        else:
            args += ["-vn"]
        if target == "mp3":
            args += ["-id3v2_version", "3"]
        args += _audio_args(target, opts.preset, opts.audio_bitrate, info)
    elif target == "gif":
        if not has_video:
            raise ValueError("El archivo no contiene vídeo.")
        width = 480 if not opts.max_height else max(160, int(opts.max_height * 16 / 9))
        fps = opts.fps or 12
        args += ["-an", "-vf", f"fps={fps},scale='min({width},iw)':-2:flags=lanczos,split[a][b];"
                               "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                 "-loop", "0"]
    else:
        if not has_video:
            raise ValueError("El archivo no contiene vídeo.")
        remux = opts.preset == "conservar" and not opts.max_height and not opts.fps and can_remux(info, target)
        args += ["-map", "0:v:0"]
        if opts.audio != "none" and has_audio:
            args += ["-map", "0:a?"]
        if target == "mkv":
            args += ["-map", "0:s?", "-c:s", "copy"]
        if remux:
            args += ["-c:v", "copy"]
            args += ["-c:a", "copy"] if opts.audio != "none" else ["-an"]
        else:
            preset = opts.preset
            compat = preset in COMPAT
            max_h = opts.max_height or COMPAT.get(preset, 0)
            codec = "h264" if compat and opts.video_codec == "auto" else opts.video_codec
            enc, family = choose_video_encoder(codec, target, encs, opts.hw, hw_check)
            args += ["-c:v", enc] + _video_quality_args(family, preset)
            if family in ("x264", "nvenc", "qsv", "amf") or compat:
                args += ["-pix_fmt", "yuv420p"]
            if compat and family == "x264":
                args += ["-profile:v", "high", "-level", "5.1" if max_h > 1080 else "4.1"]
            if preset == "moviles" and not opts.fps:
                args += ["-fpsmax", "60"]
            filters = []
            if max_h and compat and not opts.max_height:
                # Perfiles de compatibilidad: el límite es el lado corto (un vídeo vertical 1080×1920 es «1080p»).
                filters.append(f"scale='if(gte(iw,ih),-2,min({max_h},iw))':'if(gte(iw,ih),min({max_h},ih),-2)'")
            elif max_h:
                filters.append(f"scale=-2:'min({max_h},ih)'")
            if filters:
                args += ["-vf", ",".join(filters)]
            if opts.fps:
                args += ["-r", str(opts.fps)]
            if opts.audio == "none" or not has_audio:
                args += ["-an"]
            else:
                args += _audio_args(target, preset, opts.audio_bitrate, info)
        if target in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]
    args += ["-progress", "pipe:1", "-nostats", dst]
    return args


def friendly_ffmpeg_error(stderr_tail: str) -> str:
    s = stderr_tail.lower()
    if "no space left" in s:
        return "No queda espacio en el disco de destino."
    if "permission denied" in s:
        return "Sin permiso para leer el archivo o escribir en la carpeta de destino."
    if "invalid data found" in s or "moov atom not found" in s:
        return "El archivo está dañado o no es un formato multimedia válido."
    if "does not contain any stream" in s or "matches no streams" in s:
        return "El archivo no contiene las pistas necesarias para esta conversión."
    if "unknown encoder" in s or "encoder not found" in s:
        return "Tu FFmpeg no incluye el códec necesario."
    if "already exists" in s:
        return "El archivo de destino ya existe."
    if "could not open encoder" in s or "error while opening encoder" in s:
        return "No se pudo iniciar el codificador (prueba a desactivar la aceleración por hardware)."
    lines = [ln for ln in stderr_tail.strip().splitlines() if ln.strip()]
    return lines[-1][:300] if lines else "Error desconocido de FFmpeg."


# ----------------------------------------------------------------------------- avisos y tamaño estimado

LOSSLESS_AUDIO = {"flac", "wav"}
note_values: dict[str, dict] = {}   # valores de las plantillas del último `preset_notes`


def _duration(info: dict | None) -> float:
    try:
        return float((info or {}).get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def _fps(stream: dict) -> float:
    try:
        n, d = (stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "30/1").split("/")
        v = float(n) / float(d or 1)
    except (ValueError, ZeroDivisionError):
        v = 30.0
    return v if 1 <= v <= 240 else 30.0


def preset_notes(opts: ConvertOptions, src: str, info: dict | None = None) -> list[str]:
    """Avisos sobre lo que el perfil hace con el archivo (pérdida de calidad, resolución, compatibilidad).

    Cada aviso es una plantilla traducible; los valores van en `note_values`.
    """
    kind = kind_of(src)
    out: list[str] = []
    note_values.clear()
    if kind not in ("video", "audio"):
        return out
    target, preset = opts.target, opts.preset
    if preset in COMPAT and target in ("webm", "mkv", "avi", "gif") and kind == "video":
        out.append("Para la máxima compatibilidad elige MP4: este contenedor no lo reproducen todos los dispositivos.")
    v = _streams(info, "video")
    if kind == "video" and target not in dict(AUDIO_TARGETS):
        w, h = _out_size(opts, v[0]) if v else (0, 0)
        src_short = min(int(v[0].get("width") or 0), int(v[0].get("height") or 0)) if v else 0
        if v and (w, h) != (int(v[0].get("width") or 0), int(v[0].get("height") or 0)):
            out.append("Se reducirá de {a}p a {b}p.")
            note_values["Se reducirá de {a}p a {b}p."] = {"a": src_short, "b": min(w, h)}
        if preset == "moviles" and v and _fps(v[0]) > 60.5 and not opts.fps:
            out.append("Se limitará a 60 fotogramas por segundo.")
    lossless_src = any(s.get("codec_name") in ("flac", "alac") or str(s.get("codec_name", "")).startswith("pcm_")
                       for s in _streams(info, "audio"))
    if preset == "conservar" and can_remux(info, target):
        return out
    if target in LOSSLESS_AUDIO:
        if kind == "audio" and not lossless_src:
            out.append("El original ya tiene pérdida: el archivo será más grande pero no sonará mejor.")
        return out
    out.append("Se vuelve a comprimir: puede perderse algo de calidad respecto al original.")
    return out


def _audio_kbps(target: str, preset: str, bitrate: int, channels: int, rate: int) -> float:
    i = _PRESET_IDX.get(preset, 1)
    if bitrate:
        return bitrate
    if target == "mp3":
        return (245, 190, 130, 190, 245)[i]
    if target in ("m4a", "aac", "mp4", "mov", "mkv"):
        return (256, 192, 128, 192, 320)[i]
    if target in ("opus", "webm"):
        return (192, 128, 80, 128, 256)[i]
    if target == "ogg":
        return (256, 192, 128, 160, 320)[i]
    if target == "avi":
        return 192
    pcm = rate * channels * 16 / 1000
    if target == "wav":
        return pcm
    if target == "flac":
        return pcm * 0.58
    return 160


# Bits por píxel y fotograma a 1080p según el perfil, y factor de cada familia de codificador frente a x264.
_BPP = {"alta": 0.13, "equilibrado": 0.075, "reducido": 0.038, "dispositivos": 0.08, "conservar": 0.16,
        "moviles": 0.08, "windows": 0.075}
_FAMILY = {"h264": 1.0, "h265": 0.62, "vp9": 0.95, "av1": 0.6, "mpeg4": 1.8}


def _out_size(opts: ConvertOptions, stream: dict) -> tuple[int, int]:
    """Resolución de salida, igual que el filtro `scale` de `build_ffmpeg_args`."""
    w, h = int(stream.get("width") or 1920), int(stream.get("height") or 1080)
    if opts.max_height:
        return (int(w * opts.max_height / h), opts.max_height) if h > opts.max_height else (w, h)
    cap = COMPAT.get(opts.preset, 0)
    if cap and min(w, h) > cap:
        return (int(w * cap / h), cap) if w >= h else (cap, int(h * cap / w))
    return w, h


def estimate_size(src: str, opts: ConvertOptions, info: dict | None, src_size: int = 0) -> tuple[int, int] | None:
    """Tamaño aproximado del resultado (mínimo, máximo) en bytes, o None si no se puede estimar.

    Es una estimación: el tamaño real depende del contenido (movimiento, ruido, silencio).
    """
    kind = kind_of(src)
    dur = _duration(info)
    if kind not in ("video", "audio") or dur <= 0:
        return None
    target, preset = opts.target, opts.preset
    if target == "gif":
        return None
    if preset == "conservar" and can_remux(info, target) and not opts.max_height and not opts.fps and src_size:
        return int(src_size * 0.98), int(src_size * 1.01)
    a = _streams(info, "audio")
    channels = int(a[0].get("channels") or 2) if a else 2
    rate = int(a[0].get("sample_rate") or 44100) if a else 44100
    audio_kbps = 0.0
    if a and opts.audio != "none":
        audio_kbps = _audio_kbps(target, preset, opts.audio_bitrate, min(channels, 8), rate)
    video_kbps = 0.0
    if target not in dict(AUDIO_TARGETS):
        v = _streams(info, "video")
        if not v:
            return None
        w, h = _out_size(opts, v[0])
        fps = opts.fps or min(_fps(v[0]), 60 if preset == "moviles" else 240)
        codec = opts.video_codec
        if codec == "auto" or codec not in CONTAINER_VIDEO.get(target, ("h264",)) or preset in COMPAT:
            codec = "h264" if preset in COMPAT else CONTAINER_VIDEO.get(target, ("h264",))[0]
        pixels = w * h
        bpp = _BPP.get(preset, 0.075) * _FAMILY.get(codec, 1.0) * (pixels / (1920 * 1080)) ** -0.25
        video_kbps = pixels * fps * bpp / 1000
    total = (audio_kbps + video_kbps) * 1000 / 8 * dur
    lossless = target in LOSSLESS_AUDIO
    lo, hi = (0.9, 1.1) if lossless or not video_kbps else (0.6, 1.5)
    return int(total * lo), int(total * hi)
