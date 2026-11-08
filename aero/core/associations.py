"""Registro de AERO Player como aplicación capaz de abrir archivos (mecanismo oficial de Windows).

Qué se escribe (solo en HKEY_CURRENT_USER, sin permisos de administrador):
* ProgIDs `AeroPlayer.Audio`, `.Video`, `.Image`, `.Pdf`, `.Document`, `.Sheet`, `.Slides`, `.Archive` y
  `.Project`, con icono y comando. Solo se registran formatos que la aplicación abre de verdad
  (`aero.core.compat` genera la matriz de compatibilidad).
* `HKCU\\Software\\Classes\\<ext>\\OpenWithProgids` → AERO Player aparece en «Abrir con».
* `HKCU\\Software\\AeroPlayer\\Capabilities` + `HKCU\\Software\\RegisteredApplications` → AERO Player aparece en
  Configuración › Aplicaciones › Aplicaciones predeterminadas.

Qué NO se hace: no se escribe la clave protegida `UserChoice`. Windows exige que el usuario confirme el
predeterminado en su Configuración; AERO Player abre esa pantalla y solo informa del estado real.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "AERO Player"
REG_VERSION = 2          # 2: iconos .ico por categoría y ProgIDs propios para discos y torrents (2.2)
CAPS_KEY = r"Software\AeroPlayer\Capabilities"
REG_APPS = r"Software\RegisteredApplications"
CLASSES = r"Software\Classes"


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    progid: str
    exts: tuple[str, ...]
    icon: str = ""          # categoría de icono AERO (aero/core/filetypes); vacío = icono del programa


CATEGORIES = (
    Category("audio", "Música", "AeroPlayer.Audio",
             (".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".ape", ".wv", ".mka"), "audio"),
    Category("video", "Vídeo", "AeroPlayer.Video",
             (".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".m4v", ".mpg", ".mpeg", ".ts", ".m2ts", ".flv",
              ".3gp", ".ogv"), "video"),
    Category("image", "Imágenes", "AeroPlayer.Image",
             (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".avif", ".ico", ".svg"),
             "image"),
    Category("pdf", "PDF", "AeroPlayer.Pdf", (".pdf",), "pdf"),
    Category("document", "Documentos", "AeroPlayer.Document", (".docx", ".odt", ".rtf", ".md", ".txt"), "document"),
    Category("sheet", "Hojas de cálculo", "AeroPlayer.Sheet", (".xlsx", ".xlsm", ".xls", ".ods", ".csv"), "sheet"),
    Category("slides", "Presentaciones", "AeroPlayer.Slides", (".pptx", ".ppsx"), "slides"),
    Category("archive", "Archivos comprimidos", "AeroPlayer.Archive",
             (".zip", ".rar", ".7z", ".tar", ".tgz", ".gz", ".cab", ".cbz", ".cbr"), "archive"),
    Category("disc", "Imágenes de disco", "AeroPlayer.Disc", (".iso", ".img", ".bin", ".cue", ".nrg", ".mdf"), "disc"),
    Category("torrent", "Torrents", "AeroPlayer.Torrent", (".torrent",), "torrent"),
    Category("project", "Proyectos de AERO Player", "AeroPlayer.Project", (".aerovid", ".aeroimg")),
)
# Hasta la 1.2, PDF y ofimática compartían «AeroPlayer.Document»: al registrar se limpia esa entrada antigua.
LEGACY_DOCUMENT = (".pdf", ".xlsx", ".xls", ".ods", ".csv", ".pptx", ".odp")


def launch_command() -> tuple[str, str]:
    """(comando de apertura, icono) para el ejecutable instalado o para la ejecución desde el código."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return f'"{exe}" "%1"', f'"{exe}",0'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pyw if pyw.exists() else sys.executable)
    root = Path(__file__).resolve().parents[2]
    icon = root / "packaging" / "aero.ico"
    return f'"{exe}" -m aero "%1"', (f'"{icon}"' if icon.exists() else f'"{exe}",0')


OWN_EXT = ".aeroarchive"
OWN_PROGID = "AeroPlayer.AeroArchive"


def category_icon(cat: str) -> str | None:
    """Valor de DefaultIcon con el .ico AERO de la categoría (None si no existe)."""
    if not cat:
        return None
    try:
        from aero.ui.icon_export import ensure

        ico = ensure() / f"{cat}.ico"
    except (OSError, ImportError):
        return None
    return f'"{ico}",0' if ico.exists() else None


def archive_icon() -> str:
    """Icono de los archivos .aeroarchive (junto al ejecutable o en packaging/ al ejecutar desde el código)."""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2] / "packaging"
    ico = base / "aeroarchive.ico"
    return f'"{ico}",0' if ico.exists() else launch_command()[1]


class Registry:
    """Pequeña capa sobre winreg con raíz configurable (las pruebas usan una rama aislada)."""

    def __init__(self, base: str = ""):
        import winreg

        self.w = winreg
        self.base = base.strip("\\")

    def _k(self, sub: str) -> str:
        return f"{self.base}\\{sub}" if self.base else sub

    def set(self, sub: str, name: str | None, value: str) -> None:
        with self.w.CreateKeyEx(self.w.HKEY_CURRENT_USER, self._k(sub), 0, self.w.KEY_SET_VALUE) as k:
            self.w.SetValueEx(k, name, 0, self.w.REG_SZ, value)

    def get(self, sub: str, name: str | None = None) -> str | None:
        try:
            with self.w.OpenKey(self.w.HKEY_CURRENT_USER, self._k(sub)) as k:
                return str(self.w.QueryValueEx(k, name)[0])
        except OSError:
            return None

    def delete_value(self, sub: str, name: str) -> None:
        try:
            with self.w.OpenKey(self.w.HKEY_CURRENT_USER, self._k(sub), 0, self.w.KEY_SET_VALUE) as k:
                self.w.DeleteValue(k, name)
        except OSError:
            pass

    def delete_tree(self, sub: str) -> None:
        try:
            with self.w.OpenKey(self.w.HKEY_CURRENT_USER, self._k(sub), 0,
                                self.w.KEY_READ | self.w.KEY_WRITE) as k:
                while True:
                    try:
                        child = self.w.EnumKey(k, 0)
                    except OSError:
                        break
                    self.delete_tree(f"{sub}\\{child}")
            self.w.DeleteKey(self.w.HKEY_CURRENT_USER, self._k(sub))
        except OSError:
            pass


def register(reg: Registry | None = None) -> None:
    reg = reg or Registry()
    cmd, icon = launch_command()
    for ext in LEGACY_DOCUMENT:
        reg.delete_value(f"{CLASSES}\\{ext}\\OpenWithProgids", "AeroPlayer.Document")
    reg.delete_value(f"{CLASSES}\\.iso\\OpenWithProgids", "AeroPlayer.Archive")   # hasta 2.1 la ISO era «comprimido»
    reg.set(CAPS_KEY, "ApplicationName", APP_NAME)
    reg.set(CAPS_KEY, "ApplicationDescription", "Reproductor multimedia, visor universal y conversor")
    reg.set(CAPS_KEY, "ApplicationIcon", icon)
    for cat in CATEGORIES:
        pk = f"{CLASSES}\\{cat.progid}"
        reg.set(pk, None, f"{APP_NAME} · {cat.label}")
        reg.set(pk, "FriendlyTypeName", f"{cat.label} ({APP_NAME})")
        reg.set(f"{pk}\\DefaultIcon", None, category_icon(cat.icon) or icon)   # icono AERO de la categoría
        reg.set(f"{pk}\\shell\\open", "FriendlyAppName", APP_NAME)
        reg.set(f"{pk}\\shell\\open\\command", None, cmd)
        for ext in cat.exts:
            reg.set(f"{CLASSES}\\{ext}\\OpenWithProgids", cat.progid, "")
            reg.set(f"{CAPS_KEY}\\FileAssociations", ext, cat.progid)
    # Formato propio: la extensión es solo de AERO Player, así que sí se le asigna su programa y su icono.
    # Las extensiones de otros (.zip, .rar, .7z…) nunca se tocan aquí: solo aparecen en «Abrir con».
    pk = f"{CLASSES}\\{OWN_PROGID}"
    reg.set(pk, None, "Archivo comprimido de AERO Player")
    reg.set(pk, "FriendlyTypeName", "Archivo comprimido de AERO Player")
    reg.set(f"{pk}\\DefaultIcon", None, archive_icon())
    reg.set(f"{pk}\\shell\\open", "FriendlyAppName", APP_NAME)
    reg.set(f"{pk}\\shell\\open\\command", None, cmd.replace('"%1"', '--action open_archive "%1"'))
    reg.set(f"{CLASSES}\\{OWN_EXT}", None, OWN_PROGID)
    reg.set(f"{CLASSES}\\{OWN_EXT}", "Content Type", "application/x-aeroarchive")
    reg.set(f"{CLASSES}\\{OWN_EXT}\\OpenWithProgids", OWN_PROGID, "")
    reg.set(f"{CAPS_KEY}\\FileAssociations", OWN_EXT, OWN_PROGID)
    reg.set(REG_APPS, APP_NAME, CAPS_KEY)
    if getattr(sys, "frozen", False):
        app = f"{CLASSES}\\Applications\\{Path(sys.executable).name}"
        reg.set(app, "FriendlyAppName", APP_NAME)
        reg.set(f"{app}\\shell\\open\\command", None, cmd)
        for cat in CATEGORIES:
            for ext in cat.exts:
                reg.set(f"{app}\\SupportedTypes", ext, "")
    notify_shell()


def unregister(reg: Registry | None = None) -> None:
    """Elimina únicamente lo que AERO Player registró."""
    reg = reg or Registry()
    for ext in LEGACY_DOCUMENT:
        reg.delete_value(f"{CLASSES}\\{ext}\\OpenWithProgids", "AeroPlayer.Document")
    for cat in CATEGORIES:
        reg.delete_tree(f"{CLASSES}\\{cat.progid}")
        for ext in cat.exts:
            reg.delete_value(f"{CLASSES}\\{ext}\\OpenWithProgids", cat.progid)
    reg.delete_tree(f"{CLASSES}\\{OWN_PROGID}")
    if reg.get(f"{CLASSES}\\{OWN_EXT}") == OWN_PROGID:  # solo si sigue siendo nuestra
        reg.delete_tree(f"{CLASSES}\\{OWN_EXT}")
    reg.delete_value(REG_APPS, APP_NAME)
    reg.delete_tree(r"Software\AeroPlayer")
    if getattr(sys, "frozen", False):
        reg.delete_tree(f"{CLASSES}\\Applications\\{Path(sys.executable).name}")
    notify_shell()


def is_registered(reg: Registry | None = None) -> bool:
    reg = reg or Registry()
    return reg.get(REG_APPS, APP_NAME) == CAPS_KEY and reg.get(f"{CLASSES}\\AeroPlayer.Video\\shell\\open\\command") \
        is not None


def chosen_but_missing() -> list[str]:
    """Extensiones donde el usuario eligió AERO Player en Windows pero el ProgID ya no existe (por ejemplo tras
    desinstalar y reinstalar sin registrar): Windows no puede abrirlas ni dibujar su icono."""
    import winreg

    out = []
    for cat in CATEGORIES:
        for ext in cat.exts:
            prog = current_progid(ext) or ""
            if prog.startswith("AeroPlayer."):
                try:
                    winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog + r"\shell\open\command").Close()
                except OSError:
                    out.append(ext)
    return out


def current_progid(ext: str) -> str | None:
    """ProgID que Windows usa de verdad para la extensión (elección del usuario)."""
    reg = Registry()
    base = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}"
    for key in ("UserChoiceLatest\\ProgId", "UserChoice"):
        v = reg.get(f"{base}\\{key}", "ProgId")
        if v:
            return v
    return reg.get(f"{CLASSES}\\{ext}")


def status() -> dict[str, tuple[int, int]]:
    """Por categoría: (extensiones donde AERO Player es el predeterminado, total)."""
    out = {}
    for cat in CATEGORIES:
        mine = sum(1 for ext in cat.exts if (current_progid(ext) or "").startswith("AeroPlayer."))
        out[cat.key] = (mine, len(cat.exts))
    return out


def notify_shell() -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
        except (OSError, AttributeError):
            pass


def open_default_apps_settings() -> None:
    """Abre Configuración › Aplicaciones predeterminadas directamente en la ficha de AERO Player."""
    if os.name != "nt":
        return
    for uri in ("ms-settings:defaultapps?registeredAppUser=AERO%20Player", "ms-settings:defaultapps"):
        try:
            os.startfile(uri)  # noqa: S606 - URI fija del sistema
            return
        except OSError:
            continue
