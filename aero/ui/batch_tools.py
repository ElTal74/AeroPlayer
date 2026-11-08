"""Ventanas de lotes: cambiar el nombre de muchos archivos a la vez y redimensionar fotos.

La lógica está en `aero.core.batch`. El renombrado muestra la vista previa antes de aplicar y se puede deshacer;
el redimensionado crea copias y queda en el centro de tareas.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHeaderView, QLineEdit,
                               QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from aero.core import batch
from aero.i18n import ntr, tr
from aero.ui.glass import h_layout, label
from aero.ui.glasswindow import DragArea, GlassWindow


class _BatchWindow(GlassWindow):
    def __init__(self, title: str, controller=None):
        super().__init__(Qt.WindowType(0), flat=True)
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("{title} · AERO Player", title=title))
        self.backdrop.flat_opacity = 0.95
        bar = DragArea()
        self.title_label = label(title, "h3")
        bar.setLayout(h_layout(16, self.title_label, None, self.window_buttons(maximize=False), spacing=4,
                               margins=(0, 8, 8, 4)))
        lay = QVBoxLayout(self.backdrop)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(bar)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(18, 4, 18, 16)
        self.body.setSpacing(10)
        lay.addLayout(self.body, 1)

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels([tr(h) for h in headers])
        t.verticalHeader().hide()
        t.setShowGrid(False)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for c in range(len(headers)):
            t.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        return t

    def closeEvent(self, e):
        super().closeEvent(e)
        if self.controller is not None:
            self.controller.editor_closed(self)


class BatchRename(_BatchWindow):
    """Patrón con marcadores, buscar y reemplazar, mayúsculas y numeración, con vista previa en vivo."""

    def __init__(self, paths: list[str], controller=None):
        super().__init__(tr("Cambiar nombre"), controller)
        self.paths = [str(p) for p in dict.fromkeys(paths) if Path(p).is_file()]
        self.done: list[tuple[Path, Path]] = []
        self.setMinimumSize(640, 520)
        self.pattern = QLineEdit("{nombre}")
        self.pattern.setToolTip(tr("Marcadores: {nombre}, {n} (número), {fecha} y {carpeta}"))
        tokens = h_layout(spacing=4)
        from aero.i18n import SOURCE, language

        spanish = language() in (SOURCE, "es-419")
        for canon, name in batch.TOKENS.items():
            tok = canon if spanish else batch.TOKEN_EN.get(canon, canon)
            b = QPushButton(tok)
            b.setProperty("kind", "flat")
            b.setToolTip(tr(name))
            b.clicked.connect(lambda _c=False, t=tok: (self.pattern.insert(t), self.pattern.setFocus()))
            tokens.addWidget(b)
        tokens.addStretch(1)
        self.find = QLineEdit()
        self.find.setPlaceholderText(tr("Buscar"))
        self.replace = QLineEdit()
        self.replace.setPlaceholderText(tr("Reemplazar por"))
        self.match_case = QCheckBox(tr("Distinguir mayúsculas"))
        self.case = QComboBox()
        for k, v in batch.CASES.items():
            self.case.addItem(tr(v), k)
        self.start = QSpinBox()
        self.start.setRange(0, 999999)
        self.start.setValue(1)
        self.digits = QSpinBox()
        self.digits.setRange(1, 8)
        self.digits.setValue(max(2, len(str(len(self.paths)))))
        self.lower_ext = QCheckBox(tr("Extensión en minúsculas"))
        form = QFormLayout()
        form.addRow(tr("Nombre nuevo"), self.pattern)
        form.addRow("", tokens)
        form.addRow(tr("Buscar y reemplazar"), h_layout(self.find, self.replace, self.match_case, spacing=6))
        form.addRow(tr("Mayúsculas"), h_layout(self.case, None, spacing=6))
        form.addRow(tr("Numerar desde"), h_layout(self.start, label(tr("Cifras"), "muted"), self.digits, None,
                                                  self.lower_ext, spacing=6))
        self.table = self._table(["Nombre actual", "Nombre nuevo"])
        self.status = label("", "caption", wrap=True)
        self.undo_btn = QPushButton(tr("Deshacer"))
        self.undo_btn.hide()
        self.undo_btn.clicked.connect(self.undo)
        self.go = QPushButton(tr("Cambiar nombre"))
        self.go.setProperty("kind", "primary")
        self.go.clicked.connect(self.apply)
        self.body.addLayout(form)
        self.body.addWidget(self.table, 1)
        self.body.addWidget(self.status)
        self.body.addLayout(h_layout(None, self.undo_btn, self.go))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self.preview)
        for w in (self.pattern, self.find, self.replace):
            w.textChanged.connect(self._timer.start)
        for w in (self.match_case, self.lower_ext):
            w.toggled.connect(self._timer.start)
        self.case.currentIndexChanged.connect(self._timer.start)
        self.start.valueChanged.connect(self._timer.start)
        self.digits.valueChanged.connect(self._timer.start)
        self.items: list[batch.RenameItem] = []
        self.preview()

    def options(self) -> batch.RenameOptions:
        return batch.RenameOptions(self.pattern.text(), self.find.text(), self.replace.text(),
                                   self.match_case.isChecked(), self.case.currentData(), self.start.value(),
                                   self.digits.value(), self.lower_ext.isChecked())

    def preview(self):
        self.items = batch.plan_rename(self.paths, self.options())
        t = self.table
        t.setRowCount(len(self.items))
        bad = 0
        for r, it in enumerate(self.items):
            t.setItem(r, 0, QTableWidgetItem(it.src.name))
            new = QTableWidgetItem(it.name + (f"  ⚠ {tr(it.problem)}" if it.problem else ""))
            if it.problem:
                new.setForeground(QColor("#ff7a6a"))
                bad += 1
            elif not it.changed:
                new.setForeground(QColor(t.palette().color(t.foregroundRole())).darker(140))
            t.setItem(r, 1, new)
        n = sum(1 for it in self.items if it.changed and not it.problem)
        self.go.setEnabled(n > 0)
        self.go.setText(tr("Cambiar nombre") + (f" ({n})" if n else ""))
        msg = []
        if bad:
            msg.append(ntr("{n} archivo no se puede renombrar así", "{n} archivos no se pueden renombrar así", bad))
        self.status.setText(" · ".join(msg))

    def apply(self):
        try:
            self.done = batch.apply_rename(self.items)
        except OSError as e:
            self.status.setText(tr("No se pudo cambiar el nombre: {e}. No se ha modificado nada.", e=e))
            self.preview()
            return
        moved = {str(src): str(dst) for src, dst in self.done}
        self.paths = [moved.get(p, p) for p in self.paths]
        self.undo_btn.setVisible(bool(self.done))
        self.pattern.setText("{nombre}")
        self.find.clear()
        self._timer.stop()
        self.preview()
        self.status.setText(ntr("{n} archivo renombrado.", "{n} archivos renombrados.", len(self.done)))

    def undo(self):
        try:
            n = batch.undo_rename(self.done)
        except OSError as e:
            self.status.setText(tr("No se pudo deshacer: {e}", e=e))
            return
        back = {str(dst): str(src) for src, dst in self.done}
        self.paths = [back.get(p, p) for p in self.paths]
        self.done = []
        self.undo_btn.hide()
        self.preview()
        self.status.setText(ntr("{n} nombre restaurado.", "{n} nombres restaurados.", n))


class BatchResize(_BatchWindow):
    """Copias redimensionadas de varias fotos (lado mayor, porcentaje o caja), en una subcarpeta o con sufijo."""

    def __init__(self, paths: list[str], controller=None):
        super().__init__(tr("Redimensionar fotos"), controller)
        from aero.core.formats import kind_of

        self.paths = [str(p) for p in dict.fromkeys(paths) if Path(p).is_file() and kind_of(p) == "image"]
        self.setMinimumSize(600, 520)
        self.mode = QComboBox()
        for k, v in batch.MODES.items():
            self.mode.addItem(tr(v), k)
        self.side = self._spin(16, 20000, 1920, " px")
        self.percent = self._spin(1, 400, 50, " %")
        self.width_box = self._spin(16, 20000, 1280, " px")
        self.height_box = self._spin(16, 20000, 1280, " px")
        self.upscale = QCheckBox(tr("Ampliar también las fotos más pequeñas"))
        self.fmt = QComboBox()
        for k, v in batch.FORMATS.items():
            self.fmt.addItem(tr(v), k)
        self.quality = self._spin(1, 100, 88, " %")
        self.strip = QCheckBox(tr("Quitar metadatos (ubicación, cámara…)"))
        self.dest = QComboBox()
        self.dest.addItem(tr("En una subcarpeta «Redimensionadas»"), "Redimensionadas")
        self.dest.addItem(tr("Junto al original, con el tamaño en el nombre"), "")
        self.times = label("×", "muted")
        self.size_row = h_layout(self.side, self.percent, self.width_box, self.times, self.height_box, None, spacing=6)
        form = QFormLayout()
        form.addRow(tr("Tamaño"), h_layout(self.mode, None, spacing=6))
        form.addRow("", self.size_row)
        form.addRow("", self.upscale)
        form.addRow(tr("Formato"), h_layout(self.fmt, label(tr("Calidad"), "muted"), self.quality, None, spacing=6))
        form.addRow(tr("Guardar"), self.dest)
        form.addRow("", self.strip)
        self.table = self._table(["Foto", "Tamaño nuevo"])
        self.progress = QProgressBar()
        self.progress.setRange(0, max(1, len(self.paths)))
        self.progress.hide()
        self.status = label(tr("Los originales no se modifican: se crean copias."), "caption", wrap=True)
        self.open_btn = QPushButton(tr("Abrir carpeta"))
        self.open_btn.hide()
        self.open_btn.clicked.connect(self._open_folder)
        self.go = QPushButton(tr("Redimensionar"))
        self.go.setProperty("kind", "primary")
        self.go.clicked.connect(self.start)
        self.body.addLayout(form)
        self.body.addWidget(self.table, 1)
        self.body.addWidget(self.progress)
        self.body.addWidget(self.status)
        self.body.addLayout(h_layout(None, self.open_btn, self.go))
        self.sizes: dict[str, tuple[int, int]] = {}
        self.outputs: list[Path] = []
        self._queue: list[str] = []
        self._aid = ""
        self._cancelled = False
        self.mode.currentIndexChanged.connect(self._mode_changed)
        for w in (self.side, self.percent, self.width_box, self.height_box):
            w.valueChanged.connect(self.preview)
        self.upscale.toggled.connect(self.preview)
        self.fmt.currentIndexChanged.connect(lambda: self.quality.setEnabled(self.fmt.currentData() != "png"))
        self._mode_changed()
        self._read_sizes()

    @staticmethod
    def _spin(lo: int, hi: int, value: int, suffix: str) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(value)
        s.setSuffix(suffix)
        return s

    def options(self) -> batch.ResizeOptions:
        return batch.ResizeOptions(self.mode.currentData(), self.side.value(), self.percent.value(),
                                   self.width_box.value(), self.height_box.value(), self.upscale.isChecked(),
                                   self.fmt.currentData(), self.quality.value(), self.strip.isChecked(),
                                   self.dest.currentData())

    def _mode_changed(self):
        m = self.mode.currentData()
        self.side.setVisible(m == "max")
        self.percent.setVisible(m == "percent")
        for w in (self.width_box, self.height_box, self.times):
            w.setVisible(m == "box")
        self.preview()

    def _read_sizes(self):
        """Lee las dimensiones (solo la cabecera de cada foto) en segundo plano."""
        from aero.ui.async_util import run_async

        paths = list(self.paths)

        def work():
            from PIL import Image

            from aero.core import builtin_convert  # noqa: F401 - HEIC

            out = {}
            for p in paths:
                try:
                    with Image.open(p) as im:
                        w, h = im.size
                        # Orientación EXIF girada 90°: el resultado tendrá el ancho y el alto intercambiados
                        out[p] = (h, w) if im.getexif().get(0x0112, 1) in (5, 6, 7, 8) else (w, h)
                except Exception:  # noqa: BLE001 - foto ilegible: se informa al redimensionar
                    pass
            return out

        run_async(work, lambda s: (self.sizes.update(s), self.preview()), None, self)

    def preview(self):
        t = self.table
        t.setRowCount(len(self.paths))
        o = self.options()
        for r, p in enumerate(self.paths):
            t.setItem(r, 0, QTableWidgetItem(Path(p).name))
            wh = self.sizes.get(p)
            text = "…"
            if wh:
                nw, nh = batch.target_size(wh[0], wh[1], o)
                text = f"{wh[0]}×{wh[1]}  →  {nw}×{nh}" + ("" if (nw, nh) != wh else "  " + tr("(sin cambios)"))
            t.setItem(r, 1, QTableWidgetItem(text))
        self.go.setEnabled(bool(self.paths) and not self._queue)

    def start(self):
        from aero.core.activity import activities

        self._queue = list(self.paths)
        self.outputs = []
        self._errors: list[str] = []
        self._cancelled = False
        self._opts = self.options()
        self.progress.setValue(0)
        self.progress.show()
        self.open_btn.hide()
        self.go.setText(tr("Cancelar"))
        self.go.clicked.disconnect()
        self.go.clicked.connect(self.cancel)
        self._aid = activities().start(ntr("Redimensionar {n} foto", "Redimensionar {n} fotos", len(self._queue)),
                                       "image", self.cancel)
        self._next()

    def cancel(self):
        self._cancelled = True

    def _next(self):
        from aero.core.activity import CANCELLED, DONE, ERROR, activities
        from aero.ui.async_util import run_async

        total = len(self.paths)
        done = total - len(self._queue)
        self.progress.setValue(done)
        activities().update(self._aid, done / max(1, total), f"{done}/{total}")
        if self._cancelled or not self._queue:
            folder = str(self.outputs[0].parent) if self.outputs else ""
            state = CANCELLED if self._cancelled else (ERROR if self._errors and not self.outputs else DONE)
            activities().finish(self._aid, state, folder, "; ".join(self._errors[:3]))
            self._queue = []
            msg = ntr("{n} copia creada.", "{n} copias creadas.", len(self.outputs))
            if self._errors:
                msg += " " + ntr("{n} foto no se pudo leer.", "{n} fotos no se pudieron leer.", len(self._errors))
            if self._cancelled:
                msg += " " + tr("Cancelado.")
            self.status.setText(msg)
            self.open_btn.setVisible(bool(self.outputs))
            self.go.setText(tr("Redimensionar"))
            self.go.clicked.disconnect()
            self.go.clicked.connect(self.start)
            self.preview()
            return
        p = self._queue.pop(0)
        opts = self._opts

        def ok(dst):
            self.outputs.append(dst)
            self._next()

        def fail(err, p=p):
            self._errors.append(f"{Path(p).name}: {err}")
            self._next()

        run_async(lambda: batch.resize_image(p, opts), ok, fail, self)

    def closeEvent(self, e):
        if self._queue:
            from aero.core.activity import CANCELLED, activities

            self._queue = []
            activities().finish(self._aid, CANCELLED, "", "")
        super().closeEvent(e)

    def _open_folder(self):
        from aero.core import tools

        if self.outputs:
            tools.reveal_in_explorer(str(self.outputs[0]))


def open_batch_rename(paths: list[str], controller=None) -> BatchRename:
    w = BatchRename(paths, controller)
    w.resize(760, 600)
    w.show()
    w.raise_()
    return w


def open_batch_resize(paths: list[str], controller=None) -> BatchResize:
    w = BatchResize(paths, controller)
    w.resize(700, 600)
    w.show()
    w.raise_()
    return w
