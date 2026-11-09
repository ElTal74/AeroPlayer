"""Actualizaciones desde GitHub Releases (sin Qt; la interfaz está en aero/ui/update_ui.py).

* Consulta `https://api.github.com/repos/<REPO>/releases/latest` (sin cuenta, sin enviar datos del usuario: solo
  la petición con un User-Agent genérico «AERO-Player/<versión>»).
* Si hay una versión mayor, descarga `AeroPlayer-<v>-setup.exe` y **comprueba su SHA-256** con el
  `SHA256SUMS.txt` publicado en la misma versión. Si no coincide, se borra y no se ejecuta nada.
* Instala con `setup.exe --update`: sin asistente, conservando las opciones y los datos, y vuelve a abrir la
  aplicación. Nunca se instala nada sin que el usuario pulse «Actualizar».
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from aero import UPDATE_REPO, __version__

API = "https://api.github.com/repos/{repo}/releases/latest"
TIMEOUT = 15


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    page: str
    setup_url: str
    setup_name: str
    setup_size: int
    sums_url: str
    setup_api: str = ""     # la misma descarga por api.github.com: sirve si github.com falla (pasa a veces)
    sums_api: str = ""


def parse_version(v: str) -> tuple[int, ...]:
    """«v1.2.10» → (1, 2, 10). Lo que no sean números se ignora («1.1.0-beta» → (1, 1, 0))."""
    nums = re.findall(r"\d+", v.split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


TRIES = 3            # GitHub y su CDN a veces responden 502/503/504 un momento: se reintenta
RETRY_WAIT = 1.5


def _transient(e: Exception) -> bool:
    """Errores pasajeros que merece la pena reintentar: 5xx, 429 y fallos de red (no 404 ni 403)."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code >= 500 or e.code == 429
    return isinstance(e, OSError)


def _retrying(fn, tries: int = TRIES):
    for attempt in range(tries):
        try:
            return fn()
        except (OSError, urllib.error.HTTPError) as e:
            if attempt == tries - 1 or not _transient(e):
                raise
            time.sleep(RETRY_WAIT * (attempt + 1))
    return None


JSON = "application/vnd.github+json"
BINARY = "application/octet-stream"     # con la URL de la API de un archivo, GitHub devuelve el archivo


def _request(url: str, accept: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": f"AERO-Player/{__version__}", "Accept": accept})


def _sources(primary: str, api_url: str) -> list[tuple[str, str]]:
    """Dónde descargar un archivo de la versión: el enlace normal y, si lo hay, la API como alternativa."""
    return [(primary, "*/*")] + ([(api_url, BINARY)] if api_url else [])


def _get(url: str, timeout: float = TIMEOUT, accept: str = JSON) -> bytes:
    req = _request(url, accept)

    def once() -> bytes:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - URL fija de GitHub o de la versión
            return r.read(32 * 1024 * 1024)

    return _retrying(once)


def latest(repo: str = UPDATE_REPO, api: str = API) -> Release | None:
    """Última versión publicada (None si no hay ninguna). Lanza UpdateError si no se puede consultar."""
    try:
        data = json.loads(_get(api.format(repo=repo)).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise UpdateError(f"GitHub respondió {e.code}") from e
    except (OSError, ValueError) as e:
        raise UpdateError(str(e) or type(e).__name__) from e
    setup = sums = None
    for a in data.get("assets", []):
        name = a.get("name", "")
        if name.lower().endswith("-setup.exe"):
            setup = a
        elif name.upper() == "SHA256SUMS.TXT":
            sums = a
    if setup is None or sums is None:
        return None
    tag = data.get("tag_name", "")
    return Release(version=tag.lstrip("vV"), tag=tag, notes=data.get("body") or "", page=data.get("html_url", ""),
                   setup_url=setup["browser_download_url"], setup_name=setup["name"], setup_size=int(setup["size"]),
                   sums_url=sums["browser_download_url"], setup_api=setup.get("url", ""),
                   sums_api=sums.get("url", ""))


def check(repo: str = UPDATE_REPO, api: str = API) -> Release | None:
    """La versión publicada si es más nueva que esta; si no, None."""
    rel = latest(repo, api)
    return rel if rel is not None and is_newer(rel.version) else None


def updates_dir() -> Path:
    from aero.core.paths import data_dir

    d = data_dir() / "actualizaciones"
    d.mkdir(parents=True, exist_ok=True)
    return d


def expected_sha256(rel: Release) -> str:
    text, error = None, None
    for url, accept in _sources(rel.sums_url, rel.sums_api):
        try:
            text = _get(url, accept=accept).decode("utf-8-sig", "replace")
            break
        except OSError as e:            # HTTPError también es OSError
            error = e
    if text is None:
        raise UpdateError(f"No se pudo descargar la suma SHA-256: {error}") from error
    for line in text.splitlines():
        parts = line.strip().lstrip("﻿").split()         # BOM también a mitad (sumas de varios sistemas)
        if len(parts) >= 2 and parts[-1].lstrip("*") == rel.setup_name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    raise UpdateError("La versión no publica la suma SHA-256 del instalador.")


def download(rel: Release, progress=lambda done, total: None, cancelled=lambda: False,
             folder: Path | None = None) -> Path:
    """Descarga el instalador y verifica su SHA-256. Devuelve la ruta del archivo comprobado."""
    want = expected_sha256(rel)
    folder = Path(folder or updates_dir())
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / rel.setup_name
    part = out.with_suffix(".part")
    if out.exists() and _sha256(out) == want:
        return out                                             # ya descargado y comprobado

    def once(req: urllib.request.Request):
        h = hashlib.sha256()
        done = 0
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(part, "wb") as fh:  # noqa: S310
            total = int(r.headers.get("Content-Length") or rel.setup_size or 0)
            while True:
                if cancelled():
                    raise UpdateError("Cancelado.")
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                progress(done, total)
        return h

    h, error = None, None
    try:
        for url, accept in _sources(rel.setup_url, rel.setup_api):
            try:
                h = _retrying(lambda u=url, a=accept: once(_request(u, a)))     # cada intento empieza de cero
                break
            except OSError as e:
                error = e
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    if h is None:
        part.unlink(missing_ok=True)
        raise UpdateError(f"No se pudo descargar: {error}") from error
    if h.hexdigest() != want:
        part.unlink(missing_ok=True)
        raise UpdateError("El archivo descargado no coincide con su suma SHA-256: no se instalará.")
    os.replace(part, out)
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_portable() -> bool:
    """¿Se ejecuta la versión portable (un AeroPlayer.exe que no es el de la instalación registrada)?"""
    if not getattr(sys, "frozen", False):
        return False
    try:
        from aero.installer.core import find_existing

        ex = find_existing()
    except Exception:  # noqa: BLE001
        return True
    here = Path(sys.executable).resolve().parent
    return ex is None or ex.kind != "aero" or Path(ex.folder).resolve() != here


def can_install() -> bool:
    """Solo el programa instalado se actualiza a sí mismo: ni una ejecución desde el código ni la portable (el
    instalador la duplicaría en otra carpeta); en esos casos se ofrece la descarga."""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt" and not is_portable()


def launch_installer(setup: Path) -> None:
    """Lanza el instalador en modo actualización; quien llama debe cerrar AERO Player a continuación."""
    if not can_install():
        raise UpdateError("Solo la versión instalada puede actualizarse a sí misma.")
    subprocess.Popen([str(setup), "--update"], close_fds=True,  # noqa: S603 - instalador recién comprobado
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


def due(settings, hours: float = 20.0) -> bool:
    """¿Toca comprobar? (como mucho una vez al día y solo si el usuario lo permite)."""
    if not settings.get("update_check"):
        return False
    return time.time() - float(settings.get("update_last_check") or 0) >= hours * 3600


def clean_old(keep: str = "") -> None:
    """Borra instaladores descargados de versiones anteriores (solo de la carpeta de actualizaciones de AERO)."""
    for f in updates_dir().glob("AeroPlayer-*-setup.*"):
        if keep and f.name.startswith(keep):
            continue
        try:
            f.unlink()
        except OSError:
            pass
