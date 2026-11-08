"""Página del reproductor: vídeo, visualizador o portada grande, y panel de cola."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QListWidget, QListWidgetItem, QMenu, QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from aero.ui.glasswindow import TrDialog
from aero.core.formats import human_time
from aero.player.engine import PlayerEngine
from aero.ui.glass import CoverArt, GlassPanel, IconButton, h_layout, label, opaque_video, tm, v_layout
from aero.ui.visualizer import Visualizer
from aero.i18n import tr


class VideoSurface(QVideoWidget):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, e):
        self.double_clicked.emit()


class NowPlayingView(QWidget):
    """Portada grande con título; se muestra cuando el visualizador está desactivado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cover = CoverArt(300, 22)
        self.title = label("", "h1", wrap=True)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.meta = label("", "muted", wrap=True)
        self.meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tech = label("", "caption")
        self.tech.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setLayout(v_layout(None, h_layout(None, self.cover, None), 18, self.title, self.meta, self.tech, None,
                                margins=(30, 10, 30, 10)))

    def resizeEvent(self, e):
        side = max(120, min(340, int(min(self.width() * 0.6, self.height() - 190))))
        self.cover.setFixedSize(side, side)
        self.cover.set_image(getattr(self, "_img", None))

    def set_track(self, info):
        if info is None:
            self.title.setText("")
            self.meta.setText("")
            self.tech.setText("")
            self._img = None
            self.cover.set_image(None)
            return
        self._img = info.cover
        self.cover.placeholder = "video" if info.kind == "video" else "music"
        self.cover.set_image(info.cover)
        self.title.setText(info.display_title)
        self.meta.setText(" · ".join(x for x in (info.artist, info.album) if x))
        ex = info.extra
        parts = [Path(info.path).suffix.upper().lstrip(".")]
        if ex.get("sample_rate"):
            parts.append(f"{ex['sample_rate'] / 1000:g} kHz")
        if ex.get("bits_per_sample"):
            parts.append(f"{ex['bits_per_sample']} bits")
        if ex.get("bitrate"):
            parts.append(f"{ex['bitrate'] // 1000} kbps")
        if info.duration:
            parts.append(human_time(info.duration))
        self.tech.setText(" · ".join(parts))


class QueuePanel(GlassPanel):
    def __init__(self, engine: PlayerEngine, parent=None):
        super().__init__(parent, radius=18)
        self.engine = engine
        self.setFixedWidth(300)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda it: engine.jump_to(self.list.row(it)))
        self.list.model().rowsMoved.connect(self._moved)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.count = label("", "caption")
        clear = IconButton("trash", tr("Vaciar la cola"), 16, button=30)
        clear.clicked.connect(engine.clear_queue)
        self.save_btn = IconButton("list_add", tr("Guardar la cola como lista"), 16, button=30)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 8, 12)
        lay.addLayout(h_layout(label("Cola", "h3"), None, self.save_btn, clear))
        lay.addWidget(self.count)
        lay.addWidget(self.list, 1)
        engine.queue_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        e = self.engine
        self.list.blockSignals(True)
        self.list.clear()
        for i, path in enumerate(e.queue):
            it = QListWidgetItem(("▶  " if i == e.index else "     ") + Path(path).stem)
            it.setToolTip(path)
            if i == e.index:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setForeground(Qt.GlobalColor.white if tm().theme.dark else Qt.GlobalColor.black)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self.count.setText(f"{len(e.queue)}" if e.queue else "")
        if 0 <= e.index < self.list.count():
            self.list.scrollToItem(self.list.item(e.index), QAbstractItemView.ScrollHint.PositionAtCenter)

    def _moved(self, _parent, start, _end, _dest, row):
        dst = row if row < start else row - 1
        self.engine.move_in_queue(start, dst)

    def _menu(self, pos):
        rows = sorted({i.row() for i in self.list.selectedIndexes()})
        if not rows:
            return
        m = QMenu(self)
        m.addAction(tr("Reproducir"), lambda: self.engine.jump_to(rows[0]))
        m.addAction(tr("Quitar de la cola"), lambda: self.engine.remove_from_queue(rows))
        m.exec(self.list.mapToGlobal(pos))


class SubtitleDialog(TrDialog):
    def __init__(self, engine: PlayerEngine, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Subtítulos"))
        form = QFormLayout(self)
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-600, 600)
        self.offset.setSingleStep(0.1)
        self.offset.setDecimals(1)
        self.offset.setSuffix(" s")
        self.offset.setValue(engine.sub_offset_ms / 1000)
        self.offset.setToolTip(tr("Positivo: los subtítulos aparecen más tarde"))
        form.addRow(tr("Desfase:"), self.offset)
        self.size = QComboBox()
        for k, v in (("Pequeño", 0.8), ("Normal", 1.0), ("Grande", 1.25), ("Muy grande", 1.5)):
            self.size.addItem(k, v)
        idx = self.size.findData(settings.get("subtitle_scale"))
        self.size.setCurrentIndex(max(0, idx))
        form.addRow(tr("Tamaño (subtítulos externos):"), self.size)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class PlayerPage(QWidget):
    fullscreen_requested = Signal()
    close_requested = Signal()

    def __init__(self, engine: PlayerEngine, settings, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings
        self.stage = QWidget()
        self.stack = QStackedWidget()
        self.video = VideoSurface()
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        opaque_video(self.video)
        self.video.double_clicked.connect(self.fullscreen_requested)
        engine.player.setVideoOutput(self.video)
        self.visualizer = Visualizer(engine.analyzer)
        self.visualizer.configure(settings)
        self.visualizer.set_scene_key(settings.get("visualizer_key"))
        self.visualizer.mouseDoubleClickEvent = lambda e: self.fullscreen_requested.emit()
        self.now = NowPlayingView()
        for w in (self.now, self.video, self.visualizer):
            self.stack.addWidget(w)

        # Barra superior de la escena
        self.scene_box = QPushButton(tr("Visualizadores"))
        self.scene_box.setIcon(tm().icon("visualizer", 16))
        self.scene_box.setAccessibleName(tr("Galería de visualizadores"))
        self.scene_box.clicked.connect(self._gallery)
        self.aspect = QComboBox()
        for text, mode in (("Ajustar", Qt.AspectRatioMode.KeepAspectRatio),
                           ("Rellenar", Qt.AspectRatioMode.KeepAspectRatioByExpanding),
                           ("Estirar", Qt.AspectRatioMode.IgnoreAspectRatio)):
            self.aspect.addItem(text, mode)
        self.aspect.setAccessibleName(tr("Relación de aspecto"))
        self.aspect.currentIndexChanged.connect(lambda _i: self.video.setAspectRatioMode(self.aspect.currentData()))
        self.heading = label("", "h2")
        self.scene_label = label("", "muted")
        self.aspect_label = label("", "muted")
        self.head = QWidget()
        from aero.ui.glass import IconButton

        self.close_btn = IconButton("close", tr("Cerrar y volver (Esc)"), 16, button=30)
        self.close_btn.clicked.connect(self.close_requested.emit)
        self.head.setLayout(h_layout(self.heading, None, self.scene_label, self.scene_box, 10,
                                     self.aspect_label, self.aspect, 8, self.close_btn, spacing=6))
        stage_lay = QVBoxLayout(self.stage)
        stage_lay.setContentsMargins(10, 10, 10, 10)
        stage_lay.setSpacing(8)
        stage_lay.addWidget(self.head)
        stage_lay.addWidget(self.stack, 1)

        self.queue = QueuePanel(engine)
        self.queue.setVisible(False)
        lay = h_layout(self.stage, self.queue, spacing=12)
        self.setLayout(lay)

        self.viz_on = bool(settings.get("visualizer_enabled"))
        engine.track_changed.connect(self._track)
        engine.subtitle_text.connect(self._ext_sub)
        self._update_mode()

    def _gallery(self):
        from aero.ui.pages.viz_gallery import VisualizerDialog

        VisualizerDialog(self.settings, self).exec()

    def _track(self, info):
        self.now.set_track(info)
        self.heading.setText(info.display_title if info else "")
        self.visualizer.set_caption(f"{info.display_title}  ·  {info.artist}" if info and info.artist else
                                    (info.display_title if info else ""))
        self._update_mode()

    def set_visualizer(self, on: bool):
        self.viz_on = on
        self.settings.set("visualizer_enabled", on)
        self._update_mode()

    def _update_mode(self):
        info = self.engine.current
        is_video = info is not None and info.kind == "video"
        if is_video:
            target = self.video
        elif self.viz_on and info is not None:
            target = self.visualizer
        else:
            target = self.now
        self.stack.setCurrentWidget(target)
        self.scene_box.setVisible(target is self.visualizer)
        self.scene_label.setVisible(target is self.visualizer)
        self.aspect.setVisible(is_video)
        self.aspect_label.setVisible(is_video)
        self._sync_visualizer()

    def _sync_visualizer(self):
        on = self.isVisible() and self.stack.currentWidget() is self.visualizer
        self.engine.set_analysis(on)
        if on and not self.visualizer.active:
            self.visualizer.start()
        elif not on and self.visualizer.active:
            self.visualizer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_visualizer()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._sync_visualizer()

    def _ext_sub(self, text: str):
        sink = self.video.videoSink()
        if sink is not None and hasattr(sink, "setSubtitleText"):
            sink.setSubtitleText(text)

    def set_immersive(self, on: bool):
        """En pantalla completa se oculta la cabecera y el marco de cristal."""
        self.head.setVisible(not on)
        self.stage.layout().setContentsMargins(*((0, 0, 0, 0) if on else (10, 10, 10, 10)))
        if on:
            self.queue.setVisible(False)

    def subtitle_dialog(self):
        dlg = SubtitleDialog(self.engine, self.settings, self)
        if dlg.exec():
            self.engine.set_sub_offset(int(dlg.offset.value() * 1000))
            self.settings.set("subtitle_scale", float(dlg.size.currentData()))
            self._apply_sub_scale()

    def _apply_sub_scale(self):
        # El tamaño de los subtítulos se aplica a través de la fuente del widget de vídeo.
        f = self.video.font()
        f.setPointSizeF(10 * float(self.settings.get("subtitle_scale")))
        self.video.setFont(f)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        a = QAction(tr("Mostrar visualizador"), m, checkable=True)
        a.setChecked(self.viz_on)
        a.triggered.connect(self.set_visualizer)
        m.addAction(a)
        lp = QAction(tr("Modo de bajo consumo del visualizador"), m, checkable=True)
        lp.setChecked(self.visualizer.low_power)
        lp.triggered.connect(lambda on: (self.visualizer.set_low_power(on), self.settings.set("visualizer_low_power", on)))
        m.addAction(lp)
        m.exec(e.globalPos())
