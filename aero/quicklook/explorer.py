"""Obtiene el archivo seleccionado en la ventana del Explorador activa (pestaña activa en Windows 11)."""

from __future__ import annotations

import os


def _active_tab_hwnd(fg: int) -> int:
    import win32gui

    try:
        return win32gui.FindWindowEx(fg, 0, "ShellTabWindowClass", None)
    except Exception:  # noqa: BLE001
        return 0


def _tab_hwnd_of(window) -> int:
    """HWND de la pestaña (ShellTabWindowClass) asociada a una ventana del Explorador."""
    try:
        import pythoncom
        from win32com.shell import shell

        sp = window._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
        browser = sp.QueryService(shell.SID_STopLevelBrowser, shell.IID_IShellBrowser)
        return int(browser.GetWindow())
    except Exception:  # noqa: BLE001
        return 0


def selected_paths() -> list[str]:
    """Rutas seleccionadas en el Explorador en primer plano. Lista vacía si no hay o no es el Explorador."""
    if os.name != "nt":
        return []
    import pythoncom
    import win32com.client
    import win32gui

    try:
        pythoncom.CoInitialize()
    except Exception:  # noqa: BLE001
        pass
    fg = win32gui.GetForegroundWindow()
    cls = win32gui.GetClassName(fg) if fg else ""
    if cls not in ("CabinetWClass", "ExploreWClass"):
        return _desktop_selection() if cls in ("Progman", "WorkerW") else []
    shell_app = win32com.client.Dispatch("Shell.Application")
    candidates = []
    for w in shell_app.Windows():
        try:
            if int(w.HWND) == fg:
                candidates.append(w)
        except Exception:  # noqa: BLE001
            continue
    if not candidates:
        return []
    window = candidates[0]
    if len(candidates) > 1:
        tab = _active_tab_hwnd(fg)
        match = [w for w in candidates if tab and _tab_hwnd_of(w) == tab]
        if match:
            window = match[0]
        else:
            title = win32gui.GetWindowText(fg)
            by_title = [w for w in candidates if title.startswith(str(w.LocationName))]
            window = by_title[0] if by_title else candidates[0]
    try:
        doc = window.Document
        items = [it.Path for it in doc.SelectedItems()]
        if not items and doc.FocusedItem is not None:
            items = [doc.FocusedItem.Path]
    except Exception:  # noqa: BLE001
        return []
    return [p for p in items if p and os.path.exists(p)]


def _desktop_selection() -> list[str]:
    try:
        import win32com.client

        shell_app = win32com.client.Dispatch("Shell.Application")
        windows = shell_app.Windows()
        # SWC_DESKTOP = 8, SWFO_NEEDDISPATCH = 1
        desktop = windows.FindWindowSW(0, None, 8, 0, 1)
        if desktop is None:
            return []
        return [it.Path for it in desktop.Document.SelectedItems()]
    except Exception:  # noqa: BLE001
        return []
