"""Extraer y comprimir archivos (como WinRAR o 7-Zip), con seguridad y progreso.

Motores, de más a menos preferido:
* ZIP: `zipfile` (nombres UTF-8, cualquier idioma) y `pyzipper` cuando hay contraseña (AES-256).
* 7Z: `py7zr` (LZMA2, AES-256, cualquier nombre).
* TAR, TAR.GZ, TAR.XZ, TAR.BZ2: `tarfile` con el filtro seguro «data».
* RAR: extraer con `Rar.exe`/`UnRAR.exe` si WinRAR está instalado (contraseñas y cualquier nombre) o con el
  `tar.exe` de Windows; CREAR un RAR solo es posible con WinRAR instalado (formato propietario).
* CAB, ISO y otros: `tar.exe` de Windows (solo extraer).

Seguridad al extraer: nada se escribe fuera de la carpeta de destino (rutas absolutas, «..», unidades y
enlaces se rechazan); los motores externos extraen primero a una carpeta temporal dentro del destino, que se
revisa antes de mover nada; bombas de compresión (ratios anómalos) y falta de espacio se detectan antes de
empezar. Al comprimir se escribe en un archivo temporal y solo al terminar se renombra.
"""

from __future__ import annotations

import functools

import os
import re
import shutil
import stat
import subprocess
import tarfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from aero.archive import (ArchiveError, PasswordRequired, _bsdtar, _no_window, is_archive, read_archive,
                          safe_name)

BOMB_RATIO = 1000            # tamaño/comprimido por encima de esto, en archivos grandes, se rechaza
BOMB_MIN = 256 * 1024 ** 2
WRITE_FORMATS = {"zip": "ZIP", "aeroarchive": "AERO Player (.aeroarchive)", "7z": "7Z", "tar.gz": "TAR.GZ",
                 "tar.xz": "TAR.XZ", "rar": "RAR (WinRAR)"}
LEVELS = {0: "Sin comprimir", 1: "Rápida", 5: "Normal", 7: "Alta", 9: "Máxima"}


@dataclass
class Result:
    files: int = 0
    skipped: list[str] = field(default_factory=list)
    unsafe: list[str] = field(default_factory=list)
    dest: str = ""
    output: str = ""


class Cancelled(ArchiveError):
    pass


# --------------------------------------------------------------------------- progreso
class Stats:
    """Estado del trabajo en curso. Lo escribe el hilo de trabajo y lo lee la ventana con un temporizador
    (solo números y textos: asignaciones atómicas en Python, sin bloqueos ni objetos Qt).

    `total_bytes = 0` significa que no se conoce el total: la ventana muestra un indicador indeterminado
    en lugar de inventar un porcentaje.
    """

    def __init__(self):
        self.phase = "Preparando…"
        self.total_bytes = 0
        self.done_bytes = 0
        self.total_files = 0
        self.done_files = 0
        self.current = ""
        self.exact = True        # False: el avance dentro del archivo actual no se conoce (p. ej. 7Z al crear)
        self.proc: subprocess.Popen | None = None   # programa externo en marcha (se mata al cancelar)


class _Staging:
    """Mide lo que un motor externo va escribiendo en la carpeta temporal (progreso real en bytes)."""

    def __init__(self, folder: Path, st: Stats):
        self.folder, self.st = folder, st
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, name="aero-staging", daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(2)

    def _loop(self):
        wait = 0.3
        while not self._stop.wait(wait):
            t0 = time.monotonic()
            total = 0
            for root, _d, files_ in os.walk(self.folder):
                for f in files_:
                    try:
                        total += os.stat(os.path.join(root, f)).st_size
                    except OSError:
                        pass
            self.st.done_bytes = total
            # Con muchísimos archivos medir cuesta: se mide menos a menudo para no competir con la extracción.
            wait = max(0.3, (time.monotonic() - t0) * 8)


# --------------------------------------------------------------------------- herramientas externas
def winrar() -> str | None:
    """Rar.exe de WinRAR si está instalado (sirve para crear RAR y extraer RAR cifrados)."""
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        for exe in ("Rar.exe", "UnRAR.exe"):
            p = Path(base) / "WinRAR" / exe
            if base and p.exists():
                return str(p)
    return shutil.which("rar")


def can_write(fmt: str) -> bool:
    return fmt != "rar" or (winrar() or "").lower().endswith("rar.exe")


def available_write_formats() -> dict[str, str]:
    return {k: v for k, v in WRITE_FORMATS.items() if can_write(k)}


def format_of(path: str) -> str:
    low = path.lower()
    for ext in (".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tbz2", ".tar"):
        if low.endswith(ext):
            return "tar"
    ext = Path(low).suffix
    if ext in (".iso", ".img", ".bin", ".cue", ".nrg", ".mdf", ".udf"):
        return "disc"
    return {".zip": "zip", ".cbz": "zip", ".aeroarchive": "zip", ".7z": "7z", ".cb7": "7z", ".rar": "rar", ".cbr": "rar"}.get(ext, "other")


# --------------------------------------------------------------------------- utilidades
@functools.lru_cache(maxsize=8192)
def _real_dir(d: str) -> str:
    """Carpeta real (resolviendo enlaces y uniones). En Windows cada resolve() consulta al sistema: se guarda por
    carpeta, no por archivo (con 2000 archivos, 40 consultas en vez de 4000). La caché se vacía en cada extracción."""
    return os.path.normcase(str(Path(d).resolve()))


def _inside(base: Path, target: Path) -> bool:
    """¿`target` queda dentro de `base` una vez resueltos enlaces y uniones? (protección «Zip Slip»)."""
    b = _real_dir(str(base))
    t = os.path.abspath(str(target))
    parent, name = os.path.split(t)
    real = os.path.join(_real_dir(parent), os.path.normcase(name)) if name else _real_dir(t)
    if os.path.islink(t) or (name and os.path.isdir(t) and _real_dir(t) != os.path.normcase(real)):
        real = _real_dir(t)                      # el propio destino es un enlace o una unión: se resuelve entero
    return real == b or real.startswith(b.rstrip(r"\/") + os.sep)


def _unique(p: Path) -> Path:
    if not p.exists():
        return p
    stem, suf = (p.stem, p.suffix) if p.is_file() or p.suffix else (p.name, "")
    for i in range(2, 10000):
        cand = p.with_name(f"{stem} ({i}){suf}")
        if not cand.exists():
            return cand
    raise ArchiveError("No se encontró un nombre libre.")


def _free_space(path: Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 1 << 62


def suggested_folder(archive: str) -> Path:
    """Carpeta «nombre» junto al archivo (sin las extensiones dobles .tar.gz)."""
    p = Path(archive)
    name = p.name
    for ext in (".tar.gz", ".tar.xz", ".tar.bz2", ".tgz", ".txz", ".tbz2"):
        if name.lower().endswith(ext):
            return p.with_name(name[: -len(ext)])
    return p.with_name(p.stem)


def _check_bombs(info, dest: Path) -> int:
    """Rechaza bombas de compresión y falta de espacio. Devuelve el tamaño total a extraer."""
    total = 0
    for e in info.entries:
        if e.is_dir:
            continue
        total += e.size
        if e.packed > 0 and e.size > BOMB_MIN and e.size / e.packed > BOMB_RATIO:
            raise ArchiveError(f"«{e.base}» tiene una compresión anómala (posible bomba de compresión). "
                               "Por seguridad no se extrae.")
    if total > _free_space(dest) * 0.97:
        raise ArchiveError("No hay espacio suficiente en el disco de destino.")
    return total


class _Created:
    """Lo que crea una extracción directa en el destino, para deshacerlo si se cancela o falla."""

    def __init__(self, dest: Path):
        self.dest = dest
        self.files: list[Path] = []
        self.dirs: list[Path] = []

    def mkdirs(self, d: Path) -> None:
        missing = []
        while not d.exists() and d != self.dest and _inside(self.dest, d):
            missing.append(d)
            d = d.parent
        for m in reversed(missing):
            m.mkdir(exist_ok=True)
            self.dirs.append(m)

    def rollback(self) -> None:
        for f in self.files:
            try:
                f.unlink()
            except OSError:
                pass
        for d in sorted(self.dirs, key=lambda x: len(x.parts), reverse=True):
            try:
                d.rmdir()  # solo si quedó vacía: nunca se borra nada que no hayamos creado
            except OSError:
                pass


def _place(src: Path, target: Path, mode: str, created: _Created | None = None) -> Path | None:
    """Mueve un archivo extraído a su sitio según el modo: rename | overwrite | skip."""
    if target.exists():
        if mode == "skip":
            return None
        if mode == "rename":
            target = _unique(target)
        else:
            if target.is_dir():
                return None
            target.unlink()
    if created is not None:
        created.mkdirs(target.parent)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, target) if src.drive == target.drive else shutil.move(str(src), str(target))
    if created is not None:
        created.files.append(target)
    return target


def _merge_staging(staging: Path, dest: Path, mode: str, res: Result, st: Stats) -> None:
    """Revisa lo extraído por un programa externo y lo mueve al destino (sin enlaces ni rutas raras)."""
    st.phase = "Colocando los archivos…"
    created = _Created(dest)
    try:
        for root, dirs, files_ in os.walk(staging):
            rp = Path(root)
            for d in list(dirs):
                dp = rp / d
                if dp.is_symlink() or (os.name == "nt" and _is_reparse(dp)):
                    res.unsafe.append(str(dp.relative_to(staging)))
                    dirs.remove(d)
            for f in files_:
                fp = rp / f
                rel = fp.relative_to(staging)
                if fp.is_symlink() or (os.name == "nt" and _is_reparse(fp)):
                    res.unsafe.append(str(rel))
                    continue
                target = dest / rel
                if not _inside(dest, target):
                    res.unsafe.append(str(rel))
                    continue
                if _place(fp, target, mode, created) is None:
                    res.skipped.append(str(rel))
                else:
                    res.files += 1
        for root, dirs, _f in os.walk(staging):
            for d in dirs:
                created.mkdirs(dest / Path(root).relative_to(staging) / d)
    except BaseException:
        created.rollback()
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _is_reparse(p: Path) -> bool:
    try:
        return bool(os.lstat(p).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return False


def _run(args: list[str], st: Stats, cancelled, name_from_line=None, cwd: str | None = None) -> tuple[int, str]:
    """Ejecuta un programa externo sin bloquear la cancelación: la salida se lee en otro hilo y aquí se
    comprueba cada 0,1 s si el usuario canceló (entonces se termina el proceso, sin dejar huérfanos)."""
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         creationflags=_no_window(), cwd=cwd)
    st.proc = p
    tail: list[str] = []

    def reader():
        for raw in iter(p.stdout.readline, b""):
            for part in re.split(rb"[\r\x08]+", raw):
                line = part.decode("utf-8", "replace").strip()
                if not line or re.fullmatch(r"\d+%", line):
                    continue
                tail.append(line)
                del tail[:-8]
                name = name_from_line(line) if name_from_line else None
                if name:
                    st.done_files += 1
                    st.current = name

    t = threading.Thread(target=reader, name="aero-proc-out", daemon=True)
    t.start()
    try:
        while p.poll() is None:
            if cancelled():
                p.kill()
                p.wait()
                raise Cancelled("Cancelado.")
            time.sleep(0.1)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        t.join(2)
        st.proc = None
    if cancelled():  # la ventana pudo terminar el proceso directamente: su código de salida no vale
        raise Cancelled("Cancelado.")
    return p.returncode, "\n".join(tail)


def _legacy(progress, st: Stats):
    """Convierte las actualizaciones al formato antiguo progress(i, n, nombre) (pruebas y llamadas viejas)."""
    def tick(name: str):
        st.done_files += 1
        st.current = name
        progress(st.done_files, max(1, st.total_files), name)
    return tick


# --------------------------------------------------------------------------- extraer
def extract(path: str, dest: str, password: str | None = None, mode: str = "rename", members: list[str] | None = None,
            progress=lambda i, n, name: None, cancelled=lambda: False, stats: Stats | None = None) -> Result:
    """Extrae el archivo (o solo `members`, nombres internos normalizados) en `dest`.

    Si se cancela o falla, se deshace lo que esta extracción hubiera escrito en el destino."""
    st = stats or Stats()
    _real_dir.cache_clear()          # enlaces o uniones creados desde la última extracción se vuelven a mirar
    src = Path(path)
    if not src.is_file():
        raise ArchiveError("El archivo ya no existe.")
    dest_p = Path(dest)
    dest_p.mkdir(parents=True, exist_ok=True)
    fmt = format_of(path)
    res = Result(dest=str(dest_p))
    st.phase = "Leyendo el índice…"
    if fmt == "7z":
        return _extract_7z(src, dest_p, password, mode, members, progress, cancelled, res, st)
    if fmt == "disc":
        info = read_archive(str(src))
        if info.fmt == "DISC":
            return _extract_disc(src, info, dest_p, mode, members, progress, cancelled, res, st)
    if fmt == "zip" or zipfile.is_zipfile(src):
        return _extract_zip(src, dest_p, password, mode, members, progress, cancelled, res, st)
    if fmt == "tar":
        try:
            return _extract_tar(src, dest_p, mode, members, progress, cancelled, res, st)
        except tarfile.TarError:
            pass
    return _extract_external(src, dest_p, password, mode, members, progress, cancelled, res, fmt, st)


def _wanted(name: str, members) -> bool:
    if not members:
        return True
    return any(name == m or name.startswith(m.rstrip("/") + "/") for m in members)


def _extract_zip(src, dest, password, mode, members, progress, cancelled, res, st):
    info = read_archive(str(src))
    _check_bombs(info, dest)
    try:
        import pyzipper

        z = pyzipper.AESZipFile(src)
    except ImportError:
        z = zipfile.ZipFile(src)
    created = _Created(dest)
    tick = _legacy(progress, st)
    with z:
        items = [i for i in z.infolist() if _wanted(safe_name(i.filename)[0], members)]
        if any(i.flag_bits & 0x1 for i in items) and not password:
            raise PasswordRequired("Este archivo está protegido con contraseña.")
        if password:
            z.setpassword(password.encode("utf-8"))
        files_ = [i for i in items if not i.is_dir()]
        st.total_files = len(files_)
        st.total_bytes = sum(i.file_size for i in files_)
        st.phase = "Extrayendo"
        try:
            for i in items:
                if cancelled():
                    raise Cancelled("Cancelado.")
                name, unsafe = safe_name(i.filename)
                if unsafe or not name:
                    res.unsafe.append(i.filename)
                    continue
                target = dest / name
                if not _inside(dest, target):
                    res.unsafe.append(i.filename)
                    continue
                if i.is_dir():
                    created.mkdirs(target)
                    continue
                if target.exists():
                    if mode == "skip":
                        res.skipped.append(name)
                        st.done_bytes += i.file_size
                        continue
                    if mode == "rename":
                        target = _unique(target)
                created.mkdirs(target.parent)
                st.current = name
                # Nuevo: se escribe directamente (si se cancela o falla, lo borra la vuelta atrás). Si ya existe, se
                # escribe aparte y se reemplaza al final: el original nunca queda a medias.
                fresh = not target.exists()
                tmp = target if fresh else target.with_name(f".{target.name}.{uuid.uuid4().hex[:6]}.part")
                if fresh:
                    created.files.append(target)
                try:
                    with z.open(i) as fin, open(tmp, "wb") as fout:
                        limit = i.file_size + 1024
                        copied = 0
                        while True:
                            chunk = fin.read(1 << 20)
                            if not chunk:
                                break
                            copied += len(chunk)
                            if copied > limit:
                                raise ArchiveError("El contenido real supera el tamaño declarado; se detiene.")
                            fout.write(chunk)
                            st.done_bytes += len(chunk)
                            if cancelled():
                                raise Cancelled("Cancelado.")
                    if not fresh:
                        os.replace(tmp, target)
                except RuntimeError as e:
                    tmp.unlink(missing_ok=True)
                    if "password" in str(e).lower() or "encrypt" in str(e).lower():
                        raise PasswordRequired("La contraseña no es correcta.") from e
                    raise ArchiveError(str(e)) from e
                except (zipfile.BadZipFile, OSError) as e:
                    tmp.unlink(missing_ok=True)
                    raise ArchiveError(f"No se pudo extraer «{name}»: el archivo puede estar dañado.") from e
                except BaseException:
                    tmp.unlink(missing_ok=True)
                    raise
                res.files += 1
                tick(name)
        except BaseException:
            created.rollback()
            raise
    return res


def _extract_disc(src, info, dest, mode, members, progress, cancelled, res, st):
    """Imagen de disco sin montar: se abre una vez y se copia cada archivo por bloques (progreso real)."""
    from aero.archive import disc

    _check_bombs(info, dest)
    items = [e for e in info.entries if _wanted(e.name, members)]
    files_ = [e for e in items if not e.is_dir]
    st.total_files = len(files_)
    st.total_bytes = sum(e.size for e in files_)
    st.phase = "Extrayendo"
    created = _Created(dest)
    tick = _legacy(progress, st)
    try:
        with disc.Disc(str(src)) as d:
            for e in sorted(items, key=lambda x: (not x.is_dir, x.name)):
                if cancelled():
                    raise Cancelled("Cancelado.")
                if e.unsafe or not e.name:
                    res.unsafe.append(e.raw)
                    continue
                target = dest / e.name
                if not _inside(dest, target):
                    res.unsafe.append(e.raw)
                    continue
                if e.is_dir:
                    created.mkdirs(target)
                    continue
                if target.exists():
                    if mode == "skip":
                        res.skipped.append(e.name)
                        st.done_bytes += e.size
                        continue
                    if mode == "rename":
                        target = _unique(target)
                created.mkdirs(target.parent)
                st.current = e.name
                # Nuevo: se escribe directamente (si se cancela o falla, lo borra la vuelta atrás). Si ya existe, se
                # escribe aparte y se reemplaza al final: el original nunca queda a medias.
                fresh = not target.exists()
                tmp = target if fresh else target.with_name(f".{target.name}.{uuid.uuid4().hex[:6]}.part")
                if fresh:
                    created.files.append(target)
                try:
                    with d.open_member(e.raw) as fin, open(tmp, "wb") as fout:
                        copied, limit = 0, e.size + 1024
                        while True:
                            chunk = fin.read(1 << 20)
                            if not chunk:
                                break
                            copied += len(chunk)
                            if copied > limit:
                                raise ArchiveError("El contenido real supera el tamaño declarado; se detiene.")
                            fout.write(chunk)
                            st.done_bytes += len(chunk)
                            if cancelled():
                                raise Cancelled("Cancelado.")
                    if not fresh:
                        os.replace(tmp, target)
                except BaseException:
                    tmp.unlink(missing_ok=True)
                    raise
                res.files += 1
                tick(e.name)
    except disc.DiscError as err:
        created.rollback()
        raise ArchiveError(str(err)) from err
    except OSError as err:
        created.rollback()
        raise ArchiveError(f"No se pudo extraer: {err}") from err
    except BaseException:
        created.rollback()
        raise
    return res


def _extract_tar(src, dest, mode, members, progress, cancelled, res, st):
    staging = dest / f".aero-{uuid.uuid4().hex[:8]}"
    tick = _legacy(progress, st)
    with tarfile.open(src) as t:
        items = [m for m in t.getmembers() if _wanted(safe_name(m.name)[0], members)]
        st.total_files = sum(1 for m in items if m.isfile())
        st.total_bytes = sum(m.size for m in items if m.isfile())
        if st.total_bytes > _free_space(dest) * 0.97:
            raise ArchiveError("No hay espacio suficiente en el disco de destino.")
        st.phase = "Extrayendo"
        staging.mkdir()
        try:
            for m in items:
                if cancelled():
                    raise Cancelled("Cancelado.")
                name, unsafe = safe_name(m.name)
                if unsafe or not name or not (m.isfile() or m.isdir()):
                    res.unsafe.append(m.name)
                    continue
                out = staging / name
                if m.isdir():
                    out.mkdir(parents=True, exist_ok=True)
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                st.current = name
                fin = t.extractfile(m)
                with open(out, "wb") as fout:
                    while True:
                        chunk = fin.read(1 << 20)
                        if not chunk:
                            break
                        fout.write(chunk)
                        st.done_bytes += len(chunk)
                        if cancelled():
                            raise Cancelled("Cancelado.")
                tick(name)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    _merge_staging(staging, dest, mode, res, st)
    return res


def _extract_7z(src, dest, password, mode, members, progress, cancelled, res, st):
    import py7zr

    staging = None
    try:
        with py7zr.SevenZipFile(src, "r", password=password) as z:
            encrypted = z.needs_password()
            if encrypted and not password:
                raise PasswordRequired("Este archivo está protegido con contraseña.")
            infos = z.list()
            st.total_bytes = sum(i.uncompressed or 0 for i in infos if not i.is_directory)
            st.total_files = sum(1 for i in infos if not i.is_directory)
            if st.total_bytes > _free_space(dest) * 0.97:
                raise ArchiveError("No hay espacio suficiente en el disco de destino.")
            names = [i.filename for i in infos if _wanted(safe_name(i.filename)[0], members)]
            bad = [n for n in names if safe_name(n)[1]]
            res.unsafe += bad
            names = [n for n in names if n not in bad]
            if members:
                st.total_files = len(names)
                st.total_bytes = sum(i.uncompressed or 0 for i in infos if i.filename in set(names))
            staging = dest / f".aero-{uuid.uuid4().hex[:8]}"
            staging.mkdir()
            st.phase = "Extrayendo"
            tick = _legacy(progress, st)
            tar = _bsdtar()
            # Sin contraseña, el tar.exe de Windows (libarchive, en C) es ~2,5 veces más rápido que py7zr.
            if tar and not encrypted and not bad:
                with _Staging(staging, st):
                    args = [tar, "-x", "-v", "-f", str(src), "-C", str(staging)] + (names if members else [])
                    code, _tail = _run(args, st, cancelled, lambda ln: ln[2:] if ln.startswith("x ") and not ln.endswith("/") else None)
                if code == 0:
                    progress(st.total_files, max(1, st.total_files), src.name)
                else:
                    shutil.rmtree(staging, ignore_errors=True)
                    staging.mkdir()
                    st.done_files = 0
                    code = None  # se reintenta con py7zr
            else:
                code = None
            if code is None:
                z.reset()

                class _CB(py7zr.callbacks.ExtractCallback):
                    def report_start_preparation(self):
                        pass

                    def report_start(self, processing_file_path, processing_bytes):
                        if cancelled():
                            raise Cancelled("Cancelado.")
                        st.current = processing_file_path

                    def report_update(self, decompressed_bytes):
                        pass

                    def report_end(self, processing_file_path, wrote_bytes):
                        tick(processing_file_path)

                    def report_postprocess(self):
                        pass

                    def report_warning(self, message):
                        pass

                with _Staging(staging, st):
                    z.extract(path=staging, targets=names if members else None, callback=_CB())
    except py7zr.exceptions.PasswordRequired as e:
        _rm(staging)
        raise PasswordRequired("Este archivo está protegido con contraseña.") from e
    except (py7zr.exceptions.Bad7zFile, py7zr.exceptions.CrcError, OSError, EOFError) as e:
        _rm(staging)
        msg = str(e).lower()
        if password and ("crc" in msg or "password" in msg or "lzma" in msg or "data" in msg):
            raise PasswordRequired("La contraseña no es correcta.") from e
        raise ArchiveError("El archivo 7Z está dañado o no es compatible.") from e
    except ArchiveError:
        _rm(staging)
        raise
    except Exception as e:  # noqa: BLE001 - py7zr lanza errores variados con contraseñas erróneas
        _rm(staging)
        if password:
            raise PasswordRequired("La contraseña no es correcta.") from e
        raise ArchiveError(f"No se pudo extraer: {e}") from e
    except BaseException:
        _rm(staging)
        raise
    _merge_staging(staging, dest, mode, res, st)
    return res


def _rm(folder: Path | None) -> None:
    if folder is not None:
        shutil.rmtree(folder, ignore_errors=True)


def _extract_external(src, dest, password, mode, members, progress, cancelled, res, fmt, st):
    info = read_archive(str(src))
    if info.encrypted and not password and not (fmt == "rar" and winrar()):
        raise PasswordRequired("Este archivo está protegido con contraseña.")
    _check_bombs(info, dest)
    wanted = [e for e in info.files if _wanted(e.name, members)]
    st.total_files = len(wanted)
    st.total_bytes = sum(e.size for e in wanted)
    st.phase = "Extrayendo"
    staging = dest / f".aero-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    rar = winrar() if fmt == "rar" else None
    try:
        with _Staging(staging, st):
            if rar:
                args = [rar, "x", "-y", "-o+", "-idc", "-scfr", f"-p{password}" if password else "-p-", str(src)]
                args += [m.replace("/", "\\") for m in (members or [])]
                args.append(str(staging) + os.sep)
                code, tail = _run(args, st, cancelled,
                                  lambda ln: ln.split(maxsplit=1)[1].rsplit(" ", 1)[0].strip()
                                  if (ln.startswith("Extrayendo") or ln.startswith("Extracting"))
                                  and len(ln.split(maxsplit=1)) > 1 else None)
                if code in (11, 3) or "contraseña" in tail.lower() or "password" in tail.lower():
                    raise PasswordRequired("La contraseña no es correcta." if password else
                                           "Este archivo está protegido con contraseña.")
                if code not in (0, 1):
                    raise ArchiveError("WinRAR no pudo extraer el archivo: " + tail.splitlines()[-1][:160]
                                       if tail else "WinRAR no pudo extraer el archivo.")
            else:
                exe = _bsdtar()
                if exe is None:
                    raise ArchiveError("Para este formato hace falta tar.exe (incluido en Windows 10 y 11).")
                args = [exe, "-x", "-v", "-f", str(src), "-C", str(staging)]
                if password:
                    args[1:1] = ["--passphrase", password]
                args += [e.raw for e in info.entries if members and _wanted(e.name, members) and not e.is_dir]
                code, tail = _run(args, st, cancelled, lambda ln: ln[2:] if ln.startswith("x ") and not ln.endswith("/") else None)
                if code != 0:
                    low = tail.lower()
                    if "ncrypt" in low or "passphrase" in low:
                        raise PasswordRequired("La contraseña no es correcta." if password else
                                               "Este archivo está protegido con contraseña.")
                    if not any(staging.rglob("*")):
                        raise ArchiveError("No se pudo extraer: el archivo está dañado o no es compatible.")
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    progress(st.total_files, max(1, st.total_files), src.name)
    _merge_staging(staging, dest, mode, res, st)
    return res


def extract_here(path: str, **kw) -> Result:
    return extract(path, str(Path(path).parent), **kw)


def extract_to_folder(path: str, **kw) -> Result:
    """«Extraer en nombre\\»: crea (o reutiliza con nombre libre) la carpeta junto al archivo."""
    folder = suggested_folder(path)
    if folder.exists() and any(folder.iterdir()):
        folder = _unique(folder)
    return extract(path, str(folder), **kw)


# --------------------------------------------------------------------------- comprimir
def _gather(sources: list[str], st: Stats | None = None, cancelled=lambda: False
            ) -> tuple[Path, list[tuple[Path, str, int]]]:
    """(carpeta base, [(ruta, nombre en el archivo, tamaño)]). Las carpetas se recorren sin seguir enlaces."""
    srcs = [Path(s).resolve() for s in sources]
    base = srcs[0].parent
    if not all(s.parent == base for s in srcs):
        base = Path(os.path.commonpath([str(s.parent) for s in srcs]))
    items: list[tuple[Path, str, int]] = []

    def add_file(fp: Path):
        try:
            size = fp.stat().st_size
        except OSError:
            return
        items.append((fp, fp.relative_to(base).as_posix(), size))
        if st is not None:
            st.total_files += 1
            st.total_bytes += size
            if st.total_files % 200 == 0 and cancelled():
                raise Cancelled("Cancelado.")

    for s in srcs:
        if s.is_dir() and not s.is_symlink():
            items.append((s, s.relative_to(base).as_posix() + "/", 0))
            for root, dirs, files_ in os.walk(s):
                dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
                for d in dirs:
                    items.append((Path(root) / d, (Path(root) / d).relative_to(base).as_posix() + "/", 0))
                for f in files_:
                    fp = Path(root) / f
                    if not fp.is_symlink():
                        add_file(fp)
        elif s.is_file():
            add_file(s)
    return base, items


def default_archive_name(sources: list[str], fmt: str) -> Path:
    first = Path(sources[0])
    stem = first.name if (len(sources) == 1 and first.is_dir()) else (first.stem if len(sources) == 1 else
                                                                     first.parent.name or "Archivo")
    ext = {"tar.gz": ".tar.gz", "tar.xz": ".tar.xz"}.get(fmt, "." + fmt)
    return _unique(first.parent / f"{stem}{ext}")


def _compress_aero(sources, out_p: Path, level, password, progress, cancelled, st) -> Result:
    """.aeroarchive: se crea un ZIP y se le pone la cabecera propia con metadatos y huella SHA-256."""
    from aero.archive import aeroformat

    inner = out_p.with_name(f".{out_p.name}.{uuid.uuid4().hex[:6]}.zip")
    try:
        res = compress(sources, str(inner), "zip", level, password, progress, cancelled, st)
        st.phase = "Terminando…"
        aeroformat.wrap(str(inner), str(out_p), res.files, st.total_bytes, bool(password))
    finally:
        inner.unlink(missing_ok=True)
    res.output = str(out_p)
    return res


# Niveles de la interfaz → ajustes de LZMA para 7Z y TAR.XZ. Medido con 50 MB de texto en un núcleo:
# preset 1 ≈ 27 MB/s, 4 ≈ 5 MB/s, 6 ≈ 3 MB/s, 9 ≈ 2 MB/s. «Normal» usa 4: casi la compresión de 6 en
# la mitad de tiempo (el módulo lzma de Python solo usa un núcleo).
LZMA_PRESET = {1: 1, 5: 4, 7: 6, 9: 9}


def _lzma_preset(level: int) -> int:
    return LZMA_PRESET.get(level, max(0, min(9, level)))


class _CountingReader:
    """Envuelve un archivo para contar los bytes leídos (progreso real al comprimir con tarfile)."""

    def __init__(self, f, st: Stats, cancelled):
        self.f, self.st, self.cancelled = f, st, cancelled

    def read(self, n=-1):
        data = self.f.read(n)
        self.st.done_bytes += len(data)
        if self.cancelled():
            raise Cancelled("Cancelado.")
        return data


def compress(sources: list[str], out: str, fmt: str = "zip", level: int = 5, password: str | None = None,
             progress=lambda i, n, name: None, cancelled=lambda: False, stats: Stats | None = None) -> Result:
    st = stats or Stats()
    if fmt == "aeroarchive":
        return _compress_aero(sources, Path(out), level, password, progress, cancelled, st)
    if not sources:
        raise ArchiveError("No hay nada que comprimir.")
    missing = [s for s in sources if not os.path.exists(s)]
    if missing:
        raise ArchiveError(f"No existe: {missing[0]}")
    out_p = Path(out)
    if out_p.resolve() in {Path(s).resolve() for s in sources}:
        raise ArchiveError("El archivo de salida no puede ser uno de los que se comprimen.")
    st.phase = "Buscando archivos…"
    base, items = _gather(sources, st, cancelled)
    st.total_files = sum(1 for _p, n, _s in items if not n.endswith("/"))
    if st.total_bytes > _free_space(out_p.parent) * 0.97 and level == 0:
        raise ArchiveError("No hay espacio suficiente en el disco de destino.")
    tmp = out_p.with_name(f".{out_p.name}.{uuid.uuid4().hex[:6]}.part")
    level = max(0, min(9, int(level)))
    res = Result(output=str(out_p), files=st.total_files)
    tick = _legacy(progress, st)
    st.phase = "Comprimiendo"
    try:
        if fmt == "zip":
            method = zipfile.ZIP_STORED if level == 0 else zipfile.ZIP_DEFLATED
            if password:
                import pyzipper

                z = pyzipper.AESZipFile(tmp, "w", compression=method, encryption=pyzipper.WZ_AES)
                z.setpassword(password.encode("utf-8"))
            else:
                z = zipfile.ZipFile(tmp, "w", compression=method, compresslevel=None if level == 0 else level)
            with z:
                for p, name, size in items:
                    if cancelled():
                        raise Cancelled("Cancelado.")
                    if name.endswith("/") or password:
                        st.current = name
                        z.write(p, name)  # cifrado AES: pyzipper solo escribe archivos completos
                        st.done_bytes += size
                    else:
                        st.current = name
                        zi = zipfile.ZipInfo.from_file(p, name)
                        zi.compress_type = method
                        if level:
                            zi.compress_level = level
                        with open(p, "rb") as fin, z.open(zi, "w", force_zip64=size > 0x7FFF0000) as fout:
                            while True:
                                chunk = fin.read(1 << 20)
                                if not chunk:
                                    break
                                fout.write(chunk)
                                st.done_bytes += len(chunk)
                                if cancelled():
                                    raise Cancelled("Cancelado.")
                    if not name.endswith("/"):
                        tick(name)
        elif fmt == "7z":
            import py7zr

            preset = _lzma_preset(level)
            filters = [{"id": py7zr.FILTER_COPY}] if level == 0 else [{"id": py7zr.FILTER_LZMA2, "preset": preset}]
            if password:
                filters.append({"id": py7zr.FILTER_CRYPTO_AES256_SHA256})
            st.exact = False  # py7zr no informa del avance dentro de cada archivo
            with py7zr.SevenZipFile(tmp, "w", filters=filters, password=password) as z:
                if password:
                    z.set_encrypted_header(True)
                for p, name, size in items:
                    if cancelled():
                        raise Cancelled("Cancelado.")
                    st.current = name
                    if name.endswith("/"):
                        z.write(p, name.rstrip("/"))  # también las carpetas vacías
                        continue
                    z.write(p, name)
                    st.done_bytes += size
                    tick(name)
            st.exact = True
        elif fmt in ("tar.gz", "tar.xz"):
            mode = "w:gz" if fmt == "tar.gz" else "w:xz"
            kw = {"compresslevel": max(1, level)} if fmt == "tar.gz" else {"preset": _lzma_preset(level)}
            with tarfile.open(tmp, mode, **kw) as t:
                for p, name, _size in items:
                    if cancelled():
                        raise Cancelled("Cancelado.")
                    st.current = name
                    ti = t.gettarinfo(str(p), name.rstrip("/"))
                    if ti.isreg():
                        with open(p, "rb") as f:
                            t.addfile(ti, _CountingReader(f, st, cancelled))
                        tick(name)
                    else:
                        t.addfile(ti)
        elif fmt == "rar":
            rar = winrar()
            if not rar or not rar.lower().endswith("rar.exe"):
                raise ArchiveError("Crear archivos RAR requiere WinRAR instalado (formato propietario).")
            list_file = out_p.with_name(f".{out_p.name}.{uuid.uuid4().hex[:6]}.lst")
            list_file.write_text("\n".join(n.rstrip("/").replace("/", "\\") for _p, n, _s in items
                                           if not n.endswith("/")), encoding="utf-8-sig")
            made = tmp.with_suffix(".rar")
            try:
                # -r-: sin recursión (la lista ya contiene cada archivo); -scfl: lista en UTF-8
                args = [rar, "a", "-y", "-idc", "-r-", f"-m{min(5, round(level * 5 / 9))}", "-scfl", "-scfr",
                        f"-mt{max(1, (os.cpu_count() or 2) // 2)}", str(made), f"@{list_file}"]
                if password:
                    args.insert(2, f"-hp{password}")
                sizes = {n.rstrip("/").replace("/", "\\").lower(): s for _p, n, s in items}

                def added(line: str):
                    m = re.match(r"(?:Añadiendo|Adding|Agregando)\s+(.+?)(?:\s+(?:OK|BIEN|Correcto))?\s*$", line)
                    if not m:
                        return None
                    name = m.group(1).strip()
                    st.done_bytes += sizes.get(name.lower(), 0)
                    return name

                code, tail = _run(args, st, cancelled, added, cwd=str(base))
                if code not in (0, 1) or not made.exists():
                    raise ArchiveError("WinRAR no pudo crear el archivo: " + tail.splitlines()[-1][:160]
                                       if tail else "WinRAR no pudo crear el archivo.")
                os.replace(made, tmp)
                progress(st.total_files, max(1, st.total_files), out_p.name)
            finally:
                list_file.unlink(missing_ok=True)
                made.unlink(missing_ok=True)
        else:
            raise ArchiveError(f"Formato no compatible para crear: {fmt}")
        if cancelled():
            raise Cancelled("Cancelado.")
        st.phase = "Terminando…"
        os.replace(tmp, out_p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return res


def test_archive(path: str, password: str | None = None) -> tuple[bool, str]:
    """Comprueba la integridad leyendo todo el contenido sin escribir nada en disco."""
    fmt = format_of(path)
    from aero.archive import aeroformat

    if aeroformat.is_aeroarchive(path):
        ok, msg = aeroformat.verify(path)
        if not ok:
            return False, msg
    try:
        if fmt == "zip" or zipfile.is_zipfile(path):
            import pyzipper

            with pyzipper.AESZipFile(path) as z:
                if password:
                    z.setpassword(password.encode("utf-8"))
                bad = z.testzip()
            return (bad is None, "Correcto: todos los archivos se leen sin errores." if bad is None
                    else f"Dañado: «{bad}» no supera la comprobación.")
        if fmt == "7z":
            import py7zr

            with py7zr.SevenZipFile(path, "r", password=password) as z:
                ok = z.test()
            return (ok is not False, "Correcto." if ok is not False else "Dañado.")
        if fmt == "tar":
            with tarfile.open(path) as t:
                for m in t:
                    if m.isfile():
                        f = t.extractfile(m)
                        while f.read(1024 * 1024):
                            pass
            return True, "Correcto."
        rar = winrar() if fmt == "rar" else None
        if rar:
            p = subprocess.run([rar, "t", "-idq", f"-p{password}" if password else "-p-", path], capture_output=True,
                               creationflags=_no_window(), stdin=subprocess.DEVNULL)
            return p.returncode == 0, "Correcto." if p.returncode == 0 else "Dañado o contraseña incorrecta."
        exe = _bsdtar()
        p = subprocess.run([exe, "-xOf", path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           creationflags=_no_window(), stdin=subprocess.DEVNULL)
        return p.returncode == 0, "Correcto." if p.returncode == 0 else "Dañado o no compatible."
    except Exception as e:  # noqa: BLE001
        return False, f"No se pudo comprobar: {e}"


__all__ = ["extract", "extract_here", "extract_to_folder", "compress", "test_archive", "is_archive", "winrar",
           "available_write_formats", "suggested_folder", "default_archive_name", "Result", "Cancelled", "Stats"]
