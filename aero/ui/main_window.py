"""Modo A — aplicación completa: carcasa de cristal, barra de iconos, páginas bajo demanda y reproductor integrado."""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QHBoxLayout, QLineEdit, QMessageBox,
                               QVBoxLayout, QWidget)

from aero import APP_NAME
from aero.core.formats import is_media, kind_of, open_dialog_filter
from aero.player.engine import PlayerEngine
from aero.ui.glass import FadeStack, GlassPanel, IconButton, Toast, h_layout, label, make_app_icon, tm
from aero.ui.glasswindow import DragArea, GlassWindow, kill_override_cursor
from aero.ui.player_bar import PlayerBar
from aero.ui.sidebar import _Indicator
from aero.ui.theme import build_qss
from aero.i18n import tr

PAGES = [
    ("home", "Inicio", "home"),
    ("library", "Biblioteca", "library"),
    ("files", "Archivos", "files"),
    ("paint", "Paint", "palette"),
    ("player", "Reproductor", "player"),
    ("viewer", "Visor", "viewer"),
    ("converter", "Conversor", "convert"),
    ("playlists", "Listas", "playlists"),
    ("settings", "Ajustes", "settings"),
]
PAGE_KEYS = [p[0] for p in PAGES]
PLAYER_ONLY = {"seek_fwd", "seek_back", "vol_up", "vol_down"}


def resolve_theme(settings):
    """Tema activo: prediseñado, personalizado antiguo («custom») o creado por el usuario («user:<id>»)."""
    from aero.ui.theme import custom_theme, get_theme, theme_from_spec

    key = settings.get("theme") or "burbuja"
    if key.startswith("user:"):
        spec = (settings.get("user_themes") or {}).get(key[5:])
        if isinstance(spec, dict):
            return theme_from_spec(key, spec)
        key = "burbuja"
    if key == "custom":
        return custom_theme(settings.get("custom_colors"))
    return get_theme(key)


_STYLE = None


def apply_theme(app: QApplication, settings) -> None:
    """Cambio de tema completo (colores): hoja de estilos, paleta e iconos. No se usa para los deslizadores."""
    global _STYLE
    from aero.ui.style import AeroStyle, sync_palette

    apply_quality(settings, emit=False)
    tm().apply(resolve_theme(settings), float(settings.get("glass_intensity")), settings.get("glass_mode"),
               float(settings.get("window_transparency")),
               bool(settings.get("reduce_motion")) or not tm().quality.get("transitions", True))
    from aero.ui import corners

    corners.install(app)  # redondeo uniforme de todas las ventanas, diálogos y menús
    if not isinstance(app.style(), AeroStyle):
        _STYLE = AeroStyle()
        app.setStyle(_STYLE)
    sync_palette(app)
    app.setStyleSheet(build_qss(tm().theme, settings.get("glass_mode") == "opaque"))


def apply_quality(settings, emit: bool = True) -> None:
    """Perfil de rendimiento y calidad visual (más la rebaja de la optimización automática, si la hay)."""
    from aero.core import quality
    from aero.ui import backdrop_fx
    from aero.ui.perf import auto_tuner

    q = quality.apply_auto(quality.resolve(settings), auto_tuner().step)
    backdrop_fx.MOTION.update(mode=settings.get("background_motion"),
                              os_reduced=backdrop_fx.os_prefers_reduced_motion())
    if emit:
        reduce = bool(settings.get("reduce_motion")) or not q["transitions"]
        if reduce != tm().reduce_motion:
            tm().reduce_motion = reduce
        tm().set_quality(q)
    else:
        tm().quality = dict(q)
        backdrop_fx.QUALITY = tm().quality
    from aero.core.tasks import tasks

    tasks().set_limits(q["background"], q["heavy"])


def apply_levels(settings) -> None:
    """Camino rápido: transparencia e intensidad del cristal (solo repinta)."""
    tm().set_levels(float(settings.get("glass_intensity")), float(settings.get("window_transparency")))


class Rail(QWidget):
    """Navegación discreta: solo iconos con píldora de gel animada (estilo Zen)."""
    navigate = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(52)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 6, 4, 6)
        lay.setSpacing(6)
        self.logo = IconButton("aero", APP_NAME, 26, button=44)
        self.logo.setIcon(QIcon(make_app_icon(64)))
        self.logo.clicked.connect(lambda: self.navigate.emit("home"))
        self.logo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.logo)
        lay.addSpacing(10)
        self.indicator = _Indicator(self)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, IconButton] = {}
        for key, text, ic in PAGES:
            b = IconButton(ic, text, 20, checkable=True, button=44)  # la ayuda emergente se traduce sola
            b.checked_bubble = False  # la selección la muestra la burbuja deslizante
            b.clicked.connect(lambda _c=False, k=key: self.navigate.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            if key == "settings":
                lay.addStretch(1)
            lay.addWidget(b)
        self._anim = QPropertyAnimation(self.indicator, b"geometry", self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self.current = "home"

    def select(self, key: str):
        self.current = key
        b = self.buttons.get(key)
        if not b:
            return
        b.setChecked(True)
        target = b.geometry()
        if tm().reduce_motion or self.indicator.geometry().isEmpty() or not self.isVisible():
            self.indicator.setGeometry(target)
        else:
            self._anim.stop()
            self._anim.setStartValue(self.indicator.geometry())
            self._anim.setEndValue(target)
            self._anim.start()
        self.indicator.show()
        self.indicator.lower()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self, lambda: self.indicator.setGeometry(self.buttons[self.current].geometry()))


class _IdleFilter(QObject):
    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress) and self.win.immersive:
            self.win.wake_controls()
        return False


class MainWindow(GlassWindow):
    def __init__(self, settings, db, controller=None):
        super().__init__()
        self.settings = settings
        self.db = db
        self.controller = controller
        self.immersive = False
        self.quitting = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(make_app_icon(256)))
        self.setMinimumSize(860, 560)
        self.setAcceptDrops(True)

        self.engine = PlayerEngine(settings, db, self)
        self._converter = None
        # Teclas multimedia: con la ventana activa siempre; en segundo plano (Windows) solo mientras suena algo
        from aero.player import media_keys

        self._media_keys = media_keys.MediaKeys(self._media_key, self)
        self._media_shortcuts = media_keys.install_shortcuts(self, self._media_key)
        self.engine.state_changed.connect(self._sync_media_keys)
        settings.changed.connect(self._media_keys_setting)    # método: se desconecta solo al cerrar la ventana
        # Barra de tareas de Windows: botones en la miniatura y progreso de las conversiones en el icono
        from aero.ui import taskbar

        self._taskbar = None
        self._taskbar_msg = taskbar.button_created_message()
        self.engine.state_changed.connect(self._update_thumb_buttons)
        self.engine.queue_changed.connect(self._update_thumb_buttons)

        # ------------------------------------------------------------ estructura
        self.rail = Rail()
        self.title = label("", "h2")
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Buscar en la biblioteca"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.addAction(tm().icon("search", 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.returnPressed.connect(self._global_search)
        self.search.textChanged.connect(self._live_search)
        self.queue_btn = IconButton("queue", tr("Cola de reproducción"), 18, checkable=True, button=34)
        self.queue_btn.clicked.connect(self._toggle_queue)
        self.top = DragArea()
        self.top.setFixedHeight(42)
        self.winbuttons = self.window_buttons()
        from aero.ui.task_center import TaskButton

        self.tasks_btn = TaskButton()
        self.find_btn = IconButton("search", tr("Buscar en todo AERO Player (Ctrl+K)"), 18, button=34)
        self.find_btn.clicked.connect(self.open_palette)
        self.top.setLayout(h_layout(8, self.title, None, self.search, 4, self.find_btn, 4, self.tasks_btn, self.queue_btn, 12,
                                    self.winbuttons,
                                    spacing=4, margins=(0, 0, 0, 0)))

        self.stage = GlassPanel(radius=14)
        self.stack = FadeStack()
        self.pages: dict[str, QWidget] = {}
        self._placeholders = {}
        for key in PAGE_KEYS:
            ph = QWidget()
            self._placeholders[key] = ph
            self.stack.addWidget(ph)
        self.stage_lay = QHBoxLayout(self.stage)
        self.stage_lay.setContentsMargins(14, 12, 14, 12)
        self.stage_lay.setSpacing(12)
        self.stage_lay.addWidget(self.stack, 1)

        self.bar = PlayerBar(self.engine, db)
        self.bar.setMaximumHeight(0)
        self._bar_anim = QPropertyAnimation(self.bar, b"maximumHeight", self)
        self._bar_anim.setDuration(240)
        self._bar_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.column = QVBoxLayout()
        self.column.setSpacing(8)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.addWidget(self.top)
        self.column.addWidget(self.stage, 1)
        self.column.addWidget(self.bar)
        self.root = QHBoxLayout(self.backdrop)
        self.root.setContentsMargins(10, 10, 10, 10)
        self.root.setSpacing(10)
        self.root.addWidget(self.rail)
        self.root.addLayout(self.column, 1)
        self.toast = Toast(self.backdrop)

        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(2600)
        self._idle.timeout.connect(self._hide_controls)
        QApplication.instance().installEventFilter(_IdleFilter(self))

        self._wire()
        self._build_shortcuts()
        geo = settings.get("window_geometry")
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
        else:
            self.resize(1320, 820)
        self.navigate("home")
        # Precalentamiento en reposo: las páginas pesadas se construyen tras el arranque, de una en una,
        # para que la primera visita sea instantánea sin retrasar la apertura de la ventana.
        self._warm = ["player", "library", "viewer", "playlists", "settings", "converter"]
        QTimer.singleShot(1200, self._warm_next)

    def _warm_next(self):
        while self._warm and self._warm[0] in self.pages:
            self._warm.pop(0)
        if not self._warm or not self.isVisible():
            return
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            QTimer.singleShot(400, self._warm_next)
            return
        self.page(self._warm.pop(0))
        QTimer.singleShot(250, self._warm_next)

    # ------------------------------------------------------------------ páginas bajo demanda
    @property
    def converter(self):
        if self._converter is None:
            from aero.core.converter import ConversionManager

            self._converter = ConversionManager(self.settings, self)
            self._converter.queue_idle.connect(self._conversions_idle)
            self._converter.job_changed.connect(self._taskbar_progress)
        return self._converter

    def page(self, key: str) -> QWidget:
        if key in self.pages:
            return self.pages[key]
        s, e, db = self.settings, self.engine, self.db
        if key == "home":
            from aero.ui.pages.home_page import HomePage

            w = HomePage(db, s)
            w.open_file.connect(self.open_dialog)
            w.go.connect(self.navigate)
            w.open_path.connect(lambda p: self.open_paths([p]))
            w.play_path.connect(lambda p: self.open_paths([p]))
            w.quicklook_toggle.connect(self._toggle_quicklook_from_home)
            w.tool.connect(self.run_tool)
            w.continue_watching.connect(self.play)
        elif key == "library":
            from aero.ui.pages.library_page import LibraryPage

            w = LibraryPage(db, s)
            w.play_paths.connect(self.play)
            w.enqueue_paths.connect(lambda paths, nxt: (e.enqueue(paths, nxt), self.notify(tr("Añadido a la cola"), "ok")))
            w.convert_paths.connect(self.convert)
            w.add_to_playlist.connect(lambda paths: self.page("playlists").choose_and_add(paths))
            w.message.connect(self.notify)
        elif key == "files":
            from aero.files.page import FilesPage

            w = FilesPage(db, s)
            w.open_file.connect(lambda p: self.open_paths([p]))
            w.preview.connect(lambda p: self.controller and self.controller.show_quicklook(p))
            w.action.connect(lambda a, paths: self.controller and self.controller.run_action(a, paths, immediate=True))
            w.message.connect(self.notify)
        elif key == "player":
            from aero.ui.pages.player_page import PlayerPage

            w = PlayerPage(e, s)
            w.fullscreen_requested.connect(self.toggle_fullscreen)
            w.close_requested.connect(self.close_media)
            w.queue.save_btn.clicked.connect(lambda: self.page("playlists").save_queue())
            self.bar.viz.setChecked(w.viz_on)
        elif key == "viewer":
            from aero.ui.viewers.host import ViewerHost

            w = ViewerHost()
            w.layout().setContentsMargins(0, 0, 0, 0)
            w.convert_requested.connect(lambda p: self.convert([p]))
            w.media_requested.connect(lambda p: self.play([p], 0))
            w.edit_requested.connect(lambda p: self.controller and self.controller.open_editor_for(p))
            w.pdf_convert_requested.connect(lambda p: self.controller and self.controller.open_pdf_convert(p))
            w.file_opened.connect(self._record_recent)
            w.close_requested.connect(self.close_document)
            self.viewer = w
        elif key == "paint":
            from aero.editors.paint.window import PaintEditor

            # El mismo AERO Paint que la ventana independiente, como apartado propio de la ventana principal.
            w = PaintEditor(controller=self.controller)
        elif key == "converter":
            from aero.ui.pages.converter_page import ConverterPage

            w = ConverterPage(self.converter, s)
            w.message.connect(self.notify)
        elif key == "playlists":
            from aero.ui.pages.playlists_page import PlaylistsPage

            w = PlaylistsPage(db, e)
            w.play_paths.connect(self.play)
            w.message.connect(self.notify)
        else:
            from aero.ui.pages.settings_page import SettingsPage

            w = SettingsPage(s)
            w.quicklook_changed.connect(lambda: self.controller and self.controller.sync_quicklook())
            w.shortcuts_changed.connect(self._build_shortcuts)
            w.clear_history.connect(self._clear_history)
            w.clear_all.connect(self._clear_all)
            w.rescan.connect(lambda: self.page("library").scan())
            w.tutorial.connect(self.start_tutorial)
            w.message.connect(self.notify)
        self.pages[key] = w
        from aero.i18n.widgets import translate_tree

        translate_tree(w)   # textos fijos que llegan por variables
        idx = PAGE_KEYS.index(key)
        ph = self._placeholders.pop(key)
        cur = self.stack.currentWidget()
        self.stack.insertWidget(idx, w)
        self.stack.removeWidget(ph)
        ph.deleteLater()
        if cur is not None and cur is not ph:
            self.stack.setCurrentWidget(cur)
        return w

    def _wire(self):
        s, e = self.settings, self.engine
        self.rail.navigate.connect(self.navigate)
        self.bar.open_player.connect(lambda: self.navigate("player"))
        self.bar.toggle_queue.connect(self._toggle_queue)
        self.bar.toggle_visualizer.connect(self.toggle_visualizer)
        self.bar.toggle_fullscreen.connect(self.toggle_fullscreen)
        self.bar.sub_options.connect(lambda: self.page("player").subtitle_dialog())
        self.bar.file_action.connect(self._file_action)
        self.bar.favorite_toggled.connect(lambda *_: "playlists" in self.pages and self.pages["playlists"].refresh())
        e.error.connect(lambda m: self.notify(m, "error"))
        e.played.connect(self._record_played)
        e.track_changed.connect(self._track_changed)
        e.state_changed.connect(lambda _s: self._update_title())
        s.changed.connect(self._setting_changed)

    def _setting_changed(self, key: str):
        if key == "visualizer_low_power" and "player" in self.pages:
            self.pages["player"].visualizer.set_low_power(bool(self.settings.get(key)))
        elif key == "visualizer_enabled":
            on = bool(self.settings.get(key))
            if "player" in self.pages and on != self.pages["player"].viz_on:
                self.pages["player"].set_visualizer(on)
            self.bar.viz.setChecked(on)
        elif key in ("close_to_tray", "quicklook_enabled", "home_greetings", "home_seasonal", "holiday_region") \
                and "home" in self.pages:
            self.pages["home"].refresh()

    # ------------------------------------------------------------------ navegación
    def navigate(self, key: str):
        if key not in PAGE_KEYS:
            return
        cur = self.current_page()
        if cur != key and cur not in ("player", "viewer"):
            self._came_from = cur  # para volver aquí al cerrar un vídeo o un documento
        w = self.page(key)
        self.rail.select(key)
        self.title.setText("" if key == "home" else tr(dict((k, t) for k, t, _ in PAGES)[key]))
        self.stack.fade_to(self.stack.indexOf(w))
        if key in ("home", "playlists"):
            w.refresh()
        self._update_shortcut_scope()
        self._sync_backdrop_motion()

    def _sync_backdrop_motion(self):
        """El fondo con movimiento se detiene mientras se ve un vídeo o el visualizador (que ya se animan)."""
        busy = False
        if self.current_page() == "player" and "player" in self.pages:
            pp = self.pages["player"]
            busy = pp.stack.currentWidget() in (pp.video, pp.visualizer)
        self.backdrop.set_paused(busy or self.immersive)

    def current_page(self) -> str:
        w = self.stack.currentWidget()
        for k, v in self.pages.items():
            if v is w:
                return k
        return "home"

    def _live_search(self, text: str):
        if "library" in self.pages:
            self.pages["library"].search.setText(text)

    def _global_search(self):
        lib = self.page("library")
        lib.search.setText(self.search.text())
        self.navigate("library")

    # ------------------------------------------------------------------ archivos
    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Abrir"), "", open_dialog_filter())
        if paths:
            self.open_paths(paths)

    def open_paths(self, paths: list[str]):
        paths = [os.path.abspath(p) for p in paths if p and os.path.exists(p)]
        if not paths:
            return
        if len(paths) == 1 and os.path.isdir(paths[0]) and getattr(self, "_browse_dirs", False):
            self._browse_dirs = False
            self.page("files").browse(paths[0])
            self.navigate("files")
            return
        files = [p for p in paths if os.path.isfile(p)]
        torrents = [p for p in files if p.lower().endswith(".torrent")]
        if torrents:
            from aero.torrent.ui import open_torrent

            for p in torrents:
                open_torrent(p, self)
            files = [p for p in files if p not in torrents]
        for d in (p for p in paths if os.path.isdir(p)):
            for root, _ds, fs in os.walk(d):
                files.extend(os.path.join(root, f) for f in sorted(fs) if is_media(f))
        media = [p for p in files if is_media(p)]
        others = [p for p in files if not is_media(p)]
        if media:
            self.play(media, 0)
        if others:
            self.page("viewer").open(others[0])
            if not media:
                self.navigate("viewer")

    def play(self, paths: list[str], start: int = 0):
        if not paths:
            return
        self.page("player")  # el vídeo necesita su superficie antes de empezar
        self.engine.play_files(paths, start)
        if kind_of(paths[start]) == "video" or self.current_page() in ("home", "viewer"):
            self.navigate("player")

    def convert(self, paths: list[str]):
        self.page("converter").add_paths(paths)
        self.navigate("converter")

    def _record_recent(self, path: str, kind: str):
        if self.settings.get("history_enabled"):
            self.db.add_recent(path, kind)

    def _record_played(self, path: str, title: str, artist: str):
        if self.settings.get("history_enabled"):
            self.db.add_played(path, title, artist)
            self.db.add_recent(path, kind_of(path))

    def _track_changed(self, info):
        self.backdrop.set_ambient(info.cover if info else None)
        self._show_bar(info is not None)
        QTimer.singleShot(0, self._sync_backdrop_motion)
        self._update_title()

    def _show_bar(self, on: bool):
        target = PlayerBar.HEIGHT if on else 0
        if self.bar.maximumHeight() == target:
            return
        if tm().reduce_motion:
            self.bar.setMaximumHeight(target)
            return
        self._bar_anim.stop()
        self._bar_anim.setStartValue(self.bar.maximumHeight())
        self._bar_anim.setEndValue(target)
        self._bar_anim.start()

    def _update_title(self):
        info = self.engine.current
        self.setWindowTitle(f"{info.display_title} · {APP_NAME}" if info else APP_NAME)

    def notify(self, text: str, kind: str = "info"):
        self.toast.show_message(text, kind)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if self.current_page() == "converter":
            self.page("converter").add_paths(paths)
        else:
            self.open_paths(paths)

    # ------------------------------------------------------------------ atajos
    def _build_shortcuts(self):
        for sc in getattr(self, "_shortcuts", {}).values():
            sc.setEnabled(False)
            sc.deleteLater()
        e = self.engine
        actions = {
            "open": self.open_dialog, "play_pause": e.toggle, "next": e.next, "prev": e.previous,
            "seek_fwd": lambda: e.seek_relative(5000), "seek_back": lambda: e.seek_relative(-5000),
            "vol_up": lambda: e.set_volume(e.audio.volume() + 0.05),
            "vol_down": lambda: e.set_volume(e.audio.volume() - 0.05),
            "mute": e.toggle_mute, "fullscreen": self.toggle_fullscreen, "visualizer": self.toggle_visualizer,
            "shuffle": lambda: e.set_shuffle(not e.shuffle), "repeat": e.cycle_repeat,
            "search": lambda: (self.search.setFocus(), self.search.selectAll()),
        }
        self._shortcuts = {}
        for name, seq in self.settings.get("shortcuts").items():
            if seq and name in actions:
                sc = QShortcut(QKeySequence(seq), self)
                sc.activated.connect(actions[name])
                self._shortcuts[name] = sc
        for i in range(len(PAGE_KEYS)):
            sc = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.activated.connect(lambda k=PAGE_KEYS[i]: self.navigate(k))
            self._shortcuts[f"page{i}"] = sc
        pal = QShortcut(QKeySequence("Ctrl+K"), self)
        pal.activated.connect(self.open_palette)
        self._shortcuts["palette"] = pal
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.activated.connect(lambda: self.immersive and self.toggle_fullscreen())
        self._shortcuts["esc"] = esc
        self._update_shortcut_scope()

    def _update_shortcut_scope(self):
        on_player = self.current_page() == "player" or self.immersive
        for name in PLAYER_ONLY:
            sc = getattr(self, "_shortcuts", {}).get(name)
            if sc is not None:
                sc.setEnabled(on_player)
        sc = getattr(self, "_shortcuts", {}).get("play_pause")
        if sc is not None:
            sc.setEnabled(self.current_page() != "viewer")

    # ------------------------------------------------------------------ reproductor
    def toggle_visualizer(self):
        pp = self.page("player")
        on = not pp.viz_on
        pp.set_visualizer(on)
        self.bar.viz.setChecked(on)
        if on and self.engine.current and self.engine.current.kind == "audio":
            self.navigate("player")
            if self.settings.get("visualizer_fullscreen") and not self.immersive:
                self.toggle_fullscreen()
        self._sync_backdrop_motion()

    def _toggle_queue(self):
        q = self.page("player").queue
        vis = not q.isVisible()
        q.setVisible(vis)
        self.queue_btn.setChecked(vis)
        self.bar.queue_btn.setChecked(vis)
        if vis:
            self.navigate("player")

    def toggle_fullscreen(self):
        pp = self.page("player")
        self.immersive = not self.immersive
        if self.immersive:
            self._was_max = self.isMaximized()
            self.navigate("player")
            for w in (self.rail, self.top):
                w.hide()
            self.root.setContentsMargins(0, 0, 0, 0)
            self.stage_lay.setContentsMargins(0, 0, 0, 0)
            pp.set_immersive(True)
            self.showFullScreen()
            self.wake_controls()
        else:
            self._idle.stop()
            for w in (self.rail, self.top):
                w.show()
            self.bar.show()
            self.root.setContentsMargins(10, 10, 10, 10)
            self.stage_lay.setContentsMargins(14, 12, 14, 12)
            pp.set_immersive(False)
            kill_override_cursor()
            if getattr(self, "_was_max", False):
                self.showMaximized()
            else:
                self.showNormal()
        self.bar.set_fullscreen_icon(self.immersive)
        self._update_shortcut_scope()
        self._sync_backdrop_motion()

    def wake_controls(self):
        if not self.bar.isVisible():
            self.bar.show()
        kill_override_cursor()
        self._idle.start()

    def _hide_controls(self):
        if self.immersive and not self.bar.underMouse():
            self.bar.hide()
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BlankCursor))

    # ------------------------------------------------------------------ varios
    def _file_action(self, action: str, path: str):
        from aero.ui import file_actions

        file_actions.run(self.controller, action, path, self)

    def close_media(self):
        """Cierra solo lo que se está reproduciendo y vuelve a donde estabas (la aplicación sigue abierta)."""
        if self.immersive:
            self.toggle_fullscreen()
        self.engine.save_position()
        self.engine.clear_queue()
        self.navigate(getattr(self, "_came_from", "") or "library")

    def close_document(self):
        if "viewer" in self.pages:
            self.pages["viewer"].clear()
        self.navigate(getattr(self, "_came_from", "") or "files")

    def open_palette(self):
        """Búsqueda universal: herramientas, ajustes, biblioteca, recientes, tareas y archivos."""
        if getattr(self, "cmd_palette", None) is None:
            from aero.ui.command_palette import CommandPalette

            self.cmd_palette = CommandPalette(self)
        self.cmd_palette.popup()

    def start_tutorial(self):
        """Recorrido guiado por la aplicación (primera vez o desde Ajustes)."""
        from aero.ui.tutorial import Tutorial

        if getattr(self, "tutorial", None) is not None or self.immersive or not self.isVisible():
            return
        self.tutorial = Tutorial(self, self.settings)
        self.tutorial.finished.connect(self._tutorial_done)
        self.tutorial.start()

    def _tutorial_done(self, completed: bool):
        self.tutorial = None
        if not completed:
            self.notify(tr("Puedes ver el tutorial cuando quieras en Ajustes › Inicio"), "info")

    def run_tool(self, key: str):
        """Menú «Crear» de Inicio: editores vacíos, edición de imagen, PDF editable y comprimidos."""
        ctl = self.controller
        if ctl is None:
            return
        simple = {"new_document": ctl.open_document_editor, "new_sheet": ctl.open_sheet_editor,
                  "new_slides": ctl.open_slides_editor, "new_video": ctl.open_video_editor,
                  "pdf_convert": ctl.open_pdf_convert}
        if key == "paint":
            self.navigate("paint")   # apartado propio de la barra lateral
        elif key in simple:
            simple[key]()
        elif key == "edit_image":
            from aero.core.formats import IMAGE

            pat = " ".join(f"*{e}" for e in sorted(IMAGE))
            path, _ = QFileDialog.getOpenFileName(self, tr("Editar una imagen"), "", f"Imágenes ({pat})")
            if path:
                ctl.open_image_editor(path)
        elif key == "compress":
            paths, _ = QFileDialog.getOpenFileNames(self, tr("Archivos que comprimir"), "")
            if paths:
                ctl.run_action("compress", paths)
        elif key == "open_archive":
            from aero.core.formats import ARCHIVE

            pat = " ".join(f"*{e}" for e in sorted(ARCHIVE))
            path, _ = QFileDialog.getOpenFileName(self, tr("Abrir un comprimido"), "", f"Comprimidos ({pat})")
            if path:
                ctl.run_action("open_archive", [path])

    def _toggle_quicklook_from_home(self):
        on = not self.settings.get("quicklook_enabled")
        self.settings.set("quicklook_enabled", on)
        if self.controller:
            self.controller.sync_quicklook()
        hk = self.settings.get("quicklook_hotkey")
        self.notify(tr("Vista rápida activada · Espacio en el Explorador o {hk}", hk=hk) if on else tr("Vista rápida desactivada"),
                    "ok")

    def show_window(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _clear_history(self):
        self.db.clear_history()
        for k in ("home", "playlists"):
            if k in self.pages:
                self.pages[k].refresh()
        self.notify(tr("Historial borrado"), "ok")

    def _clear_all(self):
        self.engine.clear_queue()
        self.db.clear_all()
        self.settings.reset()
        for k in ("home", "library", "playlists"):
            if k in self.pages:
                self.pages[k].refresh()
        self.notify(tr("Datos borrados"), "ok")

    def _conversions_idle(self):
        if self._converter and self._converter.jobs and not self.isActiveWindow() and self.controller:
            self.controller.tray_message("Conversiones terminadas")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast._reposition()

    def closeEvent(self, e):
        tray = self.controller is not None and self.controller.tray_active()
        if not self.quitting and tray:
            e.ignore()
            self.hide()
            if self.engine.current and self.engine.current.kind == "video":
                self.engine.player.pause()
            return
        if self._converter is not None and self._converter.busy() and not self.quitting:
            r = QMessageBox.question(self, tr("Conversiones en curso"), tr("Si cierras se cancelarán. ¿Cerrar?"))
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
        paint = self.pages.get("paint")
        if paint is not None and not self.quitting:
            if not paint.can_close():
                e.ignore()
                return
            paint.doc.dirty = False   # el usuario aceptó descartar: sin borrador pendiente
        self.shutdown()
        e.accept()
        if self.controller:
            self.controller.main_closed(self)

    def _media_key(self, name: str) -> None:
        if name == "play_pause":
            self.engine.toggle()
        elif name == "next":
            self.engine.next()
        elif name == "previous":
            self.engine.previous()
        elif name == "stop":
            self.engine.stop()

    # ------------------------------------------------------------------ barra de tareas (Windows)
    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            from aero.ui import taskbar

            name = taskbar.clicked_button(message)
            if name:
                self._media_key(name)
                return True, 0
            from ctypes import wintypes

            if wintypes.MSG.from_address(int(message)).message == self._taskbar_msg:
                self._update_thumb_buttons()
        return super().nativeEvent(event_type, message)

    def _tb(self):
        if self._taskbar is None:
            from aero.ui import taskbar

            self._taskbar = taskbar.Taskbar()
        return self._taskbar

    def _update_thumb_buttons(self, *_):
        if os.name != "nt" or not self.isVisible():
            return
        self._tb().set_buttons(int(self.winId()), self.engine.playing, bool(self.engine.queue))

    def _taskbar_progress(self, _jid=None) -> None:
        if os.name != "nt" or self._converter is None:
            return
        done, total, prog = self._converter.overall()
        self._tb().set_progress(int(self.winId()), prog if total and done < total else None)

    def _media_keys_setting(self, key: str) -> None:
        if key == "media_keys":
            self._sync_media_keys(int(self.engine.player.playbackState().value))

    def _sync_media_keys(self, state: int) -> None:
        # 1 = reproduciendo, 2 = en pausa; detenido (0) suelta las teclas para el resto de aplicaciones
        self._media_keys.set_active(bool(self.settings.get("media_keys")) and state in (1, 2))

    def shutdown(self):
        self._media_keys.set_active(False)
        self.settings.set("window_geometry", bytes(self.saveGeometry().toBase64()).decode())
        self.engine.save_position()
        self.engine.stop()
        self.engine.dispose()            # salidas desconectadas antes de destruir la ventana (Linux y macOS)
        if self._converter is not None:
            self._converter.cancel_all()
        if "library" in self.pages:
            self.pages["library"].stop_scan()
        paint = self.pages.get("paint")
        if paint is not None and not paint.doc.dirty:
            paint.autosaver.stop()   # con cambios sin guardar el borrador se queda para recuperarlo
        self.settings.save_now()

    def quit_app(self):
        self.quitting = True
        if self.controller:
            self.controller.quit()
        else:
            self.close()
