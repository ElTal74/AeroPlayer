"""Iconos AERO en el Explorador de Windows para los tipos que abre **otro** programa (opcional y reversible).

Cómo decide Windows el icono de un archivo: busca el programa elegido para su extensión (la elección del usuario
o el ProgID predeterminado) y usa el `DefaultIcon` de ese programa. Por eso:

* Si AERO Player es el predeterminado, el icono es el .ico AERO de la categoría (`associations.register`).
* Si es otro programa, el icono es el de ese programa. Para mostrar el icono AERO **sin cambiar qué programa abre
  el archivo**, aquí se escribe una capa por usuario `HKCU\\Software\\Classes\\<ProgID>\\DefaultIcon`, que Windows
  antepone a la del programa. Nunca se toca `UserChoice`, ni el comando de apertura, ni nada en HKLM.

Reglas:
* Solo se aplica si el usuario lo activa (Ajustes › Archivos y asociaciones) y lo confirma.
* Antes de escribir se guarda el valor anterior en `HKCU\\Software\\AeroPlayer\\IconBackup`; «Restaurar iconos»
  lo devuelve exactamente y solo deshace lo que siga teniendo el valor que puso AERO Player.
* No se cambian programas, scripts, accesos directos, carpetas ni archivos de sistema: su icono identifica qué
  se va a ejecutar (cambiarlo sería engañoso e inseguro).
* Se omiten los ProgIDs compartidos por tipos de categorías distintas (un icono común sería falso para algunos)
  y los genéricos `Applications\\programa.exe`.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from aero.core import filetypes
from aero.core.associations import CLASSES, Registry, current_progid, notify_shell

BACKUP = r"Software\AeroPlayer\IconBackup"
CATEGORIES = ("video", "audio", "image", "document", "sheet", "slides", "pdf", "archive", "disc", "torrent", "font",
              "code", "installer")
# Scripts que se ejecutan con doble clic: conservan su icono (avisa de que es ejecutable)
RUNNABLE = {".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".js", ".jse", ".wsf", ".hta", ".sh", ".com", ".pif", ".scr",
            ".reg", ".msc", ".cpl", ".jar", ".appref-ms"}
NONE = "aero:ninguno"         # en la copia: no había valor propio en HKCU (el registro corta en el nulo)


def extensions() -> dict[str, str]:
    """Extensión → categoría AERO de las que pueden llevar icono AERO."""
    out = {}
    for ext, cat in filetypes._BY_EXT.items():
        if cat in CATEGORIES and ext not in RUNNABLE:
            out[ext] = cat
    return out


def _icon(cat: str) -> str | None:
    from aero.core.associations import category_icon

    return category_icon(cat)


def plan(reg: Registry | None = None) -> dict[str, tuple[str, list[str]]]:
    """ProgID ajeno → (categoría, extensiones) al que se le pondría el icono. Sin escribir nada."""
    reg = reg or Registry()
    by_prog: dict[str, set[str]] = {}
    exts: dict[str, list[str]] = {}
    for ext, cat in extensions().items():
        prog = current_progid(ext) if reg.base == "" else reg.get(f"{CLASSES}\\{ext}")
        if not prog or prog.startswith(("AeroPlayer.", "Applications\\")) or "\\" in prog:
            continue
        by_prog.setdefault(prog, set()).add(cat)
        exts.setdefault(prog, []).append(ext)
    return {p: (next(iter(c)), sorted(exts[p])) for p, c in by_prog.items() if len(c) == 1}


def apply(reg: Registry | None = None) -> int:
    """Pone el icono AERO en los ProgIDs ajenos (con copia del valor anterior). Devuelve cuántos cambió."""
    reg = reg or Registry()
    changed = 0
    for prog, (cat, _exts) in plan(reg).items():
        ico = _icon(cat)
        if not ico:
            continue
        key = f"{CLASSES}\\{prog}\\DefaultIcon"
        cur = reg.get(key)
        if cur == ico:
            continue
        if reg.get(BACKUP, prog) is None:          # la primera vez: se guarda lo que había en HKCU
            reg.set(BACKUP, prog, cur if cur is not None else NONE)
        reg.set(key, None, ico)
        changed += 1
    if changed:
        refresh()
    return changed


def restore(reg: Registry | None = None) -> int:
    """Deshace lo que hizo `apply`. Si el usuario u otro programa cambió el valor después, se respeta."""
    import winreg

    reg = reg or Registry()
    restored = 0
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg._k(BACKUP)) as k:
            items = []
            i = 0
            while True:
                try:
                    items.append(winreg.EnumValue(k, i)[:2])
                except OSError:
                    break
                i += 1
    except OSError:
        items = []
    ours = {_icon(c) for c in CATEGORIES} - {None}
    for prog, old in items:
        key = f"{CLASSES}\\{prog}\\DefaultIcon"
        if reg.get(key) in ours:
            if old == NONE:
                reg.delete_value(key, None)
                _drop_if_empty(reg, key)
            else:
                reg.set(key, None, old)
            restored += 1
        reg.delete_value(BACKUP, prog)
    reg.delete_tree(BACKUP)
    if restored:
        refresh()
    return restored


def _drop_if_empty(reg: Registry, key: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg._k(key)) as k:
            n_sub, n_val, _ = winreg.QueryInfoKey(k)
        if n_sub == 0 and n_val == 0:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg._k(key))
    except OSError:
        pass


def applied(reg: Registry | None = None) -> int:
    """Cuántos ProgIDs ajenos llevan ahora el icono AERO."""
    reg = reg or Registry()
    ours = {_icon(c) for c in CATEGORIES} - {None}
    return sum(1 for prog in plan(reg) if reg.get(f"{CLASSES}\\{prog}\\DefaultIcon") in ours)


def refresh() -> None:
    """Avisa al Explorador de que cambiaron los iconos (sin reiniciar nada)."""
    notify_shell()
    if os.name == "nt":
        import subprocess

        exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "ie4uinit.exe")
        if os.path.exists(exe):
            try:   # refresca la caché de iconos del usuario; sin ventana y sin permisos de administrador
                subprocess.run([exe, "-show"], timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.SubprocessError):
                pass


# ----------------------------------------------------------------------------- lo que ve el Explorador

class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HANDLE), ("iIcon", ctypes.c_int), ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", wintypes.WCHAR * 260), ("szTypeName", wintypes.WCHAR * 80)]


def shell_icon_location(path: str) -> tuple[str, int]:
    """(archivo de icono, índice) que el Shell de Windows usa para `path` (SHGetFileInfo, SHGFI_ICONLOCATION)."""
    info = _SHFILEINFOW()
    ok = ctypes.windll.shell32.SHGetFileInfoW(str(path), 0, ctypes.byref(info), ctypes.sizeof(info), 0x1000)
    return (info.szDisplayName, info.iIcon) if ok else ("", 0)


def shell_icon_image(path: str, size: int = 48):
    """QImage del icono tal como lo dibuja el Explorador (IShellItemImageFactory, solo icono)."""
    from PySide6.QtGui import QImage

    try:
        from win32com.shell import shell, shellcon  # noqa: F401
    except ImportError:
        return QImage()

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    iid = (ctypes.c_byte * 16)()
    ole32.IIDFromString("{bcc18b79-ba16-442f-80c4-8a59c30c463b}", iid)    # IID_IShellItemImageFactory
    factory = ctypes.c_void_p()
    hr = ctypes.windll.shell32.SHCreateItemFromParsingName(os.path.normpath(str(path)), None, iid,
                                                           ctypes.byref(factory))
    if hr != 0 or not factory:
        return QImage()
    vtbl = ctypes.cast(ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    get_image = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, SIZE, ctypes.c_int,
                                   ctypes.POINTER(wintypes.HBITMAP))(vtbl[3])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
    hbmp = wintypes.HBITMAP()
    hr = get_image(factory, SIZE(size, size), 0x4, ctypes.byref(hbmp))          # SIIGBF_ICONONLY
    release(factory)
    if hr != 0 or not hbmp:
        return QImage()
    img = _from_hbitmap(hbmp, size)
    ctypes.windll.gdi32.DeleteObject(hbmp)
    return img


def _from_hbitmap(hbmp, size: int):
    """HBITMAP de 32 bits con alfa premultiplicado → QImage (de arriba abajo, con su transparencia)."""
    from PySide6.QtGui import QImage

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
                    ("bmWidthBytes", ctypes.c_long), ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                    ("bmBits", ctypes.c_void_p)]

    gdi = ctypes.windll.gdi32
    bm = BITMAP()
    gdi.GetObjectW(hbmp, ctypes.sizeof(bm), ctypes.byref(bm))
    w, h = bm.bmWidth or size, abs(bm.bmHeight) or size
    hdr = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)   # -h: de arriba abajo
    buf = (ctypes.c_ubyte * (w * h * 4))()
    dc = ctypes.windll.user32.GetDC(None)
    lines = gdi.GetDIBits(dc, hbmp, 0, h, buf, ctypes.byref(hdr), 0)
    ctypes.windll.user32.ReleaseDC(None, dc)
    if lines != h:
        return QImage()
    raw = bytes(buf)
    # El Shell entrega a veces alfa premultiplicado y a veces no: si algún color supera a su alfa, no lo está.
    straight = any(max(raw[i], raw[i + 1], raw[i + 2]) > raw[i + 3] for i in range(0, len(raw), 4))
    fmt = QImage.Format.Format_ARGB32 if straight else QImage.Format.Format_ARGB32_Premultiplied
    return QImage(raw, w, h, w * 4, fmt).copy()
