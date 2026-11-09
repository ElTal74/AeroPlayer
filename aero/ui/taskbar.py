"""Barra de tareas de Windows (ITaskbarList3): botones en la miniatura y progreso en el icono.

* Botones «Anterior», «Reproducir/Pausa» y «Siguiente» en la vista previa de la ventana (como el Reproductor
  de Windows Media). Los clics llegan como WM_COMMAND con THBN_CLICKED: `handle_message`.
* Barra de progreso en el icono mientras hay conversiones.

En Linux y macOS no hace nada. Cualquier fallo de COM se ignora: es un extra, nunca debe romper la ventana.
"""

from __future__ import annotations

import ctypes
import sys

THBN_CLICKED = 0x1800
WM_COMMAND = 0x0111
THB_ICON, THB_TOOLTIP, THB_FLAGS = 0x2, 0x4, 0x8
THBF_ENABLED, THBF_DISABLED = 0x0, 0x1
TBPF_NOPROGRESS, TBPF_NORMAL = 0x0, 0x2
BUTTONS = {1: "previous", 2: "play_pause", 3: "next"}


if sys.platform == "win32":
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

        def __init__(self, text: str):
            super().__init__()
            import uuid

            u = uuid.UUID(text)
            self.Data1, self.Data2, self.Data3 = u.fields[0], u.fields[1], u.fields[2]
            self.Data4[:] = list(u.bytes[8:])

    class THUMBBUTTON(ctypes.Structure):
        _fields_ = [("dwMask", wintypes.DWORD), ("iId", wintypes.UINT), ("iBitmap", wintypes.UINT),
                    ("hIcon", wintypes.HICON), ("szTip", ctypes.c_wchar * 260), ("dwFlags", wintypes.DWORD)]

    CLSID_TaskbarList = "56FDF344-FD6D-11d0-958A-006097C9A090"
    IID_ITaskbarList3 = "EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF"


class Taskbar:
    """Envoltorio mínimo de ITaskbarList3 para una ventana."""

    def __init__(self):
        self._ptr = None
        self._vtbl = None
        self._added = False
        self._icons: dict[str, int] = {}
        self._progress_shown = False
        if sys.platform != "win32":
            return
        try:
            ole32 = ctypes.windll.ole32
            ole32.CoInitialize(None)
            ptr = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(ctypes.byref(GUID(CLSID_TaskbarList)), None, 1,     # CLSCTX_INPROC_SERVER
                                        ctypes.byref(GUID(IID_ITaskbarList3)), ctypes.byref(ptr))
            if hr != 0 or not ptr.value:
                return
            self._ptr = ptr
            self._vtbl = ctypes.cast(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0],
                                     ctypes.POINTER(ctypes.c_void_p))
            self._call(3)                                                # HrInit
        except (OSError, AttributeError):
            self._ptr = None

    @property
    def ok(self) -> bool:
        return self._ptr is not None

    def _call(self, index: int, *args, argtypes=()):
        proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        return proto(self._vtbl[index])(self._ptr, *args)

    # ------------------------------------------------------------------ botones
    def _hicon(self, name: str) -> int:
        if name not in self._icons:
            from aero.ui import icons

            self._icons[name] = int(icons.pixmap(name, "#ffffff", 16, 1.0).toImage().toHICON())
        return self._icons[name]

    def _buttons(self, playing: bool, enabled: bool):
        from aero.i18n import tr

        arr = (THUMBBUTTON * 3)()
        spec = ((1, "prev", tr("Anterior")), (2, "pause" if playing else "play", tr("Pausa") if playing else
                                              tr("Reproducir")), (3, "next", tr("Siguiente")))
        for b, (bid, icon, tip) in zip(arr, spec, strict=True):
            b.dwMask = THB_ICON | THB_TOOLTIP | THB_FLAGS
            b.iId = bid
            b.hIcon = self._hicon(icon)
            b.szTip = tip
            b.dwFlags = THBF_ENABLED if enabled else THBF_DISABLED
        return arr

    def set_buttons(self, hwnd: int, playing: bool, enabled: bool) -> bool:
        """Crea o actualiza los tres botones. Devuelve False si Windows aún no está listo (se reintenta)."""
        if not self.ok or not hwnd:
            return False
        arr = self._buttons(playing, enabled)
        types = (wintypes.HWND, wintypes.UINT, ctypes.POINTER(THUMBBUTTON))
        try:
            index = 16 if self._added else 15                 # ThumbBarUpdateButtons / ThumbBarAddButtons
            hr = self._call(index, hwnd, 3, arr, argtypes=types)
        except OSError:
            return False
        if hr == 0:
            self._added = True
        return hr == 0

    # ------------------------------------------------------------------ progreso
    def set_progress(self, hwnd: int, fraction: float | None) -> None:
        """Barra en el icono (0..1); None la quita."""
        if not self.ok or not hwnd:
            return
        try:
            if fraction is None:
                if self._progress_shown:
                    self._call(10, hwnd, TBPF_NOPROGRESS, argtypes=(wintypes.HWND, ctypes.c_int))
                    self._progress_shown = False
                return
            self._call(10, hwnd, TBPF_NORMAL, argtypes=(wintypes.HWND, ctypes.c_int))
            done = int(max(0.0, min(1.0, fraction)) * 1000)
            self._call(9, hwnd, ctypes.c_ulonglong(done), ctypes.c_ulonglong(1000),
                       argtypes=(wintypes.HWND, ctypes.c_ulonglong, ctypes.c_ulonglong))
            self._progress_shown = True
        except OSError:
            pass


def clicked_button(message_ptr: int) -> str | None:
    """Si el mensaje nativo es un clic en un botón de la miniatura, su nombre («previous», «play_pause»…)."""
    if sys.platform != "win32":
        return None
    msg = wintypes.MSG.from_address(int(message_ptr))
    if msg.message == WM_COMMAND and (msg.wParam >> 16) & 0xFFFF == THBN_CLICKED:
        return BUTTONS.get(msg.wParam & 0xFFFF)
    return None


def button_created_message() -> int:
    """Mensaje que Windows envía cuando el botón de la barra de tareas existe (hay que esperar a él)."""
    if sys.platform != "win32":
        return -1
    return ctypes.windll.user32.RegisterWindowMessageW("TaskbarButtonCreated")
