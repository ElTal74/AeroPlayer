"""Lectura segura de archivos comprimidos, sin extraerlos.

* ZIP/CBZ y TAR (también .tar.gz/.bz2/.xz) con la biblioteca estándar de Python, dentro del proceso.
* RAR, 7Z, CAB, ISO y otros con `tar.exe` (bsdtar/libarchive) que incluye Windows 10/11: un proceso aparte
  que solo se lanza al abrir el archivo. No se redistribuye nada.

Seguridad (el contenido puede venir de Internet):
* Nombres normalizados; los que intentan salir de la carpeta (`../`, rutas absolutas, unidades) se marcan
  como inseguros y no se extraen nunca (Zip Slip).
* Solo se extrae **un** elemento cada vez, a una carpeta temporal propia que se borra al cerrar.
* Límites de tamaño y de ratio de compresión (bombas de compresión); la extracción se corta si el flujo real
  supera el tamaño declarado.
* Archivos cifrados: se detectan y se informa; no se intenta nada más.
* Nunca se ejecuta nada de lo extraído: solo se abre en los visores de AERO Player.
"""

from __future__ import annotations

import datetime as dt
import locale
import os
import posixpath
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Formatos que se leen en el proceso y formatos delegados a bsdtar.
ZIP_EXT = {".zip", ".cbz", ".aeroarchive"}   # .aeroarchive: cabecera propia + ZIP (aero/archive/aeroformat.py)
TAR_EXT = {".tar", ".tgz", ".tbz", ".tbz2", ".txz", ".gz", ".bz2", ".xz"}
BSDTAR_EXT = {".rar", ".cbr", ".7z", ".cb7", ".cab", ".iso", ".lzh", ".lha", ".xar", ".cpio", ".zst"}
DISC_EXT = {".iso", ".img", ".bin", ".cue", ".nrg", ".mdf", ".udf"}   # imágenes de disco (aero/archive/disc.py)
ALL_EXT = ZIP_EXT | TAR_EXT | BSDTAR_EXT | DISC_EXT

MAX_ENTRIES = 200_000             # listados enormes o anómalos se cortan
MAX_EXTRACT = 1024 * 1024 ** 2    # 1 GB por elemento para previsualizar
MAX_RATIO = 250                   # tamaño / comprimido por encima de esto (y > 32 MB) se considera bomba
RATIO_MIN_SIZE = 32 * 1024 ** 2
_CHUNK = 1024 * 1024


class ArchiveError(Exception):
    """Error con un mensaje apto para mostrar al usuario."""


class PasswordRequired(ArchiveError):
    pass


class UnsafeEntry(ArchiveError):
    pass


@dataclass
class Entry:
    name: str                 # ruta normalizada con «/», sin barra final
    size: int = 0
    packed: int = -1          # -1: desconocido
    mtime: dt.datetime | None = None
    is_dir: bool = False
    encrypted: bool = False
    unsafe: bool = False      # el nombre original intentaba salir de la carpeta
    raw: str = ""             # nombre tal como está en el archivo (para extraer)

    @property
    def base(self) -> str:
        return posixpath.basename(self.name)

    @property
    def parent(self) -> str:
        return posixpath.dirname(self.name)


@dataclass
class ArchiveInfo:
    path: str
    fmt: str
    entries: list[Entry] = field(default_factory=list)
    truncated: bool = False
    encrypted: bool = False   # algún elemento cifrado (o la cabecera)
    warnings: list[str] = field(default_factory=list)

    @property
    def files(self) -> list[Entry]:
        return [e for e in self.entries if not e.is_dir]

    @property
    def total_size(self) -> int:
        return sum(e.size for e in self.entries if not e.is_dir)

    def children(self, prefix: str) -> list[Entry]:
        """Elementos directamente dentro de `prefix` (carpetas implícitas incluidas)."""
        prefix = prefix.strip("/")
        out: dict[str, Entry] = {}
        for e in self.entries:
            if e.parent == prefix:
                if e.name not in out or e.is_dir:
                    out.setdefault(e.name, e)
            elif (e.parent + "/").startswith(prefix + "/" if prefix else ""):
                # Carpeta intermedia que el archivo no declara
                rest = e.name[len(prefix) + 1 if prefix else 0:]
                top = rest.split("/", 1)[0]
                name = f"{prefix}/{top}" if prefix else top
                if name not in out:
                    out[name] = Entry(name, is_dir=True, raw=name + "/")
        return list(out.values())


def is_archive(path: str | os.PathLike) -> bool:
    p = str(path).lower()
    return Path(p).suffix in ALL_EXT or p.endswith((".tar.gz", ".tar.bz2", ".tar.xz"))


def safe_name(raw: str) -> tuple[str, bool]:
    """Normaliza un nombre interno. Devuelve (nombre, inseguro)."""
    n = raw.replace("\\", "/")
    unsafe = n.startswith("/") or bool(re.match(r"^[A-Za-z]:", n)) or any(part == ".." for part in n.split("/"))
    parts = [p for p in n.split("/") if p not in ("", ".", "..")]
    clean = "/".join(parts)
    if re.match(r"^[A-Za-z]:", clean):
        clean = clean[2:].lstrip("/")
        unsafe = True
    return clean, unsafe


def _bsdtar() -> str | None:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    p = os.path.join(root, "System32", "tar.exe")
    return p if os.path.exists(p) else shutil.which("bsdtar")


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------------------- listado
def read_archive(path: str) -> ArchiveInfo:
    path = os.path.abspath(path)
    low = path.lower()
    if not os.path.isfile(path):
        raise ArchiveError("El archivo ya no existe.")
    try:
        if Path(low).suffix in DISC_EXT:
            from aero.archive import disc

            try:
                return disc.read_disc(path)
            except disc.DiscError as e:
                if Path(low).suffix != ".iso":
                    raise ArchiveError(str(e)) from e
                # ISO con un sistema de archivos que pycdlib no entiende: se prueba con bsdtar
        if Path(low).suffix in ZIP_EXT or zipfile.is_zipfile(path):
            return _read_zip(path)
        if Path(low).suffix in (".7z", ".cb7"):
            try:
                return _read_7z(path)
            except ImportError:
                pass
        if Path(low).suffix in TAR_EXT or low.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
            try:
                return _read_tar(path)
            except tarfile.TarError:
                pass  # p. ej. un .gz de un solo archivo: lo intenta bsdtar
        return _read_bsdtar(path)
    except PermissionError as e:
        raise ArchiveError("No tienes permiso para leer este archivo.") from e


def _finish(info: ArchiveInfo, raw_entries) -> ArchiveInfo:
    seen = set()
    for e in raw_entries:
        if len(info.entries) >= MAX_ENTRIES:
            info.truncated = True
            info.warnings.append(f"Se muestran los primeros {MAX_ENTRIES:,} elementos.".replace(",", "."))
            break
        name, unsafe = safe_name(e.raw)
        if not name or name in seen:
            continue
        seen.add(name)
        e.name, e.unsafe = name, unsafe
        info.entries.append(e)
        info.encrypted |= e.encrypted
    if any(e.unsafe for e in info.entries):
        info.warnings.append("Algunos nombres intentan escribir fuera de la carpeta (ataque «Zip Slip»): "
                             "se muestran, pero no se pueden abrir.")
    if info.encrypted:
        info.warnings.append("Hay contenido protegido con contraseña: se lista, pero no se puede abrir.")
    return info


def _read_zip(path: str) -> ArchiveInfo:
    info = ArchiveInfo(path, "ZIP")
    try:
        with zipfile.ZipFile(path) as z:
            raw = []
            for i in z.infolist():
                try:
                    when = dt.datetime(*i.date_time)
                except ValueError:
                    when = None
                raw.append(Entry("", i.file_size, i.compress_size, when, i.is_dir(), bool(i.flag_bits & 0x1),
                                 raw=i.filename))
                if len(raw) > MAX_ENTRIES:
                    break
    except zipfile.BadZipFile as e:
        raise ArchiveError("El archivo está dañado o no es un ZIP válido.") from e
    return _finish(info, raw)


def _read_tar(path: str) -> ArchiveInfo:
    raw = []
    with tarfile.open(path) as t:
        for m in t:
            if not (m.isfile() or m.isdir()):
                continue  # enlaces y dispositivos: nunca se siguen
            raw.append(Entry("", m.size, -1, dt.datetime.fromtimestamp(m.mtime) if m.mtime else None, m.isdir(),
                             raw=m.name))
            if len(raw) > MAX_ENTRIES:
                break
    return _finish(ArchiveInfo(path, "TAR"), raw)


def _read_7z(path: str) -> ArchiveInfo:
    """7Z con py7zr: nombres en cualquier idioma y detección de cifrado (incluida la cabecera)."""
    import py7zr

    info = ArchiveInfo(path, "7Z")
    try:
        with py7zr.SevenZipFile(path, "r") as z:
            enc = z.needs_password()
            raw = []
            for i in z.list():
                raw.append(Entry("", int(i.uncompressed or 0), int(i.compressed or -1) if i.compressed else -1,
                                 i.creationtime if hasattr(i, "creationtime") else None, bool(i.is_directory),
                                 bool(enc), raw=i.filename))
                if len(raw) > MAX_ENTRIES:
                    break
    except py7zr.exceptions.PasswordRequired:
        info.encrypted = True
        info.warnings.append("El archivo está cifrado con contraseña (incluidos los nombres): no se puede listar.")
        return info
    except (py7zr.exceptions.Bad7zFile, EOFError, OSError, ValueError) as e:
        raise ArchiveError("El archivo 7Z está dañado o no es compatible.") from e
    return _finish(info, raw)


_LINE = re.compile(r"^(?P<mode>\S{10})\s+\d+\s+\S+\s+\S+\s+(?P<size>\d+)\s+\S+\s+\S+\s+\S+\s(?P<name>.*)$")


def _read_bsdtar(path: str) -> ArchiveInfo:
    exe = _bsdtar()
    ext = Path(path).suffix.lower().lstrip(".").upper() or "Archivo"
    if exe is None:
        raise ArchiveError("Para abrir este formato hace falta tar.exe, que incluye Windows 10 y 11.")
    try:
        r = subprocess.run([exe, "-tvf", path], capture_output=True, timeout=60, creationflags=_no_window())
    except subprocess.TimeoutExpired as e:
        raise ArchiveError("El archivo tarda demasiado en leerse.") from e
    enc = locale.getpreferredencoding(False) or "mbcs"
    err = r.stderr.decode(enc, "replace")
    if r.returncode != 0 and ("ncrypt" in err or "assphrase" in err):
        info = ArchiveInfo(path, ext, encrypted=True)
        info.warnings.append("El archivo está cifrado con contraseña (incluidos los nombres): no se puede listar.")
        return info
    raw = []
    for line in r.stdout.decode(enc, "replace").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        name = m["name"]
        is_dir = m["mode"].startswith("d") or name.endswith("/")
        raw.append(Entry("", int(m["size"]), -1, None, is_dir, raw=name))
        if len(raw) > MAX_ENTRIES:
            break
    if r.returncode != 0 and not raw:
        if "Unrecognized archive format" in err or "not recognized" in err.lower():
            raise ArchiveError("No es un archivo comprimido compatible o está dañado.")
        raise ArchiveError("No se pudo leer el archivo: está dañado o su formato no es compatible.")
    info = _finish(ArchiveInfo(path, ext), raw)
    if r.returncode != 0:
        info.warnings.append("El archivo parece dañado: puede que falten elementos.")
    if any("?" in e.raw for e in info.entries):
        info.warnings.append("Algunos nombres usan caracteres que Windows no puede transmitir; esos elementos no se "
                             "pueden abrir.")
    return info


# --------------------------------------------------------------------------- extracción de un elemento
class Workspace:
    """Carpeta temporal propia para las vistas previas; se borra entera al cerrar."""

    def __init__(self, base: Path | None = None):
        from aero.core.paths import cache_dir

        root = Path(base) if base else cache_dir() / "archive-preview"
        root.mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="ql-", dir=root))

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    @staticmethod
    def purge_old(base: Path | None = None) -> None:
        """Restos de sesiones anteriores (p. ej. si la aplicación se cerró de golpe)."""
        from aero.core.paths import cache_dir

        shutil.rmtree(Path(base) if base else cache_dir() / "archive-preview", ignore_errors=True)


def check_entry(e: Entry) -> None:
    if e.unsafe:
        raise UnsafeEntry("Este elemento intenta escribirse fuera de su carpeta y se ha bloqueado por seguridad.")
    if e.encrypted:
        raise PasswordRequired("Este elemento está protegido con contraseña.")
    if e.size > MAX_EXTRACT:
        raise ArchiveError("Es demasiado grande para previsualizarlo sin extraer el archivo.")
    if e.packed > 0 and e.size > RATIO_MIN_SIZE and e.size / e.packed > MAX_RATIO:
        raise ArchiveError("La compresión de este elemento es anómala (posible bomba de compresión); no se abre.")
    if "?" in e.raw and e.packed < 0:
        raise ArchiveError("El nombre de este elemento no se puede transmitir; extrae el archivo con otra herramienta.")


def _target(ws: Workspace, e: Entry) -> Path:
    # Cada extracción en su propia subcarpeta con solo el nombre base: nunca hay rutas del archivo en disco.
    d = ws.dir / uuid.uuid4().hex[:12]
    d.mkdir()
    out = (d / e.base).resolve()
    if out.parent != d.resolve():
        raise UnsafeEntry("Nombre de elemento no válido.")
    return out


def _copy_limited(src, dst: Path, limit: int) -> None:
    n = 0
    with open(dst, "wb") as fh:
        while True:
            chunk = src.read(_CHUNK)
            if not chunk:
                break
            n += len(chunk)
            if n > limit:
                raise ArchiveError("El contenido real supera el tamaño declarado; se ha detenido la extracción.")
            fh.write(chunk)


def extract_entry(info: ArchiveInfo, e: Entry, ws: Workspace) -> Path:
    """Extrae solo `e` a la carpeta temporal y devuelve la ruta del archivo."""
    check_entry(e)
    if e.is_dir:
        raise ArchiveError("Es una carpeta.")
    out = _target(ws, e)
    limit = min(MAX_EXTRACT, e.size + 1024) if e.size else MAX_EXTRACT
    try:
        if info.fmt == "ZIP":
            with zipfile.ZipFile(info.path) as z, z.open(e.raw) as src:
                _copy_limited(src, out, limit)
        elif info.fmt == "7Z":
            import py7zr

            with py7zr.SevenZipFile(info.path, "r") as z:
                z.extract(path=out.parent / "_7z", targets=[e.raw])
            got = out.parent / "_7z" / e.raw
            if not got.is_file() or got.stat().st_size > limit:
                raise ArchiveError("No se pudo leer este elemento.")
            os.replace(got, out)
            shutil.rmtree(out.parent / "_7z", ignore_errors=True)
        elif info.fmt == "DISC":
            from aero.archive import disc

            with open(out, "wb") as fh:
                disc.copy_member(info.path, e.raw, fh, limit)
        elif info.fmt == "TAR":
            with tarfile.open(info.path) as t:
                m = t.getmember(e.raw)
                if not m.isfile():
                    raise UnsafeEntry("Solo se abren archivos normales.")
                src = t.extractfile(m)
                _copy_limited(src, out, limit)
        else:
            _extract_bsdtar(info.path, e, out, limit)
    except RuntimeError as err:  # zipfile: «File is encrypted»
        out.unlink(missing_ok=True)
        if "encrypt" in str(err).lower() or "password" in str(err).lower():
            raise PasswordRequired("Este elemento está protegido con contraseña.") from err
        raise ArchiveError(str(err)) from err
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError, KeyError) as err:
        out.unlink(missing_ok=True)
        if isinstance(err, ArchiveError):
            raise
        raise ArchiveError("No se pudo leer este elemento: el archivo puede estar dañado.") from err
    except ArchiveError:
        out.unlink(missing_ok=True)
        raise
    return out


def _extract_bsdtar(path: str, e: Entry, out: Path, limit: int) -> None:
    exe = _bsdtar()
    if exe is None:
        raise ArchiveError("Para abrir este formato hace falta tar.exe, que incluye Windows 10 y 11.")
    # -O: el contenido sale por la salida estándar; bsdtar nunca escribe rutas del archivo en disco.
    p = subprocess.Popen([exe, "-xOf", path, e.raw], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=_no_window())
    try:
        _copy_limited(p.stdout, out, limit)
    except ArchiveError:
        p.kill()
        raise
    finally:
        err = p.stderr.read().decode(locale.getpreferredencoding(False) or "mbcs", "replace")
        p.wait(timeout=30)
    if p.returncode != 0:
        if "ncrypt" in err or "assphrase" in err:
            raise PasswordRequired("Este elemento está protegido con contraseña.")
        raise ArchiveError("No se pudo leer este elemento: el archivo puede estar dañado.")
