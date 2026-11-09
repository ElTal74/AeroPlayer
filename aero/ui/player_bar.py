"""Barra inferior «Reproduciendo ahora»: portada, título, controles, progreso, volumen y menús."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QFileDialog, QMenu, QVBoxLayout, QWidget

from aero.i18n import tr
from aero.core.formats import human_time
from aero.player.engine import REPEAT_ALL, REPEAT_OFF, REPEAT_ONE, PlayerEngine
from aero.ui.glass import ClickSlider, CoverArt, GlassPanel, IconButton, PlayButton, h_layout, label, transport_row

SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]


class PlayerBar(GlassPanel):
    HEIGHT = 92   # margen 6 + transporte 52 + 2 + progreso 24 + margen 6 (+2 de aire)
    open_player = Signal()
    toggle_queue = Signal()
    toggle_visualizer = Signal()
    toggle_fullscreen = Signal()
    favorite_toggled = Signal(str, bool)
    sub_options = Signal()
    file_action = Signal(str, str)   # acción (edit, tags…), ruta

    def __init__(self, engine: PlayerEngine, db, parent=None):
        super().__init__(parent, radius=14, strong=True)
        self.engine = engine
        self.db = db
        self.setMinimumHeight(0)
        self.setMaximumHeight(self.HEIGHT)
        self._seeking = False

        self.cover = CoverArt(58, 12)
        self.cover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cover.mousePressEvent = lambda e: self.open_player.emit()
        self.title = label(tr("AERO Player"), "h3")
        self.artist = label("", "caption")
        self.title.setMinimumWidth(60)
        self.fav = IconButton("heart", tr("Añadir a favoritos"), 18, checkable=True, button=32)
        self.fav.clicked.connect(self._toggle_fav)
        info = QWidget()
        info.setLayout(QVBoxLayout())
        info.layout().setContentsMargins(0, 0, 0, 0)
        info.layout().setSpacing(1)
        info.layout().addStretch(1)
        info.layout().addWidget(self.title)
        info.layout().addWidget(self.artist)
        info.layout().addStretch(1)
        left = QWidget()
        left.setLayout(h_layout(self.cover, info, self.fav, spacing=12))
        left.setMinimumWidth(180)
        left.setMaximumWidth(340)

        self.shuffle = IconButton("shuffle", tr("Aleatorio (S)"), 18, checkable=True, button=34)
        self.prev = IconButton("prev", tr("Anterior (Ctrl+←)"), 18, button=38)
        self.play = PlayButton(size=40)
        self.next = IconButton("next", tr("Siguiente (Ctrl+→)"), 18, button=38)
        self.repeat = IconButton("repeat", tr("Repetir: desactivado (R)"), 18, checkable=True, button=34)
        self.pos_label = label("0:00", "caption")
        self.dur_label = label("0:00", "caption")
        self.pos_label.setMinimumWidth(42)
        self.pos_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.dur_label.setMinimumWidth(42)
        self.seek = ClickSlider()
        self.seek.setAccessibleName(tr("Progreso de reproducción"))
        self.seek.setRange(0, 0)
        self.seek.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        cl.addWidget(transport_row(None, self.shuffle, self.prev, self.play, self.next, self.repeat, None, spacing=8))
        cl.addLayout(h_layout(self.pos_label, self.seek, self.dur_label, spacing=10))

        self.speed = IconButton("speed", tr("Velocidad de reproducción"), 18, button=34)
        # Temporizador de apagado (dormirse con música o con una película)
        from aero.player.sleep_timer import SleepTimer

        self.sleep = SleepTimer(engine, self)
        self.sleep_btn = IconButton("sleep", tr("Temporizador de apagado"), 18, checkable=True, button=34)
        self.sleep_btn.setPopupMode(self.sleep_btn.ToolButtonPopupMode.InstantPopup)
        self.sleep_menu = QMenu(self)
        self.sleep_menu.aboutToShow.connect(self._build_sleep_menu)
        self.sleep_btn.setMenu(self.sleep_menu)
        self.sleep.changed.connect(self._sleep_changed)
        self.sleep.fired.connect(lambda: self.window().notify(tr("Temporizador: reproducción detenida"), "info")
                                 if hasattr(self.window(), "notify") else None)
        self.speed.setPopupMode(self.speed.ToolButtonPopupMode.InstantPopup)
        self.media_menu_btn = IconButton("subtitles", tr("Subtítulos y pistas de audio"), 18, button=34)
        self.media_menu_btn.setPopupMode(self.media_menu_btn.ToolButtonPopupMode.InstantPopup)
        self.viz = IconButton("visualizer", tr("Visualizador (V)"), 18, checkable=True, button=34)
        self.queue_btn = IconButton("queue", tr("Cola de reproducción"), 18, checkable=True, button=34)
        self.vol_btn = IconButton("volume", tr("Silenciar (M)"), 18, button=34)
        self.volume = ClickSlider()
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(96)
        self.volume.setAccessibleName(tr("Volumen"))
        self.volume.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.full = IconButton("fullscreen", tr("Pantalla completa (F11)"), 18, button=34)
        # Editar el vídeo (o las etiquetas de la canción) sin salir del reproductor
        self.edit_btn = IconButton("edit", "Editar", 18, button=34)
        self.edit_btn.clicked.connect(self._edit)
        self.edit_btn.hide()
        right = QWidget()
        right.setLayout(h_layout(self.edit_btn, self.sleep_btn, self.speed, self.media_menu_btn, self.viz, self.queue_btn, 6, self.vol_btn,
                                 self.volume, self.full, spacing=2))

        lay = h_layout(left, center, right, spacing=18, margins=(14, 6, 14, 6))
        lay.setStretch(1, 1)
        self.setLayout(lay)

        # Menú de velocidad
        sm = QMenu(self)
        grp = QActionGroup(sm)
        for s in SPEEDS:
            a = QAction(f"{s:g}×", sm, checkable=True)
            a.setChecked(s == 1.0)
            a.triggered.connect(lambda _c=False, v=s: engine.set_rate(v))
            grp.addAction(a)
            sm.addAction(a)
        self.speed.setMenu(sm)
        self.media_menu = QMenu(self)
        self.media_menu.aboutToShow.connect(self._build_media_menu)
        self.media_menu_btn.setMenu(self.media_menu)

        # Conexiones
        self.play.clicked.connect(engine.toggle)
        self.prev.clicked.connect(engine.previous)
        self.next.clicked.connect(engine.next)
        self.shuffle.clicked.connect(lambda on: engine.set_shuffle(on))
        self.repeat.clicked.connect(lambda _c: engine.cycle_repeat())
        self.vol_btn.clicked.connect(engine.toggle_mute)
        self.volume.valueChanged.connect(lambda v: engine.set_volume(v / 100))
        self.viz.clicked.connect(lambda _c: self.toggle_visualizer.emit())
        self.queue_btn.clicked.connect(lambda _c: self.toggle_queue.emit())
        self.full.clicked.connect(self.toggle_fullscreen)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderMoved.connect(lambda v: self.pos_label.setText(human_time(v / 1000)))
        self.seek.seek_requested.connect(self._seek)

        engine.track_changed.connect(self._track)
        engine.state_changed.connect(lambda _s: self.play.set_playing(engine.playing))
        engine.position_changed.connect(self._position)
        engine.duration_changed.connect(self._duration)
        engine.modes_changed.connect(self._modes)
        engine.volume_changed.connect(self._volume)
        self._volume(engine.audio.volume(), engine.audio.isMuted())
        self._modes()


    # ------------------------------------------------------------------ temporizador de apagado
    def _build_sleep_menu(self):
        from aero.player.sleep_timer import CHOICES

        m = self.sleep_menu
        m.clear()
        off = m.addAction(tr("Desactivado"))
        off.setCheckable(True)
        off.setChecked(not self.sleep.active)
        off.triggered.connect(lambda: self.sleep.cancel())
        m.addSeparator()
        for mins in CHOICES:
            text = tr("{n} minutos", n=mins) if mins < 60 else (tr("1 hora") if mins == 60 else
                                                                 tr("{h} h {m} min", h=mins // 60, m=mins % 60)
                                                                 if mins % 60 else tr("{n} horas", n=mins // 60))
            a = m.addAction(text)
            a.triggered.connect(lambda _c=False, v=mins: self.sleep.start(v))
        end = m.addAction(tr("Al terminar esta pista"))
        end.setCheckable(True)
        end.setChecked(self.sleep.end_of_track)
        end.triggered.connect(self.sleep.start_end_of_track)

    def _sleep_changed(self):
        self.sleep_btn.setChecked(self.sleep.active)
        rem = self.sleep.remaining()
        if self.sleep.end_of_track:
            tip = tr("Se detendrá al terminar esta pista")
        elif rem is not None:
            tip = tr("Se detendrá en {t}", t=f"{int(rem // 60)}:{int(rem % 60):02d}")
        else:
            tip = tr("Temporizador de apagado")
        self.sleep_btn.setToolTip(tip)
    def _seek(self, v: int):
        self._seeking = False
        self.engine.seek(v)

    def _track(self, info):
        self.edit_btn.setVisible(info is not None and info.kind in ("video", "audio"))
        if info is not None:
            self.edit_btn.setToolTip(tr("Editar en el editor de vídeo") if info.kind == "video" else
                                     tr("Propiedades: título, artista, álbum…"))
        if info is None:
            self.title.setText(tr("AERO Player"))
            self.artist.setText("")
            self.cover.set_image(None)
            self.fav.setChecked(False)
            return
        self._duration(0)
        self._position(0)
        self.title.setText(_elide(info.display_title, 34))
        self.title.setToolTip(info.display_title)
        sub = " · ".join(x for x in (info.artist, info.album) if x)
        self.artist.setText(_elide(sub, 44))
        self.cover.placeholder = "video" if info.kind == "video" else "music"
        self.cover.set_image(info.cover)
        fav = self.db.is_favorite(info.path)
        self.fav.setChecked(fav)
        self.fav.set_icon_name("heart_fill" if fav else "heart")

    def _edit(self):
        info = self.engine.current
        if info is not None:
            if info.kind == "video":
                self.engine.player.pause()
            self.file_action.emit("edit" if info.kind == "video" else "tags", info.path)

    def _toggle_fav(self):
        info = self.engine.current
        if not info:
            self.fav.setChecked(False)
            return
        on = self.fav.isChecked()
        self.db.set_favorite(info.path, on)
        self.fav.set_icon_name("heart_fill" if on else "heart")
        self.favorite_toggled.emit(info.path, on)

    def _position(self, ms: int):
        if not self._seeking and not self.seek.isSliderDown():
            self.seek.blockSignals(True)
            self.seek.setValue(ms)
            self.seek.blockSignals(False)
            self.pos_label.setText(human_time(ms / 1000))

    def _duration(self, ms: int):
        self.seek.setRange(0, max(0, ms))
        self.dur_label.setText(human_time(ms / 1000) if ms > 0 else "--:--")

    def _modes(self):
        e = self.engine
        self.shuffle.setChecked(e.shuffle)
        self.repeat.setChecked(e.repeat != REPEAT_OFF)
        self.repeat.set_icon_name("repeat1" if e.repeat == REPEAT_ONE else "repeat")
        self.repeat.setToolTip({REPEAT_OFF: "Repetir: desactivado (R)", REPEAT_ALL: "Repetir: toda la cola (R)",
                                REPEAT_ONE: "Repetir: una canción (R)"}[e.repeat])

    def _volume(self, v: float, muted: bool):
        self.volume.blockSignals(True)
        self.volume.setValue(int(round(v * 100)))
        self.volume.blockSignals(False)
        self.vol_btn.set_icon_name("mute" if muted or v == 0 else ("volume_low" if v < 0.5 else "volume"))

    def _build_media_menu(self):
        m = self.media_menu
        m.clear()
        e = self.engine
        subs = e.subtitle_tracks()
        hdr = m.addAction(tr("Subtítulos"))
        hdr.setEnabled(False)
        grp = QActionGroup(m)
        off = QAction(tr("Desactivados"), m, checkable=True)
        off.setChecked(e.player.activeSubtitleTrack() < 0 and e.ext_subs is None)
        off.triggered.connect(lambda: (e.set_subtitle_track(-1), setattr(e, "ext_subs", None), e._set_sub_text("")))
        grp.addAction(off)
        m.addAction(off)
        for i, name in enumerate(subs):
            a = QAction(name, m, checkable=True)
            a.setChecked(e.player.activeSubtitleTrack() == i)
            a.triggered.connect(lambda _c=False, k=i: e.set_subtitle_track(k))
            grp.addAction(a)
            m.addAction(a)
        if e.ext_subs is not None:
            a = QAction(f"Externo: {e.ext_subs.name}", m, checkable=True)
            a.setChecked(True)
            grp.addAction(a)
            m.addAction(a)
        load = m.addAction(tr("Cargar archivo…"))
        load.triggered.connect(self._load_subs)
        sync = m.addAction(tr("Desfase… ({v0:+.1f} s)", v0=e.sub_offset_ms / 1000))
        sync.triggered.connect(self.sub_options)
        audios = e.audio_tracks()
        if len(audios) > 1:
            m.addSeparator()
            h2 = m.addAction(tr("Pista de audio"))
            h2.setEnabled(False)
            g2 = QActionGroup(m)
            for i, name in enumerate(audios):
                a = QAction(name, m, checkable=True)
                a.setChecked(e.player.activeAudioTrack() == i)
                a.triggered.connect(lambda _c=False, k=i: e.set_audio_track(k))
                g2.addAction(a)
                m.addAction(a)

    def _load_subs(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Cargar subtítulos"), "",
                                              "Subtítulos (*.srt *.vtt *.ass *.ssa);;Todos los archivos (*)")
        if path:
            try:
                self.engine.load_external_subtitles(path)
            except (OSError, ValueError) as err:
                self.engine.error.emit(f"No se pudieron cargar los subtítulos: {err}")

    def set_fullscreen_icon(self, on: bool):
        self.full.set_icon_name("exit_fullscreen" if on else "fullscreen")


def _elide(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"
