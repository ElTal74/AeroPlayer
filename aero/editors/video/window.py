"""Ventana del editor de vídeo: la vista previa y la línea de tiempo mandan.

Arriba, medios del proyecto (izquierda), vista previa (centro) e inspector del clip (derecha); abajo, la línea
de tiempo con sus herramientas. La vista previa reproduce el clip superior en el cabezal (o su proxy), una pista
de audio y los textos; para ver el resultado exacto de un tramo, «Vista previa exacta» lo renderiza con el
mismo motor que la exportación. Exportar y generar proxies van en segundo plano por la cola de tareas pesadas.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QMimeData, QProcess, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDrag, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QScrollArea, QScrollBar, QSlider, QSpinBox, QSplitter, QStackedWidget, QVBoxLayout,
                               QWidget)

from aero.core.formats import human_time
from aero.editors.video import export as vexport
from aero.editors.video.project import ASPECTS, PROJECT_EXT, TRANSITIONS, Clip, Project, clip_from_media, media_info
from aero.editors.video.timeline import Timeline, fmt_time
from aero.editors.video.viewer import Preview
from aero.ui.glass import GlassPanel, IconButton, h_layout, label, tm, v_layout
from aero.ui.glasswindow import DragArea, GlassWindow, TrDialog
from aero.i18n import tr

MEDIA_FILTER = "Medios (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.png " \
               "*.jpg *.jpeg *.webp *.bmp *.gif)"


class MediaBin(QListWidget):
    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setIconSize(QSize(64, 36))
        self.setSpacing(2)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count():
            return
        from PySide6.QtGui import QColor, QPainter

        from aero.ui.glass import tm

        p = QPainter(self.viewport())
        p.setPen(QColor(tm().theme.text2))
        p.drawText(self.viewport().rect().adjusted(16, 0, -16, 0), Qt.AlignmentFlag.AlignCenter
                   | Qt.TextFlag.TextWordWrap,
                   tr("Importa vídeos, música e imágenes (o arrástralos aquí desde el Explorador)"))

    def startDrag(self, actions):
        it = self.currentItem()
        if it is None:
            return
        md = QMimeData()
        md.setData("application/x-aero-media", it.data(Qt.ItemDataRole.UserRole).encode("utf-8"))
        d = QDrag(self)
        d.setMimeData(md)
        d.setPixmap(it.icon().pixmap(64, 36))
        d.exec(Qt.DropAction.CopyAction)


class VideoEditor(GlassWindow):
    def __init__(self, path: str = "", controller=None):
        super().__init__(Qt.WindowType(0), flat=True)
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumSize(1100, 700)
        self.backdrop.flat_opacity = 0.95
        self.project = Project()
        self.project_path = ""
        self.dirty = False
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._loading_inspector = False
        self.use_proxies = False
        self.proxies: dict[str, str] = {}
        self._current_src = ""
        self._playing = False
        self._last_tick = 0.0

        # Reproducción de la vista previa
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.music = QMediaPlayer(self)
        self.music_out = QAudioOutput(self)
        self.music.setAudioOutput(self.music_out)
        self._music_src = ""
        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._advance)
        self._fx_preview_timer = QTimer(self)
        self._fx_preview_timer.setSingleShot(True)
        self._fx_preview_timer.setInterval(300)
        self._fx_preview_timer.timeout.connect(self._render_fx_preview)

        # ---------------------------------------------------------- barra superior
        bar = DragArea()
        self.title = label(tr("Proyecto sin título"), "h3")
        self.info = label("", "caption")
        btns = []
        for ic, tip, fn in (("files", "Nuevo proyecto", self.new_project), ("open", "Abrir proyecto…", self.open_project),
                            ("save", "Guardar proyecto (Ctrl+S)", self.save_project),
                            ("plus", "Importar medios…", self.import_media), ("undo", "Deshacer (Ctrl+Z)", self.undo),
                            ("redo", "Rehacer (Ctrl+Y)", self.redo)):
            b = IconButton(ic, tip, 18)
            b.clicked.connect(fn)
            btns.append(b)
        export = QPushButton(tr("Exportar…"))
        export.setProperty("kind", "primary")
        export.clicked.connect(self.export_dialog)
        bar.setLayout(h_layout(14, v_layout(self.title, self.info, spacing=0), 18, *btns, None, export, 10,
                               self.window_buttons(), spacing=3, margins=(0, 8, 10, 8)))

        # ---------------------------------------------------------- medios, vista previa e inspector
        self.bin = MediaBin()
        self.bin.itemDoubleClicked.connect(lambda it: self.add_to_timeline(it.data(Qt.ItemDataRole.UserRole)))
        bin_panel = GlassPanel(radius=12, nested=True)
        bl = QVBoxLayout(bin_panel)
        bl.setContentsMargins(8, 8, 8, 8)
        imp = QPushButton(tr("Importar medios…"))
        imp.clicked.connect(self.import_media)
        self.proxy_box = QCheckBox(tr("Editar con proxies (360p)"))
        self.proxy_box.setToolTip(tr("Copias ligeras para editar con fluidez en equipos modestos; la exportación usa "
                                  "siempre los originales."))
        self.proxy_box.toggled.connect(self.set_proxies)
        # El perfil de rendimiento decide si se empieza con proxies (Ahorro de recursos: sí).
        self.proxy_box.blockSignals(True)
        self.proxy_box.setChecked(bool(tm().quality.get("proxies")))
        self.proxy_box.blockSignals(False)
        self.use_proxies = self.proxy_box.isChecked()
        media_tab = QWidget()
        media_tab.setLayout(v_layout(self.bin, imp, self.proxy_box, spacing=6))
        from PySide6.QtWidgets import QTabWidget

        from aero.editors.video.library import FxLibrary

        self.lib_tr = FxLibrary("transitions")
        self.lib_tr.apply.connect(lambda tid: self.apply_transition(None, tid))
        self.lib_fx = FxLibrary("effects")
        self.lib_fx.apply.connect(lambda eid: self.apply_effect(None, eid))
        self.library = QTabWidget()
        self.library.addTab(media_tab, tr("Medios"))
        self.library.addTab(self.lib_tr, tr("Transiciones"))
        self.library.addTab(self.lib_fx, tr("Efectos"))
        bl.addWidget(self.library, 1)

        self.preview = Preview(self)
        self.preview.clip_clicked.connect(self._select_from_viewer)
        self.preview.transform_started.connect(self._push_undo)
        self.preview.transform_changed.connect(self._transform_live)
        self.preview.transform_finished.connect(self._transform_done)
        self.play_btn = IconButton("play", tr("Reproducir (Espacio)"), 20)
        self.play_btn.clicked.connect(self.toggle_play)
        to_start = IconButton("prev", tr("Al principio (Inicio)"), 18)
        to_start.clicked.connect(lambda: self.seek(0))
        self.time_lbl = label("0:00,00 / 0:00", "caption")
        exact = QPushButton(tr("Vista previa exacta"))
        exact.setToolTip(tr("Renderiza 6 s desde el cabezal con el motor de exportación (color, transiciones, mezcla)"))
        exact.clicked.connect(self.exact_preview)
        prev_panel = QWidget()
        prev_panel.setLayout(v_layout(self.preview, h_layout(to_start, self.play_btn, self.time_lbl, None, exact,
                                                             spacing=6), spacing=6))

        self.inspector = self._build_inspector()
        insp_scroll = QScrollArea()
        insp_scroll.setWidget(self.inspector)
        insp_scroll.setWidgetResizable(True)
        insp_scroll.setFixedWidth(300)
        insp_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        top = QSplitter()
        top.addWidget(bin_panel)
        top.addWidget(prev_panel)
        top.addWidget(insp_scroll)
        top.setStretchFactor(1, 1)
        top.setSizes([290, 710, 300])

        # ---------------------------------------------------------- línea de tiempo
        self.timeline = Timeline(self.project)
        self.timeline.changed.connect(self._timeline_changed)
        self.timeline.playhead_moved.connect(self._playhead_moved)
        self.timeline.selection_changed.connect(self._load_inspector)
        self.timeline.drop_media.connect(lambda path, trk, t: self.add_to_timeline(path, trk, t))
        self.timeline.request.connect(self._timeline_request)
        self.hscroll = QScrollBar(Qt.Orientation.Horizontal)
        self.hscroll.valueChanged.connect(lambda v: (setattr(self.timeline, "offset", v / 10), self.timeline.update()))
        # Herramientas con icono y nombre corto (sin tener que adivinar qué hace cada botón)
        tools = [self._tool(ic, tip, fn, text) for ic, text, tip, fn in (
            ("crop", "Dividir", "Dividir en el cabezal (S)", self.split),
            ("trash", "Eliminar", "Eliminar lo seleccionado (Supr)", self.delete),
            ("text_tool", "Título", "Añadir un título en el cabezal", self.add_text),
            ("plus", "Pista de vídeo", "Añadir una pista de vídeo (encima de las demás)", lambda: self.add_track("video")),
            ("music", "Pista de audio", "Añadir una pista de audio (música, voz, efectos)",
             lambda: self.add_track("audio")))]
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(4, 400)
        self.zoom.setValue(60)
        self.zoom.setFixedWidth(160)
        self.zoom.setAccessibleName(tr("Zoom de la línea de tiempo"))
        self.zoom.valueChanged.connect(lambda v: self.timeline.set_zoom(float(v)))
        tl_panel = GlassPanel(radius=12, nested=True)
        tll = QVBoxLayout(tl_panel)
        tll.setContentsMargins(8, 6, 8, 6)
        tll.setSpacing(4)
        tll.addLayout(h_layout(*tools, None, label("Zoom", "caption"), self.zoom, spacing=4))
        tll.addWidget(self.timeline, 1)
        tll.addWidget(self.hscroll)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(top)
        split.addWidget(tl_panel)
        split.setSizes([480, 300])
        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(bar)
        body = QVBoxLayout()
        body.setContentsMargins(10, 0, 10, 10)
        body.addWidget(split)
        root.addLayout(body, 1)

        for seq, fn in (("Space", self.toggle_play), ("S", self.split), ("Delete", self.delete),
                        ("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+S", self.save_project),
                        ("Home", lambda: self.seek(0)), ("Left", lambda: self.seek(self.timeline.playhead - 1 / 25)),
                        ("Right", lambda: self.seek(self.timeline.playhead + 1 / 25))):
            QShortcut(QKeySequence(seq), self, activated=fn)
        if path:
            if path.lower().endswith(PROJECT_EXT):
                self.load_project(path)
            else:
                self.import_paths([path], add=True)
                # Abrir un vídeo para editarlo no es todavía un cambio: cerrar sin tocar nada no pregunta
                self.dirty = False
                self._undo.clear()
        self._sync()
        from aero.core.drafts import Autosaver

        self.autosaver = Autosaver(
            self, "video", PROJECT_EXT, lambda: self.dirty, lambda p: Path(p).write_text(self.project.to_json(),
                                                                                           encoding="utf-8"),
            lambda: Path(self.project_path).stem if self.project_path else tr("Proyecto sin título"),
            lambda: self.project_path, token=lambda: self.project.to_json(),
            settings=getattr(controller, "settings", None))

    # ------------------------------------------------------------------ inspector
    def _build_inspector(self) -> QWidget:
        """Propiedades por grupos; solo se muestran los que tienen sentido para el tipo de clip."""
        from aero.ui.collapsible import Collapsible

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(6)
        self.insp_title = label(tr("Proyecto"), "h3")
        lay.addWidget(self.insp_title)
        self.insp_stack = QStackedWidget()
        # Proyecto
        proj = QWidget()
        pf = QFormLayout(proj)
        self.aspect = QComboBox()
        self.aspect.addItems(list(ASPECTS))
        self.res = QComboBox()
        for h in (2160, 1440, 1080, 720, 480):
            self.res.addItem(f"{h}p", h)
        self.res.setCurrentIndex(2)
        self.fps = QComboBox()
        for v in (24, 25, 30, 50, 60):
            self.fps.addItem(f"{v} fps", float(v))
        self.fps.setCurrentIndex(2)
        for wdg in (self.aspect, self.res, self.fps):
            wdg.currentIndexChanged.connect(self._project_settings)
        pf.addRow(tr("Formato"), self.aspect)
        pf.addRow(tr("Resolución"), self.res)
        pf.addRow(tr("Fotogramas"), self.fps)
        pf.addRow(label(tr("Selecciona un clip para editarlo"), "caption"))
        # Clip
        clip = QWidget()
        cl = QVBoxLayout(clip)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        acts = h_layout(*[self._tool(ic, tip, fn) for ic, tip, fn in (
            ("crop", "Dividir en el cabezal (S)", self.split),
            ("up", "Capa superior", lambda: self._layer(-1)),
            ("down", "Capa inferior", lambda: self._layer(1)),
            ("trash", "Eliminar (Supr)", self.delete))], None, spacing=4)
        cl.addLayout(acts)

        def form(*rows) -> QWidget:
            box = QWidget()
            fl = QFormLayout(box)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setVerticalSpacing(4)
            for text, wdg in rows:
                fl.addRow(text, wdg)
            return box

        self.f_start = self._dspin(0, 36000, " s")
        self.f_dur = self._dspin(0.1, 36000, " s", 0.5)
        self.f_in = self._dspin(0, 36000, " s")
        self.f_out = self._dspin(0, 36000, " s")
        self.f_speed = self._dspin(0.25, 4, " ×", 0.25)
        self.sec_time = form(("Inicio", self.f_start), ("Duración", self.f_dur), ("Entrada", self.f_in),
                             ("Salida", self.f_out), ("Velocidad", self.f_speed))
        # Valores exactos (en % del medio lienzo, % de escala y grados), cada uno con su «restablecer»
        self.f_px, self.f_py = self._pspin(-500, 500, " %"), self._pspin(-500, 500, " %")
        self.f_scale = self._pspin(1, 2000, " %", 1)
        self.f_sx, self.f_sy = self._pspin(1, 2000, " %", 1), self._pspin(1, 2000, " %", 1)
        self.f_angle = self._pspin(-180, 180, "°", 1)
        self.f_angle.setWrapping(True)
        self.f_ax, self.f_ay = self._pspin(-150, 150, " %"), self._pspin(-150, 150, " %")
        self.f_rot = QComboBox()
        for v in (0, 90, 180, 270):
            self.f_rot.addItem(f"{v}°", v)
        self.f_opacity = self._pspin(0, 100, " %", 1)
        center = QPushButton(tr("Centrar"))
        center.setProperty("kind", "flat")
        center.clicked.connect(lambda: (self.f_px.setValue(0), self.f_py.setValue(0)))
        self.f_crop = [QSpinBox() for _ in range(4)]
        for sp in self.f_crop:
            sp.setRange(0, 45)
            sp.setSuffix(" %")
        self.sec_frame = form((tr("Posición X"), self._with_reset(self.f_px, 0)),
                              (tr("Posición Y"), self._with_reset(self.f_py, 0)), ("", center),
                              (tr("Escala"), self._with_reset(self.f_scale, 100)),
                              (tr("Escala X"), self._with_reset(self.f_sx, 100)),
                              (tr("Escala Y"), self._with_reset(self.f_sy, 100)),
                              (tr("Giro"), self._with_reset(self.f_angle, 0)), (tr("Rotar"), self.f_rot),
                              (tr("Anclaje X"), self._with_reset(self.f_ax, 0)),
                              (tr("Anclaje Y"), self._with_reset(self.f_ay, 0)),
                              (tr("Opacidad"), self._with_reset(self.f_opacity, 100)))
        self.sec_frame.setToolTip(tr("En el visor: arrastra para mover, esquinas para escalar (Mayús: libre), lados "
                                     "para estirar, Alt para recortar, el círculo superior para girar y la cruz "
                                     "para el anclaje."))
        self.sec_crop = Collapsible("Recorte", form(("Izq. / arriba", h_layout(self.f_crop[0], self.f_crop[1])),
                                                    ("Der. / abajo", h_layout(self.f_crop[2], self.f_crop[3]))))
        self.f_bri, self.f_con = self._slider(-100, 100), self._slider(0, 200)
        self.f_sat, self.f_gam = self._slider(0, 300), self._slider(10, 300)
        self.sec_color = Collapsible("Color", form(("Brillo", self.f_bri), ("Contraste", self.f_con),
                                                   ("Saturación", self.f_sat), ("Exposición", self.f_gam)))
        self.f_vol = self._slider(0, 200)
        self.f_mute = QCheckBox(tr("Silenciar"))
        self.f_fin = self._dspin(0, 30, " s", 0.1)
        self.f_fout = self._dspin(0, 30, " s", 0.1)
        self.sec_audio = form(("Volumen", self.f_vol), ("", self.f_mute))
        self.sec_fades = form(("Aparecer", self.f_fin), ("Desaparecer", self.f_fout))
        self.f_trans = QComboBox()
        for k, t in TRANSITIONS.items():
            self.f_trans.addItem(t, k)
        self.f_td = self._dspin(0.1, 5, " s", 0.1)
        self.sec_trans = Collapsible(tr("Transición"), form(("Tipo", self.f_trans), ("Duración", self.f_td)))
        self.f_text = QPlainTextEdit()
        self.f_text.setMaximumHeight(70)
        self.f_tsize = QSpinBox()
        self.f_tsize.setRange(8, 400)
        self.f_tcolor = QLineEdit()
        self.f_tcolor.setPlaceholderText("#ffffff")
        self.f_tpos = QComboBox()
        for k, t in (("top", "Arriba"), ("center", "Centro"), ("bottom", "Abajo")):
            self.f_tpos.addItem(t, k)
        self.sec_text = form(("Texto", self.f_text), ("Tamaño", self.f_tsize), ("Color", self.f_tcolor),
                             ("Posición", self.f_tpos))
        # Efectos aplicados: activar o desactivar, ordenar, quitar, copiar y pegar; parámetros del elegido
        self.fx_list = QListWidget()
        self.fx_list.setMaximumHeight(110)
        self.fx_list.setAccessibleName(tr("Efectos del clip"))
        self.fx_list.itemChanged.connect(self._fx_toggled)
        self.fx_list.currentRowChanged.connect(self._fx_params)
        self.fx_params = QWidget()
        self.fx_params_lay = QFormLayout(self.fx_params)
        self.fx_params_lay.setContentsMargins(0, 0, 0, 0)
        fx_acts = h_layout(*[self._tool(ic, tip, fn) for ic, tip, fn in (
            ("up", "Subir el efecto", lambda: self._fx_move(-1)), ("down", "Bajar el efecto", lambda: self._fx_move(1)),
            ("trash", "Quitar el efecto", self._fx_remove), ("refresh", "Valores originales", self._fx_reset),
            ("list_add", "Copiar los efectos del clip", self.copy_effects),
            ("drop", "Pegar efectos en este clip", self.paste_effects))], None, spacing=2)
        self.sec_fx = QWidget()
        self.sec_fx.setLayout(v_layout(self.fx_list, fx_acts, self.fx_params, spacing=4))
        self._fx_clipboard: list = []
        self.sections = {}
        for key, title, wdg in (("time", "Tiempo", self.sec_time), ("fx", "Efectos", self.sec_fx),
                                ("text", "Texto", self.sec_text),
                                ("frame", "Encuadre", self.sec_frame), ("crop", "", self.sec_crop),
                                ("color", "", self.sec_color), ("audio", "Sonido", self.sec_audio),
                                ("fades", "Fundidos", self.sec_fades), ("trans", "", self.sec_trans)):
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 4, 0, 0)
            bl.setSpacing(2)
            if title:
                bl.addWidget(label(title, "muted"))
            bl.addWidget(wdg)
            cl.addWidget(box)
            self.sections[key] = box
        cl.addStretch(1)
        for sig in (self.f_start.valueChanged, self.f_in.valueChanged, self.f_out.valueChanged, self.f_dur.valueChanged,
                    self.f_speed.valueChanged, self.f_vol.valueChanged, self.f_mute.toggled, self.f_fin.valueChanged,
                    self.f_fout.valueChanged, self.f_trans.currentIndexChanged, self.f_td.valueChanged,
                    self.f_bri.valueChanged, self.f_con.valueChanged, self.f_sat.valueChanged, self.f_gam.valueChanged,
                    self.f_rot.currentIndexChanged, self.f_scale.valueChanged, self.f_text.textChanged,
                    self.f_tsize.valueChanged, self.f_tcolor.editingFinished, self.f_tpos.currentIndexChanged,
                    self.f_px.valueChanged, self.f_py.valueChanged, self.f_angle.valueChanged,
                    self.f_sx.valueChanged, self.f_sy.valueChanged, self.f_ax.valueChanged, self.f_ay.valueChanged,
                    self.f_opacity.valueChanged, *(sp.valueChanged for sp in self.f_crop)):
            sig.connect(self._apply_inspector)
        self.insp_stack.addWidget(proj)
        self.insp_stack.addWidget(clip)
        lay.addWidget(self.insp_stack)
        lay.addStretch(1)
        return w

    def _tool(self, ic: str, tip: str, fn, text: str = "") -> QPushButton:
        b = QPushButton(text)
        b.setIcon(IconButton(ic, "", 16).icon())
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        b.setProperty("kind", "flat")
        b.clicked.connect(fn)
        return b

    def _dspin(self, lo, hi, suffix, step=0.04):
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(2)
        sp.setSingleStep(step)
        sp.setSuffix(suffix)
        sp.setKeyboardTracking(False)
        return sp

    def _pspin(self, lo, hi, suffix, step=0.5):
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(1)
        sp.setSingleStep(step)
        sp.setSuffix(suffix)
        sp.setKeyboardTracking(False)
        sp.setAccelerated(True)
        return sp

    def _with_reset(self, spin, default: float) -> QWidget:
        b = IconButton("refresh", tr("Restablecer"), 14, button=24)
        b.clicked.connect(lambda: spin.setValue(default))
        box = QWidget()
        box.setLayout(h_layout(spin, b, spacing=2))
        return box

    def _slider(self, lo, hi):
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        return s

    # ------------------------------------------------------------------ manipulación directa en el visor
    def _src_dims(self, c: Clip) -> tuple[int, int]:
        """Tamaño del original; los proyectos antiguos no lo guardaban: se mide una vez y se queda en el clip."""
        if not (c.src_w and c.src_h):
            w, h = vexport._src_size(c)
            if w and h:
                c.src_w, c.src_h = w, h
        return (c.src_w, c.src_h) if c.src_w and c.src_h else (self.project.width, self.project.height)

    def clip_locked(self, c: Clip) -> bool:
        trk, _c = self.project.find(c.id)
        return bool(trk is not None and trk.locked)

    def _select_from_viewer(self, cid: str):
        self.timeline.selected = {cid} if cid else set()
        self.timeline.selected_transition = None
        self.timeline.update()
        self._load_inspector()
        self.preview.gizmo.refresh()

    def _transform_live(self):
        """Mientras se arrastra en el visor: el inspector sigue los valores sin reconstruir la vista previa."""
        self._load_inspector()
        self.preview.gizmo.refresh()

    def _transform_done(self):
        self._mark()
        self.timeline.update()
        self._fx_preview_timer.start()

    def selected_clip(self) -> Clip | None:
        if len(self.timeline.selected) != 1:
            return None
        return self.project.find(next(iter(self.timeline.selected)))[1]

    def _load_inspector(self):
        c = self.selected_clip()
        self._loading_inspector = True
        if c is None:
            self.insp_stack.setCurrentIndex(0)
            self.insp_title.setText(tr("Proyecto"))
        else:
            self.insp_stack.setCurrentIndex(1)
            self.insp_title.setText({"video": "Vídeo", "audio": "Audio", "image": "Imagen", "text": "Título"}[c.kind])
            visual, timed = c.kind in ("video", "image"), c.kind in ("video", "audio")
            has_sound = c.kind == "audio" or (c.kind == "video" and c.has_audio)
            self._fill_fx(c)
            framed = visual or c.kind == "text"
            for key, on in (("fx", visual), ("frame", framed), ("crop", framed), ("color", visual),
                            ("audio", has_sound),
                            ("fades", True), ("trans", c.kind != "audio"), ("text", c.kind == "text")):
                self.sections[key].setVisible(on)
            form = self.sec_time.layout()
            for wdg, on in ((self.f_dur, not timed), (self.f_in, timed), (self.f_out, timed), (self.f_speed, timed)):
                wdg.setVisible(on)
                form.labelForField(wdg).setVisible(on)
            self.f_start.setValue(c.start)
            self.f_dur.setValue(c.duration)
            self.f_in.setValue(c.in_s)
            self.f_out.setValue(c.out_s)
            self.f_speed.setValue(c.speed)
            self.f_vol.setValue(int(c.volume * 100))
            self.f_mute.setChecked(c.muted)
            self.f_fin.setValue(c.fade_in)
            self.f_fout.setValue(c.fade_out)
            self.f_trans.setCurrentIndex(max(0, self.f_trans.findData(c.transition)))
            self.f_td.setValue(c.transition_d)
            self.f_bri.setValue(int(c.brightness * 100))
            self.f_con.setValue(int(c.contrast * 100))
            self.f_sat.setValue(int(c.saturation * 100))
            self.f_gam.setValue(int(c.gamma * 100))
            self.f_rot.setCurrentIndex(max(0, self.f_rot.findData(c.rotation)))
            self.f_scale.setValue(c.scale * 100)
            self.f_sx.setValue(c.sx * 100)
            self.f_sy.setValue(c.sy * 100)
            self.f_px.setValue(c.pos_x * 100)
            self.f_py.setValue(c.pos_y * 100)
            self.f_ax.setValue(c.anchor_x * 100)
            self.f_ay.setValue(c.anchor_y * 100)
            self.f_angle.setValue(((c.angle + 180) % 360) - 180)
            self.f_opacity.setValue(c.opacity * 100)
            for sp, v in zip(self.f_crop, c.crop):
                sp.setValue(int(v * 100))
            self.f_text.setPlainText(c.text)
            self.f_tsize.setValue(c.text_size)
            self.f_tcolor.setText(c.text_color)
            self.f_tpos.setCurrentIndex(max(0, self.f_tpos.findData(c.text_pos)))
        self._loading_inspector = False

    def _apply_inspector(self, *_):
        if self._loading_inspector:
            return
        c = self.selected_clip()
        if c is None:
            return
        self._push_undo()
        c.start, c.in_s = self.f_start.value(), self.f_in.value()
        if c.kind in ("video", "audio"):
            c.out_s = max(c.in_s + 0.04, self.f_out.value())
            c.speed = self.f_speed.value()
        else:
            c.out_s = c.in_s + max(0.1, self.f_dur.value())  # imágenes y títulos: duración libre
        c.volume, c.muted = self.f_vol.value() / 100, self.f_mute.isChecked()
        c.fade_in, c.fade_out = self.f_fin.value(), self.f_fout.value()
        c.transition, c.transition_d = self.f_trans.currentData(), self.f_td.value()
        c.brightness, c.contrast = self.f_bri.value() / 100, self.f_con.value() / 100
        c.saturation, c.gamma = self.f_sat.value() / 100, self.f_gam.value() / 100
        c.rotation, c.scale = self.f_rot.currentData(), self.f_scale.value() / 100
        c.pos_x, c.pos_y = self.f_px.value() / 100, self.f_py.value() / 100
        c.sx, c.sy = self.f_sx.value() / 100, self.f_sy.value() / 100
        c.anchor_x, c.anchor_y = self.f_ax.value() / 100, self.f_ay.value() / 100
        c.angle, c.opacity = float(self.f_angle.value()), self.f_opacity.value() / 100
        c.crop = [sp.value() / 100 for sp in self.f_crop]
        if c.kind == "text":
            c.text = self.f_text.toPlainText()
            c.text_size = self.f_tsize.value()
            col = QColor(self.f_tcolor.text().strip())
            c.text_color = col.name() if col.isValid() else c.text_color
            c.text_pos = self.f_tpos.currentData()
        for t in self.project.tracks:
            t.sort()
        self._mark()
        self.timeline.update()
        self._show_frame()

    # ------------------------------------------------------------------ efectos y transiciones
    def _fx_target(self, clip_id: str | None) -> Clip | None:
        if clip_id:
            return self.project.find(clip_id)[1]
        return self.selected_clip()

    def apply_effect(self, clip_id: str | None, effect_id: str) -> bool:
        from aero.editors.video import effects as fx

        c = self._fx_target(clip_id)
        if c is None or effect_id not in fx.EFFECTS:
            self.info.setText(tr("Selecciona un clip de vídeo o una imagen para aplicar el efecto"))
            return False
        if c.kind not in fx.EFFECTS[effect_id].kinds:
            self.info.setText(tr("«{v0}» no se puede aplicar a este tipo de clip", v0=fx.EFFECTS[effect_id].name))
            return False
        self._push_undo()
        c.effects.append(fx.new_instance(effect_id))
        self.timeline.selected = {c.id}
        self._effects_changed()
        self.fx_list.setCurrentRow(self.fx_list.count() - 1)
        return True

    def apply_transition(self, clip_id: str | None, tid: str) -> bool:
        from aero.editors.video import effects as fx

        c = self._fx_target(clip_id)
        if c is None or c.kind not in ("video", "image", "text") or tid not in fx.TRANSITIONS:
            self.info.setText(tr("Suelta la transición sobre el inicio de un clip de vídeo, imagen o título"))
            return False
        trk, _c = self.project.find(c.id)
        prev = next((x for x in trk.clips if abs(x.end - c.start) < 0.05 and x is not c), None)
        self._push_undo()
        c.transition = tid
        c.transition_d = round(min(fx.TRANSITIONS[tid].default,
                                   fx.max_duration(c.duration, prev.duration if prev else None)), 2)
        self.timeline.selected = {c.id}
        self.timeline.selected_transition = c.id
        self._effects_changed()
        return True

    def remove_transition(self, clip_id: str) -> None:
        c = self.project.find(clip_id)[1]
        if c is None or c.transition == "none":
            return
        self._push_undo()
        c.transition = "none"
        self.timeline.selected_transition = None
        self._effects_changed()

    def _effects_changed(self):
        self._mark()
        self._load_inspector()
        self.timeline.update()
        self._show_frame()

    def _fill_fx(self, c: Clip):
        from aero.editors.video import effects as fx

        row = self.fx_list.currentRow()
        self.fx_list.blockSignals(True)
        self.fx_list.clear()
        for inst in c.effects:
            e = fx.EFFECTS.get(inst.get("id"))
            it = QListWidgetItem(e.name if e else inst.get("id", "?"))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if inst.get("on", True) else Qt.CheckState.Unchecked)
            it.setToolTip(tr("Marca o desmarca para activar o desactivar"))
            self.fx_list.addItem(it)
        self.fx_list.blockSignals(False)
        self.fx_list.setCurrentRow(min(max(row, 0), self.fx_list.count() - 1) if self.fx_list.count() else -1)
        self._fx_params(self.fx_list.currentRow())

    def _fx_toggled(self, item: QListWidgetItem):
        c = self.selected_clip()
        if c is None or self._loading_inspector:
            return
        i = self.fx_list.row(item)
        on = item.checkState() == Qt.CheckState.Checked
        if 0 <= i < len(c.effects) and c.effects[i].get("on", True) != on:
            self._push_undo()
            c.effects[i]["on"] = on
            self._mark()
            self._show_frame()

    def _fx_params(self, row: int):
        from aero.editors.video import effects as fx
        from aero.ui.pages.theme_studio import ValueSlider

        while self.fx_params_lay.rowCount():
            self.fx_params_lay.removeRow(0)
        c = self.selected_clip()
        if c is None or not (0 <= row < len(c.effects)):
            return
        inst = c.effects[row]
        e = fx.EFFECTS.get(inst.get("id"))
        if e is None:
            return
        for prm in e.params:
            span = prm.hi - prm.lo
            vs = ValueSlider((float(inst["params"].get(prm.key, prm.default)) - prm.lo) / span, prm.label,
                             minimum=0, maximum=100)
            vs.changed.connect(lambda v, k=prm.key, lo=prm.lo, sp=span, i=row: self._fx_set(i, k, lo + v * sp))
            self.fx_params_lay.addRow(prm.label, vs)
        if not e.params:
            self.fx_params_lay.addRow(label(tr("Sin ajustes"), "caption"))

    def _fx_set(self, i: int, key: str, value: float):
        c = self.selected_clip()
        if c is None or not (0 <= i < len(c.effects)):
            return
        self._push_undo()
        c.effects[i]["params"][key] = round(value, 4)
        self._mark()
        self._fx_preview_timer.start()

    def _fx_move(self, delta: int):
        c, i = self.selected_clip(), self.fx_list.currentRow()
        j = i + delta
        if c is None or not (0 <= i < len(c.effects)) or not (0 <= j < len(c.effects)):
            return
        self._push_undo()
        c.effects[i], c.effects[j] = c.effects[j], c.effects[i]
        self.fx_list.setCurrentRow(j)
        self._effects_changed()

    def _fx_remove(self):
        c, i = self.selected_clip(), self.fx_list.currentRow()
        if c is None or not (0 <= i < len(c.effects)):
            return
        self._push_undo()
        del c.effects[i]
        self._effects_changed()

    def _fx_reset(self):
        from aero.editors.video import effects as fx

        c, i = self.selected_clip(), self.fx_list.currentRow()
        if c is None or not (0 <= i < len(c.effects)) or c.effects[i]["id"] not in fx.EFFECTS:
            return
        self._push_undo()
        c.effects[i]["params"] = fx.EFFECTS[c.effects[i]["id"]].defaults()
        self._effects_changed()

    def copy_effects(self):
        import copy

        c = self.selected_clip()
        if c is not None:
            self._fx_clipboard = copy.deepcopy(c.effects)
            self.info.setText(tr("{v0} efectos copiados", v0=len(c.effects)))

    def paste_effects(self, clip_id: str | None = None):
        import copy

        c = self._fx_target(clip_id)
        if c is None or not self._fx_clipboard or c.kind not in ("video", "image"):
            return
        self._push_undo()
        c.effects += copy.deepcopy(self._fx_clipboard)
        self._effects_changed()

    def _render_fx_preview(self):
        """Fotograma exacto (efectos y transiciones) en el cabezal, en segundo plano y a resolución reducida."""
        from aero.core import tools
        from aero.core.tasks import tasks

        t = self.timeline.playhead
        layers = self._visual_layers(t)
        needs = any(c.effects and any(x.get("on", True) for x in c.effects) for c, _z in layers) or any(
            c.transition != "none" and c.start <= t < c.start + c.transition_d for c, _z in layers)
        if not needs or self._playing:
            self.preview.show_still(None)
            return
        ff = tools.find_tool("ffmpeg")
        if ff is None:
            return
        from aero.editors.video.export import build_command

        fd, out = tempfile.mkstemp(suffix=".png", prefix="aero_fx_")
        os.close(fd)
        args, _tot, temps = build_command(self.project, out, start=t, end=t + 2 / self.project.fps, scale_to=640,
                                          ffmpeg=ff, still=True)
        key = (t, self.project.to_json())
        self._fx_key = key
        self.preview.busy(True)

        def job():
            import subprocess

            subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL,
                           creationflags=0x08000000 if os.name == "nt" else 0, timeout=60)
            for f in temps:
                try:
                    os.remove(f)
                except OSError:
                    pass
            return out

        def done(path):
            img = QImage(path)
            try:
                os.remove(path)
            except OSError:
                pass
            if getattr(self, "_fx_key", None) == key and not self._playing:
                self.preview.show_still(img if not img.isNull() else None)
            self.preview.busy(False)

        tasks().submit(job, "background", done, lambda _e: self.preview.busy(False), self)

    def _layer(self, delta: int):
        c = self.selected_clip()
        if c is None:
            return
        self._push_undo()
        self.project.to_layer(c.id, delta)
        self._tracks_changed()

    def _tracks_changed(self):
        self.timeline.setMinimumHeight(26 + 56 * len(self.project.tracks) + 4)
        self._mark()
        self._sync()
        self._show_frame()

    def _timeline_request(self, action: str, target):
        """Menú contextual de la línea de tiempo (pistas y clips)."""
        if action in ("split", "delete", "layer_up", "layer_down"):
            self.timeline.selected = {target}
            if action == "split":
                self.split()
            elif action == "delete":
                self.delete()
            else:
                self._layer(-1 if action == "layer_up" else 1)
            return
        if action == "drop_effect":
            self.apply_effect(target[0], target[1])
            return
        if action == "drop_transition":
            self.apply_transition(target[0], target[1])
            return
        if action == "transition_d":
            from aero.editors.video import effects as fx

            cid, d = target
            c = self.project.find(cid)[1]
            if c is not None:
                trk, _c = self.project.find(cid)
                prev = next((x for x in trk.clips if abs(x.end - c.start) < 0.05 and x is not c), None)
                c.transition_d = round(max(0.1, min(d, fx.max_duration(c.duration, prev.duration if prev else None))), 2)
                self._mark()
                self._load_inspector()
            return
        if action == "remove_transition":
            self.remove_transition(target)
            return
        if action == "add_text":
            self.seek(float(target))
            self.add_text()
            return
        self._push_undo()
        if action == "track_up":
            self.project.move_track(target, -1)
        elif action == "track_down":
            self.project.move_track(target, 1)
        elif action == "track_toggle":
            if target.kind == "audio":
                target.muted = not target.muted
            else:
                target.hidden = not target.hidden
        elif action == "track_remove":
            if target.clips and QMessageBox.question(self, tr("Eliminar pista"), tr("La pista tiene clips. ¿Eliminarla?")) \
                    != QMessageBox.StandardButton.Yes:
                return
            if not self.project.remove_track(target):
                self.info.setText(tr("Tiene que quedar al menos una pista de cada tipo"))
                return
        self._tracks_changed()

    def _project_settings(self, *_):
        h = self.res.currentData()
        self._push_undo()
        self.project.set_aspect(self.aspect.currentText(), h)
        self.project.fps = self.fps.currentData()
        self.preview.resize_scene()
        self._mark()

    # ------------------------------------------------------------------ medios
    def import_media(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("Importar medios"), "", MEDIA_FILTER)
        if files:
            self.import_paths(files)

    def import_paths(self, paths: list[str], add: bool = False):
        from aero.core.tasks import tasks

        for path in paths:
            path = os.path.abspath(path)
            if any(self.bin.item(i).data(Qt.ItemDataRole.UserRole) == path for i in range(self.bin.count())):
                if add:
                    self.add_to_timeline(path)
                continue
            info = media_info(path) if os.path.exists(path) else {}
            if not info or (info.get("kind") != "image" and not info.get("has_video") and not info.get("has_audio")):
                # Archivo inexistente, dañado o sin pistas: no se añade (no se fingen clips vacíos)
                self.info.setText(tr("No se puede usar «{v0}»: no tiene audio ni vídeo legibles", v0=Path(path).name))
                continue
            if info.get("kind") == "image" and QImage(path).isNull():
                self.info.setText(tr("No se puede leer la imagen «{v0}»", v0=Path(path).name))
                continue
            it = QListWidgetItem(Path(path).name)
            it.setData(Qt.ItemDataRole.UserRole, path)
            self.bin.addItem(it)
            it.setData(Qt.ItemDataRole.UserRole + 1, json.dumps(info))
            it.setToolTip(f"{path}\n{human_time(info['duration'])}" if info["kind"] != "image" else path)
            if add:
                self.add_to_timeline(path)
            # Miniatura y forma de onda en segundo plano
            if info["kind"] == "image":
                img = QImage(path)
                if not img.isNull():
                    self._set_thumb(path, img.scaledToHeight(72, Qt.TransformationMode.SmoothTransformation))
            elif info.get("has_video"):
                from aero.editors.video.media import thumbnail_png

                t = min(1.0, info["duration"] / 2)
                tasks().submit(lambda p=path, tt=t: thumbnail_png(p, tt), "background",
                               lambda data, p=path: self._set_thumb(p, QImage.fromData(data)), None, self)
            if info.get("has_audio"):
                from aero.editors.video.media import waveform

                tasks().submit(lambda p=path: waveform(p), "background",
                               lambda peaks, p=path: self._set_wave(p, peaks), None, self)

    def _set_thumb(self, path: str, img: QImage):
        if img.isNull():
            return
        self.timeline.thumbs[path] = img
        for i in range(self.bin.count()):
            it = self.bin.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == path:
                it.setIcon(QPixmap.fromImage(img))
        self.timeline.update()

    def _set_wave(self, path: str, peaks: list[float]):
        self.timeline.waves[path] = peaks
        self.timeline.update()

    def add_to_timeline(self, path: str, track=None, at: float | None = None):
        info = None
        for i in range(self.bin.count()):
            it = self.bin.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == path:
                info = json.loads(it.data(Qt.ItemDataRole.UserRole + 1))
        if info is None:
            self.import_paths([path], add=True)  # se importa y, si es válido, se añade
            return
        clip = clip_from_media(path, info)
        want = "audio" if clip.kind == "audio" else "video"
        self._push_undo()
        if track is None or track.kind != want:
            track = self._auto_track(clip, at)
        if track is None:
            return
        self.project.add_clip(track, clip, at)
        self.timeline.selected = {clip.id}
        self._mark()
        self._load_inspector()
        self._sync()

    def _auto_track(self, clip: Clip, at: float | None):
        """Pista para un medio añadido sin indicar dónde:
        * vídeo: al final de la pista base (V1);
        * audio: la primera pista de audio libre en ese instante (música, voz y efectos se superponen);
        * imagen: encima del vídeo que haya en ese instante (si no hay hueco arriba, se crea una pista)."""
        from aero.editors.video.project import Track

        t = self.timeline.playhead if at is None else at
        videos = [x for x in self.project.tracks if x.kind == "video"]  # de arriba abajo
        if clip.kind == "video":
            return videos[-1] if videos else None

        def free(trk: Track) -> bool:
            return all(c.end <= t or c.start >= t + clip.duration for c in trk.clips)

        if clip.kind == "audio":
            audios = [x for x in self.project.tracks if x.kind == "audio"]
            if at is None:
                return audios[0] if audios else None  # sin posición: a continuación en la primera pista
            for trk in audios:
                if free(trk):
                    return trk
            trk = Track("audio", f"A{len(audios) + 1}")
            self.project.tracks.append(trk)
            return trk
        # Imagen: la primera pista libre por encima de lo que se ve en ese instante
        busy = [i for i, trk in enumerate(videos) if not free(trk)]
        candidates = videos[: min(busy)] if busy else videos
        for trk in reversed(candidates):
            if free(trk):
                return trk
        trk = Track("video", f"V{len(videos) + 1}")
        self.project.tracks.insert(0, trk)
        self.timeline.setMinimumHeight(26 + 56 * len(self.project.tracks) + 4)
        return trk

    def set_proxies(self, on: bool):
        from aero.core.tasks import tasks
        from aero.editors.video.media import make_proxy

        self.use_proxies = on
        if not on:
            self._current_src = ""
            self._show_frame()
            return
        srcs = {c.src for _t, c in self.project.all_clips() if c.kind == "video" and not c.missing()}
        pending = self.__dict__.setdefault("_proxy_pending", set())
        for s in srcs - set(self.proxies) - pending:
            pending.add(s)
            self.info.setText(tr("Creando proxies…"))
            tasks().submit(lambda p=s: make_proxy(p), "heavy",
                           lambda out, p=s: (pending.discard(p), self.proxies.__setitem__(p, out),
                                             self.info.setText(tr("Proxies listos"))),
                           lambda e, p=s: (pending.discard(p), self.info.setText(f"Proxy: {e}")), self)

    # ------------------------------------------------------------------ edición
    def _snapshot(self) -> str:
        return self.project.to_json()

    def _push_undo(self):
        snap = self._snapshot()
        if not self._undo or self._undo[-1] != snap:
            self._undo.append(snap)
            del self._undo[:-100]
            self._redo.clear()

    def _restore(self, snap: str):
        fd, tmp = tempfile.mkstemp(suffix=PROJECT_EXT)
        os.close(fd)
        Path(tmp).write_text(snap, encoding="utf-8")
        p = Project.load(tmp)
        os.remove(tmp)
        p.path = self.project.path
        self.project = p
        self.timeline.project = p
        self.timeline.selected &= {c.id for _t, c in p.all_clips()}
        self._mark()
        self._sync()

    def undo(self):
        if self._undo:
            self._redo.append(self._snapshot())
            self._restore(self._undo.pop())

    def redo(self):
        if self._redo:
            self._undo.append(self._snapshot())
            self._restore(self._redo.pop())

    def _timeline_changed(self):
        self._push_undo()
        self._mark()
        self._load_inspector()
        self._sync()

    def split(self):
        t = self.timeline.playhead
        targets = list(self.timeline.selected) or [c.id for _tr, c in self.project.all_clips() if c.start < t < c.end]
        self._push_undo()
        for cid in targets:
            self.project.split(cid, t)
        self._mark()
        self._sync()

    def delete(self):
        sel_tr = getattr(self.timeline, "selected_transition", None)
        if sel_tr:
            self.remove_transition(sel_tr)
            return
        if not self.timeline.selected:
            return
        self._push_undo()
        self.project.delete(list(self.timeline.selected))
        self.timeline.selected.clear()
        self._mark()
        self._load_inspector()
        self._sync()

    def add_text(self):
        track = next((t for t in self.project.tracks if t.kind == "video"), None)
        self._push_undo()
        c = self.project.add_clip(track, Clip(kind="text", text="Título", out_s=3.0, fade_in=0.3, fade_out=0.3),
                                  at=self.timeline.playhead)
        self.timeline.selected = {c.id}
        self._mark()
        self._load_inspector()
        self._sync()

    def add_track(self, kind: str):
        from aero.editors.video.project import Track

        self._push_undo()
        n = sum(1 for t in self.project.tracks if t.kind == kind) + 1
        if kind == "video":
            self.project.tracks.insert(0, Track("video", f"V{n}"))
        else:
            self.project.tracks.append(Track("audio", f"A{n}"))
        self.timeline.setMinimumHeight(26 + 56 * len(self.project.tracks) + 4)
        self._mark()
        self._sync()

    # ------------------------------------------------------------------ reproducción
    def _src_for(self, c: Clip) -> str:
        return self.proxies.get(c.src, c.src) if self.use_proxies else c.src

    def seek(self, t: float):
        self.timeline.set_playhead(min(max(0.0, t), max(0.0, self.project.duration)))

    def _playhead_moved(self, t: float):
        self._update_time()
        if not self._playing:
            self._show_frame()

    def _visual_layers(self, t: float) -> list[tuple[Clip, float]]:
        """Vídeos e imágenes visibles en t, de abajo arriba (las pistas de arriba tapan a las de abajo)."""
        out = []
        for z, trk in enumerate(self.project.video_tracks_bottom_up()):
            if trk.hidden:
                continue
            for c in trk.clips:
                if c.kind in ("video", "image") and c.start <= t < c.end and not c.missing():
                    out.append((c, float(z)))
        return out

    def _layer_key(self, t: float) -> tuple:
        texts = tuple(x.id for trk in self.project.tracks if trk.kind == "video" and not trk.hidden for x in trk.clips
                      if x.kind == "text" and x.start <= t < x.end)
        return tuple(c.id for c, _z in self._visual_layers(t)), texts

    def _show_frame(self):
        """Compone la vista previa en el cabezal: el vídeo superior, las imágenes encima o debajo según su pista
        (con posición, escala, giro y opacidad) y los textos. Para la mezcla exacta de varios vídeos a la vez
        está «Vista previa exacta»."""
        t = self.timeline.playhead
        layers = self._visual_layers(t)
        texts = [x for trk in self.project.tracks if trk.kind == "video" and not trk.hidden for x in trk.clips
                 if x.kind == "text" and x.start <= t < x.end]
        self.preview.show_texts(texts)
        self.preview.show_images([(c, z) for c, z in layers if c.kind == "image"])
        videos = [(c, z) for c, z in layers if c.kind == "video"]
        self._fx_preview_timer.start()
        if not videos:
            self.preview.set_video(None)
            if self._playing:
                self.player.pause()
            return
        c, z = videos[-1]
        src = self._src_for(c)
        if src != self._current_src:
            self._current_src = src
            self.player.setVideoOutput(self.preview.video)
            self.player.setSource(QUrl.fromLocalFile(src))
        self.preview.set_video(c, *self._src_dims(c), z)
        self.player.setPlaybackRate(c.speed)
        self.audio_out.setMuted(c.muted or not c.has_audio)
        self.audio_out.setVolume(min(1.0, c.volume))
        pos = int((c.in_s + (t - c.start) * c.speed) * 1000)
        if abs(self.player.position() - pos) > 120 or not self._playing:
            self.player.setPosition(pos)
        if self._playing and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self.player.play()
        elif not self._playing and self.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
            self.player.pause()  # en pausa el reproductor sí entrega el fotograma de esa posición
        self._clip_shown = c.id
        self._fx_preview_timer.start()

    def _music_at(self, t: float):
        for trk in self.project.tracks:
            if trk.kind == "audio" and not trk.muted:
                for c in trk.clips:
                    if c.start <= t < c.end and not c.missing() and not c.muted:
                        return c
        return None

    def toggle_play(self):
        if self._playing:
            self._playing = False
            self._tick.stop()
            self.player.pause()
            self.music.pause()
            self.play_btn.set_icon_name("play")
        else:
            if self.timeline.playhead >= self.project.duration - 0.05:
                self.seek(0)
            self._playing = True
            self.preview.show_still(None)
            self._last_tick = time.perf_counter()
            self._tick.start()
            self._show_frame()
            self.play_btn.set_icon_name("pause")

    def _advance(self):
        now = time.perf_counter()
        dt = now - self._last_tick
        self._last_tick = now
        t = self.timeline.playhead + dt
        if t >= self.project.duration:
            self.toggle_play()
            return
        prev = self._layer_key(self.timeline.playhead)
        self.timeline.set_playhead(t)
        self.timeline.ensure_visible(t)
        if self._layer_key(t) != prev:
            self._show_frame()  # entra o sale algún clip: se recompone; si no, el vídeo sigue solo
        m = self._music_at(t)
        if m is None:
            self.music.pause()
        else:
            if m.src != self._music_src:
                self._music_src = m.src
                self.music.setSource(QUrl.fromLocalFile(m.src))
            self.music_out.setVolume(min(1.0, m.volume))
            want = int((m.in_s + (t - m.start) * m.speed) * 1000)
            if abs(self.music.position() - want) > 250:
                self.music.setPosition(want)
            if self.music.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                self.music.play()

    def exact_preview(self):
        """Renderiza 6 s desde el cabezal (baja resolución) con el motor de exportación y lo abre."""
        from aero.core import tools
        from aero.core.tasks import tasks

        ff = tools.find_tool("ffmpeg")
        if not ff:
            QMessageBox.information(self, tr("Vista previa"), tr("Hace falta FFmpeg (Ajustes › Conversión)."))
            return
        t = self.timeline.playhead
        out = os.path.join(tempfile.gettempdir(), f"aero_vista_previa_{os.getpid()}.mp4")
        args, _total, temps = vexport.build_command(self.project, out, start=t, end=t + 6, scale_to=640, fast=True,
                                                    ffmpeg=ff)
        self.info.setText(tr("Renderizando vista previa exacta…"))

        def job():
            import subprocess

            r = subprocess.run(args, capture_output=True, timeout=300,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for f in temps:
                try:
                    os.remove(f)
                except OSError:
                    pass
            if r.returncode != 0:
                raise RuntimeError(r.stderr.decode("utf-8", "replace")[-300:])
            return out

        def done(path):
            self.info.setText(tr("Vista previa exacta lista"))
            if self.controller is not None:
                self.controller.open_media_window(path)

        tasks().submit(job, "heavy", done, lambda e: self.info.setText(tr("Vista previa: {e}", e=e)), self)

    # ------------------------------------------------------------------ proyecto
    def new_project(self):
        if not self._confirm_discard():
            return
        self.project = Project()
        self.timeline.project = self.project
        self.project_path = ""
        self.bin.clear()
        self._undo.clear()
        self.dirty = False
        self._sync()

    def open_project(self):
        if not self._confirm_discard():
            return
        f, _ = QFileDialog.getOpenFileName(self, tr("Abrir proyecto"), "", f"Proyecto de vídeo (*{PROJECT_EXT})")
        if f:
            self.load_project(f)

    def load_project(self, path: str):
        try:
            p = Project.load(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, tr("Abrir proyecto"), tr("No se pudo abrir: {e}", e=e))
            return
        self.project = p
        self.project_path = path
        self.timeline.project = p
        self.timeline.setMinimumHeight(26 + 56 * len(p.tracks) + 4)
        self.bin.clear()
        self.import_paths(sorted({c.src for _t, c in p.all_clips() if c.kind != "text" and not c.missing()}))
        self.dirty = False
        missing = p.missing_media()
        self._sync()
        if missing:
            QMessageBox.warning(self, tr("Faltan medios"), tr("Estos archivos se han movido o eliminado; sus clips aparecen "
                                "en rojo y no se exportarán:\n\n") + "\n".join(missing[:12]))

    def save_project(self):
        if not self.project_path:
            f, _ = QFileDialog.getSaveFileName(self, tr("Guardar proyecto"), "Proyecto" + PROJECT_EXT,
                                               f"Proyecto de vídeo (*{PROJECT_EXT})")
            if not f:
                return
            if not f.lower().endswith(PROJECT_EXT):
                f += PROJECT_EXT
            self.project_path = f
        self.project.save(self.project_path)
        self.dirty = False
        self._sync()

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        return QMessageBox.question(self, tr("Proyecto"), tr("Hay cambios sin guardar. ¿Continuar sin guardarlos?")) \
            == QMessageBox.StandardButton.Yes

    def _mark(self):
        self.dirty = True

    def _update_time(self):
        self.time_lbl.setText(f"{fmt_time(self.timeline.playhead, True, self.project.fps)} / "
                              f"{fmt_time(self.project.duration)}")

    def _sync(self):
        name = Path(self.project_path).stem if self.project_path else tr("Proyecto sin título")
        self.title.setText(name + (" •" if self.dirty else ""))
        p = self.project
        missing = p.missing_media()
        self.info.setText(tr("{width}×{height} · {fps:g} fps · {v3}", width=p.width, height=p.height, fps=p.fps, v3=fmt_time(p.duration)) +
                          (tr(" · faltan {v0} medios", v0=len(missing)) if missing else ""))
        self.setWindowTitle(tr("{name} · Editor de vídeo · AERO Player", name=name))
        visible = max(1.0, (self.timeline.width() - 92) / self.timeline.pps)
        self.hscroll.setRange(0, int(max(0.0, p.duration + 5 - visible) * 10))
        self.timeline.update()
        self._update_time()
        if self.use_proxies:
            self.set_proxies(True)   # clips nuevos: su proxy se crea en segundo plano
        if not self._playing:
            self._show_frame()

    # ------------------------------------------------------------------ exportar
    def export_dialog(self):
        if self.project.duration <= 0:
            QMessageBox.information(self, tr("Exportar"), tr("Añade algún clip a la línea de tiempo."))
            return
        ExportDialog(self).exec()

    def closeEvent(self, e):
        if not self._confirm_discard():
            e.ignore()
            return
        self._tick.stop()
        self._fx_preview_timer.stop()
        # Se sueltan los archivos y las salidas de audio antes de destruir la ventana: así los hilos de audio
        # de Qt Multimedia terminan ordenadamente (un bloqueo intermitente aparecía al abrir otro editor justo
        # después con uno de ellos aún vivo).
        for player in (self.player, self.music):
            player.stop()
            player.setSource(QUrl())
            player.setAudioOutput(None)
        super().closeEvent(e)
        if self.controller is not None:
            self.controller.editor_closed(self)


class ExportDialog(TrDialog):
    """Formato, códec, resolución, fps, calidad y destino; progreso y cancelación (FFmpeg en otro proceso)."""

    def __init__(self, ed: VideoEditor):
        super().__init__(ed)
        self.ed = ed
        self.setWindowTitle(tr("Exportar vídeo"))
        self.proc: QProcess | None = None
        self.held = False
        self.temps: list[str] = []
        p = ed.project
        ex = p.export
        self.format = QComboBox()
        for k, (t, _c) in vexport.FORMATS.items():
            self.format.addItem(t, k)
        self.format.setCurrentIndex(max(0, self.format.findData(ex.get("format", "mp4"))))
        self.codec = QComboBox()
        self.format.currentIndexChanged.connect(self._codecs)
        self.res = QComboBox()
        self.res.addItem(tr("Proyecto ({width}×{height})", width=p.width, height=p.height), 0)
        for h in (2160, 1080, 720, 480):
            if h < max(p.width, p.height):
                self.res.addItem(f"{h}p", h)
        self.fps = QComboBox()
        for v in (p.fps, 24.0, 25.0, 30.0, 60.0):
            if self.fps.findData(v) < 0:
                self.fps.addItem(f"{v:g} fps", v)
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(14, 36)
        self.quality.setInvertedAppearance(True)
        self.quality.setValue(int(ex.get("quality", 23)))
        self.audio = QComboBox()
        for k in (96, 128, 192, 256, 320):
            self.audio.addItem(f"{k} kbps", k)
        self.audio.setCurrentIndex(max(0, self.audio.findData(int(ex.get("audio_kbps", 192)))))
        folder = ex.get("folder") or str(Path(ed.project_path).parent if ed.project_path else Path.home() / "Videos")
        self.dest = QLineEdit(str(Path(folder) / ((Path(ed.project_path).stem if ed.project_path else "Montaje"))))
        browse = QPushButton("…")
        browse.clicked.connect(self._browse)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.status = label("", "caption")
        self.go = QPushButton(tr("Exportar"))
        self.go.setProperty("kind", "primary")
        self.go.clicked.connect(self.start)
        self.cancel = QPushButton(tr("Cancelar"))
        self.cancel.clicked.connect(self.stop)
        form = QFormLayout()
        form.addRow(tr("Formato"), self.format)
        form.addRow(tr("Códec"), self.codec)
        form.addRow(tr("Resolución"), self.res)
        form.addRow(tr("Fotogramas"), self.fps)
        form.addRow(tr("Calidad"), h_layout(label("menor", "caption"), self.quality, label("mayor", "caption")))
        form.addRow(tr("Audio"), self.audio)
        form.addRow(tr("Destino"), h_layout(self.dest, browse, spacing=4))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addLayout(form)
        missing = p.missing_media()
        if missing:
            lay.addWidget(label(tr("Aviso: faltan {v0} medios; sus clips se omiten.", v0=len(missing)), "caption"))
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addLayout(h_layout(None, self.cancel, self.go))
        self._codecs()
        self.setMinimumWidth(520)

    def _codecs(self):
        fmt = self.format.currentData()
        self.codec.clear()
        for c in vexport.FORMATS[fmt][1]:
            self.codec.addItem(vexport.CODECS[c], c)

    def _browse(self):
        fmt = self.format.currentData()
        f, _ = QFileDialog.getSaveFileName(self, tr("Exportar como"), self.dest.text() + "." + fmt, f"*.{fmt}")
        if f:
            self.dest.setText(str(Path(f).with_suffix("")))

    def out_path(self) -> str:
        base = self.dest.text().strip() or str(Path.home() / "Montaje")
        out = base + "." + self.format.currentData()
        from aero.core.convert_spec import unique_path

        return str(unique_path(Path(out)))

    def start(self, path: str | None = None):
        from aero.core import tools
        from aero.core.tasks import tasks

        ff = tools.find_tool("ffmpeg")
        if not ff:
            self.status.setText(tr("Hace falta FFmpeg (Ajustes › Conversión)."))
            return
        if not tasks().acquire("heavy"):
            self.status.setText(tr("Hay otra tarea pesada en marcha; se exportará en cuanto termine."))
            tasks().slot_freed.connect(self._retry)
            return
        self.held = True
        p = self.ed.project
        h = self.res.currentData()
        fps0 = p.fps
        p.fps = self.fps.currentData()
        self.target = path or self.out_path()
        Path(self.target).parent.mkdir(parents=True, exist_ok=True)
        args, self.total, self.temps = vexport.build_command(
            p, self.target, self.format.currentData(), self.codec.currentData(), self.quality.value(),
            self.audio.currentData(), scale_to=h or 0, ffmpeg=ff)
        p.fps = fps0
        p.export.update({"format": self.format.currentData(), "codec": self.codec.currentData(),
                         "quality": self.quality.value(), "audio_kbps": self.audio.currentData(),
                         "folder": str(Path(self.target).parent)})
        self.proc = QProcess(self)
        from aero.core import activity as act

        self._aid = act.activities().start(Path(path or self.out_path()).name, "export", cancel=self.stop)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.go.setEnabled(False)
        self.status.setText(tr("Exportando…"))
        self._t0 = time.monotonic()
        self.proc.start(args[0], args[1:])

    def _retry(self, kind: str):
        from aero.core.tasks import tasks

        if kind == "heavy" and self.proc is None:
            tasks().slot_freed.disconnect(self._retry)
            self.start()

    def _read(self):
        chunk = bytes(self.proc.readAllStandardOutput().data()).decode("utf-8", "replace")
        frac = vexport.parse_progress(chunk, self.total)
        if frac is not None:
            self.progress.setValue(int(frac * 1000))
            el = time.monotonic() - self._t0
            if frac > 0.02:
                self.status.setText(tr("Exportando… {v0:.0f} % · quedan {v1}", v0=frac * 100, v1=human_time(el / frac - el)))

    def _finished(self, code, _status):
        from aero.core.tasks import tasks

        if self.held:
            self.held = False
            tasks().release("heavy")
        for f in self.temps:
            try:
                os.remove(f)
            except OSError:
                pass
        err = bytes(self.proc.readAllStandardError().data()).decode("utf-8", "replace") if self.proc else ""
        self.go.setEnabled(True)
        if getattr(self, "_cancelled", False):
            try:
                os.remove(self.target)
            except OSError:
                pass
            self.status.setText(tr("Exportación cancelada."))
        elif code == 0:
            self.progress.setValue(1000)
            self.status.setText(tr("Listo: {target}", target=self.target))
        else:
            self.status.setText(tr("Error al exportar: ") + (err.strip().splitlines() or ["desconocido"])[-1][:200])
        self.result_code = code
        aid, self._aid = getattr(self, "_aid", None), None
        if aid:
            from aero.core import activity as act

            state = act.DONE if code == 0 else (act.CANCELLED if getattr(self, "_cancelled", False) else act.ERROR)
            act.activities().finish(aid, state, self.target if code == 0 else "",
                                    "" if code == 0 else self.status.text())
        # El proceso se libera con el diálogo (nunca deleteLater dentro de finished)

    def stop(self):
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            self._cancelled = True
            self.proc.kill()
        else:
            self.reject()

    def closeEvent(self, e):
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            self.stop()
            self.proc.waitForFinished(3000)
        super().closeEvent(e)


def open_editor(path: str = "", controller=None) -> VideoEditor:
    w = VideoEditor(path, controller)
    w.resize(1440, 900)
    w.show()
    w.raise_()
    w.activateWindow()
    return w

