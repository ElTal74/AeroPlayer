"""Utilidades de ventana para la vista rápida (la ventana en sí es `aero.ui.media_window.MediaWindow`)."""

from __future__ import annotations

import ctypes
import os


def force_foreground(hwnd: int) -> None:
    """Traer la ventana al frente aunque otra aplicación tenga el foco (técnica AttachThreadInput)."""
    if os.name != "nt":
        return
    u = ctypes.windll.user32
    fg = u.GetForegroundWindow()
    if fg == hwnd:
        return
    cur = ctypes.windll.kernel32.GetCurrentThreadId()
    other = u.GetWindowThreadProcessId(fg, None)
    if other and other != cur:
        u.AttachThreadInput(other, cur, True)
        u.SetForegroundWindow(hwnd)
        u.BringWindowToTop(hwnd)
        u.AttachThreadInput(other, cur, False)
    else:
        u.SetForegroundWindow(hwnd)
