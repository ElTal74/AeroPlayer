"""Detección segura y barata del equipo (solo lectura, sin procesos externos ni dependencias).

* Memoria total y disponible: `GlobalMemoryStatusEx`.
* Procesador: núcleos lógicos (`os.cpu_count`) y nombre (registro, solo lectura).
* Gráficas: `EnumDisplayDevicesW` (nombres de los adaptadores; se distingue integrada de dedicada por nombre).
* Carga del sistema durante la ejecución: `GetSystemTimes` (dos lecturas separadas en el tiempo).

La recomendación es orientativa: el usuario siempre puede elegir otro perfil.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass, field

GB = 1024 ** 3


@dataclass
class Hardware:
    ram_total: int = 0
    ram_free: int = 0
    cores: int = 1
    cpu: str = ""
    gpus: list[str] = field(default_factory=list)
    screen: tuple[int, int] = (0, 0)   # se rellena desde la interfaz

    @property
    def dedicated_gpu(self) -> bool:
        names = " ".join(self.gpus).lower()
        return any(k in names for k in ("geforce", "rtx", "gtx", "quadro", "radeon rx", "radeon pro", "arc a"))

    def summary(self) -> str:
        from aero.i18n import tr

        parts = [tr("{a:.0f} GB de RAM ({b:.1f} GB libres)", a=self.ram_total / GB, b=self.ram_free / GB)
                 if self.ram_total else "", tr("{n} núcleos lógicos", n=self.cores), ", ".join(self.gpus[:2])]
        if self.screen[0]:
            parts.append(tr("pantalla {w}×{h}", w=self.screen[0], h=self.screen[1]))
        return " · ".join(p for p in parts if p)


class _MEMSTATUS(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("DeviceName", ctypes.c_wchar * 32), ("DeviceString", ctypes.c_wchar * 128),
                ("StateFlags", ctypes.c_ulong), ("DeviceID", ctypes.c_wchar * 128),
                ("DeviceKey", ctypes.c_wchar * 128)]


def memory() -> tuple[int, int]:
    if os.name != "nt":
        return 0, 0
    m = _MEMSTATUS()
    m.dwLength = ctypes.sizeof(m)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return 0, 0
    return int(m.ullTotalPhys), int(m.ullAvailPhys)


def _cpu_name() -> str:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            return " ".join(str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).split())
    except OSError:
        return ""


def _gpus() -> list[str]:
    if os.name != "nt":
        return []
    out: list[str] = []
    d = _DISPLAY_DEVICE()
    d.cb = ctypes.sizeof(d)
    i = 0
    while ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0) and i < 16:
        name = d.DeviceString.strip()
        if name and name not in out and not any(k in name for k in ("Remote", "Basic Display", "Virtual", "Mirror")):
            out.append(name)
        i += 1
    return out


def detect() -> Hardware:
    total, free = memory()
    return Hardware(total, free, os.cpu_count() or 1, _cpu_name(), _gpus())


def recommend(hw: Hardware) -> tuple[str, str]:
    """(perfil, motivo). Umbrales a partir de lo medido en docs/RENDIMIENTO.md."""
    ram = hw.ram_total / GB if hw.ram_total else 8
    big_screen = hw.screen[0] * hw.screen[1] > 2560 * 1440
    if ram < 6 or hw.cores <= 2:
        return "ultra", "Poca memoria o pocos núcleos: se prioriza la fluidez."
    if ram < 12 or hw.cores <= 4 or (big_screen and not hw.dedicated_gpu):
        return "balanced", "Equipo intermedio: buena calidad con consumo contenido."
    return "high", "Equipo con recursos de sobra para los efectos más elaborados."


class CpuLoad:
    """Carga total del sistema entre dos llamadas (0–1), con `GetSystemTimes`. Coste despreciable."""

    def __init__(self):
        self._last = self._times()

    @staticmethod
    def _times():
        if os.name != "nt":
            return None
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return idle.value, kernel.value + user.value

    def sample(self) -> float:
        now = self._times()
        if now is None or self._last is None:
            return 0.0
        di, dt = now[0] - self._last[0], now[1] - self._last[1]
        self._last = now
        return 0.0 if dt <= 0 else max(0.0, min(1.0, 1.0 - di / dt))
