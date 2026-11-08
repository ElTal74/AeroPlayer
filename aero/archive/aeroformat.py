"""Formato propio `.aeroarchive` (archivos comprimidos creados por AERO Player con su icono).

Estructura (versión 1):

    0   8 bytes   firma «AEROARC\\x1a»
    8   2 bytes   versión del formato (little-endian, 1)
    10  2 bytes   indicadores (bit 0: contenido cifrado)
    12  4 bytes   longitud N de los metadatos
    16  N bytes   metadatos JSON en UTF-8 (programa, fecha, número de archivos, tamaños, SHA-256 del contenido…)
    16+N …        contenido: un ZIP estándar (Deflate, o AES-256 si tiene contraseña)

Por qué así:
* Firma y versión permiten reconocerlo sin mirar la extensión y evolucionar el formato (un lector de la versión
  1 rechaza con un mensaje claro una versión superior que no entienda).
* El contenido es un ZIP normal: cualquier herramienta ZIP puede recuperarlo (los lectores ZIP admiten datos
  delante del archivo), cada archivo tiene su CRC-32 y el conjunto un SHA-256 en los metadatos.
* Extensión propia: no se apropia de .zip, .rar ni .7z ni cambia su icono.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import time

MAGIC = b"AEROARC\x1a"
VERSION = 1
EXT = ".aeroarchive"
HEADER = struct.Struct("<8sHHI")
FLAG_ENCRYPTED = 1


class FormatError(ValueError):
    pass


def is_aeroarchive(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(8) == MAGIC
    except OSError:
        return False


def wrap(zip_path: str, out_path: str, files: int, total: int, encrypted: bool, comment: str = "") -> None:
    """Convierte un ZIP recién creado en .aeroarchive (cabecera + metadatos + ZIP)."""
    from aero import __version__

    h = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    meta = {"format": "aeroarchive", "version": VERSION, "creator": f"AERO Player {__version__}",
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": files, "size": total,
            "payload_sha256": h.hexdigest(), "encrypted": encrypted, "comment": comment}
    blob = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    tmp = out_path + ".part"
    with open(tmp, "wb") as out, open(zip_path, "rb") as src:
        out.write(HEADER.pack(MAGIC, VERSION, FLAG_ENCRYPTED if encrypted else 0, len(blob)))
        out.write(blob)
        for chunk in iter(lambda: src.read(1 << 20), b""):
            out.write(chunk)
    os.replace(tmp, out_path)


def read_meta(path: str) -> tuple[dict, int]:
    """(metadatos, posición donde empieza el ZIP)."""
    with open(path, "rb") as f:
        head = f.read(HEADER.size)
        if len(head) < HEADER.size:
            raise FormatError("El archivo está incompleto.")
        magic, version, _flags, n = HEADER.unpack(head)
        if magic != MAGIC:
            raise FormatError("No es un archivo de AERO Player.")
        if version > VERSION:
            raise FormatError("Este archivo se creó con una versión más nueva de AERO Player: actualiza para abrirlo.")
        if n > 1 << 20:
            raise FormatError("Los metadatos están dañados.")
        try:
            meta = json.loads(f.read(n).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise FormatError("Los metadatos están dañados.") from e
    return meta, HEADER.size + n


def verify(path: str) -> tuple[bool, str]:
    """Comprueba la firma, los metadatos y el SHA-256 del contenido."""
    try:
        meta, offset = read_meta(path)
    except (OSError, FormatError) as e:
        return False, str(e)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        f.seek(offset)
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != meta.get("payload_sha256"):
        return False, "El contenido no coincide con su huella (SHA-256): el archivo está dañado."
    return True, f"Correcto: {meta.get('files', '?')} archivos, creado con {meta.get('creator', 'AERO Player')}."
