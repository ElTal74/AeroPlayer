"""Iconos vectoriales propios (trazos SVG 24×24), coloreados en tiempo de ejecución y cacheados."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_S = 'fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
_F = 'fill="{c}" stroke="none"'

KIND_ICONS = {"image": "image", "pdf": "pdf", "document": "viewer", "sheet": "sheet", "slides": "slides",
              "text": "text", "archive": "archive", "folder": "folder", "audio": "music", "video": "video", "unknown": "file"}


PATHS: dict[str, str] = {
    "home": f'<path {_S} d="M3.5 11 12 4l8.5 7"/><path {_S} d="M5.5 9.5V20h5v-5.5h3V20h5V9.5"/>',
    "library": f'<rect {_S} x="3.5" y="4" width="4" height="16" rx="1"/><rect {_S} x="9.5" y="4" width="4" height="16" rx="1"/><path {_S} d="m15.8 5.2 3.9-1 3 15.4-3.9 1z"/>',
    "player": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_F} d="M10 8.3v7.4l6-3.7z"/>',
    "viewer": f'<path {_S} d="M14 3.5H6.5a1.5 1.5 0 0 0-1.5 1.5v14a1.5 1.5 0 0 0 1.5 1.5h11a1.5 1.5 0 0 0 1.5-1.5V8.5z"/><path {_S} d="M14 3.5v5h5"/><path {_S} d="M8.5 13h7M8.5 16.5h5"/>',
    "convert": f'<path {_S} d="M4 8.5h13l-3.5-3.5"/><path {_S} d="M20 15.5H7l3.5 3.5"/>',
    "playlists": f'<path {_S} d="M4 6h11M4 11h11M4 16h7"/><path {_S} d="M17.5 18.5V9l3.5-1"/><circle {_S} cx="16" cy="18.5" r="1.8"/>',
    "settings": f'<circle {_S} cx="12" cy="12" r="3"/><path {_S} d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>',
    "play": f'<path {_F} d="M7.5 4.8v14.4c0 .8.9 1.3 1.6.9l11.3-7.2c.6-.4.6-1.4 0-1.8L9.1 3.9c-.7-.4-1.6.1-1.6.9z"/>',
    "pause": f'<rect {_F} x="6" y="4.5" width="4" height="15" rx="1.3"/><rect {_F} x="14" y="4.5" width="4" height="15" rx="1.3"/>',
    "next": f'<path {_F} d="M5 5.6v12.8c0 .7.8 1.2 1.4.8l9.4-6.4c.5-.4.5-1.2 0-1.6L6.4 4.8C5.8 4.4 5 4.9 5 5.6z"/><rect {_F} x="17" y="4.5" width="2.6" height="15" rx="1.2"/>',
    "prev": f'<path {_F} d="M19 5.6v12.8c0 .7-.8 1.2-1.4.8l-9.4-6.4c-.5-.4-.5-1.2 0-1.6l9.4-6.4c.6-.4 1.4.1 1.4.8z"/><rect {_F} x="4.4" y="4.5" width="2.6" height="15" rx="1.2"/>',
    "shuffle": f'<path {_S} d="M3.5 7h3.2c2 0 3.3 1 4.3 2.6l2 3.3c1 1.6 2.3 2.6 4.3 2.6h3.2"/><path {_S} d="M3.5 17h3.2c1.4 0 2.4-.5 3.2-1.3M13.8 8.3c.8-.8 1.8-1.3 3.2-1.3h3.5"/><path {_S} d="m18 4.5 2.5 2.5L18 9.5M18 13l2.5 2.5L18 18"/>',
    "repeat": f'<path {_S} d="M4 11V9.5A3.5 3.5 0 0 1 7.5 6H19l-3-3"/><path {_S} d="M20 13v1.5a3.5 3.5 0 0 1-3.5 3.5H5l3 3"/>',
    "repeat1": f'<path {_S} d="M4 11V9.5A3.5 3.5 0 0 1 7.5 6H19l-3-3"/><path {_S} d="M20 13v1.5a3.5 3.5 0 0 1-3.5 3.5H5l3 3"/><path {_S} d="M11.3 10.3 12.5 9.5v5"/>',
    "volume": f'<path {_S} d="M4 9.5h3l4.5-4v13l-4.5-4H4z"/><path {_S} d="M15 9a4 4 0 0 1 0 6M17.6 6.4a7.5 7.5 0 0 1 0 11.2"/>',
    "volume_low": f'<path {_S} d="M4 9.5h3l4.5-4v13l-4.5-4H4z"/><path {_S} d="M15 9a4 4 0 0 1 0 6"/>',
    "mute": f'<path {_S} d="M4 9.5h3l4.5-4v13l-4.5-4H4z"/><path {_S} d="m15.5 9.5 5 5M20.5 9.5l-5 5"/>',
    "fullscreen": f'<path {_S} d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    "exit_fullscreen": f'<path {_S} d="M9 4v5H4M20 9h-5V4M15 20v-5h5M4 15h5v5"/>',
    "visualizer": f'<path {_S} d="M4 14v4M8 9v9M12 5v13M16 10v8M20 13v5"/>',
    "queue": f'<path {_S} d="M4 6h16M4 11h16M4 16h10"/><path {_F} d="M17 14v6l4.5-3z"/>',
    "folder": f'<path {_S} d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4.2l2 2H19a1.5 1.5 0 0 1 1.5 1.5V17a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 17z"/>',
    "file": f'<path {_S} d="M14 3.5H6.5A1.5 1.5 0 0 0 5 5v14a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 19V8.5z"/><path {_S} d="M14 3.5v5h5"/>',
    "open": f'<path {_S} d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4.2l2 2H18a1.5 1.5 0 0 1 1.5 1.5V11"/><path {_S} d="M3.5 7.5V17a1.5 1.5 0 0 0 1.5 1.5h12.5l3-7H7z"/>',
    "search": f'<circle {_S} cx="10.5" cy="10.5" r="6"/><path {_S} d="m15 15 5 5"/>',
    "heart": f'<path {_S} d="M12 19.5s-7.5-4.3-7.5-9.8A4.2 4.2 0 0 1 12 7.2a4.2 4.2 0 0 1 7.5 2.5c0 5.5-7.5 9.8-7.5 9.8z"/>',
    "heart_fill": f'<path {_F} d="M12 19.5s-7.5-4.3-7.5-9.8A4.2 4.2 0 0 1 12 7.2a4.2 4.2 0 0 1 7.5 2.5c0 5.5-7.5 9.8-7.5 9.8z"/>',
    "plus": f'<path {_S} d="M12 5v14M5 12h14"/>',
    "minus": f'<path {_S} d="M5 12h14"/>',
    "close": f'<path {_S} d="m6 6 12 12M18 6 6 18"/>',
    "check": f'<path {_S} d="m5 12.5 4.5 4.5L19 7.5"/>',
    "trash": f'<path {_S} d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
    "edit": f'<path {_S} d="M4.5 19.5h4l10-10-4-4-10 10z"/><path {_S} d="m13 7 4 4"/>',
    "info": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_S} d="M12 11v5.5"/><circle {_F} cx="12" cy="7.8" r="1.1"/>',
    "image": f'<rect {_S} x="3.5" y="4.5" width="17" height="15" rx="2"/><circle {_S} cx="9" cy="10" r="1.8"/><path {_S} d="m4 17.5 5-4.5 4 3.5 3-2.5 4.5 4"/>',
    "music": f'<path {_S} d="M9 18V6l10-2v12"/><circle {_S} cx="6.5" cy="18" r="2.5"/><circle {_S} cx="16.5" cy="16" r="2.5"/>',
    "video": f'<rect {_S} x="3" y="6" width="13" height="12" rx="2"/><path {_S} d="m16 10.5 5-3v9l-5-3z"/>',
    "pdf": f'<path {_S} d="M14 3.5H6.5A1.5 1.5 0 0 0 5 5v14a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 19V8.5z"/><path {_S} d="M14 3.5v5h5"/><path {_S} d="M8 16v-4h1.5a1.2 1.2 0 0 1 0 2.4H8M12.5 16v-4h1a2 2 0 0 1 0 4z"/>',
    "sheet": f'<rect {_S} x="4" y="4" width="16" height="16" rx="2"/><path {_S} d="M4 9.5h16M4 14.5h16M9.5 4v16"/>',
    "slides": f'<rect {_S} x="3.5" y="4.5" width="17" height="11" rx="1.5"/><path {_S} d="M12 15.5V19M8.5 19.5h7"/>',
    "text": f'<path {_S} d="M5 6h14M5 10h14M5 14h14M5 18h9"/>',
    "zoom_in": f'<circle {_S} cx="10.5" cy="10.5" r="6"/><path {_S} d="m15 15 5 5M8 10.5h5M10.5 8v5"/>',
    "zoom_out": f'<circle {_S} cx="10.5" cy="10.5" r="6"/><path {_S} d="m15 15 5 5M8 10.5h5"/>',
    "fit": f'<rect {_S} x="4" y="4" width="16" height="16" rx="2"/><path {_S} d="M8 12h8M12 8v8" opacity=".0"/><path {_S} d="M8 10V8h2M14 8h2v2M16 14v2h-2M10 16H8v-2"/>',
    "rotate": f'<path {_S} d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path {_S} d="M19.5 4v4h-4"/>',
    "rotate_left": f'<path {_S} d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path {_S} d="M4.5 4v4h4"/>',
    "left": f'<path {_S} d="m14.5 6-6 6 6 6"/>',
    "right": f'<path {_S} d="m9.5 6 6 6-6 6"/>',
    "up": f'<path {_S} d="m6 14.5 6-6 6 6"/>',
    "down": f'<path {_S} d="m6 9.5 6 6 6-6"/>',
    "download": f'<path {_S} d="M12 4v11M7.5 10.5 12 15l4.5-4.5"/><path {_S} d="M5 19.5h14"/>',
    "subtitles": f'<rect {_S} x="3" y="5" width="18" height="14" rx="2.5"/><path {_S} d="M6.5 12.5h4M13 12.5h4.5M6.5 15.5h7M15.5 15.5h2"/>',
    "audio_track": f'<path {_S} d="M4 12h2M8 8v8M12 5v14M16 9v6M20 11v2"/>',
    "speed": f'<path {_S} d="M4.5 16a7.5 7.5 0 1 1 15 0"/><path {_S} d="m12 16 4-5"/>',
    "menu": f'<path {_S} d="M4 7h16M4 12h16M4 17h16"/>',
    "more": f'<circle {_F} cx="6" cy="12" r="1.6"/><circle {_F} cx="12" cy="12" r="1.6"/><circle {_F} cx="18" cy="12" r="1.6"/>',
    "eye": f'<path {_S} d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle {_S} cx="12" cy="12" r="3"/>',
    "pause_small": f'<path {_S} d="M9 6v12M15 6v12"/>',
    "refresh": f'<path {_S} d="M19.5 12a7.5 7.5 0 0 1-13.3 4.8M4.5 12a7.5 7.5 0 0 1 13.3-4.8"/><path {_S} d="M18 3.5v4h-4M6 20.5v-4h4"/>',
    "external": f'<path {_S} d="M13.5 4.5H19.5v6M19.5 4.5 11 13"/><path {_S} d="M17 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 4 18.5v-10A1.5 1.5 0 0 1 5.5 7H10"/>',
    "clock": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_S} d="M12 7.5V12l3 2"/>',
    "star": f'<path {_S} d="m12 4 2.4 5 5.4.6-4 3.7 1.1 5.4L12 16l-4.9 2.7 1.1-5.4-4-3.7 5.4-.6z"/>',
    "keyboard": f'<rect {_S} x="2.5" y="6" width="19" height="12" rx="2"/><path {_S} d="M6 10h.01M9.5 10h.01M13 10h.01M16.5 10h.01M7.5 14h9"/>',
    "drop": f'<path {_S} d="M12 3.5v11M7.5 10l4.5 4.5 4.5-4.5"/><path {_S} d="M4 15.5v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    "tag": f'<path {_S} d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7l8.3 8.3-8.7 8.7z"/><circle {_S} cx="8" cy="8" r="1.4"/>',
    "aero": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_S} d="M6 14c3-5 9-6 12-3"/><path {_S} d="M8 17c2.5-3 6-3.5 8.5-2"/>',
    "list_add": f'<path {_S} d="M4 6h11M4 11h11M4 16h7"/><path {_S} d="M18 13v7M14.5 16.5h7"/>',
    "maximize": f'<rect {_S} x="5" y="5" width="14" height="14" rx="2.5"/>',
    "restore": f'<rect {_S} x="4.5" y="8" width="11.5" height="11.5" rx="2.2"/><path {_S} d="M8.5 5.5V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-.5"/>',
    "series": f'<rect {_S} x="3" y="6" width="18" height="12.5" rx="2"/><path {_S} d="M8 3.5 12 6l4-2.5"/><path {_F} d="M10 9.5v6l5-3z"/>',
    "continue": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_F} d="M10 8.3v7.4l6-3.7z"/><path {_S} d="M12 3.5a8.5 8.5 0 0 1 8.5 8.5"/>',
    "stop": f'<rect {_F} x="6" y="6" width="12" height="12" rx="2"/>',
    "archive": f'<rect {_S} x="4" y="3.5" width="16" height="17" rx="2"/><path {_S} d="M12 3.5v2M12 7.5v2M12 11.5v2"/><rect {_S} x="10.2" y="13.5" width="3.6" height="4" rx="1"/>',
    "files": f'<path {_S} d="M3.5 8A1.5 1.5 0 0 1 5 6.5h3.8l1.8 1.8H19A1.5 1.5 0 0 1 20.5 9.8v7.7A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/><path {_S} d="M6.5 6.5V5A1.5 1.5 0 0 1 8 3.5h4l1.5 1.5"/>',
    "grid": f'<rect {_S} x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect {_S} x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect {_S} x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect {_S} x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>',
    "list": f'<path {_S} d="M9 6.5h11M9 12h11M9 17.5h11"/><circle {_F} cx="5" cy="6.5" r="1.2"/><circle {_F} cx="5" cy="12" r="1.2"/><circle {_F} cx="5" cy="17.5" r="1.2"/>',
    "sort": f'<path {_S} d="M7 4.5v15M3.5 16 7 19.5l3.5-3.5"/><path {_S} d="M13 7h7.5M13 12h5.5M13 17h3.5"/>',
    "lock": f'<rect {_S} x="5" y="10.5" width="14" height="10" rx="2"/><path {_S} d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
    "back": f'<path {_S} d="M10 5.5 3.5 12l6.5 6.5"/><path {_S} d="M4 12h16.5"/>',
    "crop": f'<path {_S} d="M6.5 3v14.5H21"/><path {_S} d="M3 6.5h14.5V21"/>',
    "sliders": f'<path {_S} d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle {_S} cx="15" cy="7" r="2"/><circle {_S} cx="9" cy="17" r="2"/>',
    "pixel": f'<rect {_S} x="4" y="4" width="16" height="16" rx="2"/><path {_F} d="M4 4h5.3v5.3H4zM14.7 4H20v5.3h-5.3zM9.3 9.3h5.4v5.4H9.3zM4 14.7h5.3V20H4zM14.7 14.7H20V20h-5.3z"/>',
    "brush": f'<path {_S} d="M19.5 4.5 11 13"/><path {_S} d="M10.5 12.5c-2.5-.3-4.5 1.4-4.5 3.8 0 1.5-.8 2.6-2 3.2 3.6.9 8.4-.1 8.4-4.3 0-1.1-.7-2.2-1.9-2.7z"/>',
    "text_tool": f'<path {_S} d="M5 6.5V5h14v1.5M12 5v14M9.5 19h5"/>',
    "layers": f'<path {_S} d="m12 4 8.5 4.5L12 13 3.5 8.5z"/><path {_S} d="m3.5 12.5 8.5 4.5 8.5-4.5M3.5 16.5 12 21l8.5-4.5"/>',
    "undo": f'<path {_S} d="M9 7.5 4.5 12 9 16.5"/><path {_S} d="M5 12h9.5a5 5 0 0 1 0 10H12"/>',
    "redo": f'<path {_S} d="M15 7.5 19.5 12 15 16.5"/><path {_S} d="M19 12H9.5a5 5 0 0 0 0 10H12"/>',
    "flip_h": f'<path {_S} d="M12 3v18"/><path {_S} d="M9 7 4 17h5zM15 7l5 10h-5z"/>',
    "flip_v": f'<path {_S} d="M3 12h18"/><path {_S} d="M7 9 17 4v5zM7 15l10 5v-5z"/>',
    "line": f'<path {_S} d="M5 19 19 5"/>',
    "arrow": f'<path {_S} d="M5 19 19 5"/><path {_S} d="M10 5h9v9"/>',
    "rect": f'<rect {_S} x="4" y="6" width="16" height="12" rx="1.5"/>',
    "ellipse": f'<ellipse {_S} cx="12" cy="12" rx="8.5" ry="6.5"/>',
    "highlight": f'<path {_S} d="m14.5 4.5 5 5-8 8H6.5v-5z"/><path {_S} d="M4 20.5h16"/>',
    "select": f'<path {_S} stroke-dasharray="2.5 2.5" d="M4.5 4.5h15v15h-15z"/>',
    "move": f'<path {_S} d="M12 3v18M3 12h18"/><path {_S} d="m9 5.5 3-2.5 3 2.5M9 18.5l3 2.5 3-2.5M5.5 9 3 12l2.5 3M18.5 9l2.5 3-2.5 3"/>',
    "align_left": f'<path {_S} d="M4 6h16M4 10h10M4 14h16M4 18h10"/>',
    "align_center": f'<path {_S} d="M4 6h16M7 10h10M4 14h16M7 18h10"/>',
    "align_right": f'<path {_S} d="M4 6h16M10 10h10M4 14h16M10 18h10"/>',
    "align_justify": f'<path {_S} d="M4 6h16M4 10h16M4 14h16M4 18h16"/>',
    "list_num": f'<path {_S} d="M10 6.5h10M10 12h10M10 17.5h10"/><path {_S} d="M4.5 5 6 4v5M4.3 14.2c.4-.9 2.2-.9 2.2.3 0 1-2.4 1.6-2.4 3h2.6"/>',
    "save": f'<path {_S} d="M5 4.5h11l3.5 3.5v11.5H5z"/><path {_S} d="M8 4.5v5h7v-5M8 19.5v-6h8v6"/>',
    "eject": f'<path {_S} d="M5 19h14M12 5l7 9H5z"/>',
    "pencil": f'<path {_S} d="M4.5 19.5 5.6 15 16 4.6a1.6 1.6 0 0 1 2.3 0l1.1 1.1a1.6 1.6 0 0 1 0 2.3L9 18.4z"/><path {_S} d="M14.5 6 18 9.5"/>',
    "eraser": f'<path {_S} d="M8.5 19.5h11"/><path {_S} d="M4.6 14.6 13.8 5.4a1.8 1.8 0 0 1 2.5 0l3.3 3.3a1.8 1.8 0 0 1 0 2.5L11.3 19.5H8.5z"/><path {_S} d="m9.5 9.5 5 5"/>',
    "bucket": f'<path {_S} d="M5.5 11 11 5.5l7 7-5.5 5.5a1.5 1.5 0 0 1-2.1 0l-4.9-4.9a1.5 1.5 0 0 1 0-2.1z"/><path {_S} d="M5 11.5h13"/><path {_S} d="M19.5 15.5s1.5 1.8 1.5 2.9a1.5 1.5 0 0 1-3 0c0-1.1 1.5-2.9 1.5-2.9z"/>',
    "picker": f'<path {_S} d="M14 6.5 17.5 10M15.8 4.7a2 2 0 0 1 2.9 0l.6.6a2 2 0 0 1 0 2.9L9 18.5l-3.5 1 1-3.5z"/>',
    "lasso": f'<path {_S} stroke-dasharray="2.4 2.2" d="M12 4.5c4.7 0 8 2.4 8 5.4s-3.3 5.4-8 5.4-8-2.4-8-5.4 3.3-5.4 8-5.4z"/><path {_S} d="M7.5 14.5c-.8 1.3-.4 3 1 3.6 1.2.5 2.6 0 2.8 1.4"/>',
    "triangle": f'<path {_S} d="M12 4.5 20 19H4z"/>',
    "star_shape": f'<path {_S} d="m12 4 2.4 5 5.4.6-4 3.7 1.1 5.3L12 16l-4.9 2.6 1.1-5.3-4-3.7 5.4-.6z"/>',
    "palette": f'<path {_S} d="M12 3.5a8.5 8.5 0 1 0 0 17c1.2 0 1.8-.8 1.8-1.7 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-.9.8-1.7 1.7-1.7h2a4 4 0 0 0 4-4c0-4-3.8-7.2-8.5-7.2z"/><circle {_F} cx="7.5" cy="11" r="1.2"/><circle {_F} cx="10" cy="7.5" r="1.2"/><circle {_F} cx="14.5" cy="7.5" r="1.2"/>',
    "swap": f'<path {_S} d="M7 4.5 4.5 7 7 9.5M4.5 7H15a4.5 4.5 0 0 1 4.5 4.5V13M17 19.5l2.5-2.5-2.5-2.5M19.5 17H9a4.5 4.5 0 0 1-4.5-4.5V11"/>',
    "effects": f'<path {_S} d="m5 19 9-9M13 5l1 2 2 1-2 1-1 2-1-2-2-1 2-1zM18 11l.6 1.4L20 13l-1.4.6L18 15l-.6-1.4L16 13l1.4-.6zM8 4l.6 1.4L10 6l-1.4.6L8 8l-.6-1.4L6 6l1.4-.6z"/>',
    "transition": f'<rect {_S} x="3.5" y="6.5" width="8" height="11" rx="1.5"/><rect {_S} x="12.5" y="6.5" width="8" height="11" rx="1.5"/><path {_S} d="m10 9.5 4 5M14 9.5l-4 5"/>',
    "tasks": f'<path {_S} d="M9 6.5h11M9 12h11M9 17.5h11"/><path {_S} d="m3.8 6.5 1.3 1.3 2.2-2.4M3.8 12l1.3 1.3 2.2-2.4"/><circle {_S} cx="5.3" cy="17.5" r="1.4"/>',
    "language": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_S} d="M3.5 12h17M12 3.5c2.4 2.4 3.6 5.2 3.6 8.5S14.4 18.1 12 20.5M12 3.5C9.6 5.9 8.4 8.7 8.4 12s1.2 6.1 3.6 8.5"/>',
}


@lru_cache(maxsize=512)
def svg_bytes(name: str, color: str) -> bytes:
    body = PATHS.get(name, PATHS["file"]).replace("{c}", color)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'.encode()


@lru_cache(maxsize=1024)
def pixmap(name: str, color: str, size: int = 20, dpr: float = 2.0) -> QPixmap:
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    r = QSvgRenderer(QByteArray(svg_bytes(name, color)))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, size: int = 20, active: str | None = None) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    if active:
        ic.addPixmap(pixmap(name, active, size), QIcon.Mode.Normal, QIcon.State.On)
    return ic
