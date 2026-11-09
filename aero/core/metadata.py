"""Lectura/escritura de etiquetas y portadas con mutagen."""

from __future__ import annotations

import base64
from pathlib import Path

mutagen = None        # se carga al primer uso: con el núcleo Rust casi nunca hace falta (37 ms menos al arrancar)
_MUTAGEN_MISSING = False


def _mg():
    """mutagen, importado la primera vez que se necesita (None si no está instalado)."""
    global mutagen, _MUTAGEN_MISSING
    if mutagen is None and not _MUTAGEN_MISSING:
        try:
            import mutagen as m
            import mutagen.flac  # noqa: F401 - Picture para las portadas de OGG/Opus

            mutagen = m
        except ImportError:  # pragma: no cover
            _MUTAGEN_MISSING = True
    return mutagen

COVER_NAMES = ("cover", "folder", "front", "album", "albumart")
EDITABLE_FIELDS = ("title", "artist", "album", "albumartist", "genre", "date", "tracknumber")
FIELD_LABELS = {
    "title": "Título", "artist": "Artista", "album": "Álbum", "albumartist": "Artista del álbum",
    "genre": "Género", "date": "Año", "tracknumber": "Pista",
}


def _first(tags, key) -> str:
    try:
        v = tags.get(key)
    except Exception:
        return ""
    if not v:
        return ""
    if isinstance(v, (list, tuple)):
        v = v[0]
    return str(v).strip()


def _int(text: str) -> int | None:
    digits = ""
    for c in text:
        if c.isdigit():
            digits += c
        elif digits:
            break
    return int(digits) if digits else None


def read_tags(path: str | Path) -> dict:
    """Devuelve título, artista, álbum, etc. Nunca lanza excepciones: los archivos dañados dan {}.

    Primero el núcleo nativo (Rust, lofty); si no entiende el formato (WMA, vídeos…), mutagen."""
    from aero.core import native

    nc = native.core()
    if nc is not None:
        try:
            got = nc.read_tags(str(path))
        except Exception:  # noqa: BLE001 - nunca lanza: se intenta con mutagen
            got = None
        if got is not None:
            return got
    return read_tags_py(path)


def read_tags_many(paths: list[str]) -> list[dict]:
    """Etiquetas de muchos archivos: en paralelo en todos los núcleos con Rust; lo que no entienda, con mutagen."""
    from aero.core import native

    nc = native.core()
    got = None
    if nc is not None:
        try:
            got = nc.read_tags_many([str(p) for p in paths])
        except Exception:  # noqa: BLE001
            got = None
    if got is None:
        return [read_tags_py(p) for p in paths]
    return [g if g is not None else read_tags_py(p) for p, g in zip(paths, got)]


def read_tags_py(path: str | Path) -> dict:
    """Versión mutagen de `read_tags` (respaldo y referencia de las pruebas de equivalencia)."""
    out: dict = {}
    if _mg() is None:
        return out
    try:
        f = mutagen.File(str(path), easy=True)
    except Exception:
        return out
    if f is None:
        return out
    info = getattr(f, "info", None)
    if info is not None and getattr(info, "length", None):
        out["duration"] = float(info.length)
        for attr in ("bitrate", "sample_rate", "channels", "bits_per_sample"):
            val = getattr(info, attr, None)
            if val:
                out[attr] = val
    tags = f.tags
    if tags:
        out["title"] = _first(tags, "title")
        out["artist"] = _first(tags, "artist")
        out["album"] = _first(tags, "album")
        out["album_artist"] = _first(tags, "albumartist")
        out["genre"] = _first(tags, "genre")
        out["year"] = _int(_first(tags, "date"))
        out["track"] = _int(_first(tags, "tracknumber"))
    return out


def read_cover(path: str | Path) -> bytes | None:
    """Portada incrustada o, en su defecto, cover.jpg/folder.jpg de la misma carpeta."""
    data = _embedded_cover(path)
    if data:
        return data
    folder = Path(path).parent
    try:
        for entry in folder.iterdir():
            if entry.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and entry.stem.lower() in COVER_NAMES:
                if entry.stat().st_size < 20 * 1024 * 1024:
                    return entry.read_bytes()
    except OSError:
        pass
    return None


def _embedded_cover(path) -> bytes | None:
    if _mg() is None:
        return None
    try:
        f = mutagen.File(str(path))
    except Exception:
        return None
    if f is None:
        return None
    try:
        pics = getattr(f, "pictures", None)
        if pics:
            return pics[0].data
        tags = f.tags
        if tags is None:
            return None
        if hasattr(tags, "getall"):
            apic = tags.getall("APIC")
            if apic:
                front = [p for p in apic if getattr(p, "type", 0) == 3]
                return (front or apic)[0].data
        covr = tags.get("covr") if hasattr(tags, "get") else None
        if covr:
            return bytes(covr[0])
        mbp = tags.get("metadata_block_picture") if hasattr(tags, "get") else None
        if mbp:
            return mutagen.flac.Picture(base64.b64decode(mbp[0])).data
        wm = tags.get("WM/Picture") if hasattr(tags, "get") else None
        if wm:
            raw = bytes(wm[0].value)
            # Estructura ASF: tipo(1) tamaño(4) mime(utf16z) descripción(utf16z) datos
            pos = 5
            for _ in range(2):
                end = raw.find(b"\x00\x00", pos)
                while end != -1 and (end - pos) % 2:
                    end = raw.find(b"\x00\x00", end + 1)
                pos = end + 2
            return raw[pos:] or None
    except Exception:
        return None
    return None


def read_editable(path: str | Path) -> dict[str, str] | None:
    """Etiquetas editables, o None si el formato no admite edición."""
    if _mg() is None:
        return None
    try:
        f = mutagen.File(str(path), easy=True)
    except Exception:
        return None
    if f is None or not hasattr(f, "tags"):
        return None
    tags = f.tags
    return {k: (_first(tags, k) if tags else "") for k in EDITABLE_FIELDS}


def write_tags(path: str | Path, values: dict[str, str]) -> None:
    """Escribe etiquetas. Lanza ValueError con un mensaje comprensible si no es posible."""
    if _mg() is None:
        raise ValueError("La biblioteca de etiquetas no está disponible.")
    try:
        f = mutagen.File(str(path), easy=True)
    except Exception as e:
        raise ValueError(f"No se pudo leer el archivo: {e}") from e
    if f is None:
        raise ValueError("Formato no compatible con la edición de etiquetas.")
    if f.tags is None:
        try:
            f.add_tags()
        except Exception as e:
            raise ValueError("Este formato no admite etiquetas.") from e
    for k, v in values.items():
        if k not in EDITABLE_FIELDS:
            continue
        try:
            if v:
                f.tags[k] = [v]
            elif k in f.tags:
                del f.tags[k]
        except (KeyError, ValueError, TypeError):
            continue
    try:
        f.save()
    except PermissionError as e:
        raise ValueError("Sin permiso para modificar el archivo (¿está abierto en otro programa?).") from e
    except Exception as e:
        raise ValueError(f"No se pudieron guardar las etiquetas: {e}") from e
