"""Lectura de archivos .torrent (BitTorrent v1 e híbridos): bencode y metadatos.

No toca la red ni el disco salvo para leer el propio .torrent. Las rutas de los archivos se sanean: un torrent no
puede escribir fuera de su carpeta (`..`, rutas absolutas, unidades o nombres reservados de Windows).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field

MAX_TORRENT = 32 * 1024 * 1024           # un .torrent normal ocupa kilobytes
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class TorrentError(ValueError):
    pass


# ----------------------------------------------------------------------------- bencode

def decode(data: bytes):
    """Decodifica bencode. Devuelve (valor, posición del diccionario «info» en bruto o None)."""
    info_span: list[tuple[int, int]] = []

    def parse(i: int, depth: int = 0):
        if depth > 64:
            raise TorrentError("Estructura demasiado anidada.")
        c = data[i:i + 1]
        if c == b"i":
            j = data.index(b"e", i)
            return int(data[i + 1:j]), j + 1
        if c == b"l":
            out, i = [], i + 1
            while data[i:i + 1] != b"e":
                v, i = parse(i, depth + 1)
                out.append(v)
            return out, i + 1
        if c == b"d":
            out, i = {}, i + 1
            while data[i:i + 1] != b"e":
                k, i = parse(i, depth + 1)
                if not isinstance(k, bytes):
                    raise TorrentError("Clave no válida.")
                start = i
                v, i = parse(i, depth + 1)
                if k == b"info" and depth == 0:
                    info_span.append((start, i))
                out[k] = v
            return out, i + 1
        if c.isdigit():
            j = data.index(b":", i)
            n = int(data[i:j])
            if n < 0 or j + 1 + n > len(data):
                raise TorrentError("Texto truncado.")
            return data[j + 1:j + 1 + n], j + 1 + n
        raise TorrentError("Formato bencode no válido.")

    try:
        value, end = parse(0)
    except (ValueError, IndexError) as e:
        raise TorrentError("El archivo .torrent está dañado.") from e
    return value, (info_span[0] if info_span else None)


def encode(v) -> bytes:
    if isinstance(v, int):
        return b"i%de" % v
    if isinstance(v, (bytes, bytearray)):
        return b"%d:%s" % (len(v), bytes(v))
    if isinstance(v, str):
        return encode(v.encode("utf-8"))
    if isinstance(v, list):
        return b"l" + b"".join(encode(x) for x in v) + b"e"
    if isinstance(v, dict):
        items = sorted(((k.encode() if isinstance(k, str) else k), x) for k, x in v.items())
        return b"d" + b"".join(encode(k) + encode(x) for k, x in items) + b"e"
    raise TypeError(type(v))


# ----------------------------------------------------------------------------- metadatos

@dataclass
class FileInfo:
    path: str          # ruta relativa saneada con «/»
    length: int
    offset: int        # posición del primer byte en el flujo continuo del torrent


@dataclass
class Torrent:
    name: str
    info_hash: bytes
    piece_length: int
    pieces: list[bytes]
    files: list[FileInfo]
    trackers: list[str] = field(default_factory=list)
    comment: str = ""
    created_by: str = ""
    created: dt.datetime | None = None
    private: bool = False
    single: bool = False         # un solo archivo (sin carpeta propia)

    @property
    def total(self) -> int:
        return sum(f.length for f in self.files)

    def piece_size(self, i: int) -> int:
        if i == len(self.pieces) - 1:
            return self.total - self.piece_length * i
        return self.piece_length

    def pieces_of(self, f: FileInfo) -> range:
        if f.length == 0:
            return range(0)
        return range(f.offset // self.piece_length, (f.offset + f.length - 1) // self.piece_length + 1)


def _text(b) -> str:
    if isinstance(b, bytes):
        try:
            return b.decode("utf-8")
        except UnicodeDecodeError:
            return b.decode("latin-1")
    return str(b or "")


def safe_part(name: str) -> str:
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(".")
    if not n or n in (".", ".."):
        n = "_"
    if n.split(".")[0].upper() in RESERVED:
        n = "_" + n
    return n[:200]


def parse(data: bytes) -> Torrent:
    if len(data) > MAX_TORRENT:
        raise TorrentError("El archivo es demasiado grande para ser un .torrent.")
    meta, span = decode(data)
    if not isinstance(meta, dict) or not isinstance(meta.get(b"info"), dict) or span is None:
        raise TorrentError("No es un archivo .torrent válido.")
    info = meta[b"info"]
    if b"pieces" not in info:
        if info.get(b"meta version") == 2:
            raise TorrentError("Es un torrent solo de la versión 2 de BitTorrent, que AERO Player aún no descarga.")
        raise TorrentError("Al torrent le falta la lista de piezas.")
    raw_pieces = info[b"pieces"]
    if len(raw_pieces) % 20:
        raise TorrentError("La lista de piezas está dañada.")
    pieces = [raw_pieces[i:i + 20] for i in range(0, len(raw_pieces), 20)]
    plen = int(info.get(b"piece length", 0))
    if plen <= 0 or plen > 256 * 1024 * 1024:
        raise TorrentError("Tamaño de pieza no válido.")
    name = safe_part(_text(info.get(b"name.utf-8") or info.get(b"name") or "torrent"))
    files: list[FileInfo] = []
    off = 0
    if b"files" in info:
        for f in info[b"files"]:
            parts = f.get(b"path.utf-8") or f.get(b"path") or []
            clean = [safe_part(_text(p)) for p in parts if _text(p) not in ("", ".", "..")]
            if not clean or f.get(b"attr", b"").find(b"p") >= 0:   # archivos de relleno (BEP 47): se omiten
                off += int(f.get(b"length", 0))
                continue
            length = int(f.get(b"length", 0))
            files.append(FileInfo("/".join(clean), length, off))
            off += length
        single = False
    else:
        length = int(info.get(b"length", 0))
        files.append(FileInfo(name, length, 0))
        off = length
        single = True
    if not files:
        raise TorrentError("El torrent no contiene archivos.")
    expected = (off + plen - 1) // plen
    if expected != len(pieces):
        raise TorrentError("El número de piezas no coincide con el tamaño de los archivos.")
    trackers: list[str] = []
    for tier in meta.get(b"announce-list", []) or []:
        for t in tier if isinstance(tier, list) else [tier]:
            u = _text(t).strip()
            if u and u not in trackers:
                trackers.append(u)
    if meta.get(b"announce") and _text(meta[b"announce"]) not in trackers:
        trackers.insert(0, _text(meta[b"announce"]))
    created = None
    if isinstance(meta.get(b"creation date"), int):
        try:
            created = dt.datetime.fromtimestamp(meta[b"creation date"])
        except (OverflowError, OSError, ValueError):
            created = None
    return Torrent(name=name, info_hash=hashlib.sha1(data[span[0]:span[1]]).digest(), piece_length=plen,
                   pieces=pieces, files=files, trackers=trackers, comment=_text(meta.get(b"comment", b"")),
                   created_by=_text(meta.get(b"created by", b"")), created=created,
                   private=bool(info.get(b"private")), single=single)


def load(path: str) -> Torrent:
    import os

    if os.path.getsize(path) > MAX_TORRENT:
        raise TorrentError("El archivo es demasiado grande para ser un .torrent.")
    with open(path, "rb") as fh:
        return parse(fh.read())


def make(files: list[tuple[str, bytes]], name: str, piece_length: int = 32768, announce: str = "") -> bytes:
    """Crea un .torrent (para pruebas y para compartir archivos propios)."""
    blob = b"".join(d for _n, d in files)
    pieces = b"".join(hashlib.sha1(blob[i:i + piece_length]).digest() for i in range(0, len(blob), piece_length))
    if len(files) == 1 and files[0][0] == name:
        info = {"name": name, "piece length": piece_length, "pieces": pieces, "length": len(files[0][1])}
    else:
        info = {"name": name, "piece length": piece_length, "pieces": pieces,
                "files": [{"length": len(d), "path": n.split("/")} for n, d in files]}
    meta = {"info": info, "created by": "AERO Player"}
    if announce:
        meta["announce"] = announce
    return encode(meta)
