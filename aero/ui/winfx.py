"""Transparencia real de ventana en Windows.

Técnicas (ver docs/AUDITORIA.md, probadas con capturas reales activas e inactivas):
* Alfa por píxel (`WA_TranslucentBackground` en ventana sin marco): deja ver nítido lo que hay detrás.
* Acrílico por composición (`SetWindowCompositionAttribute` + `ACCENT_ENABLE_ACRYLICBLURBEHIND`): lo de detrás
  se ve desenfocado y, a diferencia del acrílico de DWM, se mantiene con la ventana en segundo plano.
Mica y el acrílico de DWM se descartaron: el primero no muestra las aplicaciones de detrás y el segundo se
apaga al perder el foco y no funciona sin marco.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

GLASS_BLUR, GLASS_CLEAR, GLASS_OPAQUE = "blur", "clear", "opaque"
_ACCENT_DISABLED, _ACCENT_ACRYLIC = 0, 4
_WCA_ACCENT_POLICY = 19


class _Accent(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int), ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int)]


class _WCAData(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]


def available() -> bool:
    return os.name == "nt"


def set_glass(hwnd: int, mode: str, tint: int = 0x18000000) -> bool:
    """Activa o desactiva el desenfoque del contenido de detrás. `tint` en formato AABBGGRR."""
    if not available():
        return False
    try:
        user32 = ctypes.windll.user32
        state = _ACCENT_ACRYLIC if mode == GLASS_BLUR else _ACCENT_DISABLED
        accent = _Accent(state, 2 if state else 0, tint if state else 0, 0)
        data = _WCAData(_WCA_ACCENT_POLICY, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p),
                        ctypes.sizeof(accent))
        return bool(user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(data)))
    except (OSError, AttributeError):
        return False


def set_round_region(hwnd: int, width: int, height: int, radius: int) -> None:
    """Recorta la ventana (incluido el desenfoque y la zona de clic) a un rectángulo redondeado."""
    if not available():
        return
    try:
        gdi, user32 = ctypes.windll.gdi32, ctypes.windll.user32
        gdi.CreateRoundRectRgn.restype = wintypes.HRGN
        user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        if radius <= 0:
            user32.SetWindowRgn(wintypes.HWND(hwnd), None, True)
            return
        rgn = gdi.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius * 2, radius * 2)
        user32.SetWindowRgn(wintypes.HWND(hwnd), rgn, True)  # el sistema se queda con la región
    except (OSError, AttributeError):
        pass


def set_round_corners(hwnd: int, on: bool = True) -> None:
    """Esquinas redondeadas de Windows 11 (8 px). Es lo único que recorta también el desenfoque acrílico:
    SetWindowRgn se ignora en ventanas «layered»."""
    try:
        v = ctypes.c_int(2 if on else 1)  # DWMWCP_ROUND / DWMWCP_DONOTROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(v), ctypes.sizeof(v))
    except (OSError, AttributeError):
        pass


def set_dark_title(hwnd: int, dark: bool) -> None:
    try:
        v = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), ctypes.sizeof(v))
    except (OSError, AttributeError):
        pass
