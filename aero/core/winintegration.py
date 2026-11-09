"""Integración con el sistema por usuario (sin permisos de administrador): inicio automático.

* Windows: valor en HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
* Linux: ~/.config/autostart/aero-player.desktop (estándar XDG).
* macOS: ~/Library/LaunchAgents/io.github.eltal74.aeroplayer.plist.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "AERO Player"
MAC_LABEL = "io.github.eltal74.aeroplayer"


def launch_command(background: bool = True) -> str:
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}"'
    else:
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        exe = pyw if os.path.exists(pyw) else sys.executable
        cmd = f'"{exe}" -m aero'
    return cmd + (" --background" if background else "")


def _argv(background: bool = True) -> list[str]:
    """La orden de arranque como lista (Linux y macOS)."""
    base = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "aero"]
    return base + (["--background"] if background else [])


def _unix_file() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "autostart" / "aero-player.desktop"


def _unix_set(enabled: bool) -> bool:
    f = _unix_file()
    try:
        if not enabled:
            f.unlink(missing_ok=True)
            return True
        f.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            import plistlib

            f.write_bytes(plistlib.dumps({"Label": MAC_LABEL, "ProgramArguments": _argv(True), "RunAtLoad": True}))
        else:
            lines = ["[Desktop Entry]", "Type=Application", "Name=AERO Player", f"Exec={shlex.join(_argv(True))}",
                     "X-GNOME-Autostart-enabled=true", "Terminal=false"]
            f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    if sys.platform != "win32":
        return _unix_set(enabled)
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, launch_command(True))
            else:
                try:
                    winreg.DeleteValue(k, VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def autostart_enabled() -> bool:
    if sys.platform != "win32":
        return _unix_file().exists()
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as k:
            winreg.QueryValueEx(k, VALUE)
            return True
    except OSError:
        return False
