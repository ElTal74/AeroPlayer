"""Imágenes de disco (ISO, IMG, BIN/CUE, NRG, MDF) sin montarlas: listar, previsualizar y extraer.

* Lectura con `pycdlib` (LGPL-2.1, Python puro): ISO 9660, Joliet (nombres largos), Rock Ridge y UDF (DVD y
  Blu-ray de datos). Se usa el sistema de nombres más completo que tenga el disco.
* Disposición física detectada por la firma del sistema de archivos («CD001» o «BEA01» en el sector 16):
  sectores de 2048 bytes (ISO, IMG), sectores brutos de 2352 en modo 1 o 2 (BIN, MDF), desplazamiento de Nero
  (NRG) o lo que indique el CUE. Un adaptador presenta los datos como una ISO normal.
* Un CD de audio (pistas AUDIO) o una imagen sin sistema de archivos legible se informa con claridad: no se
  inventa contenido.
* Montar en Windows (ISO, IMG, VHD, VHDX) con las funciones nativas, siempre a petición del usuario.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import re
import subprocess
from pathlib import Path

DISC_EXT = {".iso", ".img", ".bin", ".cue", ".nrg", ".mdf", ".udf"}
MOUNTABLE = {".iso", ".img", ".vhd", ".vhdx"}      # lo que Windows monta de forma nativa


class DiscError(Exception):
    pass


# ----------------------------------------------------------------------------- disposición física

class SectorFile(io.RawIOBase):
    """Vista de 2048 bytes por sector sobre una imagen con otro tamaño de sector o un desplazamiento."""

    def __init__(self, path: str, base: int = 0, sector: int = 2048, data: int = 0):
        super().__init__()
        self._f = open(path, "rb")
        self.base, self.sector, self.data = base, sector, data
        phys = os.path.getsize(path) - base
        self.length = max(0, phys // sector) * 2048
        self.pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.length + off)
        self.pos = max(0, self.pos)
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.length - self.pos
        n = min(n, max(0, self.length - self.pos))
        if self.sector == 2048:
            self._f.seek(self.base + self.pos)
            data = self._f.read(n)
            self.pos += len(data)
            return data
        out = bytearray()
        while n > 0:
            lba, inner = divmod(self.pos, 2048)
            self._f.seek(self.base + lba * self.sector + self.data + inner)
            chunk = self._f.read(min(n, 2048 - inner))
            if not chunk:
                break
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
        return bytes(out)

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)

    def close(self):
        try:
            self._f.close()
        finally:
            super().close()


def _signature(path: str, base: int, sector: int, data: int) -> bool:
    try:
        with open(path, "rb") as f:
            f.seek(base + 16 * sector + data)
            head = f.read(8)
    except OSError:
        return False
    return head[1:6] in (b"CD001", b"BEA01", b"NSR02", b"NSR03")


def _nrg_offset(path: str) -> int | None:
    """Nero: el pie («NER5» + 8 bytes o «NERO» + 4) apunta a la lista de pistas; el primer DAOX/DAOI da el
    desplazamiento de los datos. Si no se entiende, None (se prueban los desplazamientos típicos)."""
    try:
        with open(path, "rb") as f:
            f.seek(-12, 2)
            tail = f.read(12)
            if tail[:4] == b"NER5":
                chunks = int.from_bytes(tail[4:12], "big")
            elif tail[4:8] == b"NERO":
                chunks = int.from_bytes(tail[8:12], "big")
            else:
                return None
            f.seek(chunks)
            block = f.read(4096)
    except OSError:
        return None
    for tag in (b"DAOX", b"DAOI"):
        i = block.find(tag)
        if i >= 0:
            # cabecera de 22 bytes del bloque DAO y, en la primera pista, índice 0 / 1 / fin (8 bytes en DAOX)
            try:
                start = i + 8 + 22
                if tag == b"DAOX":
                    return int.from_bytes(block[start + 20:start + 28], "big")
                return int.from_bytes(block[start + 20:start + 24], "big")
            except (IndexError, ValueError):
                return None
    return None


def parse_cue(path: str) -> tuple[str, int, int, bool]:
    """(BIN de datos, tamaño de sector, desplazamiento de datos en el sector, solo audio)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    file_ = None
    for line in text.splitlines():
        m = re.match(r'\s*FILE\s+"?(.+?)"?\s+(BINARY|MOTOROLA|WAVE|MP3|AIFF)\s*$', line, re.I)
        if m:
            file_ = m.group(1)
            continue
        m = re.match(r"\s*TRACK\s+\d+\s+(\S+)", line, re.I)
        if m and file_:
            mode = m.group(1).upper()
            target = file_ if os.path.isabs(file_) else os.path.join(os.path.dirname(path), file_)
            if mode == "AUDIO":
                return target, 2352, 0, True
            sector, data = {"MODE1/2048": (2048, 0), "MODE1/2352": (2352, 16), "MODE2/2336": (2336, 8),
                            "MODE2/2352": (2352, 24), "CDI/2352": (2352, 24)}.get(mode, (2352, 16))
            return target, sector, data, False
    raise DiscError("El archivo CUE no indica ninguna pista.")


def layout(path: str) -> tuple[str, int, int, int]:
    """(archivo de datos, base, tamaño de sector, desplazamiento de datos). Error si no hay sistema de archivos."""
    ext = Path(path).suffix.lower()
    if ext == ".cue":
        data_file, sector, data, audio = parse_cue(path)
        if not os.path.isfile(data_file):
            raise DiscError(f"Falta el archivo de datos del CUE: «{os.path.basename(data_file)}».")
        if audio:
            raise DiscError("Es un CD de audio: sus pistas no tienen archivos que extraer.")
        if _signature(data_file, 0, sector, data):
            return data_file, 0, sector, data
        path = data_file
    candidates = [(0, 2048, 0), (0, 2352, 16), (0, 2352, 24), (0, 2336, 8), (307200, 2048, 0),
                  (150 * 2352, 2352, 16)]
    if ext == ".nrg":
        off = _nrg_offset(path)
        if off is not None:
            candidates = [(off, 2048, 0), (off, 2352, 16), (off, 2352, 24)] + candidates
    for base, sector, data in candidates:
        if _signature(path, base, sector, data):
            return path, base, sector, data
    raise DiscError("No se reconoce ningún sistema de archivos de disco (ISO 9660 o UDF) en esta imagen.")


# ----------------------------------------------------------------------------- lectura

class Disc:
    """Imagen abierta con pycdlib y el sistema de nombres elegido (udf, rr, joliet o iso)."""

    def __init__(self, path: str):
        import pycdlib

        data_file, base, sector, data = layout(path)
        self.fp = SectorFile(data_file, base, sector, data)
        self.iso = pycdlib.PyCdlib()
        try:
            self.iso.open_fp(self.fp)
        except Exception as e:  # noqa: BLE001 - pycdlib lanza PyCdlibInvalidInput con discos raros
            self.fp.close()
            raise DiscError("La imagen de disco está dañada o usa un formato no compatible.") from e
        if self.iso.has_udf():
            self.kind = "udf_path"
        elif self.iso.has_rock_ridge():
            self.kind = "rr_path"
        elif self.iso.has_joliet():
            self.kind = "joliet_path"
        else:
            self.kind = "iso_path"
        label = ""
        try:
            pvd = self.iso.pvd
            label = (pvd.volume_identifier or b"").decode("ascii", "replace").strip()
        except Exception:  # noqa: BLE001
            pass
        self.label = label

    def close(self):
        try:
            self.iso.close()
        except Exception:  # noqa: BLE001
            pass
        self.fp.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @staticmethod
    def clean(name: str) -> str:
        name = name.split(";")[0]      # «FILE.TXT;1» (ISO 9660 sin nombres largos)
        return name[:-1] if name.endswith(".") and "." in name[:-1] else name.rstrip(".") or name

    def walk(self):
        """(ruta interna «a/b.txt», ruta para pycdlib, es carpeta, tamaño, fecha)."""
        for root, dirs, files in self.iso.walk(**{self.kind: "/"}):
            rel = root.strip("/")
            nice_root = "/".join(self.clean(p) for p in rel.split("/") if p)
            for d in dirs:
                inner = f"{nice_root}/{self.clean(d)}" if nice_root else self.clean(d)
                yield inner, (root.rstrip("/") + "/" + d), True, 0, None
            for f in files:
                full = root.rstrip("/") + "/" + f
                size, when = 0, None
                try:
                    rec = self.iso.get_record(**{self.kind: full})
                    size = int(rec.get_data_length())
                    d = getattr(rec, "date", None)
                    if d is not None and getattr(d, "years_since_1900", 0):
                        when = dt.datetime(1900 + d.years_since_1900, max(1, d.month), max(1, d.day_of_month),
                                           d.hour, d.minute, d.second)
                except Exception:  # noqa: BLE001 - fecha o tamaño ilegibles: se muestra igual
                    pass
                inner = f"{nice_root}/{self.clean(f)}" if nice_root else self.clean(f)
                yield inner, full, False, size, when

    def open_member(self, raw: str):
        return self.iso.open_file_from_iso(**{self.kind: raw})


def read_disc(path: str):
    """ArchiveInfo de la imagen (mismo formato que los comprimidos: el explorador la abre igual)."""
    from aero.archive import ArchiveInfo, Entry, safe_name

    info = ArchiveInfo(path=os.path.abspath(path), fmt="DISC")
    with Disc(path) as d:
        for inner, raw, is_dir, size, when in d.walk():
            name, unsafe = safe_name(inner)
            info.entries.append(Entry(name, size, -1, when, is_dir, False, unsafe, raw))
        if d.label:
            info.warnings.append(f"Etiqueta: {d.label}")
    return info


def copy_member(path: str, raw: str, out, limit: int, on_chunk=None, cancelled=lambda: False) -> int:
    """Copia un archivo de la imagen a `out` (objeto abierto en binario) por bloques. Devuelve los bytes."""
    n = 0
    with Disc(path) as d, d.open_member(raw) as src:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            n += len(chunk)
            if n > limit:
                raise DiscError("El contenido real supera el tamaño declarado; se detiene.")
            out.write(chunk)
            if on_chunk:
                on_chunk(len(chunk))
            if cancelled():
                from aero.archive.ops import Cancelled

                raise Cancelled("Cancelado.")
    return n


# ----------------------------------------------------------------------------- montar en Windows

def _ps(cmd: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                          text=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _q(path: str) -> str:
    return "'" + os.path.abspath(path).replace("'", "''") + "'"


def can_mount(path: str) -> bool:
    return os.name == "nt" and Path(path).suffix.lower() in MOUNTABLE


def mounted_drive(path: str) -> str:
    """Letra («E:») si la imagen ya está montada en Windows; vacío si no."""
    r = _ps(f"$i = Get-DiskImage -ImagePath {_q(path)} -ErrorAction SilentlyContinue; "
            "if ($i -and $i.Attached) { ($i | Get-Volume).DriveLetter }")
    letter = (r.stdout or "").strip()
    return f"{letter[0]}:" if letter[:1].isalpha() else ""


def mount(path: str) -> str:
    """Monta la imagen con Windows (Mount-DiskImage) y devuelve la letra de unidad."""
    if not can_mount(path):
        raise DiscError("Windows solo monta imágenes ISO, IMG, VHD y VHDX.")
    # Windows tarda un momento en dar letra a la unidad nueva: se espera hasta ~8 s
    r = _ps(f"$p = {_q(path)}; Mount-DiskImage -ImagePath $p -ErrorAction Stop | Out-Null; "
            "for ($k = 0; $k -lt 32; $k++) { $l = (Get-DiskImage -ImagePath $p | Get-Volume).DriveLetter; "
            "if ($l) { $l; break }; Start-Sleep -Milliseconds 250 }")
    letter = (r.stdout or "").strip()
    if r.returncode != 0:
        err = (r.stderr or "").strip().splitlines()
        raise DiscError("Windows no pudo montar la imagen" + (f": {err[-1]}" if err else "."))
    if not letter[:1].isalpha():
        # Conectada pero sin unidad: Windows no pudo leer su sistema de archivos (o la carpeta tiene permisos que
        # el servicio de discos virtuales no puede usar). No se deja una unidad fantasma conectada.
        _ps(f"Dismount-DiskImage -ImagePath {_q(path)} -ErrorAction SilentlyContinue | Out-Null")
        raise DiscError("Windows conectó la imagen pero no le dio letra de unidad: no reconoce su contenido o no "
                        "puede leer la carpeta donde está. Puedes explorarla y extraerla sin montarla.")
    return f"{letter[0]}:"


def unmount(path: str) -> None:
    r = _ps(f"Dismount-DiskImage -ImagePath {_q(path)} -ErrorAction Stop | Out-Null")
    if r.returncode != 0:
        err = (r.stderr or "").strip().splitlines()
        raise DiscError("Windows no pudo desmontar la imagen" + (f": {err[-1]}" if err else "."))
