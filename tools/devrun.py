"""Ejecutor de tareas de desarrollo que no molesta a quien usa el ordenador.

Uso:
    python tools/devrun.py run <nombre> -- <orden> [args…]   # en segundo plano; vuelve enseguida
    python tools/devrun.py wait <nombre> [segundos]           # espera a que termine (sin ventanas)
    python tools/devrun.py status                             # estado de todas las tareas
    python tools/devrun.py log <nombre> [líneas]              # últimas líneas del registro
    python tools/devrun.py stop <nombre>                      # detiene la tarea y sus procesos hijos

Cómo evita interferir:
* La orden se lanza en un **escritorio de Windows aparte** («AeroDev», `CreateDesktop`). Las ventanas que abran
  las pruebas, Qt o PyInstaller existen y se pintan, pero en un escritorio que nadie ve: no aparecen encima de
  tus aplicaciones, no roban el foco y no capturan el ratón ni el teclado. Es un mecanismo normal de Windows
  (sin permisos de administrador ni cambios del sistema); el escritorio desaparece cuando ya no lo usa nadie.
* Sin consola (`CREATE_NO_WINDOW`) y con prioridad baja (`BELOW_NORMAL_PRIORITY_CLASS`) para que tu equipo siga
  respondiendo.
* Todo va a `.devrun/<nombre>.log`; el estado (orden, PID, inicio, fin, código de salida) a `.devrun/<nombre>.json`.
  `tools/devmonitor.py` lo muestra en una página HTML local que solo se abre si tú quieres.
* `stop` termina el árbol de procesos con un Job Object, sin dejar procesos colgados.

Lo que necesita la pantalla real (capturas con `mss` de `visual_check.py`, `input_check.py`) se lanza con
`--visible`: entonces va al **monitor secundario** si existe, y sus ventanas se muestran sin activarse.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = Path(os.environ.get("AERO_DEVRUN_DIR") or ROOT / ".devrun")
DESKTOP = "AeroDev"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)

CREATE_NO_WINDOW = 0x08000000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
BELOW_NORMAL = 0x00004000
GENERIC_ALL = 0x10000000
JOB_KILL_ON_CLOSE = 0x2000


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE), ("dwProcessId", wintypes.DWORD),
                ("dwThreadId", wintypes.DWORD)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


u32.CreateDesktopW.restype = wintypes.HANDLE
u32.CloseDesktop.argtypes = [wintypes.HANDLE]
k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
u32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                               wintypes.DWORD, ctypes.c_void_p]
k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateJobObjectW.restype = wintypes.HANDLE
k32.OpenProcess.restype = wintypes.HANDLE


def _paths(name: str) -> tuple[Path, Path]:
    DIR.mkdir(exist_ok=True)
    return DIR / f"{name}.json", DIR / f"{name}.log"


def _read(name: str) -> dict:
    try:
        return json.loads(_paths(name)[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(name: str, data: dict) -> None:
    p = _paths(name)[0]
    tmp = p.with_suffix(f".{os.getpid()}.tmp")       # un temporal por proceso: el vigilante y quien detiene
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for _ in range(50):                               # Windows no deja reemplazar si otro lo está leyendo
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.02)
    os.replace(tmp, p)


def _alive(pid: int) -> bool:
    h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return code.value == 259                        # STILL_ACTIVE


def _secondary_monitor() -> tuple[int, int, int, int] | None:
    """Rectángulo (x, y, ancho, alto) del primer monitor que no es el principal."""
    out = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                         ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    def cb(h, _dc, _r, _l):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        u32.GetMonitorInfoW(h, ctypes.byref(mi))
        if not mi.dwFlags & 1:
            w = mi.rcWork
            out.append((w.left, w.top, w.right - w.left, w.bottom - w.top))
        return True

    u32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    return out[0] if out else None


def run(name: str, cmd: list[str], visible: bool = False) -> int:
    """Lanza la tarea a través de un vigilante sin ventana (que la crea, espera y anota cómo terminó)."""
    _meta, log = _paths(name)
    old = _read(name)
    if old.get("state") in ("running", "starting") and _alive(old.get("pid", 0)):
        print(f"«{name}» ya está en marcha (PID {old['pid']}).")
        return 1
    exe = Path(cmd[0])
    if not exe.is_absolute() and (ROOT / exe).exists():
        cmd = [str(ROOT / exe), *cmd[1:]]            # CreateProcess no busca en el directorio de trabajo nuevo
    _write(name, {"name": name, "cmd": subprocess.list2cmdline(cmd), "pid": 0, "state": "starting",
                  "started": time.time(), "finished": 0, "exit": None, "log": str(log)})
    subprocess.Popen([sys.executable, __file__, "_launch", name, *(["--visible"] if visible else []), "--", *cmd],
                     cwd=str(ROOT), creationflags=CREATE_NO_WINDOW | 0x00000008,      # DETACHED_PROCESS
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.time() + 90           # con el equipo cargado, Python puede tardar en arrancar
    while time.time() < end:
        d = _read(name)
        if d.get("state") != "starting":
            break
        time.sleep(0.05)
    d = _read(name)
    if d.get("state") == "starting":
        print(f"«{name}»: el vigilante no arrancó")
        return 1
    if d.get("state") == "failed" and not d.get("pid"):
        print(f"«{name}»: no se pudo lanzar: {d.get('error', '')}")
        return 1
    print(f"«{name}» en marcha (PID {d.get('pid')}); registro: {log}")
    return 0


def _launch(name: str, cmd: list[str], visible: bool = False) -> None:
    _meta, log = _paths(name)
    env = dict(os.environ)
    env["AERO_DEVRUN"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONUNBUFFERED"] = "1"
    if visible:
        mon = _secondary_monitor()
        if mon:
            env["AERO_DEV_SCREEN"] = ",".join(map(str, mon))   # visual_check coloca allí sus ventanas
    sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    hlog = k32.CreateFileW(str(log), 0x40000000, 0x3, ctypes.byref(sa), 2, 0x80, None)  # GENERIC_WRITE, CREATE_ALWAYS
    if hlog in (None, wintypes.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error(), "no se pudo crear el registro")
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.dwFlags = 0x100 | 0x1                                         # STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW
    si.wShowWindow = 4 if visible else 0                             # SW_SHOWNOACTIVATE | SW_HIDE
    si.hStdOutput = si.hStdError = hlog
    desk = None
    if not visible:
        desk = u32.CreateDesktopW(DESKTOP, None, None, 0, GENERIC_ALL, None)
        if not desk:
            raise OSError(ctypes.get_last_error(), "no se pudo crear el escritorio de desarrollo")
        si.lpDesktop = DESKTOP
    block = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
    pi = PROCESS_INFORMATION()
    line = subprocess.list2cmdline(cmd)
    ok = k32.CreateProcessW(None, ctypes.create_unicode_buffer(line), None, None, True,
                            CREATE_NO_WINDOW | BELOW_NORMAL | CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED,
                            ctypes.create_unicode_buffer(block), str(ROOT), ctypes.byref(si), ctypes.byref(pi))
    k32.CloseHandle(hlog)
    if not ok:
        _write(name, {**_read(name), "state": "failed", "error": f"{ctypes.get_last_error()}: {line}",
                      "finished": time.time()})
        return
    k32.ResumeThread(pi.hThread)
    k32.CloseHandle(pi.hThread)
    _write(name, {"name": name, "cmd": line, "pid": pi.dwProcessId, "state": "running", "started": time.time(),
                  "finished": 0, "exit": None, "desktop": DESKTOP if desk else ("secundario" if visible else ""),
                  "log": str(log)})
    # Este proceso tiene el identificador de la tarea desde que nace: el código de salida nunca se pierde,
    # y mantener `desk` abierto conserva el escritorio mientras dure.
    k32.WaitForSingleObject(pi.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD(1)
    k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    k32.CloseHandle(pi.hProcess)
    d = _read(name)
    if d.get("pid") == pi.dwProcessId and d.get("state") == "running":
        d.update(state="done" if code.value == 0 else "failed", exit=code.value, finished=time.time())
        _write(name, d)
    if desk:
        u32.CloseDesktop(desk)


def _tree(pid: int) -> list[int]:
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                          "Get-CimInstance Win32_Process | Select ProcessId,ParentProcessId | ConvertTo-Json"],
                         capture_output=True, text=True, creationflags=CREATE_NO_WINDOW).stdout
    rows = json.loads(out or "[]")
    kids: dict[int, list[int]] = {}
    for r in rows:
        kids.setdefault(r["ParentProcessId"], []).append(r["ProcessId"])
    seen, todo = [], [pid]
    while todo:
        p = todo.pop()
        if p not in seen:
            seen.append(p)
            todo.extend(kids.get(p, []))
    return seen


def stop(name: str) -> int:
    d = _read(name)
    if not d or d.get("state") != "running":
        print(f"«{name}» no está en marcha.")
        return 1
    for p in reversed(_tree(d["pid"])):
        h = k32.OpenProcess(0x0001, False, p)       # PROCESS_TERMINATE
        if h:
            k32.TerminateProcess(h, 1)
            k32.CloseHandle(h)
    d.update(state="stopped", finished=time.time(), exit=-1)
    _write(name, d)
    print(f"«{name}» detenida.")
    return 0


def status() -> list[dict]:
    out = []
    for p in sorted(DIR.glob("*.json")) if DIR.exists() else []:
        d = _read(p.stem)
        if d.get("state") == "running" and not _alive(d.get("pid", 0)):
            d["state"] = "lost"                        # terminó sin que el vigilante lo anotara
        out.append(d)
    return out


def wait(name: str, timeout: float = 3600) -> int:
    end = time.time() + timeout
    while time.time() < end:
        d = _read(name)
        if d.get("state") != "running":
            print(f"«{name}»: {d.get('state')} (código {d.get('exit')})")
            return 0 if d.get("state") == "done" else 1
        time.sleep(1)
    print(f"«{name}» sigue en marcha tras {timeout:.0f} s")
    return 2


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv:
        print(__doc__)
        return 2
    op = argv[0]
    if op == "run":
        visible = "--visible" in argv
        args = [a for a in argv[1:] if a != "--visible"]
        name = args[0]
        cmd = args[args.index("--") + 1:]
        return run(name, cmd, visible)
    if op == "_launch":
        rest = argv[1:]
        visible = "--visible" in rest[:rest.index("--")]
        _launch(rest[0], rest[rest.index("--") + 1:], visible)
        return 0
    if op == "wait":
        return wait(argv[1], float(argv[2]) if len(argv) > 2 else 3600)
    if op == "stop":
        return stop(argv[1])
    if op == "log":
        n = int(argv[2]) if len(argv) > 2 else 40
        text = _paths(argv[1])[1].read_text(encoding="utf-8", errors="replace")
        print("\n".join(text.splitlines()[-n:]))
        return 0
    if op == "status":
        for d in status():
            dur = (d.get("finished") or time.time()) - d.get("started", time.time())
            print(f"{d.get('name', '?'):16} {d.get('state', '?'):8} {dur:7.0f} s  código={d.get('exit')}  "
                  f"{d.get('cmd', '')[:80]}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
