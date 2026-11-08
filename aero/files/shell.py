"""Integración con el shell de Windows para «Archivos»: iconos reales, tipos, accesos directos y programas.

Seguridad (nunca se ejecuta nada al entrar en una carpeta):
* Los programas y scripts (`RUNNABLE`) solo se lanzan tras una acción explícita y una confirmación.
* Se lee la marca «descargado de Internet» (secuencia NTFS `Zone.Identifier`, Mark of the Web) y se avisa.
* Se abren con `ShellExecute` (`os.startfile`): Windows aplica sus propias protecciones (SmartScreen, aviso de
  archivo descargado, UAC). No se desactiva ni se sortea ninguna.
* Los accesos directos se resuelven para mostrar su destino y avisar si apuntan a un programa.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Se ejecutan al abrirse (programas, instaladores, scripts y formatos que Windows trata como ejecutables).
PROGRAMS = {".exe", ".com", ".msi", ".msix", ".appx", ".scr", ".cpl", ".msc", ".appref-ms", ".application",
            ".gadget", ".pif"}
SCRIPTS = {".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta", ".reg", ".jar"}
RUNNABLE = PROGRAMS | SCRIPTS
SHORTCUTS = {".lnk", ".url"}
# Icono propio de cada archivo (no del tipo): se piden uno a uno
OWN_ICON = PROGRAMS | SHORTCUTS | {".ico", ".cur", ".dll"}

ZONES = {0: "Este equipo", 1: "Intranet local", 2: "Sitios de confianza", 3: "Internet", 4: "Sitios restringidos"}


@dataclass
class Target:
    """Destino de un acceso directo."""
    path: str = ""          # ruta resuelta (vacía si no se puede resolver o es una dirección web)
    url: str = ""           # para accesos .url
    exists: bool = False
    is_dir: bool = False
    runnable: bool = False


def ext_of(path: str) -> str:
    return Path(path).suffix.lower()


def is_runnable(path: str) -> bool:
    return ext_of(path) in RUNNABLE


def is_shortcut(path: str) -> bool:
    return ext_of(path) in SHORTCUTS


def resolve_shortcut(path: str) -> Target:
    """Destino de un .lnk (Qt lo lee con la API del shell) o de un .url (archivo INI con URL=)."""
    ext = ext_of(path)
    if ext == ".url":
        try:
            for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().lower().startswith("url="):
                    url = line.split("=", 1)[1].strip()
                    if url.lower().startswith("file:///"):
                        local = url[8:].replace("/", os.sep)
                        return Target(local, url, os.path.exists(local), os.path.isdir(local), is_runnable(local))
                    return Target("", url)
        except OSError:
            pass
        return Target()
    if ext != ".lnk":
        return Target()
    from PySide6.QtCore import QFileInfo

    target = QFileInfo(path).symLinkTarget()
    if not target:
        return Target()
    target = os.path.normpath(target)
    return Target(target, "", os.path.exists(target), os.path.isdir(target), is_runnable(target))


def zone_of(path: str) -> int:
    """Zona de seguridad con la que Windows marcó el archivo al descargarlo (-1 si no tiene marca)."""
    if os.name != "nt":
        return -1
    try:
        with open(path + ":Zone.Identifier", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip().lower().startswith("zoneid="):
                    return int(line.split("=", 1)[1].strip())
    except (OSError, ValueError):
        pass
    return -1


def from_internet(path: str) -> bool:
    return zone_of(path) >= 3


def has_association(path: str) -> bool:
    """¿Hay una aplicación de Windows asociada a esta extensión? (AssocQueryString)."""
    ext = ext_of(path)
    if not ext or os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    size = wintypes.DWORD(0)
    # ASSOCF_INIT_IGNOREUNKNOWN = 0x400, ASSOCSTR_EXECUTABLE = 2; S_FALSE (1) devuelve el tamaño necesario
    hr = ctypes.windll.shlwapi.AssocQueryStringW(0x400, 2, ext, None, None, ctypes.byref(size))
    return hr in (0, 1) and size.value > 1


def type_name(path: str, is_dir: bool = False) -> str:
    """Tipo legible en el idioma de AERO, con la extensión: «Aplicación · EXE», «Acceso directo», «Script · BAT».

    No se usa el nombre que da Windows/Qt: vendría en el idioma del sistema (o como tipo MIME en inglés) y
    mezclaría idiomas en la lista.
    """
    from aero.core.formats import KIND_LABELS, kind_of
    from aero.i18n import tr

    if is_dir:
        return tr("Carpeta")
    ext = ext_of(path)
    if ext in SHORTCUTS:
        return tr("Acceso directo") if ext == ".lnk" else tr("Acceso directo a Internet")
    if ext in PROGRAMS:
        base = tr("Aplicación")
    elif ext in SCRIPTS:
        base = tr("Script")
    else:
        kind = kind_of(path)
        base = tr(KIND_LABELS.get(kind, "Archivo")) if kind != "unknown" else tr("Archivo")
    return f"{base} · {ext[1:].upper()}" if ext else base


_PROVIDER = None


def _provider():
    global _PROVIDER
    if _PROVIDER is None:
        from PySide6.QtWidgets import QFileIconProvider

        _PROVIDER = QFileIconProvider()
        # Sin acceder a unidades de red lentas por cada icono
        _PROVIDER.setOptions(QFileIconProvider.Option.DontUseCustomDirectoryIcons)
    return _PROVIDER


def icon_key(path: str, is_dir: bool) -> str:
    """Clave de caché: un icono por extensión salvo los que tienen icono propio (programas, accesos, .ico)."""
    if is_dir:
        return "<dir>"
    ext = ext_of(path)
    return path.lower() if ext in OWN_ICON else (ext or "<none>")


def shell_icon(path: str):
    """QIcon real del shell (hilo de la interfaz). Puede ser nulo si Windows no lo da."""
    from PySide6.QtCore import QFileInfo

    return _provider().icon(QFileInfo(path))


# ----------------------------------------------------------------------------- abrir y ejecutar

def open_default(path: str) -> None:
    """Abre con la aplicación asociada de Windows (ShellExecute «open»)."""
    os.startfile(path)  # noqa: S606 - acción explícita del usuario; Windows aplica sus protecciones


def open_with(path: str) -> None:
    """Diálogo «Abrir con» de Windows."""
    subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", os.path.normpath(path)])  # noqa: S603,S607


def run(path: str, admin: bool = False) -> None:
    """Ejecuta un programa o script en su carpeta. Con `admin`, Windows pide confirmación (UAC)."""
    path = os.path.normpath(path)
    os.startfile(path, "runas" if admin else "open", cwd=os.path.dirname(path) or None)  # noqa: S606


def warning_for(path: str, target: Target | None = None) -> str:
    """Advertencia que se muestra antes de ejecutar (vacía si no hay nada especial que avisar)."""
    from aero.i18n import tr

    notes = []
    real = target.path if target and target.path else path
    if from_internet(path) or (real != path and from_internet(real)):
        notes.append(tr("Windows indica que este archivo se descargó de Internet. Ejecútalo solo si confías en "
                        "su origen."))
    if ext_of(real) in SCRIPTS:
        notes.append(tr("Es un script: puede cambiar archivos o ajustes del equipo."))
    if target is not None and target.path and not target.exists:
        notes.append(tr("El destino del acceso directo no existe."))
    return "\n".join(notes)
