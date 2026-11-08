"""Categorías visuales de archivos (una por tipo de contenido, no una por extensión).

Fuente única para el explorador, la búsqueda, los recientes y los visores: todos los vídeos comparten categoría,
todos los audios, todas las imágenes… Se decide por la extensión (sin tocar el disco) y, solo si la extensión no
se conoce o no hay, por la firma de los primeros bytes (`sniff`, se llama desde el hilo que lista la carpeta).
"""

from __future__ import annotations

import os

from aero.core import formats

CATEGORIES = {
    "folder": "Carpeta", "video": "Vídeo", "audio": "Audio", "image": "Imagen", "document": "Documento",
    "sheet": "Hoja de cálculo", "slides": "Presentación", "pdf": "PDF", "archive": "Archivo comprimido",
    "app": "Aplicación", "installer": "Instalador", "shortcut": "Acceso directo", "system": "Sistema y configuración", "font": "Fuente",
    "code": "Código", "torrent": "Torrent", "disc": "Imagen de disco", "unknown": "Archivo",
}

DISC = {".iso", ".img", ".bin", ".cue", ".nrg", ".mdf", ".mds", ".ccd", ".vhd", ".vhdx", ".dmg", ".udf", ".toast"}
APP = {".exe", ".com", ".scr", ".application", ".gadget", ".apk", ".xapk"}
INSTALLER = {".msi", ".msix", ".msixbundle", ".appx", ".appxbundle", ".msp", ".appinstaller"}
SHORTCUT = {".lnk", ".url", ".appref-ms", ".website", ".desktop"}
FONT = {".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2", ".fon", ".fnt", ".eot", ".pfb", ".pfm"}
SYSTEM = {".dll", ".sys", ".drv", ".ocx", ".cpl", ".msc", ".inf", ".cat", ".reg", ".ini", ".cfg", ".conf", ".toml",
          ".yaml", ".yml", ".env", ".plist", ".properties", ".manifest", ".mui", ".dat", ".db", ".sqlite", ".lock",
          ".pol", ".efi", ".bak", ".tmp"}
CODE = {".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".scss", ".sass", ".less", ".c", ".h",
        ".cpp", ".cc", ".hpp", ".cs", ".java", ".kt", ".swift", ".rs", ".go", ".rb", ".php", ".sh", ".bash", ".bat",
        ".cmd", ".ps1", ".psm1", ".vbs", ".sql", ".lua", ".r", ".pl", ".dart", ".scala", ".json", ".xml", ".xaml",
        ".html", ".htm", ".vue", ".svelte", ".ipynb", ".gradle", ".cmake", ".makefile", ".asm", ".diff", ".patch",
        ".gitignore", ".editorconfig"}
TORRENT = {".torrent"}
ARCHIVE = (formats.ARCHIVE - DISC) | {".zst", ".lz", ".lzma", ".lz4", ".z", ".arj", ".jar", ".war", ".wim", ".rpm",
                                      ".deb", ".pkg"}
PLAYLIST = {".m3u", ".m3u8", ".pls", ".xspf"}
DOCUMENT = (formats.DOCUMENT - {".html", ".htm"}) | {".txt", ".log", ".nfo", ".rtf", ".md", ".markdown", ".tex",
                                                    ".pages", ".wpd", ".xps", ".oxps", ".djvu", ".mobi", ".azw3",
                                                    ".fb2"} | formats.SUBTITLE

_BY_EXT: dict[str, str] = {}
# Orden: lo de abajo gana (p. ej. .bat es código aunque también sea texto, .iso es imagen de disco y no comprimido)
for _cat, _exts in (("document", DOCUMENT), ("code", CODE), ("system", SYSTEM), ("archive", ARCHIVE),
                    ("audio", formats.AUDIO | PLAYLIST), ("video", formats.VIDEO), ("image", formats.IMAGE),
                    ("sheet", formats.SHEET), ("slides", formats.SLIDES), ("pdf", formats.PDF), ("font", FONT),
                    ("app", APP), ("installer", INSTALLER), ("shortcut", SHORTCUT), ("disc", DISC), ("torrent", TORRENT)):
    _BY_EXT.update(dict.fromkeys(_exts, _cat))
_BY_EXT[".ts"] = "video"        # .ts es casi siempre vídeo de TDT/cámara; el código TypeScript suele ser .tsx/.ts…
_BY_EXT[".bin"] = "disc"        # .bin suelto: imagen de disco (BIN/CUE); el firmware y otros se ven como disco


def ext_of(name: str) -> str:
    dot = name.rfind(".")
    if dot <= max(name.rfind("/"), name.rfind("\\")) + 1:
        return ""
    return name[dot:].lower()


def by_extension(name: str, is_dir: bool = False) -> str:
    """Categoría sin tocar el disco. «unknown» si la extensión no se conoce o no hay."""
    if is_dir:
        return "folder"
    return _BY_EXT.get(ext_of(os.fspath(name)), "unknown")


# Firmas de los primeros bytes (solo para archivos sin extensión conocida)
_MAGIC: list[tuple[int, bytes, str]] = [
    (0, b"\x89PNG\r\n\x1a\n", "image"), (0, b"\xff\xd8\xff", "image"), (0, b"GIF8", "image"), (0, b"BM", "image"),
    (0, b"%PDF", "pdf"), (0, b"PK\x03\x04", "archive"), (0, b"Rar!\x1a\x07", "archive"),
    (0, b"7z\xbc\xaf\x27\x1c", "archive"), (0, b"\x1f\x8b", "archive"), (0, b"BZh", "archive"),
    (0, b"\xfd7zXZ\x00", "archive"), (0, b"MSCF", "archive"), (0, b"MZ", "app"),
    (0, b"ID3", "audio"), (0, b"fLaC", "audio"), (0, b"OggS", "audio"), (0, b"\x1aE\xdf\xa3", "video"),
    (0, b"d8:announce", "torrent"), (0, b"d4:info", "torrent"), (0, b"d13:announce-list", "torrent"),
    (0, b"\x00\x01\x00\x00\x00", "font"), (0, b"OTTO", "font"), (0, b"wOFF", "font"), (0, b"wOF2", "font"),
    (0, b"SQLite format 3", "system"), (0, b"{\\rtf", "document"), (0, b"\xd0\xcf\x11\xe0", "document"),
    (0, b"L\x00\x00\x00\x01\x14\x02\x00", "shortcut"),
]


def sniff(path: str, size: int | None = None) -> str:
    """Categoría por la firma (lee como mucho 64 bytes). «unknown» si no se reconoce o no se puede leer."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(64)
    except OSError:
        return "unknown"
    if not head:
        return "unknown"
    for off, sig, cat in _MAGIC:
        if head[off:off + len(sig)] == sig:
            return cat
    if head[:4] == b"RIFF":
        return {b"WAVE": "audio", b"AVI ": "video", b"WEBP": "image"}.get(head[8:12], "unknown")
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B "):
            return "audio"
        if brand in (b"heic", b"heix", b"mif1", b"avif"):
            return "image"
        return "video"
    if size is None or size >= 0x8006:
        try:   # ISO 9660: «CD001» en el sector 16
            with open(path, "rb") as fh:
                fh.seek(0x8001)
                if fh.read(5) == b"CD001":
                    return "disc"
        except OSError:
            pass
    try:
        head.decode("utf-8")
        if all(c >= 9 for c in head):
            return "document"         # texto plano sin extensión (LÉAME, LICENSE…)
    except UnicodeDecodeError:
        pass
    return "unknown"


def category_of(path: str, is_dir: bool = False, look: bool = False) -> str:
    """Categoría de `path`. Con `look`, si la extensión no la decide se mira la firma (hilo de trabajo)."""
    cat = by_extension(path, is_dir)
    if cat == "unknown" and look and not is_dir:
        cat = sniff(path)
    return cat
