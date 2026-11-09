"""Conversor: zona de soltar, opciones por tipo de archivo, perfiles y cola con progreso."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout,
                               QHeaderView, QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from aero.core import tools
from aero.core.builtin_convert import pillow_has_avif
from aero.core.convert_spec import (PRESETS, VIDEO_CODECS, ConvertOptions, estimate_size, note_values, preset_notes,
                                    targets_for)
from aero.core.converter import ACTIVE, DONE, ERROR, CANCELLED, PAUSED, ConversionManager
from aero.core.formats import KIND_LABELS, human_size, human_time, kind_of
from aero.ui import icons
from aero.ui.glass import GlassPanel, IconButton, h_layout, label, tm, v_layout
from aero.i18n import ntr, tr

KIND_GROUP = {"image": "image", "audio": "audio", "video": "video", "pdf": "pdf", "document": "document",
              "text": "document", "sheet": "sheet", "slides": "slides"}
GROUP_LABEL = {"image": "Imágenes", "audio": "Audio", "video": "Vídeo", "pdf": "PDF", "document": "Documentos",
               "sheet": "Hojas de cálculo", "slides": "Presentaciones"}


def estimate_lines(rows: list[tuple[str, ConvertOptions, dict | None]], total: int, probing: bool) -> list[str]:
    """Texto de la estimación de tamaño y avisos del perfil para (ruta, opciones, información de ffprobe)."""
    lo = hi = known = 0
    notes: list[str] = []
    for p, opts, info in rows:
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        est = estimate_size(p, opts, info, size)
        if est:
            lo += est[0]
            hi += est[1]
            known += 1
        for n in preset_notes(opts, p, info):
            text = tr(n, **note_values.get(n, {}))
            if text not in notes:
                notes.append(text)
    parts = []
    if known:
        parts.append(tr("Tamaño estimado: {a} – {b}", a=human_size(lo), b=human_size(hi))
                     + (tr(" ({n} de {t} archivos)", n=known, t=total) if known < total else ""))
    elif probing:
        parts.append(tr("Calculando el tamaño estimado…"))
    return parts + notes[:3]


class DropList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setIconSize(QSize(32, 32))
        self.setSpacing(2)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            e.acceptProposedAction()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count() == 0:
            from PySide6.QtGui import QPainter, QPen, QColor

            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            t = tm().theme
            r = self.viewport().rect().adjusted(10, 10, -10, -10)
            pen = QPen(QColor(t.accent), 1.5, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(r, 14, 14)
            pm = icons.pixmap("drop", t.accent, 40)
            p.drawPixmap(r.center().x() - 20, r.center().y() - 46, pm)
            p.setPen(QColor(t.text))
            p.drawText(r.adjusted(0, 20, 0, 0), Qt.AlignmentFlag.AlignCenter,
                       tr("Suelta aquí fotos, música, vídeos o documentos") + "\n"
                       + tr("o usa «Archivos» y «Carpeta»"))


class QueueTable(QTableWidget):
    """Tabla de la cola con un estado vacío que explica qué hacer (en lugar de un panel en blanco)."""

    def __init__(self, *a):
        super().__init__(*a)
        m = self.model()
        for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset):
            sig.connect(lambda *_: self.horizontalHeader().setVisible(self.rowCount() > 0))
        self.horizontalHeader().setVisible(False)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.rowCount():
            return
        from PySide6.QtGui import QColor, QPainter

        t = tm().theme
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.viewport().rect()
        pm = icons.pixmap("convert", t.accent, 44)
        p.setOpacity(0.85)
        p.drawPixmap(r.center().x() - 22, r.center().y() - 70, pm)
        p.setOpacity(1.0)
        p.setPen(QColor(t.text))
        f = p.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setBold(True)
        p.setFont(f)
        p.drawText(r.adjusted(24, 0, -24, -10), Qt.AlignmentFlag.AlignCenter, tr("La cola está vacía"))
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() - 2)
        p.setFont(f)
        p.setPen(QColor(t.text2))
        p.drawText(r.adjusted(32, r.height() // 2 + 18, -32, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                   | Qt.TextFlag.TextWordWrap,
                   tr("Añade archivos a la izquierda, elige el formato y pulsa «Convertir». Aquí verás el avance "
                      "de cada uno, y podrás pausar, reintentar o abrir el resultado."))


class ConverterPage(QWidget):
    message = Signal(str, str)

    def __init__(self, manager: ConversionManager, settings, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.settings = settings
        self.staged: list[tuple[str, str]] = []   # (ruta, carpeta relativa)
        self.rows: dict[int, int] = {}

        # ------------------------------------------------------------ panel izquierdo: archivos y opciones
        left = GlassPanel(radius=22)
        self.drop = DropList()
        self.drop.files_dropped.connect(self.add_paths)
        add_files = QPushButton(tr("Archivos"))
        add_files.setIcon(tm().icon("plus", 16))
        add_folder = QPushButton(tr("Carpeta"))
        add_folder.setIcon(tm().icon("folder", 16))
        clear = IconButton("trash", tr("Quitar los seleccionados (o todos)"), 16)
        add_files.clicked.connect(self._pick_files)
        add_folder.clicked.connect(self._pick_folder)
        clear.clicked.connect(self._remove_staged)

        self.target_boxes: dict[str, QComboBox] = {}
        self.targets_form = QFormLayout()
        self.targets_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.preset = QComboBox()
        for k, v in PRESETS.items():
            self.preset.addItem(tr(v), k)
        self.preset.setToolTip(tr("«Conservar» copia las pistas sin recomprimir cuando el contenedor lo permite (instantáneo). "
                               "«Compatible con móviles» y «con Windows» usan H.264 y AAC, que se reproducen en todas "
                               "partes sin instalar nada."))
        # Aviso del perfil y tamaño estimado (con ffprobe en segundo plano)
        self.estimate = label("", "caption", wrap=True)
        self._probes: dict[str, dict | None] = {}
        self._probing: set[str] = set()
        self._est_timer = QTimer(self)
        self._est_timer.setSingleShot(True)
        self._est_timer.setInterval(120)
        self._est_timer.timeout.connect(self._update_estimate)

        # Opciones avanzadas
        self.adv_toggle = QPushButton(tr("Avanzado ▾"))
        self.adv_toggle.setProperty("kind", "flat")
        self.adv_toggle.setCheckable(True)
        self.adv = QWidget()
        g = QGridLayout(self.adv)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(10)
        self.codec = QComboBox()
        for k, v in VIDEO_CODECS.items():
            self.codec.addItem(v, k)
        self.res = QComboBox()
        for txt, h in (("Original", 0), ("2160p (4K)", 2160), ("1440p", 1440), ("1080p", 1080), ("720p", 720),
                       ("480p", 480), ("360p", 360)):
            self.res.addItem(txt, h)
        self.fps = QComboBox()
        for txt, v in (("Original", 0), ("60", 60), ("30", 30), ("25", 25), ("24", 24), ("15", 15)):
            self.fps.addItem(txt, v)
        self.audio_mode = QComboBox()
        self.audio_mode.addItem(tr("Incluir audio"), "auto")
        self.audio_mode.addItem(tr("Sin audio"), "none")
        self.abr = QComboBox()
        for txt, v in (("Según perfil", 0), ("96 kbps", 96), ("128 kbps", 128), ("192 kbps", 192), ("256 kbps", 256),
                       ("320 kbps", 320)):
            self.abr.addItem(txt, v)
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(90)
        self.quality.setSuffix(" %")
        self.max_side = QSpinBox()
        self.max_side.setRange(0, 20000)
        self.max_side.setSingleStep(100)
        self.max_side.setSpecialValueText(tr("Original"))
        self.max_side.setSuffix(tr(" px"))
        self.bg = QComboBox()
        self.bg.addItem(tr("Blanco"), "#ffffff")
        self.bg.addItem(tr("Negro"), "#000000")
        self.strip = QCheckBox(tr("Quitar metadatos"))
        self.hw = QCheckBox(tr("Aceleración por hardware"))
        self.hw.setChecked(bool(settings.get("use_hw_encoding")))
        self.hw.toggled.connect(lambda on: settings.set("use_hw_encoding", on))
        rows = [("Códec de vídeo", self.codec), ("Resolución máx.", self.res), ("Fotogramas/s", self.fps),
                ("Audio", self.audio_mode), ("Bitrate de audio", self.abr), ("Calidad de imagen", self.quality),
                ("Lado mayor máx.", self.max_side), ("Fondo al quitar transparencia", self.bg)]
        for i, (t, w) in enumerate(rows):
            g.addWidget(label(t, "muted"), i // 2, (i % 2) * 2)
            g.addWidget(w, i // 2, (i % 2) * 2 + 1)
        g.addWidget(self.strip, 4, 0, 1, 4)
        g.addWidget(self.hw, 5, 0, 1, 4)
        self.adv.hide()
        self.adv_toggle.toggled.connect(lambda on: (self.adv.setVisible(on),
                                                    self.adv_toggle.setText(tr("Avanzado ▴") if on else tr("Avanzado ▾"))))

        self.out_dir = QLineEdit(settings.get("output_dir"))
        self.out_dir.setReadOnly(True)
        pick_out = QPushButton(tr("Cambiar…"))
        pick_out.setIcon(tm().icon("folder", 16))
        pick_out.setToolTip(tr("Elegir la carpeta donde se guardan las conversiones"))
        pick_out.clicked.connect(self._pick_out)
        open_out = IconButton("external", tr("Abrir la carpeta de destino"), 16)
        open_out.clicked.connect(lambda: tools.reveal_in_explorer(self.out_dir.text()))
        self.same_dir = QCheckBox(tr("Junto al original"))
        self.keep_struct = QCheckBox(tr("Mantener subcarpetas"))
        self.keep_struct.setChecked(bool(settings.get("keep_structure")))
        self.keep_struct.toggled.connect(lambda on: settings.set("keep_structure", on))
        self.go = QPushButton(tr("Convertir"))
        self.go.setProperty("kind", "primary")
        self.go.setIcon(tm().icon("convert", 16))
        self.go.setMinimumHeight(40)
        self.go.clicked.connect(self._start)
        self.tool_note = label("", "caption", wrap=True)

        ll = QVBoxLayout(left)
        ll.setContentsMargins(20, 18, 20, 18)
        ll.setSpacing(10)
        self.count_label = label("", "muted")
        ll.addLayout(h_layout(add_files, add_folder, None, self.count_label, clear))
        ll.addWidget(self.drop, 1)
        ll.addWidget(label("Formato", "h3"))
        ll.addLayout(self.targets_form)
        ll.addLayout(h_layout(label("Perfil", "muted"), self.preset, None, self.adv_toggle))
        ll.addWidget(self.estimate)
        ll.addWidget(self.adv)
        ll.addWidget(label("Destino", "h3"))
        ll.addLayout(h_layout(self.out_dir, pick_out, open_out))
        ll.addLayout(h_layout(self.same_dir, self.keep_struct, None))
        ll.addWidget(self.go)
        ll.addWidget(self.tool_note)

        # ------------------------------------------------------------ panel derecho: cola
        right = GlassPanel(radius=22)
        self.table = QueueTable(0, 4)
        self.table.setHorizontalHeaderLabels([tr("Archivo"), tr("Estado"), tr("Progreso"), ""])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c, w in ((1, 150), (2, 110), (3, 96)):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(c, w)
        self.overall = QProgressBar()
        self.overall.setRange(0, 1000)
        self.overall_label = label("", "muted")
        clear_done = IconButton("check", tr("Limpiar terminados"), 16)
        clear_done.clicked.connect(manager.clear_finished)
        cancel_all = IconButton("close", tr("Cancelar todo"), 16)
        cancel_all.clicked.connect(manager.cancel_all)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(20, 18, 20, 18)
        rl.addLayout(h_layout(label("Cola", "h2"), None, clear_done, cancel_all))
        rl.addLayout(h_layout(self.overall_label, None))
        rl.addWidget(self.overall)
        rl.addWidget(self.table, 1)

        lay = h_layout(left, right, spacing=12)
        lay.setStretch(0, 5)
        lay.setStretch(1, 6)
        self.setLayout(lay)

        for w in (self.preset, self.codec, self.res, self.fps, self.audio_mode, self.abr):
            w.currentIndexChanged.connect(self._est_timer.start)
        manager.job_added.connect(self._job_added)
        manager.job_changed.connect(self._job_changed)
        manager.job_removed.connect(self._job_removed)
        self._rebuild_targets()
        self._update_tool_note()

    # ------------------------------------------------------------------ archivos
    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Añadir archivos para convertir"))
        self.add_paths(paths)

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("Añadir carpeta"))
        if d:
            self.add_paths([d])

    def add_paths(self, paths: list[str]):
        added = 0
        known = {p for p, _ in self.staged}
        for p in paths:
            if os.path.isdir(p):
                base = Path(p)
                for root, _dirs, files in os.walk(p):
                    for f in files:
                        full = os.path.join(root, f)
                        if kind_of(full) in KIND_GROUP and full not in known:
                            rel = str(Path(root).relative_to(base.parent))
                            self.staged.append((full, rel))
                            known.add(full)
                            added += 1
            elif os.path.isfile(p) and p not in known:
                if kind_of(p) not in KIND_GROUP:
                    self.message.emit(tr("Formato no compatible para conversión: {v0}", v0=Path(p).name), "error")
                    continue
                self.staged.append((p, ""))
                known.add(p)
                added += 1
        self._refresh_staged()

    def _refresh_staged(self):
        from aero.core.formats import human_size
        from aero.ui.file_icons import icon_for

        self.drop.clear()
        total = 0
        for p, _rel in self.staged:
            k = kind_of(p)
            try:
                size = os.path.getsize(p)
            except OSError:
                size = 0
            total += size
            it = QListWidgetItem(icon_for(p, 32), f"{Path(p).name}\n{tr(KIND_LABELS.get(k, ''))} · {human_size(size)}")
            it.setToolTip(p)
            self.drop.addItem(it)
        n = len(self.staged)
        self.count_label.setText(ntr("{n} archivo", "{n} archivos", n) + f" · {human_size(total)}" if n else "")
        self._rebuild_targets()

    def _remove_staged(self):
        rows = sorted({i.row() for i in self.drop.selectedIndexes()}, reverse=True)
        if not rows:
            self.staged.clear()
        for r in rows:
            del self.staged[r]
        self._refresh_staged()

    def _rebuild_targets(self):
        while self.targets_form.rowCount():
            self.targets_form.removeRow(0)
        self.target_boxes.clear()
        office = tools.find_tool("soffice") is not None
        avif = pillow_has_avif()
        groups: dict[str, str] = {}
        for p, _ in self.staged:
            groups.setdefault(KIND_GROUP[kind_of(p)], p)
        if not groups:
            self.targets_form.addRow(label(tr("Añade archivos y elige aquí a qué formato convertirlos."), "caption",
                                           wrap=True))
            self.go.setEnabled(False)
            self.estimate.setText("")
            return
        self.go.setEnabled(True)
        for g, sample in groups.items():
            box = QComboBox()
            for key, text in targets_for(sample, office, avif):
                box.addItem(text, key)
            if box.count() == 0:
                box.addItem("—", "")
                box.setEnabled(False)
            box.currentIndexChanged.connect(self._est_timer.start)
            self.target_boxes[g] = box
            self.targets_form.addRow(GROUP_LABEL[g] + ":", box)
        self._est_timer.start()

    # ------------------------------------------------------------------ estimación
    def _options_for(self, path: str) -> ConvertOptions | None:
        box = self.target_boxes.get(KIND_GROUP.get(kind_of(path), ""))
        target = box.currentData() if box else ""
        if not target:
            return None
        return ConvertOptions(target=target, preset=self.preset.currentData(), video_codec=self.codec.currentData(),
                              max_height=self.res.currentData(), fps=self.fps.currentData(),
                              audio=self.audio_mode.currentData(), audio_bitrate=self.abr.currentData())

    def _update_estimate(self):
        """Suma la estimación de los archivos de audio y vídeo de la lista y muestra los avisos del perfil."""
        from aero.ui.async_util import run_async

        media = [p for p, _ in self.staged if kind_of(p) in ("audio", "video")][:200]
        if not media:
            self.estimate.setText("")
            return
        missing = [p for p in media if p not in self._probes and p not in self._probing][:40]
        for p in missing:
            self._probing.add(p)

            def done(info, p=p):
                self._probing.discard(p)
                self._probes[p] = info
                self._est_timer.start()

            run_async(lambda p=p: tools.probe(p), done, lambda _e, p=p: done(None, p), self)
        rows = [(p, self._options_for(p), self._probes[p]) for p in media if p in self._probes]
        parts = estimate_lines([(p, o, i) for p, o, i in rows if o is not None], len(media), bool(self._probing))
        self.estimate.setText("\n".join(parts))

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, tr("Carpeta de destino"), self.out_dir.text())
        if d:
            self.out_dir.setText(d)
            self.settings.set("output_dir", d)

    def _update_tool_note(self):
        notes = []
        if not tools.find_tool("ffmpeg"):
            notes.append(tr("Falta FFmpeg (audio/vídeo)."))
        if not tools.find_tool("soffice"):
            pass  # sin LibreOffice se usa el conversor integrado; no hace falta avisar
        self.tool_note.setText(" ".join(notes))

    # ------------------------------------------------------------------ inicio
    def _start(self):
        if not self.staged:
            return
        base = ConvertOptions(
            target="", preset=self.preset.currentData(), video_codec=self.codec.currentData(),
            max_height=self.res.currentData(), fps=self.fps.currentData(), audio=self.audio_mode.currentData(),
            audio_bitrate=self.abr.currentData(), hw=self.hw.isChecked(), quality=self.quality.value(),
            max_side=self.max_side.value(), bg_color=self.bg.currentData(), strip_metadata=self.strip.isChecked())
        out_dir = self.out_dir.text()
        by_group: dict[str, list[tuple[str, str]]] = {}
        for p, rel in self.staged:
            by_group.setdefault(KIND_GROUP[kind_of(p)], []).append((p, rel))
        started = 0
        for g, items in by_group.items():
            box = self.target_boxes.get(g)
            target = box.currentData() if box else ""
            if not target:
                continue
            opts = ConvertOptions(**{**base.__dict__, "target": target})
            if self.same_dir.isChecked():
                for p, _rel in items:
                    self.manager.add([(p, "")], opts, str(Path(p).parent))
            else:
                self.manager.add(items, opts, out_dir)
            started += len(items)
        if started:
            self.staged.clear()
            self._refresh_staged()
            self.message.emit(tr("{started} archivos añadidos a la cola.", started=started), "ok")

    # ------------------------------------------------------------------ cola
    def _job_added(self, jid: int):
        job = self.manager.jobs[jid]
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.rows[jid] = r
        it = QTableWidgetItem(f"{job.src.name}  →  {job.opts.target.upper()}")
        it.setToolTip(str(job.src))
        self.table.setItem(r, 0, it)
        self.table.setItem(r, 1, QTableWidgetItem(job.state))
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setFixedHeight(8)
        holder = QWidget()
        holder.setLayout(v_layout(None, bar, None, margins=(4, 0, 8, 0)))
        self.table.setCellWidget(r, 2, holder)
        actions = QWidget()
        pause = IconButton("pause_small", "Pausar", 14, button=28)
        cancel = IconButton("close", tr("Cancelar"), 14, button=28)
        retry = IconButton("refresh", "Reintentar", 14, button=28)
        open_btn = IconButton("folder", tr("Mostrar el resultado"), 14, button=28)
        remove = IconButton("trash", tr("Quitar de la lista"), 14, button=28)
        pause.clicked.connect(lambda: self._toggle_pause(jid))
        cancel.clicked.connect(lambda: self.manager.cancel(jid))
        retry.clicked.connect(lambda: self.manager.retry(jid))
        open_btn.clicked.connect(lambda: self._reveal(jid))
        remove.clicked.connect(lambda: self.manager.remove(jid))
        actions.setLayout(h_layout(pause, cancel, retry, open_btn, remove, None, spacing=0))
        actions._btns = (pause, cancel, retry, open_btn, remove)
        self.table.setCellWidget(r, 3, actions)
        self._job_changed(jid)

    def _toggle_pause(self, jid):
        job = self.manager.jobs.get(jid)
        if job and job.state == PAUSED:
            self.manager.resume(jid)
        else:
            self.manager.pause(jid)

    def _reveal(self, jid):
        job = self.manager.jobs.get(jid)
        if job and job.outputs:
            tools.reveal_in_explorer(str(job.outputs[0]))

    def _job_changed(self, jid: int):
        job = self.manager.jobs.get(jid)
        r = self.rows.get(jid)
        if job is None or r is None:
            return
        st = job.state
        if st in ("Convirtiendo", "En pausa") and job.eta is not None:
            st += f" · {human_time(job.eta)}"
        item = self.table.item(r, 1)
        item.setText(st)
        item.setToolTip(job.message or job.state)
        if job.state == ERROR:
            item.setText(tr("Error: {message}", message=job.message))
        holder = self.table.cellWidget(r, 2)
        bar = holder.findChild(QProgressBar)
        bar.setValue(int(job.progress * 1000))
        pause, cancel, retry, open_btn, remove = self.table.cellWidget(r, 3)._btns
        active = job.state in ACTIVE or job.state == "En cola"
        pause.setVisible(job.state in ("Convirtiendo", "En pausa") and self.manager.can_pause(jid))
        pause.set_icon_name("play" if job.state == PAUSED else "pause_small")
        pause.setToolTip("Reanudar" if job.state == PAUSED else "Pausar")
        cancel.setVisible(active)
        retry.setVisible(job.state in (ERROR, CANCELLED))
        open_btn.setVisible(job.state == DONE)
        remove.setVisible(not active)
        done, total, prog = self.manager.overall()
        self.overall.setValue(int(prog * 1000))
        self.overall_label.setText(f"{done}/{total} · {prog * 100:.0f} %" if total else "")

    def _job_removed(self, jid: int):
        r = self.rows.pop(jid, None)
        if r is None:
            return
        self.table.removeRow(r)
        for k, v in self.rows.items():
            if v > r:
                self.rows[k] = v - 1
        done, total, prog = self.manager.overall()
        self.overall.setValue(int(prog * 1000))
        self.overall_label.setText(f"{done}/{total}" if total else "")
