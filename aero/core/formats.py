"""Clasificación de archivos por tipo. Fuente única de verdad para extensiones."""

from __future__ import annotations

import os
from pathlib import Path

AUDIO = {
    ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".oga", ".opus", ".wma", ".aiff", ".aif",
    ".alac", ".ape", ".wv", ".mka", ".ac3", ".dts", ".mid", ".midi", ".amr",
}
VIDEO = {
    ".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv", ".mpg", ".mpeg", ".ts",
    ".m2ts", ".mts", ".3gp", ".ogv", ".vob", ".divx", ".f4v",
}
IMAGE = {
    ".jpg", ".jpeg", ".jfif", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico", ".svg",
    ".svgz", ".tga", ".heic", ".heif", ".avif", ".psd", ".ppm", ".pgm", ".pbm", ".dds", ".icns",
}
PDF = {".pdf"}
DOCUMENT = {".docx", ".odt", ".rtf", ".doc", ".html", ".htm", ".md", ".markdown", ".epub"}
SHEET = {".xlsx", ".xlsm", ".xlsb", ".xls", ".ods", ".csv", ".tsv"}
SLIDES = {".pptx", ".ppt", ".odp", ".ppsx"}
SUBTITLE = {".srt", ".vtt", ".ass", ".ssa"}
ARCHIVE = {".zip", ".cbz", ".aeroarchive", ".rar", ".cbr", ".7z", ".cb7", ".tar", ".tgz", ".tbz2", ".txz", ".gz", ".bz2", ".xz",
           ".cab", ".iso", ".img", ".cue", ".nrg", ".mdf", ".udf", ".bin"}   # imágenes de disco: se exploran como un comprimido
TEXT = {
    ".txt", ".log", ".json", ".xml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".toml", ".py",
    ".js", ".ts", ".tsx", ".jsx", ".css", ".scss", ".c", ".h", ".cpp", ".hpp", ".cs", ".java",
    ".rs", ".go", ".rb", ".php", ".sh", ".bat", ".ps1", ".sql", ".lua", ".kt", ".swift", ".m3u",
    ".m3u8", ".nfo", ".diff", ".patch", ".gitignore", ".env",
} | SUBTITLE

# Formatos que requieren LibreOffice para verse con fidelidad.
NEEDS_OFFICE = {".doc", ".ppt"}

KIND_LABELS = {
    "audio": "Audio", "video": "Vídeo", "image": "Imagen", "pdf": "PDF", "document": "Documento",
    "sheet": "Hoja de cálculo", "slides": "Presentación", "text": "Texto", "archive": "Archivo comprimido",
    "folder": "Carpeta", "unknown": "Desconocido",
}


_KIND_BY_EXT: dict[str, str] = {}
for _kind, _exts in (("archive", ARCHIVE), ("text", TEXT), ("document", DOCUMENT), ("slides", SLIDES),
                     ("sheet", SHEET), ("pdf", PDF), ("image", IMAGE), ("video", VIDEO), ("audio", AUDIO)):
    _KIND_BY_EXT.update(dict.fromkeys(_exts, _kind))  # en orden inverso: gana la prioridad más alta


def kind_of(path: str | Path) -> str:
    """Tipo por extensión. Las carpetas se distinguen con `is_dir` donde importa (no se toca el disco aquí).

    Se llama miles de veces al listar carpetas: búsqueda directa en un diccionario, sin `pathlib`."""
    name = os.fspath(path)
    dot = name.rfind(".")
    if dot <= max(name.rfind("/"), name.rfind("\\")) + 1:
        return "unknown"
    return _KIND_BY_EXT.get(name[dot:].lower(), "unknown")


def is_media(path: str | Path) -> bool:
    return kind_of(path) in ("audio", "video")


def open_dialog_filter() -> str:
    def pat(exts):
        return " ".join("*" + e for e in sorted(exts))

    allexts = AUDIO | VIDEO | IMAGE | PDF | DOCUMENT | SHEET | SLIDES | TEXT | ARCHIVE
    return ";;".join([
        f"Todos los compatibles ({pat(allexts)})",
        f"Audio ({pat(AUDIO)})",
        f"Vídeo ({pat(VIDEO)})",
        f"Imágenes ({pat(IMAGE)})",
        f"Documentos y PDF ({pat(DOCUMENT | PDF)})",
        f"Hojas de cálculo ({pat(SHEET)})",
        f"Presentaciones ({pat(SLIDES)})",
        f"Texto ({pat(TEXT)})",
        f"Archivos comprimidos ({pat(ARCHIVE)})",
        "Todos los archivos (*)",
    ])


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:
        return "--:--"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
