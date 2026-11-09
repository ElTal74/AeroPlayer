"""Preferencias persistentes (JSON atómico en la carpeta de datos)."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from aero.core.paths import data_dir, default_output_dir

DEFAULT_SHORTCUTS = {
    "open": "Ctrl+O",
    "play_pause": "Space",
    "next": "Ctrl+Right",
    "prev": "Ctrl+Left",
    "seek_fwd": "Right",
    "seek_back": "Left",
    "vol_up": "Up",
    "vol_down": "Down",
    "mute": "M",
    "fullscreen": "F11",
    "visualizer": "V",
    "shuffle": "S",
    "repeat": "R",
    "search": "Ctrl+F",
}

SHORTCUT_LABELS = {
    "open": "Abrir archivo",
    "play_pause": "Reproducir / pausar",
    "next": "Siguiente",
    "prev": "Anterior",
    "seek_fwd": "Avanzar 5 s",
    "seek_back": "Retroceder 5 s",
    "vol_up": "Subir volumen",
    "vol_down": "Bajar volumen",
    "mute": "Silenciar",
    "fullscreen": "Pantalla completa",
    "visualizer": "Visualizador",
    "shuffle": "Aleatorio",
    "repeat": "Repetir",
    "search": "Buscar",
}

DEFAULTS: dict = {
    "theme": "burbuja",
    "language": "",                  # código de aero.i18n.LANGUAGES; vacío = el de Windows
    "custom_colors": {},
    "user_themes": {},
    "theme_favorites": [],
    "glass_mode": "blur",
    "window_transparency": 0.6,
    "glass_intensity": 0.55,
    "reduce_motion": False,
    "background_motion": "on",       # fondo animado: on | reduced | static
    "visualizer_enabled": True,
    "visualizer_scene": 0,
    "visualizer_key": "glass_bars",
    "visualizer_favorites": [],
    "visualizer_intensity": 0.7,
    "visualizer_speed": 0.5,
    "visualizer_sensitivity": 0.5,
    "visualizer_palette": "theme",
    "visualizer_color": "#8fe3ff",
    "visualizer_fullscreen": False,
    "quicklook_visualizer": True,
    "update_check": True,            # buscar versiones nuevas en GitHub al iniciar (como mucho una vez al día)
    "update_last_check": 0.0,
    "update_skip": "",               # versión que el usuario decidió omitir
    "seen_version": "",              # última versión cuyas novedades vio el usuario («Novedades» tras actualizar)
    "photos_in_main": True,          # las fotos abiertas desde Windows van al visor de la ventana principal
    "assoc_version": 0,              # versión del registro de asociaciones de AERO (2 = iconos por categoría)
    "explorer_icons_foreign": False, # iconos AERO también en tipos que abren otros programas (lo activa el usuario)
    "open_office_in_editor": True,   # DOCX, XLSX, PPTX… desde Windows se abren en su editor
    "context_menu": True,
    "archive_format": "zip",         # formato por defecto al comprimir
    "archive_level": 5,
    "archive_auto_close": True,      # la ventana de progreso se cierra sola al terminar bien
    "torrent_enabled": True,         # BitTorrent: con False no se crea el motor (ni hilo ni conexiones)
    "torrent_folder": "",            # carpeta de descargas; vacío = Descargas del usuario
    "tutorial_done": False,          # el tutorial de bienvenida ya se vio (o se saltó)
    "quality_profile": "",           # ultra | balanced | high | custom | user:<nombre>; vacío = recomendar al iniciar
    "quality_custom": {},            # valores del perfil personalizado (aero.core.quality)
    "quality_user": {},              # perfiles guardados por el usuario: nombre → valores
    "quality_auto": False,           # optimización automática según la carga del equipo
    "motion_rest": True,             # el fondo animado se detiene sin actividad (3 min) o con batería
    "home_greetings": True,          # felicitar fechas especiales y estaciones en Inicio
    "home_seasonal": True,
    "home_widgets": [],              # widgets de Inicio: [{type, size, hidden, fields}] (aero.ui.home_widgets)
    "home_widgets_custom": False,    # False: distribución predeterminada
    "home_widgets_visible": True,
    "holiday_region": "auto",        # región de las fechas especiales (aero.core.seasons.REGIONS)
    "visualizer_low_power": False,
    "remember_position": True,
    "remember_volume": True,
    "volume": 0.8,
    "subtitle_scale": 1.0,
    "history_enabled": True,
    "library_folders": [],
    "library_excludes": [],
    "output_dir": str(default_output_dir()),
    "keep_structure": False,
    "max_parallel_jobs": 2,
    "use_hw_encoding": True,
    "ffmpeg_path": "",
    "soffice_path": "",
    "quicklook_enabled": False,
    "quicklook_hotkey": "Ctrl+Shift+Space",
    "quicklook_space_in_explorer": True,
    "close_to_tray": False,
    "autosave_drafts": True,
    "start_with_windows": False,
    "sidebar_collapsed": False,
    "viewer_remember_size": False,
    "viewer_last_size": [],
    "shortcuts": DEFAULT_SHORTCUTS,
    "window_geometry": "",
}


class Settings(QObject):
    changed = Signal(str)

    def __init__(self, path: Path | None = None):
        super().__init__()
        self.path = path or (data_dir() / "settings.json")
        self._data = deepcopy(DEFAULTS)
        self._load()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_now)

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))  # admite archivos con BOM (Bloc de notas)
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for k, v in raw.items():
            if k not in DEFAULTS:
                continue
            if type(DEFAULTS[k]) is float and isinstance(v, int):
                v = float(v)
            if type(v) is type(DEFAULTS[k]):
                self._data[k] = v
        shortcuts = dict(DEFAULT_SHORTCUTS)
        shortcuts.update({k: v for k, v in self._data["shortcuts"].items() if k in DEFAULT_SHORTCUTS})
        self._data["shortcuts"] = shortcuts

    def get(self, key: str):
        return self._data.get(key, DEFAULTS.get(key))

    def __getitem__(self, key: str):
        return self.get(key)

    def set(self, key: str, value) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self._save_timer.start()
        self.changed.emit(key)

    def reset(self) -> None:
        self._data = deepcopy(DEFAULTS)
        self.save_now()
        for k in DEFAULTS:
            self.changed.emit(k)

    def save_now(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass
