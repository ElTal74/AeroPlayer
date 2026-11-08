"""Menú contextual «AERO Player» del Explorador (clic derecho), con submenú.

Mecanismo clásico de Windows: verbos en HKCU\\Software\\Classes (sin administrador, reversible). Cada opción
lleva un filtro `AppliesTo` para aparecer solo donde tiene sentido (extraer solo en comprimidos, convertir
solo en formatos convertibles…). En Windows 11 los menús clásicos se muestran en «Mostrar más opciones»
(o Mayús+F10); el menú compacto de Windows 11 solo admite extensiones empaquetadas y firmadas.

Las órdenes lanzan `AeroPlayer.exe --action <acción> "<ruta>"`; con varios archivos seleccionados Windows
lanza una orden por archivo y la instancia en marcha las agrupa (comprimir y convertir).
"""

from __future__ import annotations

from aero.core.associations import CLASSES, Registry, launch_command, notify_shell
from aero.core.formats import ARCHIVE, AUDIO, DOCUMENT, IMAGE, PDF, SHEET, SLIDES, TEXT, VIDEO

ROOT_FILES = rf"{CLASSES}\*\shell\AeroPlayer"
ROOT_DIRS = rf"{CLASSES}\Directory\shell\AeroPlayer"
SEPARATOR_BEFORE = 0x20

OPENABLE = AUDIO | VIDEO | IMAGE | PDF | DOCUMENT | SHEET | SLIDES | TEXT | ARCHIVE | {".aerovid", ".aeroimg"}
CONVERTIBLE = AUDIO | VIDEO | IMAGE | PDF | (DOCUMENT - {".epub"}) | SHEET | SLIDES
EDITABLE = IMAGE | VIDEO | {".docx", ".odt", ".rtf", ".md", ".txt", ".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".pptx",
                            ".ppsx", ".pdf"}
ARCHIVES = ARCHIVE | {".tar.gz"} | {".img", ".bin", ".cue", ".nrg", ".mdf"}   # también imágenes de disco


def applies_to(exts) -> str:
    return " OR ".join(f"System.FileExtension:={e}" for e in sorted(exts))


# (clave, texto, acción, extensiones o None = todas, separador antes)
FILE_ITEMS = [
    ("01open", "Abrir con AERO Player", "open", OPENABLE, False),
    ("02quicklook", "Vista rápida", "quicklook", OPENABLE - ARCHIVE, False),
    ("03edit", "Editar", "edit", EDITABLE, False),
    ("10extract_here", "Extraer aquí", "extract_here", ARCHIVES, True),
    ("11extract_folder", "Extraer en una carpeta con su nombre", "extract_folder", ARCHIVES, False),
    ("12extract_to", "Extraer en…", "extract_to", ARCHIVES, False),
    ("13open_archive", "Abrir el archivo comprimido", "open_archive", ARCHIVES, False),
    ("20compress_zip", "Comprimir en ZIP", "compress_zip", None, True),
    ("21compress_7z", "Comprimir en 7Z", "compress_7z", None, False),
    ("22compress", "Comprimir…", "compress", None, False),
    ("30convert", "Convertir…", "convert", CONVERTIBLE, True),
]
DIR_ITEMS = [
    ("01open", "Abrir en AERO Player", "browse", None, False),
    ("20compress_zip", "Comprimir en ZIP", "compress_zip", None, True),
    ("21compress_7z", "Comprimir en 7Z", "compress_7z", None, False),
    ("22compress", "Comprimir…", "compress", None, False),
]
ACTIONS = {a for _k, _t, a, _e, _s in FILE_ITEMS + DIR_ITEMS}


def _command(action: str) -> str:
    cmd, _icon = launch_command()
    # launch_command devuelve «"exe" "%1"» o «"python" -m aero "%1"»: se inserta la acción antes de la ruta
    return cmd.replace('"%1"', f'--action {action} "%1"')


def register(reg: Registry | None = None) -> None:
    reg = reg or Registry()
    _cmd, icon = launch_command()
    for root, items in ((ROOT_FILES, FILE_ITEMS), (ROOT_DIRS, DIR_ITEMS)):
        reg.delete_tree(root)  # rehacer desde cero (versiones anteriores, rutas cambiadas)
        reg.set(root, "MUIVerb", "AERO Player")
        reg.set(root, "Icon", icon.replace('"', ""))  # «C:\ruta\AeroPlayer.exe,0» o «C:\ruta\aero.ico»
        reg.set(root, "SubCommands", "")
        for key, text, action, exts, sep in items:
            k = rf"{root}\shell\{key}"
            reg.set(k, "MUIVerb", text)
            if exts is not None:
                reg.set(k, "AppliesTo", applies_to(exts))
            if sep:
                _set_dword(reg, k, "CommandFlags", SEPARATOR_BEFORE)
            reg.set(rf"{k}\command", None, _command(action))
    notify_shell()


def _set_dword(reg: Registry, sub: str, name: str, value: int) -> None:
    w = reg.w
    with w.CreateKeyEx(w.HKEY_CURRENT_USER, reg._k(sub), 0, w.KEY_SET_VALUE) as k:
        w.SetValueEx(k, name, 0, w.REG_DWORD, int(value))


def unregister(reg: Registry | None = None) -> None:
    reg = reg or Registry()
    reg.delete_tree(ROOT_FILES)
    reg.delete_tree(ROOT_DIRS)
    notify_shell()


def is_registered(reg: Registry | None = None) -> bool:
    reg = reg or Registry()
    return reg.get(rf"{ROOT_FILES}\shell\10extract_here\command") == _command("extract_here")


def is_present(reg: Registry | None = None) -> bool:
    return (reg or Registry()).get(ROOT_FILES, "MUIVerb") is not None


def sync(enabled: bool, reg: Registry | None = None, refresh_only: bool = False) -> None:
    """Deja el registro como indica la preferencia. Con `refresh_only` (al arrancar) no lo crea si no existe
    (respeta la casilla del instalador), pero sí lo actualiza si cambió la ruta del programa."""
    reg = reg or Registry()
    if not enabled:
        if is_present(reg):
            unregister(reg)
    elif not is_registered(reg) and (is_present(reg) or not refresh_only):
        register(reg)
