"""Conversión rápida (menú contextual «Convertir…»): elegir formato y convertir, sin abrir la aplicación.

Usa el conversor común (`ConversionManager`): misma cola, mismos límites de tareas pesadas, nunca
sobrescribe los originales. Con varios archivos de tipos distintos solo se ofrecen los formatos comunes.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from aero.core import tools
from aero.core.convert_spec import PRESETS, ConvertOptions, targets_for
from aero.core.formats import kind_of
from aero.ui.glass import h_layout, label
from aero.ui.glasswindow import DragArea, GlassWindow
from aero.i18n import tr

def common_targets(paths: list[str]) -> list[tuple[str, str]]:
    office = tools.find_tool("soffice") is not None
    sets = [targets_for(p, office) for p in paths]
    if not sets or not sets[0]:
        return []
    keys = [k for k, _t in sets[0] if all(any(k == k2 for k2, _ in s) for s in sets[1:])]
    labels = dict(sets[0])
    return [(k, labels[k]) for k in keys]


class QuickConvert(GlassWindow):
    def __init__(self, paths: list[str], controller=None):
        super().__init__(Qt.WindowType(0), flat=True)
        from aero.core.converter import ConversionManager

        self.controller = controller
        self.paths = list(dict.fromkeys(paths))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("Convertir · AERO Player"))
        self.setMinimumSize(560, 420)
        self.backdrop.flat_opacity = 0.95
        settings = controller.settings if controller is not None else None
        if settings is None:
            from aero.core.config import Settings

            settings = Settings()
        self.cm = ConversionManager(settings, self)
        self.cm.job_changed.connect(self._job_changed)
        self.ids: dict[int, QListWidgetItem] = {}

        bar = DragArea()
        title = label("Convertir" + (f" {Path(self.paths[0]).name}" if len(self.paths) == 1 else
                                     f" {len(self.paths)} archivos"), "h3")
        bar.setLayout(h_layout(16, title, None, self.window_buttons(maximize=False), spacing=4, margins=(0, 8, 8, 4)))
        self.target = QComboBox()
        for k, t in common_targets(self.paths):
            self.target.addItem(t, k)
        self.preset = QComboBox()
        for k, t in PRESETS.items():
            self.preset.addItem(tr(t), k)
        self.folder = QLineEdit(str(Path(self.paths[0]).parent))
        browse = QPushButton(tr("Examinar…"))
        browse.clicked.connect(self._browse)
        self.list = QListWidget()
        for p in self.paths:
            it = QListWidgetItem(f"{Path(p).name}")
            it.setToolTip(p)
            self.list.addItem(it)
        self.status = label("", "caption", wrap=True)
        self.go = QPushButton(tr("Convertir"))
        self.go.setProperty("kind", "primary")
        self.go.clicked.connect(self.start)
        self.open_btn = QPushButton(tr("Abrir carpeta"))
        self.open_btn.hide()
        self.open_btn.clicked.connect(lambda: tools.open_with_default(self.folder.text()))
        form = QFormLayout()
        form.addRow(tr("Convertir a"), self.target)
        form.addRow(tr("Calidad"), self.preset)
        form.addRow(tr("Guardar en"), h_layout(self.folder, browse, spacing=4))
        lay = QVBoxLayout(self.backdrop)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(bar)
        body = QVBoxLayout()
        body.setContentsMargins(18, 4, 18, 16)
        body.setSpacing(10)
        body.addLayout(form)
        body.addWidget(self.list, 1)
        body.addWidget(self.status)
        body.addLayout(h_layout(None, self.open_btn, self.go))
        lay.addLayout(body, 1)
        if not self.target.count():
            self.status.setText(tr("No hay un formato de destino común para estos archivos. Conviértelos por tipo."))
            self.go.setEnabled(False)
        # Tamaño estimado y avisos del perfil (ffprobe en segundo plano)
        self._probes: dict[str, dict | None] = {}
        self.target.currentIndexChanged.connect(self._estimate)
        self.preset.currentIndexChanged.connect(self._estimate)
        from aero.ui.async_util import run_async

        for p in [p for p in self.paths if kind_of(p) in ("audio", "video")][:40]:
            def done(info, p=p):
                self._probes[p] = info
                self._estimate()

            run_async(lambda p=p: tools.probe(p), done, lambda _e, p=p: done(None, p), self)

    def _estimate(self):
        from aero.ui.pages.converter_page import estimate_lines

        if not self.target.count() or not self.go.isEnabled():
            return
        media = [p for p in self.paths if kind_of(p) in ("audio", "video")]
        if not media:
            return
        opts = ConvertOptions(target=self.target.currentData(), preset=self.preset.currentData())
        rows = [(p, opts, self._probes[p]) for p in media if p in self._probes]
        self.status.setText("\n".join(estimate_lines(rows, len(media), len(rows) < min(len(media), 40))))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("Guardar en"), self.folder.text())
        if d:
            self.folder.setText(d)

    def start(self):
        opts = ConvertOptions(target=self.target.currentData(), preset=self.preset.currentData())
        jids = self.cm.add([(p, "") for p in self.paths], opts, self.folder.text())
        items = [self.list.item(i) for i in range(self.list.count())]
        self.ids = dict(zip(jids, items))
        self.go.setEnabled(False)
        self.go.setText(tr("Convirtiendo…"))

    def _job_changed(self, jid: int):
        job = self.cm.jobs.get(jid)
        it = self.ids.get(jid)
        if job is None or it is None:
            return
        from aero.core.converter import DONE, ERROR, RUNNING

        pct = f" · {job.progress * 100:.0f} %" if job.state == RUNNING else ""
        it.setText(f"{job.src.name}  —  {job.state}{pct}" + (f": {job.message}" if job.state == ERROR and job.message
                                                             else ""))
        if not self.cm.busy():
            done = sum(1 for j in self.cm.jobs.values() if j.state == DONE)
            self.status.setText(tr("{done} de {v1} convertidos.", done=done, v1=len(self.cm.jobs)))
            self.go.setText(tr("Convertir"))
            self.go.setEnabled(True)
            self.open_btn.setVisible(done > 0)

    def closeEvent(self, e):
        from aero.core.converter import ACTIVE, PENDING

        for jid, job in list(self.cm.jobs.items()):
            if job.state in ACTIVE or job.state == PENDING:
                self.cm.cancel(jid)
        QTimer.singleShot(0, lambda: None)
        super().closeEvent(e)
        if self.controller is not None:
            self.controller.editor_closed(self)


def open_quick_convert(paths: list[str], controller=None) -> QuickConvert:
    w = QuickConvert(paths, controller)
    w.resize(620, 480)
    w.show()
    w.raise_()
    w.activateWindow()
    return w
