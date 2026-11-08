"""Lógica del instalador propio de AERO Player (sin Qt: se puede probar y ejecutar en un hilo).

* Instalación por usuario en %LOCALAPPDATA%\\Programs\\AeroPlayer: sin administrador, todo en HKCU.
* El contenido llega como `payload.tar.xz` + `manifest.json` (lista de archivos y tamaños).
* En la carpeta instalada se guarda `uninstall.json` con lo que se instaló: al desinstalar o actualizar solo se
  borra eso, nunca otros archivos (aunque el usuario elija una carpeta propia con más cosas).
* Los datos del usuario (%APPDATA%\\AeroPlayer) nunca se tocan.
* Si había una instalación anterior hecha con Inno Setup (1.4 y anteriores) se desinstala en silencio antes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

APP_NAME = "AERO Player"
EXE = "AeroPlayer.exe"
APP_USER_MODEL_ID = "AeroPlayer.AeroPlayer.1"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AeroPlayer"
INNO_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{6B7C1E2A-4F3D-4E8B-9C21-AE20F1A70001}_is1"
MANIFEST = "uninstall.json"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def default_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / "AeroPlayer"


def safe_target(folder: str | Path) -> Path:
    """Carpeta final de instalación. Si el usuario elige una carpeta que ya tiene otras cosas y no es una
    instalación de AERO Player, se instala en una subcarpeta propia para no mezclar archivos."""
    p = Path(folder)
    if p.name.lower() in ("aeroplayer", "aero player"):
        return p
    if p.exists() and any(p.iterdir()) and not (p / EXE).exists():
        return p / "AeroPlayer"
    return p


@dataclass
class Options:
    target: Path = field(default_factory=default_dir)
    start_menu: bool = True
    desktop: bool = False
    context_menu: bool = True
    associations: bool = True
    theme: str = ""            # tema inicial elegido en el instalador ("" = no cambiar)
    language: str = ""         # idioma elegido en el instalador


@dataclass
class Existing:
    """Instalación previa encontrada."""
    kind: str                  # "aero" (este instalador) o "inno" (versiones anteriores)
    folder: Path
    version: str = ""
    uninstall: str = ""


# ---------------------------------------------------------------------------------------------- registro
def _reg():
    import winreg

    return winreg


def reg_read(key: str, name: str):
    w = _reg()
    try:
        with w.OpenKey(w.HKEY_CURRENT_USER, key) as k:
            return w.QueryValueEx(k, name)[0]
    except OSError:
        return None


def find_existing() -> Existing | None:
    loc = reg_read(UNINSTALL_KEY, "InstallLocation")
    if loc and (Path(loc) / EXE).exists():
        return Existing("aero", Path(loc), reg_read(UNINSTALL_KEY, "DisplayVersion") or "")
    loc = reg_read(INNO_KEY, "InstallLocation")
    unins = reg_read(INNO_KEY, "UninstallString")
    if loc and unins:
        return Existing("inno", Path(str(loc).rstrip("\\")), reg_read(INNO_KEY, "DisplayVersion") or "",
                        str(unins).strip('"'))
    return None


def write_uninstall_entry(folder: Path, version: str, size_bytes: int) -> None:
    w = _reg()
    exe = folder / EXE
    with w.CreateKeyEx(w.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, w.KEY_SET_VALUE) as k:
        for name, value in (("DisplayName", APP_NAME), ("DisplayVersion", version),
                            ("Publisher", "Proyecto AERO Player"), ("DisplayIcon", f"{exe},0"),
                            ("InstallLocation", str(folder)), ("UninstallString", f'"{exe}" --uninstall'),
                            ("QuietUninstallString", f'"{exe}" --uninstall --quiet'),
                            ("InstallDate", time.strftime("%Y%m%d"))):
            w.SetValueEx(k, name, 0, w.REG_SZ, value)
        w.SetValueEx(k, "EstimatedSize", 0, w.REG_DWORD, max(1, size_bytes // 1024))
        w.SetValueEx(k, "NoModify", 0, w.REG_DWORD, 1)
        w.SetValueEx(k, "NoRepair", 0, w.REG_DWORD, 1)


def remove_uninstall_entry() -> None:
    w = _reg()
    try:
        w.DeleteKey(w.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------- accesos directos
def known_folder(name: str) -> Path:
    """Escritorio o menú Inicio del usuario (respeta carpetas redirigidas, p. ej. a OneDrive)."""
    try:
        from win32com.shell import shell

        fid = {"desktop": shell.FOLDERID_Desktop, "programs": shell.FOLDERID_Programs}[name]
        return Path(shell.SHGetKnownFolderPath(fid, 0, None))
    except Exception:  # noqa: BLE001 - sin pywin32: rutas habituales
        if name == "desktop":
            return Path.home() / "Desktop"
        return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def shortcut_paths() -> dict[str, Path]:
    return {"programs": known_folder("programs") / f"{APP_NAME}.lnk",
            "desktop": known_folder("desktop") / f"{APP_NAME}.lnk"}


def create_shortcut(lnk: Path, exe: Path) -> None:
    """Acceso directo con el identificador de la aplicación (agrupa bien en la barra de tareas)."""
    lnk.parent.mkdir(parents=True, exist_ok=True)
    try:
        import pythoncom
        from win32com.propsys import propsys, pscon
        from win32com.shell import shell

        pythoncom.CoInitialize()
        link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                          shell.IID_IShellLink)
        link.SetPath(str(exe))
        link.SetWorkingDirectory(str(exe.parent))
        link.SetIconLocation(str(exe), 0)
        link.SetDescription("Reproductor, visor, conversor y gestor de comprimidos")
        store = link.QueryInterface(propsys.IID_IPropertyStore)
        store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_USER_MODEL_ID))
        store.Commit()
        link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(lnk), 0)
        return
    except ImportError:
        pass
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{exe}';"
          f"$s.WorkingDirectory='{exe.parent}';$s.IconLocation='{exe},0';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], creationflags=NO_WINDOW,
                   check=False, timeout=60)


def remove_shortcuts() -> None:
    for lnk in shortcut_paths().values():
        try:
            lnk.unlink()
        except OSError:
            pass
    # Grupo del menú Inicio que creaba el instalador antiguo
    old = known_folder("programs") / APP_NAME
    if old.is_dir():
        for f in old.glob("*.lnk"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            old.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------------------------- archivos
def is_running(folder: Path) -> bool:
    """El ejecutable instalado está en uso (no se puede renombrar mientras corre)."""
    exe = folder / EXE
    if not exe.exists():
        return False
    tmp = exe.with_name(EXE + ".check")
    try:
        os.replace(exe, tmp)
        os.replace(tmp, exe)
        return False
    except OSError:
        return True


def request_quit() -> bool:
    """Pide a AERO Player que se cierre (como «Salir» en la bandeja). Usa Qt: llamar desde el hilo principal."""
    import getpass

    try:
        from PySide6.QtNetwork import QLocalSocket
    except ImportError:
        return False
    sock = QLocalSocket()
    sock.connectToServer(f"AeroPlayer-{getpass.getuser()}")
    if not sock.waitForConnected(500):
        return False
    sock.write(json.dumps({"quit": True}).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def wait_closed(folder: Path, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not is_running(folder):
            return True
        time.sleep(0.25)
    return not is_running(folder)


def read_manifest(folder: Path) -> list[str]:
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        return [str(f) for f in data.get("files", [])]
    except (OSError, ValueError, AttributeError):
        return []


def _inside(folder: Path, rel: str) -> Path | None:
    p = (folder / rel).resolve()
    try:
        p.relative_to(folder.resolve())
    except ValueError:
        return None
    return p


def remove_files(folder: Path, files: list[str]) -> None:
    """Borra solo los archivos listados y las carpetas que queden vacías (nunca otras cosas)."""
    dirs = set()
    for rel in files:
        p = _inside(folder, rel)
        if p is None:
            continue
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            continue
        dirs.update(p.parents)
    root = folder.resolve()
    for d in sorted((d for d in dirs if d != root and root in d.parents), key=lambda d: len(d.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass


def uninstall_inno(existing: Existing, timeout: float = 120.0) -> None:
    """Desinstala en silencio una versión hecha con Inno Setup y espera a que termine."""
    exe = existing.uninstall
    if not exe or not Path(exe).exists():
        return
    subprocess.run([exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=False, timeout=timeout)
    # El desinstalador de Inno se copia a una carpeta temporal y sigue trabajando: se espera a que acabe.
    end = time.monotonic() + timeout
    while time.monotonic() < end and (reg_read(INNO_KEY, "UninstallString") or Path(exe).exists()):
        time.sleep(0.3)


class Cancelled(Exception):
    pass


@dataclass
class Payload:
    archive: Path
    files: list[dict]          # [{"path": rel, "size": n}]
    version: str

    @classmethod
    def load(cls, folder: Path) -> "Payload":
        m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        return cls(folder / "payload.tar.xz", m["files"], m["version"])

    @property
    def total(self) -> int:
        return sum(int(f["size"]) for f in self.files)


def extract(payload: Payload, target: Path, progress: Callable[[float, str], None],
            cancelled: Callable[[], bool] = lambda: False) -> list[str]:
    """Extrae el contenido en `target` (sobrescribiendo) e informa del avance (0-1, archivo actual)."""
    target.mkdir(parents=True, exist_ok=True)
    total = max(1, payload.total)
    done = 0
    written: list[str] = []
    root = target.resolve()
    with tarfile.open(payload.archive, "r:xz") as tar:
        for member in tar:
            if cancelled():
                raise Cancelled()
            dest = (target / member.name).resolve()
            if root not in dest.parents and dest != root:
                continue  # ruta peligrosa: no puede venir de nuestro paquete, pero nunca se escribe fuera
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            tmp = dest.with_name(dest.name + ".aero-new")
            with open(tmp, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            os.replace(tmp, dest)
            written.append(member.name.replace("\\", "/"))
            done += member.size
            progress(done / total, member.name)
    return written


def run_app(folder: Path, *args: str, wait: bool = True, timeout: float = 120.0) -> None:
    exe = folder / EXE
    if wait:
        subprocess.run([str(exe), *args], creationflags=NO_WINDOW, check=False, timeout=timeout)
    else:
        subprocess.Popen([str(exe), *args], close_fds=True)


def _data_dir() -> Path:
    return Path(os.environ.get("AERO_DATA_DIR") or os.path.join(os.environ.get("APPDATA") or str(Path.home()),
                                                                 "AeroPlayer"))


def current_setting(key: str) -> str:
    try:
        return str(json.loads((_data_dir() / "settings.json").read_text(encoding="utf-8-sig")).get(key) or "")
    except (OSError, ValueError, AttributeError):
        return ""


def set_setting(key: str, value) -> None:
    """Escribe un ajuste en settings.json sin tocar los demás."""
    base = _data_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = base / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[key] = value
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def remove_user_settings() -> None:
    """Solo con permiso expreso al desinstalar: ajustes, bibliotecas y listas de AERO Player (su carpeta en
    %APPDATA% y su caché). Nunca los archivos del usuario."""
    for folder in (_data_dir(), Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "AeroPlayer"):
        if folder.name == "AeroPlayer" and folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)


def set_initial_theme(theme: str) -> None:
    """Guarda el tema elegido en el instalador en los ajustes del usuario (sin tocar el resto)."""
    if not theme:
        return
    base = Path(os.environ.get("AERO_DATA_DIR") or os.path.join(os.environ.get("APPDATA") or str(Path.home()),
                                                                 "AeroPlayer"))
    base.mkdir(parents=True, exist_ok=True)
    path = base / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data["theme"] = theme
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def current_theme() -> str:
    base = Path(os.environ.get("AERO_DATA_DIR") or os.path.join(os.environ.get("APPDATA") or str(Path.home()),
                                                                 "AeroPlayer"))
    try:
        return str(json.loads((base / "settings.json").read_text(encoding="utf-8")).get("theme") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def install(payload: Payload, opts: Options, progress: Callable[[float, str], None],
            cancelled: Callable[[], bool] = lambda: False, integrate: bool = True) -> Path:
    """Instalación completa. `progress(fracción, texto)`. Devuelve la carpeta instalada.

    `integrate=False` (pruebas) omite registro, accesos directos y menú contextual.
    """
    target = safe_target(opts.target)
    existing = find_existing() if integrate else None
    if existing is not None and existing.kind == "inno":
        progress(0.0, "Quitando la versión anterior…")
        uninstall_inno(existing)
    old = read_manifest(target)
    if is_running(target):
        progress(0.0, "Esperando a que se cierre AERO Player…")
        if not wait_closed(target):
            raise RuntimeError("AERO Player sigue abierto. Ciérralo (también desde la bandeja) y vuelve a intentarlo.")

    written = extract(payload, target, lambda f, name: progress(0.02 + f * 0.86, name), cancelled)
    # Archivos de la versión anterior que ya no forman parte de esta
    stale = sorted(set(old) - set(written))
    if stale:
        remove_files(target, stale)
    (target / MANIFEST).write_text(json.dumps({"version": payload.version, "files": written}, indent=1),
                                   encoding="utf-8")
    if not integrate:
        progress(1.0, "Listo")
        return target

    progress(0.9, "Creando accesos directos…")
    exe = target / EXE
    links = shortcut_paths()
    for key, wanted in (("programs", opts.start_menu), ("desktop", opts.desktop)):
        if wanted:
            create_shortcut(links[key], exe)
        else:
            try:
                links[key].unlink()
            except OSError:
                pass
    progress(0.93, "Registrando en Windows…")
    write_uninstall_entry(target, payload.version, payload.total)
    if opts.associations:
        run_app(target, "--register-associations")
    progress(0.96, "Añadiendo el menú del clic derecho…")
    run_app(target, "--register-context-menu" if opts.context_menu else "--unregister-context-menu")
    set_initial_theme(opts.theme)
    if opts.language:
        set_setting("language", opts.language)
    progress(1.0, "Listo")
    return target


# ---------------------------------------------------------------------------------------------- desinstalar
def unregister_everything(folder: Path) -> None:
    """Quita todo lo que el programa registró en Windows (solo HKCU). Se llama desde el propio programa."""
    from aero.core import associations, shellmenu

    for fn in (associations.unregister, shellmenu.unregister):
        try:
            fn()
        except OSError:
            pass
    try:
        from aero.core.winintegration import set_autostart

        set_autostart(False)
    except (OSError, ImportError):
        pass
    remove_shortcuts()
    remove_uninstall_entry()


def schedule_removal(folder: Path, pid: int) -> None:
    """Borra los archivos instalados cuando termine este proceso (un programa no puede borrarse a sí mismo
    mientras se ejecuta). Solo se borra lo que aparece en uninstall.json."""
    files = read_manifest(folder) + [MANIFEST]
    lst = Path(os.environ.get("TEMP", str(folder.parent))) / f"aero_uninstall_{pid}.txt"
    lst.write_text("\n".join(files), encoding="utf-8")
    script = lst.with_suffix(".ps1")
    script.write_text(f"""
$ErrorActionPreference = 'SilentlyContinue'
Wait-Process -Id {pid} -Timeout 60
Start-Sleep -Milliseconds 300
$root = '{str(folder).replace("'", "''")}'
Get-Content -LiteralPath '{str(lst).replace("'", "''")}' -Encoding UTF8 | ForEach-Object {{
    if ($_ -and -not $_.Contains('..')) {{ Remove-Item -LiteralPath (Join-Path $root $_) -Force }}
}}
Get-ChildItem -LiteralPath $root -Recurse -Directory | Sort-Object {{ $_.FullName.Length }} -Descending |
    ForEach-Object {{ if (-not (Get-ChildItem -LiteralPath $_.FullName -Force)) {{ Remove-Item -LiteralPath $_.FullName }} }}
if (-not (Get-ChildItem -LiteralPath $root -Force)) {{ Remove-Item -LiteralPath $root }}
Remove-Item -LiteralPath '{str(lst).replace("'", "''")}'
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path
""", encoding="utf-8-sig")
    subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle",
                      "Hidden", "-File", str(script)], creationflags=NO_WINDOW, close_fds=True)
