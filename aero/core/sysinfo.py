"""Información del equipo para los widgets de Inicio (sin dependencias nuevas).

Fuentes, de la más barata a la más cara:
* API de Windows con ctypes: uso de CPU (`GetSystemTimes`), memoria (`GlobalMemoryStatusEx`), batería
  (`GetSystemPowerStatus`), discos (`GetLogicalDrives` + espacio libre).
* Registro: modelo de CPU, placa base (BIOS), versión de Windows, memoria dedicada de la GPU.
* Contadores de rendimiento de Windows (PDH, los del Administrador de tareas): uso y memoria de la GPU.
* WMI (pywin32, ya incluido): nombres de GPU, ratón y teclado. Se consulta una sola vez, en segundo plano.

Las temperaturas solo se muestran si Windows las expone de forma estándar (`MSAcpi_ThermalZoneTemperature`,
que en la mayoría de equipos exige permisos o no existe). Si no, se devuelve None y la interfaz dice
«No disponible»: nunca se inventa un valor.

Nada aquí usa Qt: se puede ejecutar en un hilo.
"""

from __future__ import annotations

import ctypes
import os
import platform
import string
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass, field

_IS_WIN = os.name == "nt"


# ---------------------------------------------------------------------------------------------- registro
def _reg(path: str, name: str, root: str = "HKLM"):
    if not _IS_WIN:
        return None
    import winreg

    hive = winreg.HKEY_LOCAL_MACHINE if root == "HKLM" else winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(hive, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


# ---------------------------------------------------------------------------------------------- datos fijos
@dataclass
class Gpu:
    name: str
    vram: int = 0            # bytes de memoria dedicada (0 = desconocida)


@dataclass
class StaticInfo:
    cpu_model: str = "No disponible"
    cpu_cores: int = 0
    cpu_threads: int = 0
    gpus: list[Gpu] = field(default_factory=list)
    board: str = "No disponible"
    bios: str = ""
    os_name: str = ""
    os_build: str = ""
    arch: str = ""
    mice: list[str] = field(default_factory=list)
    keyboards: list[str] = field(default_factory=list)
    ram_total: int = 0


def _physical_cores() -> int:
    """Núcleos físicos con GetLogicalProcessorInformationEx (RelationProcessorCore)."""
    if not _IS_WIN:
        return 0
    k32 = ctypes.windll.kernel32
    size = wintypes.DWORD(0)
    k32.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    if not k32.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(size)):
        return 0
    n, off = 0, 0
    while off < size.value:
        rel = int.from_bytes(buf.raw[off:off + 4], "little")
        rsize = int.from_bytes(buf.raw[off + 4:off + 8], "little")
        if rel == 0 and rsize:
            n += 1
        if not rsize:
            break
        off += rsize
    return n


def _gpus_from_registry() -> dict[str, int]:
    """Memoria dedicada real por nombre de adaptador (WMI la corta a 4 GB)."""
    out: dict[str, int] = {}
    if not _IS_WIN:
        return out
    import winreg

    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            for i in range(64):
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                name = _reg(rf"{base}\{sub}", "DriverDesc")
                mem = _reg(rf"{base}\{sub}", "HardwareInformation.qwMemorySize")
                if mem is None:
                    raw = _reg(rf"{base}\{sub}", "HardwareInformation.MemorySize")
                    mem = int.from_bytes(raw, "little") if isinstance(raw, bytes) else raw
                if name:
                    out[str(name)] = int(mem or 0)
    except OSError:
        pass
    return out


def _wmi_names(cls: str, prop: str = "Name") -> list[str]:
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            svc = win32com.client.GetObject(r"winmgmts:root\cimv2")
            rows = svc.ExecQuery(f"select {prop} from {cls}")
            out = [str(getattr(o, prop)) for o in rows if getattr(o, prop)]
            del rows, svc  # liberar los objetos COM antes de CoUninitialize
            return out
        finally:
            pythoncom.CoUninitialize()
    except Exception:  # noqa: BLE001 - WMI no disponible o sin permisos: se dice «No disponible»
        return []


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    for n in names:
        seen[n] = seen.get(n, 0) + 1
    return [f"{n} ×{c}" if c > 1 else n for n, c in seen.items()]


def static_info() -> StaticInfo:
    """Datos que no cambian mientras la aplicación está abierta (tarda ~0,1 s: llamar en un hilo)."""
    info = StaticInfo()
    if not _IS_WIN:
        return _unix_static(info)
    cpu = _reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")
    if cpu:
        info.cpu_model = " ".join(str(cpu).split())
    info.cpu_threads = os.cpu_count() or 0
    info.cpu_cores = _physical_cores() or info.cpu_threads
    vram = _gpus_from_registry()
    names = _wmi_names("Win32_VideoController") or list(vram)
    virtual = ("virtual", "basic display", "parsec", "remote", "meta", "idd")
    real = [n for n in names if not any(v in n.lower() for v in virtual)] or names
    info.gpus = [Gpu(n, vram.get(n, 0)) for n in dict.fromkeys(real)]
    manu = _reg(r"HARDWARE\DESCRIPTION\System\BIOS", "BaseBoardManufacturer")
    prod = _reg(r"HARDWARE\DESCRIPTION\System\BIOS", "BaseBoardProduct")
    if manu or prod:
        info.board = " ".join(x for x in (str(manu or "").strip(), str(prod or "").strip()) if x)
    bios = _reg(r"HARDWARE\DESCRIPTION\System\BIOS", "BIOSVersion")
    info.bios = str(bios or "")
    nt = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    build = _reg(nt, "CurrentBuild") or platform.version()
    product = str(_reg(nt, "ProductName") or platform.system())
    if product.startswith("Windows 10") and build and str(build).isdigit() and int(build) >= 22000:
        product = product.replace("Windows 10", "Windows 11")  # el registro sigue diciendo 10 en Windows 11
    info.os_name = product
    disp = _reg(nt, "DisplayVersion")
    info.os_build = f"{disp} · compilación {build}" if disp else f"compilación {build}"
    info.arch = {"AMD64": "64 bits (x64)", "ARM64": "64 bits (ARM)", "x86": "32 bits"}.get(platform.machine(),
                                                                                           platform.machine())
    info.mice = _unique(_wmi_names("Win32_PointingDevice"))
    info.keyboards = _unique(_wmi_names("Win32_Keyboard"))
    info.ram_total = memory()[0]
    return info


def _unix_static(info: StaticInfo) -> StaticInfo:
    """Linux y macOS: procesador, sistema y memoria (sin procesos externos)."""
    from aero.core.hardware import _cpu_name

    info.cpu_model = _cpu_name()
    info.cpu_threads = os.cpu_count() or 0
    try:
        import psutil

        info.cpu_cores = psutil.cpu_count(logical=False) or info.cpu_threads
    except ImportError:
        info.cpu_cores = info.cpu_threads
    if sys.platform == "darwin":
        info.os_name = f"macOS {platform.mac_ver()[0]}".strip()
        info.os_build = f"Darwin {platform.release()}"
    else:
        info.os_name = _os_release().get("PRETTY_NAME") or "Linux"
        info.os_build = f"Linux {platform.release()}"
    info.arch = {"x86_64": "64 bits (x64)", "amd64": "64 bits (x64)", "arm64": "64 bits (ARM)",
                 "aarch64": "64 bits (ARM)"}.get(platform.machine().lower(), platform.machine())
    info.ram_total = memory()[0]
    return info


def _os_release() -> dict[str, str]:
    out: dict[str, str] = {}
    for f in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    k, sep, v = line.strip().partition("=")
                    if sep:
                        out[k] = v.strip().strip('"')
            return out
        except OSError:
            continue
    return out


# ---------------------------------------------------------------------------------------------- datos vivos
class _FT(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    def value(self) -> int:
        return (self.hi << 32) | self.lo


class CpuMeter:
    """Uso total de CPU entre dos lecturas (igual que el Administrador de tareas)."""

    def __init__(self):
        self._last = self._times()

    @staticmethod
    def _times() -> tuple[int, int, int]:
        if not _IS_WIN:
            try:
                import psutil

                ct = psutil.cpu_times()
                # como en Windows: (ocioso, «núcleo» que incluye el ocioso, usuario)
                return int(ct.idle * 1000), int(sum(ct) * 1000), 0
            except (ImportError, OSError):
                return 0, 0, 0
        idle, kern, user = _FT(), _FT(), _FT()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        return idle.value(), kern.value(), user.value()

    def percent(self) -> float | None:
        now = self._times()
        di, dk, du = (a - b for a, b in zip(now, self._last))
        self._last = now
        total = dk + du  # el tiempo de núcleo incluye el ocioso
        if total <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (total - di) / total))


class _MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64), ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64), ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64), ("ullAvailExtendedVirtual", ctypes.c_uint64)]


def memory() -> tuple[int, int]:
    """(total, disponible) en bytes."""
    if not _IS_WIN:
        from aero.core.hardware import memory as unix_memory

        return unix_memory()
    m = _MEMSTAT()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return int(m.ullTotalPhys), int(m.ullAvailPhys)


@dataclass
class Disk:
    root: str
    label: str
    total: int
    free: int


def disks() -> list[Disk]:
    out: list[Disk] = []
    if not _IS_WIN:
        return _unix_disks()
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = f"{letter}:\\"
        if k32.GetDriveTypeW(root) not in (2, 3):  # extraíble o fijo (no red, no CD)
            continue
        free, total = ctypes.c_uint64(), ctypes.c_uint64()
        if not k32.GetDiskFreeSpaceExW(root, None, ctypes.byref(total), ctypes.byref(free)):
            continue
        name = ctypes.create_unicode_buffer(261)
        k32.GetVolumeInformationW(root, name, 261, None, None, None, None, 0)
        out.append(Disk(root, name.value or "Disco local", int(total.value), int(free.value)))
    return out


def _unix_disks() -> list[Disk]:
    """Volúmenes reales montados (sin los del sistema, snaps ni imágenes de solo lectura)."""
    try:
        import psutil
    except ImportError:
        return []
    out: list[Disk] = []
    skip_fs = {"squashfs", "tmpfs", "devtmpfs", "overlay", "iso9660", "udf", "autofs"}
    for part in psutil.disk_partitions(all=False):
        mp = part.mountpoint
        if part.fstype.lower() in skip_fs or mp.startswith(("/snap", "/boot", "/sys", "/proc", "/run/snapd")):
            continue
        if sys.platform == "darwin" and not (mp == "/" or mp.startswith("/Volumes/")):
            continue
        try:
            u = psutil.disk_usage(mp)
        except OSError:
            continue
        if u.total < 1 << 30:                       # menos de 1 GB: particiones auxiliares
            continue
        out.append(Disk(mp, "Disco del sistema" if mp == "/" else os.path.basename(mp.rstrip("/")) or mp,
                        int(u.total), int(u.free)))
    return out


class _POWER(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


@dataclass
class Battery:
    percent: int
    plugged: bool
    seconds_left: int | None


def battery() -> Battery | None:
    """None si el equipo no tiene batería."""
    if not _IS_WIN:
        try:
            import psutil

            b = psutil.sensors_battery()
        except (ImportError, OSError, AttributeError):
            return None
        if b is None:
            return None
        left = b.secsleft if isinstance(b.secsleft, int) and b.secsleft >= 0 else None
        return Battery(int(round(b.percent)), bool(b.power_plugged), left)
    p = _POWER()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(p)):
        return None
    if p.BatteryFlag & 128 or p.BatteryLifePercent == 255:  # 128: sin batería del sistema
        return None
    left = None if p.BatteryLifeTime == 0xFFFFFFFF else int(p.BatteryLifeTime)
    return Battery(int(p.BatteryLifePercent), p.ACLineStatus == 1, left)


class GpuMeter:
    """Uso de la GPU (motor 3D más ocupado) y memoria dedicada en uso, con los contadores de Windows."""

    def __init__(self):
        self.ok = False
        self._q = wintypes.HANDLE()
        self._util = wintypes.HANDLE()
        self._mem = wintypes.HANDLE()
        if not _IS_WIN:
            return
        try:
            pdh = ctypes.windll.pdh
            if pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._q)) != 0:
                return
            a = pdh.PdhAddEnglishCounterW(self._q, r"\GPU Engine(*engtype_3D)\Utilization Percentage", 0,
                                          ctypes.byref(self._util))
            b = pdh.PdhAddEnglishCounterW(self._q, r"\GPU Adapter Memory(*)\Dedicated Usage", 0,
                                          ctypes.byref(self._mem))
            self.ok = a == 0
            self._has_mem = b == 0
            pdh.PdhCollectQueryData(self._q)
        except (OSError, AttributeError):
            self.ok = False

    def _array(self, counter) -> list[float]:
        class _Item(ctypes.Structure):
            _fields_ = [("name", ctypes.c_wchar_p), ("status", wintypes.DWORD), ("pad", wintypes.DWORD),
                        ("value", ctypes.c_double)]

        pdh = ctypes.windll.pdh
        PDH_FMT_DOUBLE = 0x200
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None)
        if not size.value:
            return []
        buf = ctypes.create_string_buffer(size.value)
        if pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count),
                                            buf) != 0:
            return []
        items = ctypes.cast(buf, ctypes.POINTER(_Item))
        return [items[i].value for i in range(count.value) if items[i].status in (0, 1)]

    def sample(self) -> tuple[float | None, int | None]:
        """(uso %, bytes de memoria dedicada en uso)."""
        if not self.ok:
            return None, None
        try:
            ctypes.windll.pdh.PdhCollectQueryData(self._q)
            util = self._array(self._util)
            mem = self._array(self._mem) if self._has_mem else []
        except (OSError, AttributeError):
            return None, None
        # Suma por proceso de cada motor 3D; el total del adaptador es la suma (acotada a 100).
        usage = min(100.0, sum(util)) if util else 0.0
        return usage, int(max(mem)) if mem else None

    def close(self):
        if self.ok:
            ctypes.windll.pdh.PdhCloseQuery(self._q)
            self.ok = False


def cpu_temperature() -> float | None:
    """Temperatura por la interfaz estándar de ACPI. En la mayoría de equipos no está expuesta (o exige
    permisos de administrador): entonces None. Nunca se estima."""
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            svc = win32com.client.GetObject(r"winmgmts:root\wmi")
            rows = svc.ExecQuery("select CurrentTemperature from MSAcpi_ThermalZoneTemperature")
            temps = [o.CurrentTemperature / 10.0 - 273.15 for o in rows]
            del rows, svc
        finally:
            pythoncom.CoUninitialize()
        temps = [t for t in temps if 5 < t < 120]
        return max(temps) if temps else None
    except Exception:  # noqa: BLE001
        return None


@dataclass
class LiveSample:
    time: float
    cpu: float | None
    ram_total: int
    ram_free: int
    gpu: float | None
    gpu_mem: int | None
    battery: Battery | None


class Sampler:
    """Lecturas periódicas baratas. Se crea y usa en el mismo hilo de trabajo."""

    def __init__(self):
        self.cpu = CpuMeter()
        self.gpu = GpuMeter()

    def sample(self) -> LiveSample:
        total, free = memory()
        g, gm = self.gpu.sample()
        return LiveSample(time.time(), self.cpu.percent(), total, free, g, gm, battery())
