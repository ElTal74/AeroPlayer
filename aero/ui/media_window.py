"""Modo B (visor minimalista) y Modo C (Quick Look): una ventana de cristal centrada en el contenido.

* Imagen: la imagen ocupa toda la ventana; controles flotantes que se ocultan solos.
* Vídeo: el vídeo ocupa toda la ventana con su proporción; controles flotantes, subtítulos y volumen.
* Audio: reproductor compacto con portada, visualizador y controles.
* PDF / documentos / hojas / presentaciones: visor limpio con su barra de herramientas.
La ventana se dimensiona según el contenido y el monitor donde se abre.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QLinearGradient, QPainter, QShortcut, QColor
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMenu, QSizePolicy, QSlider, QStackedWidget,
                               QVBoxLayout, QWidget)

from aero.i18n import tr
from aero.core.formats import AUDIO, human_size, human_time, kind_of
from aero.core.geometry import fit_window, keep_aspect
from aero.core.series import folder_episodes
from aero.ui.glass import (ClickSlider, CoverArt, GlassPanel, IconButton, PlayButton, h_layout, label, opaque_video,
                           tm, transport_row, v_layout)
from aero.ui.glasswindow import RADIUS, DragArea, GlassWindow, OverlayWindow, kill_override_cursor
from aero.ui.async_util import run_async

WM_SIZING = 0x0214


class ElideLabel(QLabel):
    """Etiqueta de una línea que se acorta con «…» cuando no cabe (y enseña el texto entero al pasar el ratón)."""

    def __init__(self, role: str | None = None, mode=Qt.TextElideMode.ElideRight, parent=None):
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def setText(self, text: str) -> None:
        self._full = text or ""
        self._elide()

    def text(self) -> str:
        return self._full

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(self._full, self._mode, max(0, self.width()))
        super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def minimumSizeHint(self):
        h = super().minimumSizeHint()
        h.setWidth(0)
        return h


class _Shade(DragArea):
    """Barra superior flotante con degradado oscuro: título, información y botones."""

    def paintEvent(self, e):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainterPath

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(0, 8, 20, 150))
        g.setColorAt(1, QColor(0, 8, 20, 0))
        # La capa de controles es otra ventana: Windows no la redondea. El degradado se recorta con el mismo
        # radio que la ventana (salvo a pantalla completa) para no dejar picos oscuros en las esquinas.
        win = self.window().parent()
        square = win is not None and (win.isFullScreen() or win.isMaximized())
        r = 0 if square else RADIUS
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0, 0, 0, r), r, r)
        p.fillPath(path, g)


class _Pill(GlassPanel):
    """Cápsula de controles: cristal oscuro (vive en una capa sin desenfoque propio)."""

    def paintEvent(self, e):
        from PySide6.QtCore import QRectF

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)   # trazo de 1 px nítido en todo el borde
        rad = min(r.height() / 2, 26.0)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(40, 70, 105, 225))
        g.setColorAt(0.5, QColor(14, 34, 60, 225))
        g.setColorAt(1, QColor(10, 26, 48, 235))
        p.setBrush(g)
        p.setPen(QColor(255, 255, 255, 100))
        p.drawRoundedRect(r, rad, rad)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor(255, 255, 255, 28))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rad - 1, rad - 1)


class _Activity(QObject):
    def __init__(self, win: "MediaWindow"):
        super().__init__(win)
        self.win = win

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel) \
                and isinstance(obj, QWidget) and obj.window() in (self.win, self.win.overlay):
            self.win.wake()
        elif t == QEvent.Type.Leave and obj in (self.win, self.win.overlay):
            self.win.pointer_left()
        return False


class MediaWindow(GlassWindow):
    closed = Signal()
    IDLE_MS = 1500          # quieto este tiempo → los controles se desvanecen
    LEAVE_MS = 500          # el puntero sale de la ventana → se ocultan antes
    PILL_H = 52             # una fila (imagen)
    PILL_MEDIA_H = 94       # progreso + controles (audio y vídeo)

    def __init__(self, settings, db, controller=None, quicklook: bool = False):
        flags = Qt.WindowType.WindowStaysOnTopHint if quicklook else Qt.WindowType(0)
        super().__init__(flags, flat=True)
        self.settings, self.db, self.controller = settings, db, controller
        self.quicklook = quicklook
        self.path = ""
        self.kind = ""
        self.aspect = 0.0
        self.engine = None
        self._sized_for_video = False
        self._placed = False
        self.setMinimumSize(360, 240)
        if not quicklook:
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAcceptDrops(True)

        self.stack = QStackedWidget()
        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.stack)
        # Al cambiar de contenido (foto, vídeo con su superficie nativa…) se vuelve a recortar con esquinas redondas
        self.stack.currentChanged.connect(lambda _i: QTimer.singleShot(0, self._round_content))

        # Capa de controles: ventana transparente propia encima del contenido. El vídeo de Qt usa una
        # superficie nativa (GPU) que taparía a cualquier widget hermano; una ventana superpuesta no.
        # Sus píxeles vacíos son transparentes a los clics, así que el contenido sigue siendo interactivo.
        self.overlay = OverlayWindow(self, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                               | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.overlay.drag_target = self
        self.shade = _Shade(self.overlay)
        # Nombre y datos: se acortan con puntos suspensivos; nunca empujan ni tapan los botones
        self.name = ElideLabel("h3", Qt.TextElideMode.ElideMiddle)
        self.name.setStyleSheet("color: white;")
        self.info = ElideLabel("caption", Qt.TextElideMode.ElideRight)
        self.info.setStyleSheet("color: rgba(255,255,255,0.75);")
        self.btn_back = IconButton("back", tr("Volver (Retroceso)"), 16, button=32)
        self.btn_back.clicked.connect(self.go_back)
        self.btn_back.hide()
        self._history: list[tuple[str, str, str]] = []   # (raíz, ubicación, archivo abierto) para «Volver»
        self.btn_app = IconButton("external", tr("Abrir en AERO Player (Intro)"), 16, button=32)
        self.btn_app.clicked.connect(self.open_in_app)
        # Acciones visibles según el tipo (Editar, Recortar, Convertir, Extraer…): sin menús escondidos
        from aero.ui.file_actions import ActionBar

        self.actions_bar = ActionBar(dark=True)
        self.actions_bar.triggered.connect(self._file_action)
        self.btn_full = IconButton("fullscreen", tr("Pantalla completa (F)"), 16, button=32)
        self.btn_full.clicked.connect(self.toggle_fullscreen)
        self.winbtns = self.window_buttons(maximize=not quicklook)
        if quicklook:
            self.winbtns.min.hide()
        for b in (self.btn_app, self.btn_full):
            b.setIcon(b.icon())
        self._titles = QWidget()
        self._titles.setLayout(v_layout(self.name, self.info, spacing=0))
        self._titles.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        head = h_layout(8, self.btn_back, 6, self._titles, 6, self.actions_bar, 6, self.btn_app, self.btn_full,
                        8, self.winbtns, spacing=2, margins=(0, 8, 10, 18))
        head.setStretchFactor(self._titles, 1)
        self.shade.setLayout(head)

        # Cápsula inferior (flotante)
        # Cápsula inferior (flotante): fila de progreso opcional + fila de controles.
        self.pill = _Pill(self.overlay)
        root = QVBoxLayout(self.pill)
        root.setContentsMargins(14, 6, 14, 6)
        root.setSpacing(0)
        self.pill_top = QHBoxLayout()
        self.pill_top.setSpacing(10)
        self.pill_lay = QHBoxLayout()
        self.pill_lay.setSpacing(4)
        root.addLayout(self.pill_top)
        root.addLayout(self.pill_lay)
        self._fade = QPropertyAnimation(self.overlay, b"windowOpacity", self)

        # Ocultado automático: un solo temporizador que se reinicia con la actividad (sin sondeo).
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(self.IDLE_MS)
        self._idle.timeout.connect(self._hide_controls)
        self._activity = _Activity(self)
        QApplication.instance().installEventFilter(self._activity)
        self._controls_visible = True
        self._views: dict[str, QWidget] = {}
        self._restore = None
        self._shortcuts()

    # ------------------------------------------------------------------ apertura
    def open(self, path: str, playlist: list[str] | None = None, _nav: bool = False) -> None:
        if not _nav:
            self._history.clear()
            if "browse" in self._views:
                self._views["browse"].cleanup()
        self._stop_media()
        self.path = os.path.abspath(path)
        self.kind = "folder" if os.path.isdir(self.path) else kind_of(self.path)
        p = Path(self.path)
        self.name.setText(p.name)
        self.setWindowTitle(tr("{name} · AERO Player", name=p.name))
        try:
            size = "" if self.kind == "folder" else human_size(p.stat().st_size)
        except OSError:
            size = ""
        self.info.setText(size)
        self.btn_back.setVisible(bool(self._history))
        for k in self._viewer_keys:
            k.setEnabled(self.kind not in ("folder", "archive"))
        self._watch_first_frame()
        self.aspect = 0.0
        self.btn_full.setVisible(self.kind in ("image", "video", "slides", "pdf"))
        self.actions_bar.set_path(self.path)
        self._fit_header(self.width())
        self._clear_pill()
        if self.kind == "image":
            self._open_image()
        elif self.kind in ("folder", "archive"):
            self._open_browser()
        elif self.kind in ("video", "audio"):
            self._open_media(playlist)
        else:
            self._open_document()
        self.show()
        self.raise_()
        self.activateWindow()
        if self.quicklook:
            from aero.quicklook.window import force_foreground

            force_foreground(int(self.winId()))
        self.wake()

    def _view(self, key: str, factory) -> QWidget:
        if key not in self._views:
            w = factory()
            self._views[key] = w
            self.stack.addWidget(w)
        w = self._views[key]
        self.stack.setCurrentWidget(w)
        return w

    # ------------------------------------------------------------------ imagen
    def _open_image(self):
        from aero.ui.viewers.image_viewer import ImageViewer, load_qimage

        iv = self._view("image", ImageViewer)
        if not hasattr(iv, "_wired"):
            iv._wired = True
            iv.zoom_changed.connect(lambda z: self._zoom_lbl.setText(f"{z * 100:.0f} %"))
        self._floating(True)
        self._zoom_lbl = label("100 %", "caption")
        self._zoom_lbl.setMinimumWidth(44)
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (self._btn("left", "Anterior (←)", lambda: self._sibling(-1)),
                  self._btn("zoom_out", "Alejar (−)", lambda: iv.zoom(1 / 1.25)), self._zoom_lbl,
                  self._btn("zoom_in", "Acercar (+)", lambda: iv.zoom(1.25)),
                  self._btn("fit", "Ajustar (0)", iv.fit), self._btn("search", "Tamaño real (1)", iv.actual_size),
                  self._btn("rotate_left", "Girar a la izquierda", lambda: iv.rotate_by(-90)),
                  self._btn("rotate", "Girar a la derecha (R)", lambda: iv.rotate_by(90)),
                  self._btn("right", "Siguiente (→)", lambda: self._sibling(1)),
                  self._btn("edit", "Editar la imagen (E)", self.edit_image)):
            self.pill_lay.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        path = self.path

        def done(img):
            if path != self.path:
                return
            iv.set_image(path, img)
            self.info.setText(tr("{v0} × {v1} px · {v2}", v0=img.width(), v1=img.height(), v2=self.info.text()))
            self._resize_for(img.width(), img.height(), upscale=False)
            iv.fit()

        def fail(err):
            if path == self.path:
                self.info.setText(tr("No se puede mostrar: {err}", err=err))

        run_async(lambda: load_qimage(path), done, fail, self)

    def edit_current(self):
        """Abre el archivo en su editor (en un PDF: la conversión a documento editable)."""
        if not self.path or self.controller is None:
            return
        path = self.path
        if self.quicklook:
            self.close_preview()
        self.controller.open_editor_for(path)

    def _file_action(self, key: str):
        from aero.ui import file_actions

        path = self.path
        if not path:
            return
        if key in ("edit", "crop", "paint", "convert") and self.quicklook:
            self.close_preview()
        if key in ("edit", "crop") and self.engine is not None:
            self.engine.player.pause()  # el editor se abre con el vídeo parado
        file_actions.run(self.controller, key, path, self)

    def edit_image(self):
        if self.kind != "image" or not self.path or self.controller is None:
            return
        path = self.path
        if self.quicklook:
            self.close_preview()
        self.controller.open_image_editor(path)

    def _sibling(self, step: int):
        iv = self._views.get("image")
        if iv is not None:
            nxt = iv.neighbor(step)
            if nxt:
                self.path = nxt
                self.name.setText(Path(nxt).name)
                try:
                    self.info.setText(human_size(Path(nxt).stat().st_size))
                except OSError:
                    pass
                from aero.ui.viewers.image_viewer import load_qimage

                run_async(lambda: load_qimage(nxt), lambda img: nxt == self.path and (
                    iv.set_image(nxt, img), self.info.setText(tr("{v0} × {v1} px · {v2}", v0=img.width(), v1=img.height(), v2=self.info.text()))),
                    None, self)

    # ------------------------------------------------------------------ vídeo y audio
    def _open_media(self, playlist):
        from aero.player.engine import PlayerEngine

        if self.engine is None:
            self.engine = PlayerEngine(self.settings, self.db, self)
            self.engine.error.connect(lambda m: self.info.setText(m))
            self.engine.track_changed.connect(self._track_changed)
            self.engine.position_changed.connect(self._position)
            self.engine.duration_changed.connect(self._duration)
            self.engine.state_changed.connect(lambda _s: self._play.set_playing(self.engine.playing))
            self.engine.played.connect(self._record_played)
        e = self.engine
        if playlist is None:
            if self.kind == "video":
                playlist = folder_episodes(self.path)  # siguiente episodio automático
            else:
                folder = Path(self.path).parent
                try:
                    playlist = sorted((str(f) for f in folder.iterdir() if f.suffix.lower() in AUDIO),
                                      key=str.lower)
                except OSError:
                    playlist = [self.path]
                if self.path in playlist:
                    playlist = playlist[playlist.index(self.path):]
                else:
                    playlist = [self.path]
        self._play = PlayButton(size=38)
        self._play.clicked.connect(e.toggle)
        self._seek = ClickSlider()
        self._seek.setMinimumWidth(80)
        self._seek.setAccessibleName(tr("Progreso"))
        self._seek.seek_requested.connect(e.seek)
        self._seek.sliderMoved.connect(lambda v: self._elapsed.setText(human_time(v / 1000)))
        # Tiempos con anchura fija (calculada para «0:00:00»): el progreso nunca salta ni se solapa.
        self._elapsed = label("0:00", "caption")
        self._total = label("--:--", "caption")
        fm = self._elapsed.fontMetrics()
        tw = fm.horizontalAdvance("0:00:00") + 6
        for lb, al in ((self._elapsed, Qt.AlignmentFlag.AlignRight), (self._total, Qt.AlignmentFlag.AlignLeft)):
            lb.setFixedWidth(tw)
            lb.setAlignment(al | Qt.AlignmentFlag.AlignVCenter)
            lb.setStyleSheet("color: rgba(255,255,255,0.82);")
        self._vol = ClickSlider()
        self._vol.setRange(0, 100)
        self._vol.setFixedWidth(84)
        self._vol.setAccessibleName(tr("Volumen"))
        self._vol.setValue(int(e.audio.volume() * 100))
        self._vol.valueChanged.connect(lambda v: e.set_volume(v / 100))
        mute = self._btn("volume", "Silenciar (M)", e.toggle_mute)
        self.pill_top.addWidget(self._elapsed)
        self.pill_top.addWidget(self._seek, 1)
        self.pill_top.addWidget(self._total)
        left: list = []
        if self.kind == "video":
            video = self._view("video", self._make_video)
            e.player.setVideoOutput(video)
            self._floating(True)
            subs = self._btn("subtitles", "Subtítulos y audio", None)
            subs.setPopupMode(subs.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(subs)
            menu.aboutToShow.connect(lambda: self._subs_menu(menu))
            subs.setMenu(menu)
            left = [subs]
        else:
            self._view("audio", self._make_audio)
            self._floating(False)
            left = [self._viz_button()]
        side = 44 * max(1, len(left))
        lw = QWidget()
        lw.setFixedWidth(max(side, 130))
        lw.setLayout(h_layout(*left, None, spacing=2))
        rw = QWidget()
        rw.setFixedWidth(130)
        rw.setLayout(h_layout(None, mute, self._vol, spacing=2))
        self._side_widgets = (lw, rw)
        self.pill_lay.addWidget(lw)
        self.pill_lay.addWidget(transport_row(None, self._btn("prev", "Anterior", e.previous), self._play,
                                              self._btn("next", "Siguiente", e.next), None, spacing=6), 1)
        self.pill_lay.addWidget(rw)
        if self.kind == "video":
            self._apply_size(*self._size_doc(0.55, 0.55))
        else:
            self._apply_size(400, 640, keep_center=True)
            self._audio_viz.start()
            e.set_analysis(True)
        e.play_files(playlist, 0)

    def _make_video(self):
        v = QVideoWidget()
        v.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        opaque_video(v)
        self._frame_sink = v.videoSink()
        self._frame_sink.videoFrameChanged.connect(self._first_frame)
        self._frame_watch = True
        v.mouseDoubleClickEvent = lambda e: self.toggle_fullscreen()
        return v

    def _watch_first_frame(self) -> None:
        """Vuelve a escuchar el primer fotograma (para ajustar la ventana) de un vídeo nuevo."""
        self._sized_for_video = False
        sink = getattr(self, "_frame_sink", None)
        if sink is not None and not getattr(self, "_frame_watch", False):
            sink.videoFrameChanged.connect(self._first_frame)
            self._frame_watch = True

    def _unwatch_first_frame(self) -> None:
        sink = getattr(self, "_frame_sink", None)
        if sink is not None and getattr(self, "_frame_watch", False):
            self._frame_watch = False
            try:
                sink.videoFrameChanged.disconnect(self._first_frame)
            except (RuntimeError, TypeError):
                pass

    def _first_frame(self, frame):
        if self._sized_for_video or not frame.isValid():
            return
        size = frame.size()
        if size.width() > 0 and size.height() > 0:
            self._sized_for_video = True
            self._unwatch_first_frame()            # ya se sabe el tamaño: sin una llamada a Python por fotograma
            self.aspect = size.width() / size.height()
            self.info.setText(f"{size.width()} × {size.height()} · {self.info.text()}")
            self._resize_for(size.width(), size.height(), upscale=True)

    def _make_audio(self):
        from aero.ui.visualizer import Visualizer

        w = QWidget()
        self._cover = CoverArt(240, 18)
        self._title = label("", "h2")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        self._artist = label("", "muted")
        self._artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._audio_viz = Visualizer(self.engine.analyzer)
        self._audio_viz.configure(self.settings)
        self._audio_viz.set_scene_key(self.settings.get("visualizer_key"))
        self._audio_viz.setFixedHeight(110)
        self._audio_viz.setVisible(bool(self.settings.get("quicklook_visualizer")))
        self._title.setMaximumHeight(60)
        w.setLayout(v_layout(54, h_layout(None, self._cover, None), 14, self._title, self._artist, None,
                             self._audio_viz, self.PILL_MEDIA_H + 22, spacing=4, margins=(22, 0, 22, 0)))
        return w

    def _viz_button(self) -> IconButton:
        """Selector compacto de visualizadores para la vista rápida de audio (favoritos primero)."""
        from aero.ui.visualizer import SCENE_KEYS, SCENE_NAMES

        b = self._btn("visualizer", "Visualizador", None)
        b.setPopupMode(b.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(b)

        def build():
            menu.clear()
            cur = self.settings.get("visualizer_key")
            on = bool(self.settings.get("quicklook_visualizer"))
            off = menu.addAction(tr("Sin visualizador"))
            off.setCheckable(True)
            off.setChecked(not on)
            off.triggered.connect(lambda: self._set_ql_viz(None))
            menu.addSeparator()
            favs = [k for k in self.settings.get("visualizer_favorites") if k in SCENE_KEYS]
            for k in favs + [k for k in SCENE_KEYS if k not in favs]:
                a = menu.addAction(("★ " if k in favs else "") + SCENE_NAMES[k])
                a.setCheckable(True)
                a.setChecked(on and k == cur)
                a.triggered.connect(lambda _c=False, key=k: self._set_ql_viz(key))

        menu.aboutToShow.connect(build)
        b.setMenu(menu)
        return b

    def _set_ql_viz(self, key):
        """Cambia de visualizador sin tocar la reproducción (el análisis de audio sigue igual)."""
        on = key is not None
        self.settings.set("quicklook_visualizer", on)
        if on:
            self.settings.set("visualizer_key", key)
            self._audio_viz.set_scene_key(key)
        self._audio_viz.setVisible(on)
        if on and not self._audio_viz.active:
            self._audio_viz.start()
        elif not on:
            self._audio_viz.stop()

    def _track_changed(self, info):
        if info is None:
            return
        self.name.setText(Path(info.path).name)
        self.path = info.path
        if self.kind == "audio" and hasattr(self, "_cover"):
            self._cover.placeholder = "music"
            self._cover.set_image(info.cover)
            self._title.setText(info.display_title)
            self._artist.setText(" · ".join(x for x in (info.artist, info.album) if x))
            self._audio_viz.set_caption("")
            self.backdrop.set_ambient(info.cover)
        else:
            self._watch_first_frame()  # el siguiente episodio puede tener otra proporción

    def _duration(self, d: int):
        self._seek.setRange(0, max(0, d))
        self._total.setText(human_time(d / 1000) if d > 0 else "--:--")

    def _position(self, ms: int):
        if not self._seek.isSliderDown():
            self._seek.setValue(ms)
            self._elapsed.setText(human_time(ms / 1000))

    def _subs_menu(self, menu: QMenu):
        e = self.engine
        menu.clear()
        off = menu.addAction(tr("Sin subtítulos"))
        off.triggered.connect(lambda: (e.set_subtitle_track(-1), setattr(e, "ext_subs", None), e._set_sub_text("")))
        for i, name in enumerate(e.subtitle_tracks()):
            menu.addAction(name, lambda k=i: e.set_subtitle_track(k))
        if e.ext_subs is not None:
            menu.addAction(f"✓ {e.ext_subs.name}")
        audios = e.audio_tracks()
        if len(audios) > 1:
            menu.addSeparator()
            for i, name in enumerate(audios):
                menu.addAction(tr("Audio · {name}", name=name), lambda k=i: e.set_audio_track(k))
        if not hasattr(self, "_sub_wired"):
            self._sub_wired = True
            e.subtitle_text.connect(lambda t: self._views["video"].videoSink().setSubtitleText(t))

    def _record_played(self, path, title, artist):
        if self.settings.get("history_enabled"):
            self.db.add_played(path, title, artist)

    # ------------------------------------------------------------------ carpetas y comprimidos
    def _make_browser(self):
        from aero.files.browser import FolderBrowser

        b = FolderBrowser(compact=True)
        b.layout().setContentsMargins(16, 58, 16, 10)
        b.open_requested.connect(self._open_inside)
        b.location_changed.connect(self._browser_moved)
        return b

    def _open_browser(self):
        b = self._view("browse", self._make_browser)
        self._floating(False, pill=False)
        self.info.setText(tr("Carpeta") if self.kind == "folder" else tr("Archivo comprimido · ") + self.info.text())
        if self._restore is not None:
            b.restore(*self._restore)
            self._restore = None
        else:
            b.set_root(self.path)
        QTimer.singleShot(0, b.view.setFocus)  # tras activarse la ventana: las flechas mueven la selección
        self._apply_size(*self._size_doc(0.50, 0.62))

    def _browser_moved(self):
        b = self._views["browse"]
        self.btn_back.setVisible(bool(self._history))
        root, cwd = b.location()
        if b.archive is None and cwd and os.path.normcase(cwd) != os.path.normcase(root):
            self.name.setText(Path(cwd).name)

    def _open_inside(self, path: str):
        """Abrir un elemento desde la carpeta o el comprimido, recordando dónde estábamos para volver."""
        b = self._views["browse"]
        root, cwd = b.location()
        self._history.append((root, cwd, path))
        self.open(path, _nav=True)

    def go_back(self):
        if not self._history:
            return
        root, cwd, _path = self._history.pop()
        self._restore = (root, cwd)
        self.open(root, _nav=True)

    # ------------------------------------------------------------------ documentos
    def _open_document(self):
        from aero.ui.viewers.host import ViewerHost

        host = self._view("doc", lambda: ViewerHost(compact=True))
        host.layout().setContentsMargins(14, 58, 14, 12)
        host.title.hide()
        host.kind_icon.hide()
        host.subtitle.hide()
        host.btn_ext.hide()
        host.btn_reveal.hide()
        self._floating(False, pill=False)
        host.open(self.path)
        if self.kind == "pdf" or self.kind == "document":
            self._apply_size(*self._size_doc(0.52, 0.86, portrait=True))
        else:
            self._apply_size(*self._size_doc(0.72, 0.78))

    # ------------------------------------------------------------------ tamaño y posición
    def _screen(self):
        return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()

    def _size_doc(self, fw: float, fh: float, portrait: bool = False) -> tuple[int, int]:
        avail = self._screen().availableGeometry()
        h = int(avail.height() * fh)
        w = int(min(avail.width() * fw, h * 0.80)) if portrait else int(avail.width() * fw)
        return w, h

    def _resize_for(self, cw: int, ch: int, upscale: bool):
        if self.isFullScreen() or self.isMaximized():
            return
        remember = self.settings.get("viewer_remember_size") and self.settings.get("viewer_last_size")
        if remember and not self.quicklook:
            w, h = self.settings.get("viewer_last_size")
        else:
            avail = self._screen().availableGeometry()
            dpr = self._screen().devicePixelRatio()
            w, h, _ = fit_window(cw / dpr, ch / dpr, avail.width(), avail.height(),
                                 max_frac=0.72 if self.quicklook else 0.86, upscale=upscale)
        self._apply_size(w, h)

    def _apply_size(self, w: int, h: int, keep_center: bool = False):
        if self.isFullScreen() or self.isMaximized():
            return
        avail = self._screen().availableGeometry()
        w, h = min(w, avail.width()), min(h, avail.height())
        rect = QRect(0, 0, w, h)
        # La primera vez se centra en el monitor; después se conserva la posición que eligió el usuario.
        rect.moveCenter(self.geometry().center() if (self._placed and self.isVisible()) or keep_center and self.isVisible()
                        else avail.center())
        if not avail.contains(rect):
            rect.moveLeft(max(avail.left(), min(rect.left(), avail.right() - rect.width())))
            rect.moveTop(max(avail.top(), min(rect.top(), avail.bottom() - rect.height())))
        self.setGeometry(rect)
        self._placed = self._placed or self.isVisible()

    def nativeEvent(self, event_type, message):
        # Mantener la proporción del vídeo al redimensionar a mano (WM_SIZING).
        if self.kind == "video" and self.aspect > 0 and event_type == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_SIZING:
                r = ctypes.wintypes.RECT.from_address(msg.lParam)
                r.left, r.top, r.right, r.bottom = keep_aspect((r.left, r.top, r.right, r.bottom), msg.wParam,
                                                               self.aspect)
                return True, 1
        return super().nativeEvent(event_type, message)

    # ------------------------------------------------------------------ controles flotantes
    def _btn(self, icon: str, tip: str, fn):
        b = IconButton(icon, tip, 18, button=34)
        if fn is not None:
            b.clicked.connect(fn)
        return b

    def _clear_pill(self):
        self._side_widgets = None
        for lay in (self.pill_top, self.pill_lay):
            while lay.count():
                it = lay.takeAt(0)
                w = it.widget()
                if w is not None:
                    # Ocultar y soltar ya: deleteLater es diferido y el control viejo seguiría visible encima.
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()

    def _floating(self, overlay: bool, pill: bool = True):
        self._overlay = overlay
        self.pill.setVisible(pill)
        # Documentos: cristal más denso para que el contenido no compita con lo de detrás.
        self.backdrop.flat_opacity = 0.9 if self.kind not in ("image", "video", "audio") else None
        self.backdrop._rebuild()
        self._layout_overlays()

    def _layout_overlays(self):
        if self.isVisible():
            self.overlay.setGeometry(self.geometry())
            if not self.overlay.isVisible():
                self.overlay.show()
        w, h = self.width(), self.height()
        self.shade.setGeometry(0, 0, w, 64)
        self._fit_header(w)
        media = self.kind in ("video", "audio")
        pw = min(w - 32, 760 if self.kind == "video" else 520)
        if self.kind == "audio":
            pw = w - 32
        ph = self.PILL_MEDIA_H if media else self.PILL_H
        self.pill.setGeometry((w - pw) // 2, h - ph - 16, pw, ph)
        # Ventanas estrechas: el volumen se queda solo con el botón para que nada se monte encima.
        if media and getattr(self, "_side_widgets", None):
            # Lo que queda a cada lado del transporte (≈140 px) se reparte; si no cabe el volumen, solo su botón.
            side = min(140, (pw - 28 - 140) // 2)
            narrow = side < 96
            try:
                self._vol.setVisible(not narrow)
                self._vol.setFixedWidth(max(40, side - 42))
                for sw in self._side_widgets:
                    sw.setFixedWidth(44 if narrow else side)
            except RuntimeError:
                pass

    TITLE_MIN = 110      # ancho que se reserva al nombre antes de pasar los botones a «solo iconos»

    def _fit_header(self, w: int) -> None:
        """Reparte la cabecera: lo fijo (volver, abrir, pantalla completa, ventana), las acciones y el nombre.

        Con sitio, las acciones llevan texto; si no caben, quedan solo los iconos; y en ventanas muy
        pequeñas se ocultan las últimas. Así ningún botón se monta sobre otro ni sale recortado.
        """
        fixed = 8 + 6 + 6 + 6 + 8 + 10                         # separaciones y margen derecho del diseño
        for b in (self.btn_back, self.btn_app, self.btn_full, self.winbtns):
            if not b.isHidden():
                fixed += b.sizeHint().width() + 2
        room = w - fixed
        bar = self.actions_bar
        if bar.buttons:
            keep = self.TITLE_MIN if room - bar.compact_width() >= self.TITLE_MIN else 0
            room -= bar.fit(max(bar.ICON_W, room - keep))
        self._titles.setVisible(room >= 40)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_overlays()
        self._round_content()

    def _round_content(self) -> None:
        """Esquinas redondeadas también en el contenido. La ventana es «layered»: Windows 11 no la redondea y
        la imagen o el vídeo llenaban el rectángulo entero, así que las esquinas se veían cuadradas. Se recorta
        el contenido (y la superficie nativa del vídeo, que es otra ventana) con el mismo radio que el cristal.
        A pantalla completa o maximizada, recto, como en Windows."""
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainterPath, QRegion

        square = self.isFullScreen() or self.isMaximized()
        targets = [self.stack] + [w for w in self.stack.findChildren(QWidget)
                                  if w.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)]
        for w in targets:
            if square or w.width() <= 0:
                w.clearMask()
                continue
            path = QPainterPath()
            top_left = w.mapTo(self, w.rect().topLeft())
            path.addRoundedRect(QRectF(-top_left.x(), -top_left.y(), self.width(), self.height()), RADIUS, RADIUS)
            w.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def moveEvent(self, e):
        super().moveEvent(e)
        if self.overlay.isVisible():
            self.overlay.move(self.pos())

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._layout_overlays)
        QTimer.singleShot(0, self._round_content)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.overlay.hide()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                self.overlay.hide()
            else:
                QTimer.singleShot(0, self._layout_overlays)
                QTimer.singleShot(0, self._round_content)

    def _fade_to(self, value: float):
        self._fade.stop()
        if tm().reduce_motion:
            self.overlay.setWindowOpacity(value)
            return
        # Aparecer rápido; desaparecer con una transición más lenta y discreta.
        showing = value > self.overlay.windowOpacity()
        self._fade.setDuration(160 if showing else 420)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic if showing else QEasingCurve.Type.InOutQuad)
        self._fade.setStartValue(self.overlay.windowOpacity())
        self._fade.setEndValue(value)
        self._fade.start()

    def wake(self):
        if not self._controls_visible:
            self._controls_visible = True
            self._fade_to(1.0)
            kill_override_cursor()
        self._idle.start(self.IDLE_MS)

    def pointer_left(self):
        """El puntero ha salido de la ventana: si no vuelve, los controles se ocultan antes."""
        if getattr(self, "_overlay", False) and self._controls_visible:
            self._idle.start(self.LEAVE_MS)

    def controls_in_use(self) -> bool:
        """¿Se está usando un control? (puntero sobre la cápsula o la barra, botón pulsado, menú o arrastre)."""
        pos = QCursor.pos()
        for w in (self.pill, self.shade):
            if w.isVisible() and QRect(w.mapToGlobal(w.rect().topLeft()), w.size()).contains(pos):
                return True
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return True
        if any(m.isVisible() for m in self.findChildren(QMenu)):
            return True
        return any(s.isSliderDown() for s in self.pill.findChildren(QSlider))

    def _hide_controls(self):
        if not getattr(self, "_overlay", False):
            return
        if self.controls_in_use():
            self._idle.start(self.IDLE_MS)
            return
        self._controls_visible = False
        self._fade_to(0.0)
        if self.isFullScreen():
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BlankCursor))

    # ------------------------------------------------------------------ teclado y acciones
    def _shortcuts(self):
        # Atajos de visor: en el explorador de carpetas se desactivan para que las flechas, Intro y las letras
        # lleguen a la lista y al buscador.
        self._viewer_keys: list[QShortcut] = []

        def sc(key, fn):
            s = QShortcut(QKeySequence(key), self)
            s.activated.connect(fn)
            if key not in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Backspace):
                self._viewer_keys.append(s)

        sc(Qt.Key.Key_Escape, self._escape)
        sc(Qt.Key.Key_Space, self._space)
        sc(Qt.Key.Key_F, self.toggle_fullscreen)
        sc(Qt.Key.Key_F11, self.toggle_fullscreen)
        sc(Qt.Key.Key_Return, self.open_in_app)
        sc(Qt.Key.Key_Left, lambda: self._arrow(-1))
        sc(Qt.Key.Key_Right, lambda: self._arrow(1))
        sc(Qt.Key.Key_Up, lambda: self.engine and self.engine.set_volume(self.engine.audio.volume() + 0.05))
        sc(Qt.Key.Key_Down, lambda: self.engine and self.engine.set_volume(self.engine.audio.volume() - 0.05))
        sc(Qt.Key.Key_M, lambda: self.engine and self.engine.toggle_mute())
        sc(Qt.Key.Key_Plus, lambda: self._img("zoom", 1.25))
        sc(Qt.Key.Key_Minus, lambda: self._img("zoom", 0.8))
        sc(Qt.Key.Key_0, lambda: self._img("fit"))
        sc(Qt.Key.Key_1, lambda: self._img("actual_size"))
        sc(Qt.Key.Key_R, lambda: self._img("rotate_by", 90))
        sc(Qt.Key.Key_E, lambda: self.edit_image() if self.kind == "image" else self.edit_current())
        sc(Qt.Key.Key_Backspace, self._backspace)

    def keyPressEvent(self, e):
        # Respaldo de los atajos cuando la ventana aún no es la activa (p. ej. justo al abrir la vista rápida).
        if e.key() == Qt.Key.Key_Space:
            self._space()
        elif e.key() == Qt.Key.Key_Escape:
            self._escape()
        else:
            super().keyPressEvent(e)

    def _backspace(self):
        from PySide6.QtWidgets import QLineEdit

        fw = QApplication.focusWidget()
        if isinstance(fw, QLineEdit) and fw.window() is self:
            fw.backspace()
            return
        b = self._views.get("browse")
        if self.kind in ("folder", "archive") and b is not None and b._can_go_up():
            b.go_up()
        else:
            self.go_back()

    def _img(self, method: str, *args):
        if self.kind == "image" and "image" in self._views:
            getattr(self._views["image"], method)(*args)

    def _arrow(self, d: int):
        if self.kind in ("folder", "archive"):
            return
        if self.kind == "image":
            self._sibling(d)
        elif self.kind == "video" and self.engine:
            self.engine.seek_relative(5000 * d)
        elif self.kind == "audio" and self.engine:
            (self.engine.next if d > 0 else self.engine.previous)()

    def _space(self):
        from PySide6.QtWidgets import QLineEdit

        fw = QApplication.focusWidget()
        if isinstance(fw, QLineEdit) and fw.window() is self:
            fw.insert(" ")  # escribir en el buscador no cierra la vista rápida
            return
        if self.quicklook:
            self.close_preview()
        elif self.engine and self.kind in ("video", "audio"):
            self.engine.toggle()

    def _escape(self):
        if self.isFullScreen():
            self.toggle_fullscreen()
        elif self.quicklook:
            self.close_preview()
        else:
            self.close()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            kill_override_cursor()
        else:
            self.showFullScreen()
        self.btn_full.set_icon_name("exit_fullscreen" if self.isFullScreen() else "fullscreen")
        QTimer.singleShot(50, lambda: (self._layout_overlays(), self.wake()))

    def open_in_app(self):
        if not self.path or self.controller is None:
            return
        path = self.path
        if self.quicklook:
            self.close_preview()
        else:
            self.close()
        self.controller.open_in_main(path)

    def _stop_media(self):
        if self.engine is not None:
            self.engine.set_analysis(False)      # antes de parar: ver PlayerEngine._quiet_pipeline
            self.engine.save_position()
            self.engine.stop()
        if hasattr(self, "_audio_viz"):
            self._audio_viz.stop()
        if "image" in self._views:
            self._views["image"].clear()
        if "doc" in self._views:
            self._views["doc"].clear()
        self.backdrop.set_ambient(None)

    def close_preview(self):
        self._stop_media()
        self._history.clear()
        if "browse" in self._views:
            self._views["browse"].cleanup()
        kill_override_cursor()
        self.hide()

    def closeEvent(self, e):
        if self.settings.get("viewer_remember_size") and not self.quicklook and not self.isFullScreen():
            self.settings.set("viewer_last_size", [self.width(), self.height()])
        self._stop_media()
        if self.engine is not None and not self.quicklook:
            self.engine.dispose()        # salidas desconectadas antes de destruir la ventana (Linux y macOS)
        kill_override_cursor()
        if "browse" in self._views:
            self._views["browse"].cleanup()
        if self.quicklook:
            e.ignore()
            self.hide()
            return
        super().closeEvent(e)
        if self.controller is not None:
            self.controller.media_window_closed(self)
        self.closed.emit()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.open(paths[0])

