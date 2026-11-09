"""«Usar AERO Player para todo»: hacerlo la aplicación predeterminada de todos los tipos que abre.

* Windows: no se puede (ni se debe) imponer. Windows protege la elección del usuario (`UserChoice`, con una firma)
  y exige que la confirme él. Se registra AERO Player y se abre su página en Configuración › Aplicaciones
  predeterminadas, donde un solo botón («Establecer predeterminada») lo aplica a todos sus tipos.
* Linux: `xdg-mime default aero-player.desktop <tipos>` (estándar freedesktop), para el usuario.
* macOS: LaunchServices (`LSSetDefaultRoleHandlerForContentType`) para cada tipo, con el identificador del
  paquete AeroPlayer.app. Solo funciona desde la aplicación empaquetada.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from aero.core.associations import CATEGORIES

SETTINGS = "settings"     # Windows abrió su página: falta el clic del usuario
DONE = "done"             # aplicado
MANUAL = "manual"         # no se pudo: hay que hacerlo desde el sistema

DESKTOP_ID = "aero-player.desktop"
MAC_BUNDLE_ID = "io.github.eltal74.aeroplayer"

# Los mismos tipos que packaging/linux/aero-player.desktop (una prueba comprueba que coinciden)
LINUX_MIME_TYPES = (
    "audio/mpeg", "audio/flac", "audio/x-flac", "audio/x-wav", "audio/wav", "audio/ogg", "audio/opus", "audio/mp4",
    "audio/aac", "audio/x-m4a", "audio/x-ms-wma", "audio/x-aiff", "audio/x-matroska", "video/mp4",
    "video/x-matroska", "video/webm", "video/quicktime", "video/x-msvideo", "video/x-ms-wmv", "video/mpeg",
    "video/mp2t", "video/x-flv", "video/3gpp", "video/ogg", "image/jpeg", "image/png", "image/gif", "image/webp",
    "image/bmp", "image/tiff", "image/heic", "image/avif", "image/svg+xml", "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.oasis.opendocument.text", "application/rtf", "text/markdown", "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel",
    "application/vnd.oasis.opendocument.spreadsheet", "text/csv",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/zip",
    "application/vnd.rar", "application/x-rar", "application/x-7z-compressed", "application/x-tar",
    "application/gzip", "application/x-compressed-tar", "application/x-iso9660-image", "application/x-cd-image",
    "application/x-bittorrent",
)


def extensions() -> list[str]:
    """Todas las extensiones que AERO Player sabe abrir (sin el punto)."""
    return sorted({e.lstrip(".") for c in CATEGORIES for e in c.exts})


def make_default_everywhere() -> str:
    """Hace (o prepara) AERO Player predeterminado para todos sus tipos. Devuelve SETTINGS, DONE o MANUAL."""
    if sys.platform == "win32":
        return _windows()
    if sys.platform == "darwin":
        return _mac()
    return _linux()


# ---------------------------------------------------------------------------------------------- Windows
def _windows() -> str:
    from aero.core import associations

    try:
        associations.register()
    except OSError:
        return MANUAL
    associations.open_default_apps_settings()
    return SETTINGS


# ---------------------------------------------------------------------------------------------- Linux
def _launch_argv() -> list[str]:
    return [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "aero"]


def linux_desktop_file() -> Path:
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data / "applications" / DESKTOP_ID


def _ensure_desktop_file() -> Path:
    """La entrada del menú; si install.sh no la creó, se crea aquí con la orden de esta copia."""
    f = linux_desktop_file()
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        lines = ["[Desktop Entry]", "Type=Application", "Name=AERO Player",
                 f"Exec={shlex.join(_launch_argv())} %F", "Icon=aero-player", "Terminal=false",
                 "Categories=AudioVideo;Audio;Video;Player;Graphics;Viewer;Office;Utility;",
                 "MimeType=" + ";".join(LINUX_MIME_TYPES) + ";"]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


def _linux() -> str:
    exe = shutil.which("xdg-mime")
    if not exe:
        return MANUAL
    try:
        f = _ensure_desktop_file()
        upd = shutil.which("update-desktop-database")
        if upd:
            subprocess.run([upd, str(f.parent)], capture_output=True, timeout=30)
        r = subprocess.run([exe, "default", DESKTOP_ID, *LINUX_MIME_TYPES], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return MANUAL
    return DONE if r.returncode == 0 else MANUAL


# ---------------------------------------------------------------------------------------------- macOS
def _mac() -> str:
    if not getattr(sys, "frozen", False):
        return MANUAL                       # sin AeroPlayer.app no hay identificador de paquete que registrar
    try:
        done = _mac_set_all(extensions())
    except (OSError, AttributeError, ValueError):
        return MANUAL
    return DONE if done else MANUAL


def _mac_set_all(exts: list[str]) -> int:
    import ctypes
    from ctypes import c_char_p, c_int32, c_uint32, c_void_p

    cs = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreServices.framework/CoreServices")
    cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    cf.CFStringCreateWithCString.restype = c_void_p
    cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint32]
    cf.CFRelease.argtypes = [c_void_p]
    cs.UTTypeCreatePreferredIdentifierForTag.restype = c_void_p
    cs.UTTypeCreatePreferredIdentifierForTag.argtypes = [c_void_p, c_void_p, c_void_p]
    cs.LSSetDefaultRoleHandlerForContentType.restype = c_int32
    cs.LSSetDefaultRoleHandlerForContentType.argtypes = [c_void_p, c_uint32, c_void_p]
    utf8 = 0x08000100
    tag_class = c_void_p.in_dll(cs, "kUTTagClassFilenameExtension")
    bundle = cf.CFStringCreateWithCString(None, MAC_BUNDLE_ID.encode(), utf8)
    ok = 0
    try:
        for ext in exts:
            cf_ext = cf.CFStringCreateWithCString(None, ext.encode(), utf8)
            uti = cs.UTTypeCreatePreferredIdentifierForTag(tag_class, cf_ext, None)
            cf.CFRelease(cf_ext)
            if not uti:
                continue
            if cs.LSSetDefaultRoleHandlerForContentType(uti, 0xFFFFFFFF, bundle) == 0:   # kLSRolesAll
                ok += 1
            cf.CFRelease(uti)
    finally:
        cf.CFRelease(bundle)
    return ok
