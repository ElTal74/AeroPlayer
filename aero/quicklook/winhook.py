"""Atajo global (RegisterHotKey) y, opcionalmente, barra espaciadora restringida al Explorador.

Diseño de seguridad:
* El atajo global usa RegisterHotKey: no lee el teclado, solo recibe esa combinación.
* El modo «Espacio» instala un gancho de teclado de bajo nivel que SOLO actúa (y solo consume la tecla)
  cuando la ventana activa es el Explorador o el escritorio, el foco está en la lista de archivos
  (no en un cuadro de texto ni al renombrar) y no hay modificadores pulsados. En cualquier otro caso
  la pulsación se reenvía intacta. No se registra ni almacena ninguna pulsación.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from PySide6.QtCore import QThread, Signal

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_KEYDOWN = 0x0100
WH_KEYBOARD_LL = 13
VK_SPACE = 0x20
LLKHF_INJECTED = 0x10
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
EXPLORER_CLASSES = {"CabinetWClass", "ExploreWClass", "Progman", "WorkerW"}
FILE_VIEW_CLASSES = {"DirectUIHWND", "SysListView32"}

NAMED_KEYS = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "backspace": 0x08,
    "ins": 0x2D, "insert": 0x2D, "del": 0x2E, "delete": 0x2E, "home": 0x24, "end": 0x23, "pgup": 0x21,
    "pgdown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "pause": 0x13,
    ",": 0xBC, ".": 0xBE, "-": 0xBD, "+": 0xBB, "´": 0xDE, "`": 0xC0,
}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'Ctrl+Shift+Space' → (modificadores, código virtual). None si no es válido."""
    if not text:
        return None
    parts = [p.strip() for p in text.replace(" ", "").split("+") if p.strip()] if text != "+" else ["+"]
    mods, vk = 0, None
    for part in parts:
        low = part.lower()
        if low in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif low == "shift":
            mods |= MOD_SHIFT
        elif low == "alt":
            mods |= MOD_ALT
        elif low in ("meta", "win"):
            mods |= MOD_WIN
        elif low in NAMED_KEYS:
            vk = NAMED_KEYS[low]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
            vk = 0x70 + int(low[1:]) - 1
        else:
            return None
    if vk is None:
        return None
    return mods, vk


if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hwndActive", wintypes.HWND),
                    ("hwndFocus", wintypes.HWND), ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]

    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    user32.CallNextHookEx.restype = LRESULT
    user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE  # evitar truncar el manejador a 32 bits
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


def class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def explorer_file_view_focused() -> bool:
    fg = user32.GetForegroundWindow()
    if not fg or class_name(fg) not in EXPLORER_CLASSES:
        return False
    tid = user32.GetWindowThreadProcessId(fg, None)
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
        return False
    if info.hwndCaret or info.hwndMenuOwner or info.hwndMoveSize:
        return False  # se está escribiendo, hay un menú abierto o se mueve la ventana
    return bool(info.hwndFocus) and class_name(info.hwndFocus) in FILE_VIEW_CLASSES


def _modifiers_down() -> bool:
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C))


class HotkeyThread(QThread):
    triggered = Signal(str)
    failed = Signal(str)

    def __init__(self, hotkey: str, space_mode: bool, parent=None):
        super().__init__(parent)
        self.hotkey = hotkey
        self.space_mode = space_mode
        self._tid = 0
        self._proc = None

    def run(self):
        if os.name != "nt":
            return
        self._tid = kernel32.GetCurrentThreadId()
        registered = False
        parsed = parse_hotkey(self.hotkey)
        if parsed:
            mods, vk = parsed
            registered = bool(user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk))
            if not registered:
                self.failed.emit(f"El atajo «{self.hotkey}» ya lo usa otra aplicación. Elige otro en Ajustes.")
        elif self.hotkey:
            self.failed.emit(f"El atajo «{self.hotkey}» no es válido.")
        hook = None
        if self.space_mode:
            self._proc = HOOKPROC(self._hook)
            hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
            if not hook:
                self.failed.emit("No se pudo activar la barra espaciadora en el Explorador.")
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.triggered.emit("hotkey")
        if registered:
            user32.UnregisterHotKey(None, 1)
        if hook:
            user32.UnhookWindowsHookEx(hook)

    def _hook(self, n_code, w_param, l_param):
        try:
            if n_code == 0 and w_param == WM_KEYDOWN:
                kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                # Se aceptan también pulsaciones sintéticas (teclado en pantalla y otras ayudas técnicas).
                if kb.vkCode == VK_SPACE and not _modifiers_down() and explorer_file_view_focused():
                    self.triggered.emit("space")
                    return 1
        except Exception:  # noqa: BLE001 - un gancho nunca debe romper el teclado
            pass
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self.wait(2000)
