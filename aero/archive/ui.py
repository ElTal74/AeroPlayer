"""Interfaz del extractor y compresor: progreso, diálogos y gestor de archivos comprimidos (estilo WinRAR).

El trabajo va a la cola de tareas pesadas; el progreso llega por una cola de mensajes que la ventana lee con
un temporizador (ningún objeto Qt viaja al hilo de trabajo). Si un archivo pide contraseña, se pregunta y se
reintenta. Nada se borra: los originales siempre se conservan.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QInputDialog, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from aero.archive import ArchiveError, PasswordRequired, ops
from aero.core.formats import human_size
from aero.ui.glass import IconButton, h_layout, label, v_layout
from aero.ui.glasswindow import DragArea, GlassWindow, TrDialog
from aero.i18n import tr

AUTO_CLOSE_S = 3
MODES = [("rename", "Conservar ambos (renombrar)"), ("overwrite", "Sobrescribir"), ("skip", "Omitir los existentes")]
_ACTIVE: dict[tuple, "ProgressWindow"] = {}   # operaciones en curso: la misma no se lanza dos veces


def _open_folder(path: str):
    from aero.core import tools

    if os.path.isdir(path):
        tools.open_with_default(path)
    elif os.path.exists(path):
        tools.reveal_in_explorer(path)


def _eta(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60:02d} s"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


class ProgressWindow(GlassWindow):
    """Ventana de progreso de una extracción o compresión.

    El trabajo corre en un hilo propio (no espera en la cola de tareas pesadas detrás de conversiones o
    escaneos) y escribe en un `ops.Stats`; esta ventana lo lee 8 veces por segundo, así que nunca se congela.
    Porcentaje, tamaño, velocidad y tiempo restante salen de bytes reales; si no se conocen, la barra pasa a
    modo indeterminado en lugar de inventar un porcentaje.
    """

    finished = Signal(bool)

    def __init__(self, title: str, controller=None):
        super().__init__(Qt.WindowType.WindowStaysOnTopHint, flat=True, resizable=False)
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("{title} · AERO Player", title=title))
        self.backdrop.flat_opacity = 0.95
        self.setFixedSize(500, 206)
        self.stats = ops.Stats()
        self._results: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self.result_path = ""
        self.ok = None
        self.retry = None              # función para reintentar tras un error
        self.key: tuple | None = None
        self._t0 = time.monotonic()
        self._speed = deque(maxlen=12)  # (instante, bytes) para una velocidad estable
        self._last_bytes = -1
        self._last_change = time.monotonic()
        self._countdown = 0
        self._hover = False
        self.title = label(title, "h3")
        self.item = label(tr("Preparando…"), "caption")
        self.item.setMinimumWidth(440)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.count = label("", "caption")
        self.detail = label("", "caption")
        self.cancel_btn = QPushButton(tr("Cancelar"))
        self.cancel_btn.clicked.connect(self.cancel)
        self.retry_btn = QPushButton(tr("Reintentar"))
        self.retry_btn.hide()
        self.retry_btn.clicked.connect(self._retry)
        self.open_btn = QPushButton(tr("Abrir carpeta"))
        self.open_btn.setProperty("kind", "primary")
        self.open_btn.hide()
        self.open_btn.clicked.connect(lambda: (_open_folder(self.result_path), self.close()))
        bar = DragArea()
        bar.setLayout(h_layout(16, self.title, None, self.window_buttons(maximize=False), spacing=4,
                               margins=(0, 8, 8, 0)))
        lay = QVBoxLayout(self.backdrop)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(bar)
        lay.addLayout(v_layout(self.item, self.bar, self.count, h_layout(self.detail, None, self.retry_btn,
                                                                         self.cancel_btn, self.open_btn, spacing=6),
                               spacing=6, margins=(18, 2, 18, 14)))
        self._poll = QTimer(self)
        self._poll.setInterval(125)
        self._poll.timeout.connect(self._drain)
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(1000)
        self._close_timer.timeout.connect(self._tick_close)

    def progress_cb(self):
        return lambda i, n, name: None  # el avance real llega por `stats`

    def cancelled_cb(self):
        ev = self._cancel
        return ev.is_set

    def start(self, job, on_done=None, on_error=None):
        """`job(stats, cancelled)` se ejecuta en un hilo propio; no debe tocar objetos Qt."""
        self._t0 = time.monotonic()
        self._on_done, self._on_error = on_done, on_error
        st, cancelled, results = self.stats, self._cancel.is_set, self._results

        def work():
            try:
                results.put(("ok", job(st, cancelled)))
            except BaseException as e:  # noqa: BLE001 - se muestra al usuario
                results.put(("err", e))

        self._thread = threading.Thread(target=work, name="aero-archive", daemon=True)
        self._thread.start()
        from aero.core import activity as act

        kind = "extract" if self.key and self.key[0] == "extract" else "compress"
        self._aid = act.activities().start(self.title.text(), kind, cancel=self.cancel)
        self._poll.start()
        self._place()
        self.show()

    def busy(self) -> bool:
        return self.ok is None

    def _place(self):
        """Varias operaciones a la vez: ventanas escalonadas en lugar de una encima de otra."""
        from PySide6.QtGui import QGuiApplication

        scr = QGuiApplication.primaryScreen()
        if scr is None:
            return
        others = [w for w in (self.controller.editors if self.controller is not None else [])
                  if isinstance(w, ProgressWindow) and w is not self and w.isVisible()]
        g = scr.availableGeometry()
        off = 36 * (len(others) % 8)
        self.move(g.center().x() - self.width() // 2 + off, g.center().y() - self.height() // 2 + off)

    # ------------------------------------------------------------------ progreso
    def _drain(self):
        st = self.stats
        now = time.monotonic()
        if self._cancel.is_set() and self.ok is None:
            self.item.setText(tr("Cancelando…"))
        elif st.current:
            self.item.setText(self.item.fontMetrics().elidedText(
                f"{st.phase if st.phase != 'Extrayendo' and st.phase != 'Comprimiendo' else ''} {st.current}".strip(),
                Qt.TextElideMode.ElideMiddle, 460))
        else:
            self.item.setText(st.phase)
        if st.done_bytes != self._last_bytes:
            self._last_bytes, self._last_change = st.done_bytes, now
            self._speed.append((now, st.done_bytes))
        stalled = now - self._last_change > 1.2
        if st.total_bytes > 0 and (st.exact or not stalled):
            if self.bar.maximum() == 0:
                self.bar.setRange(0, 1000)
            frac = min(1.0, st.done_bytes / st.total_bytes)
            self.bar.setValue(int(frac * 1000))
            parts = [f"{frac * 100:.0f} %"]
        else:
            # Total desconocido, o un archivo grande sin avance parcial (7Z al crear): indicador honesto.
            self.bar.setRange(0, 0)
            frac = None
            parts = []
        if frac is None and st.total_bytes > 0:
            parts.append("archivo grande, sin avance parcial")
        if st.total_files:
            parts.append(f"{min(st.done_files, st.total_files):,} de {st.total_files:,} archivos".replace(",", "."))
        if st.total_bytes:
            parts.append(f"{human_size(st.done_bytes)} de {human_size(st.total_bytes)}")
        self.count.setText(" · ".join(parts))
        detail = []
        if len(self._speed) >= 2:
            (t0, b0), (t1, b1) = self._speed[0], self._speed[-1]
            if t1 - t0 > 0.4 and b1 > b0:
                rate = (b1 - b0) / (t1 - t0)
                detail.append(f"{human_size(rate)}/s")
                if frac is not None and st.total_bytes > st.done_bytes:
                    detail.append(f"quedan {_eta((st.total_bytes - st.done_bytes) / rate)}")
        self.detail.setText(" · ".join(detail))
        if getattr(self, "_aid", None):
            from aero.core import activity as act

            act.activities().update(self._aid, frac, self.count.text())
        try:
            kind, value = self._results.get_nowait()
        except queue.Empty:
            return
        self._poll.stop()
        if kind == "ok":
            self._done(value)
        else:
            self._fail(value)

    def _report_end(self, state: str, result: str = "", error: str = "") -> None:
        aid, self._aid = getattr(self, "_aid", None), None
        if aid:
            from aero.core import activity as act

            act.activities().finish(aid, state, result, error)

    def _done(self, res):
        from aero.core import activity as act

        self._report_end(act.DONE, getattr(res, "dest", "") or getattr(res, "output", ""))
        self.ok = True
        self.bar.setRange(0, 1000)
        self.bar.setValue(1000)
        self.cancel_btn.setText(tr("Cerrar"))
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.close)
        _ACTIVE.pop(self.key, None)
        if self._on_done:
            self._on_done(self, res)
        self.finished.emit(True)

    def _fail(self, err):
        from aero.core import activity as act

        self._report_end(act.CANCELLED if isinstance(err, ops.Cancelled) else act.ERROR, "",
                         "" if isinstance(err, ops.Cancelled) else str(err))
        self.ok = False
        _ACTIVE.pop(self.key, None)
        if self._on_error and self._on_error(self, err):
            return
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        cancelled = isinstance(err, ops.Cancelled)
        self.item.setText(tr("Cancelado. No se ha dejado nada a medias.") if cancelled else
                          (str(err) if isinstance(err, ArchiveError) else tr("Error inesperado: {err}", err=err)))
        self.item.setWordWrap(True)
        self.count.setText("")
        self.detail.setText("")
        self.retry_btn.setVisible(self.retry is not None)
        self.cancel_btn.setText(tr("Cerrar"))
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.close)
        self.finished.emit(False)

    def cancel(self):
        if self.ok is not None:
            return
        self._cancel.set()
        proc = self.stats.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()  # WinRAR o tar.exe: se detienen al momento, sin quedar huérfanos
            except OSError:
                pass
        self.item.setText(tr("Cancelando…"))
        self.cancel_btn.setEnabled(False)

    def _retry(self):
        fn = self.retry
        self.close()
        if fn is not None:
            fn()

    # ------------------------------------------------------------------ final
    def show_success(self, text: str, folder: str, auto_close: bool | None = None):
        if auto_close is None:
            settings = getattr(self.controller, "settings", None)
            auto_close = True if settings is None else bool(settings.get("archive_auto_close"))
        self.result_path = folder
        self.item.setText(text)
        self.open_btn.show()
        self.detail.setText(tr("Hecho en {v0}", v0=_eta(time.monotonic() - self._t0)))
        self._hover = False  # solo cuenta si el usuario pone el ratón encima después de terminar
        from PySide6.QtGui import QCursor

        self._cursor_at_end = QCursor.pos()   # si la ventana aparece bajo el puntero quieto, no es «pasar por encima»
        if auto_close:
            # Se cierra sola a los pocos segundos; con el ratón encima la cuenta se pausa (para abrir la
            # carpeta) y sigue al apartarlo.
            self._countdown = AUTO_CLOSE_S
            self._close_timer.start()
            self._update_countdown()

    def _update_countdown(self):
        base = self.detail.text().split("  ·  ")[0]
        extra = ("  ·  " + tr("se cerrará al apartar el ratón") if self._hover else
                 "  ·  " + tr("se cierra en {n} s", n=self._countdown))
        self.detail.setText(base + extra)

    def _tick_close(self):
        if self._hover:
            return
        self._countdown -= 1
        if self._countdown <= 0:
            self._close_timer.stop()
            self.close()
        else:
            self._update_countdown()

    def enterEvent(self, e):
        from PySide6.QtGui import QCursor

        if self._close_timer.isActive() and QCursor.pos() == getattr(self, "_cursor_at_end", None):
            super().enterEvent(e)              # la ventana apareció bajo el puntero: el usuario no lo ha movido
            return
        self._hover = True
        if self._close_timer.isActive():
            self._update_countdown()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        if self._close_timer.isActive():
            self._countdown = max(self._countdown, 2)
            self._update_countdown()
        super().leaveEvent(e)

    def closeEvent(self, e):
        if self.ok is None:
            self.cancel()  # el hilo termina por su cuenta y deshace lo escrito
        _ACTIVE.pop(self.key, None)
        self._poll.stop()
        self._close_timer.stop()
        super().closeEvent(e)
        if self.controller is not None:
            self.controller.editor_closed(self)


def _existing(key: tuple) -> "ProgressWindow | None":
    w = _ACTIVE.get(key)
    if w is not None:
        try:
            if w.busy():
                w.show()
                w.raise_()
                w.activateWindow()
                return w
        except RuntimeError:  # ventana ya destruida
            pass
        _ACTIVE.pop(key, None)
    return None


# --------------------------------------------------------------------------- acciones
def run_extract(controller, path: str, dest: str, mode: str = "rename", password: str | None = None,
                members: list[str] | None = None, open_after: bool = False, parent=None) -> ProgressWindow:
    """Extrae con ventana de progreso; si pide contraseña, la pregunta y reintenta."""
    key = ("extract", os.path.abspath(path), os.path.abspath(dest), tuple(members or ()))
    running = _existing(key)
    if running is not None:
        return running
    w = ProgressWindow(f"Extrayendo {Path(path).name}", controller)
    w.key = key
    _ACTIVE[key] = w
    w.retry = lambda: run_extract(controller, path, dest, mode, password, members, open_after, parent)
    if controller is not None:
        controller.editors.append(w)

    def job(st, cancelled):
        return ops.extract(path, dest, password=password, mode=mode, members=members, cancelled=cancelled, stats=st)

    def done(win, res):
        extra = []
        if res.skipped:
            extra.append(f"{len(res.skipped)} omitidos")
        if res.unsafe:
            extra.append(f"{len(res.unsafe)} bloqueados por seguridad")
        win.show_success(f"Listo: {res.files} archivos en «{Path(res.dest).name}»" +
                         (f" ({', '.join(extra)})" if extra else ""), res.dest)
        if open_after:
            _open_folder(res.dest)

    def error(win, err):
        if isinstance(err, PasswordRequired):
            pw, ok = QInputDialog.getText(win, tr("Contraseña"), tr("{err}\nContraseña de «{v1}»:", err=err, v1=Path(path).name),
                                          QLineEdit.EchoMode.Password)
            if ok and pw:
                win.close()
                run_extract(controller, path, dest, mode, pw, members, open_after, parent)
                return True
        return False

    w.start(job, done, error)
    return w


def run_compress(controller, sources: list[str], out: str, fmt: str, level: int = 5, password: str | None = None,
                 open_after: bool = False) -> ProgressWindow:
    key = ("compress", tuple(os.path.abspath(s) for s in sources), os.path.abspath(out))
    running = _existing(key)
    if running is not None:
        return running
    w = ProgressWindow(f"Comprimiendo en {Path(out).name}", controller)
    w.key = key
    _ACTIVE[key] = w
    w.retry = lambda: run_compress(controller, sources, out, fmt, level, password, open_after)
    if controller is not None:
        controller.editors.append(w)

    def job(st, cancelled):
        return ops.compress(sources, out, fmt, level, password, cancelled=cancelled, stats=st)

    def done(win, res):
        size = os.path.getsize(res.output) if os.path.exists(res.output) else 0
        win.show_success(f"Listo: «{Path(res.output).name}» · {res.files} archivos · {human_size(size)}",
                         res.output)
        if open_after:
            _open_folder(res.output)

    w.start(job, done)
    return w


# --------------------------------------------------------------------------- diálogos
class ExtractDialog(TrDialog):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Extraer {Path(path).name}")
        self.path = path
        self.dest = QLineEdit(str(ops.suggested_folder(path)))
        browse = QPushButton(tr("Examinar…"))
        browse.clicked.connect(self._browse)
        self.mode = QComboBox()
        for k, t in MODES:
            self.mode.addItem(t, k)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(tr("Solo si el archivo está protegido"))
        self.open_after = QCheckBox(tr("Abrir la carpeta al terminar"))
        self.open_after.setChecked(True)
        form = QFormLayout()
        form.addRow(tr("Extraer en"), h_layout(self.dest, browse, spacing=4))
        form.addRow(tr("Si ya existe"), self.mode)
        form.addRow(tr("Contraseña"), self.password)
        form.addRow(self.open_after)
        ok = QPushButton(tr("Extraer"))
        ok.setProperty("kind", "primary")
        ok.clicked.connect(self.accept)
        cancel = QPushButton(tr("Cancelar"))
        cancel.clicked.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addLayout(form)
        lay.addLayout(h_layout(None, cancel, ok))
        self.setMinimumWidth(560)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("Carpeta de destino"), str(Path(self.path).parent))
        if d:
            self.dest.setText(d)


class CompressDialog(TrDialog):
    def __init__(self, sources: list[str], parent=None, fmt: str = "zip", level: int = 5):
        super().__init__(parent)
        self.sources = sources
        self.setWindowTitle("Comprimir" + (f" {Path(sources[0]).name}" if len(sources) == 1 else
                                          f" {len(sources)} elementos"))
        self.format = QComboBox()
        for k, t in ops.available_write_formats().items():
            self.format.addItem(t, k)
        self.level = QComboBox()
        for k, t in ops.LEVELS.items():
            self.level.addItem(t, k)
        self.level.setCurrentIndex(max(0, self.level.findData(level)))
        self.format.setCurrentIndex(max(0, self.format.findData(fmt)))
        default = ops.default_archive_name(sources, self.format.currentData() or "zip")
        self.name = QLineEdit(default.name)
        self.folder = QLineEdit(str(default.parent))
        browse = QPushButton(tr("Examinar…"))
        browse.clicked.connect(self._browse)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(tr("Opcional"))
        self.password2 = QLineEdit()
        self.password2.setEchoMode(QLineEdit.EchoMode.Password)
        self.password2.setPlaceholderText(tr("Repite la contraseña"))
        self.open_after = QCheckBox(tr("Mostrar el archivo al terminar"))
        self.note = label("", "caption", wrap=True)
        self.format.currentIndexChanged.connect(self._format_changed)
        form = QFormLayout()
        form.addRow(tr("Formato"), self.format)
        form.addRow(tr("Compresión"), self.level)
        form.addRow(tr("Nombre"), self.name)
        form.addRow(tr("Carpeta"), h_layout(self.folder, browse, spacing=4))
        form.addRow(tr("Contraseña"), self.password)
        form.addRow("", self.password2)
        form.addRow(self.open_after)
        ok = QPushButton(tr("Comprimir"))
        ok.setProperty("kind", "primary")
        ok.clicked.connect(self._accept)
        cancel = QPushButton(tr("Cancelar"))
        cancel.clicked.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addLayout(form)
        lay.addWidget(self.note)
        lay.addLayout(h_layout(None, cancel, ok))
        self.setMinimumWidth(560)
        self._format_changed()

    def fmt(self) -> str:
        return self.format.currentData()

    def _format_changed(self, *_):
        fmt = self.fmt()
        ext = {"tar.gz": ".tar.gz", "tar.xz": ".tar.xz"}.get(fmt, "." + fmt)
        name = self.name.text()
        for e in (".tar.gz", ".tar.xz", ".zip", ".aeroarchive", ".7z", ".rar"):
            if name.lower().endswith(e):
                name = name[: -len(e)]
                break
        self.name.setText(name + ext)
        tar = fmt.startswith("tar")
        self.password.setEnabled(not tar)
        self.password2.setEnabled(not tar)
        self.note.setText({"aeroarchive": "Formato de AERO Player con su propio icono y comprobación de integridad. "
                                          "Por dentro es un ZIP: también se puede recuperar con otras herramientas.",
                           "zip": "ZIP se abre en cualquier equipo. Con contraseña se cifra con AES-256 (los "
                                  "nombres de archivo quedan visibles).",
                           "7z": "7Z comprime más que ZIP. Con contraseña se cifran también los nombres (AES-256).",
                           "rar": "RAR se crea con tu WinRAR instalado. Con contraseña se cifran también los nombres.",
                           }.get(fmt, "TAR conserva la estructura y comprime todo junto; no admite contraseña."))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("Carpeta de destino"), self.folder.text())
        if d:
            self.folder.setText(d)

    def output(self) -> str:
        return str(Path(self.folder.text()) / self.name.text().strip())

    def _accept(self):
        if self.password.text() != self.password2.text():
            QMessageBox.warning(self, tr("Comprimir"), tr("Las contraseñas no coinciden."))
            return
        if not self.name.text().strip():
            return
        if os.path.exists(self.output()):
            r = QMessageBox.question(self, tr("Comprimir"), tr("Ya existe un archivo con ese nombre. ¿Reemplazarlo?"))
            if r != QMessageBox.StandardButton.Yes:
                return
        self.accept()


# --------------------------------------------------------------------------- gestor
class ArchiveManager(GlassWindow):
    """Abrir un comprimido, ver su contenido, extraer todo o una selección, comprobarlo y añadir archivos."""

    def __init__(self, path: str, controller=None):
        super().__init__(Qt.WindowType(0), flat=True)
        from aero.files.browser import FolderBrowser

        self.controller = controller
        self.path = os.path.abspath(path)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("{v0} · AERO Player", v0=Path(path).name))
        self.setMinimumSize(760, 480)
        self.backdrop.flat_opacity = 0.94
        bar = DragArea()
        self.title = label(Path(path).name, "h3")
        self.info = label("", "caption")  # resumen para lectores de pantalla y pruebas; la vista ya lo muestra
        self.info.hide()
        buttons = []
        folder = ops.suggested_folder(path).name
        for ic, text, tip, fn in (
                ("open", "Extraer en…", "Elegir carpeta, contraseña y qué hacer con los archivos existentes",
                 self.extract_to),
                ("drop", "Extraer aquí", f"Extraer junto al archivo, en «{Path(path).parent.name}»", self.extract_here),
                ("files", "Extraer en carpeta", f"Extraer en la carpeta «{folder}»", self.extract_folder),
                ("check", "Comprobar", "Comprobar que el archivo no está dañado", self.test),
                ("plus", "Añadir…", "Añadir archivos (también puedes arrastrarlos aquí)", self.add_files)):
            b = QPushButton(text)
            b.setIcon(IconButton(ic, "", 16).icon())
            b.setToolTip(tip + (tr(". Si hay elementos seleccionados, solo esos.") if fn in (
                self.extract_to, self.extract_here, self.extract_folder) else ""))
            b.setProperty("kind", "primary" if fn == self.extract_folder else "flat")
            b.clicked.connect(fn)
            buttons.append(b)
        self.add_btn = buttons[-1]
        self.add_btn.setEnabled(ops.format_of(path) in ("zip", "7z"))
        if not self.add_btn.isEnabled():
            self.add_btn.setToolTip(tr("Solo se pueden añadir archivos a ZIP y 7Z"))
        bar.setLayout(h_layout(16, self.title, None, self.window_buttons(), spacing=2, margins=(0, 8, 10, 0)))
        tools_row = h_layout(*buttons[:3], 12, *buttons[3:], None, spacing=4, margins=(12, 2, 14, 4))
        self.browser = FolderBrowser()
        self.browser.open_requested.connect(lambda p: controller and controller.show_quicklook(p))
        self.browser.action_requested.connect(self._browser_action)
        lay = QVBoxLayout(self.backdrop)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(bar)
        lay.addLayout(tools_row)
        body = QWidget()
        body.setLayout(v_layout(self.browser, margins=(14, 0, 14, 12)))
        lay.addWidget(body, 1)
        self.setAcceptDrops(True)
        self.browser.set_root(self.path)
        self.browser.location_changed.connect(self._sync)

    def _browser_action(self, action: str, args: list):
        if action == "extract_members":
            self.extract_to()
        elif self.controller is not None:
            self.controller.run_action(action, args, immediate=True)

    def _sync(self):
        a = self.browser.archive
        if a is not None:
            self.info.setText(tr("{fmt} · {v1} archivos · {v2} · {v3} comprimido", fmt=a.fmt, v1=len(a.files), v2=human_size(a.total_size), v3=human_size(os.path.getsize(self.path))))

    def _members(self) -> list[str] | None:
        sel = [e.inner for e in self.browser.selected_entries() if e.inner]
        return sel or None

    def extract_to(self):
        dlg = ExtractDialog(self.path, self)
        if dlg.exec():
            run_extract(self.controller, self.path, dlg.dest.text(), dlg.mode.currentData(),
                        dlg.password.text() or None, self._members(), dlg.open_after.isChecked())

    def extract_here(self):
        run_extract(self.controller, self.path, str(Path(self.path).parent), members=self._members())

    def extract_folder(self):
        folder = ops.suggested_folder(self.path)
        if folder.exists() and any(folder.iterdir()):
            folder = ops._unique(folder)
        run_extract(self.controller, self.path, str(folder), members=self._members(), open_after=True)

    def test(self):
        ok, msg = ops.test_archive(self.path)
        (QMessageBox.information if ok else QMessageBox.warning)(self, "Comprobar", msg)

    def add_files(self, paths: list[str] | None = None):
        if not paths:
            paths, _ = QFileDialog.getOpenFileNames(self, tr("Añadir al archivo"), str(Path(self.path).parent))
        if not paths:
            return
        try:
            add_to_archive(self.path, paths)
        except ArchiveError as e:
            QMessageBox.warning(self, tr("Añadir"), str(e))
            return
        self.browser.set_root(self.path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths and self.add_btn.isEnabled():
            self.add_files(paths)

    def closeEvent(self, e):
        self.browser.cleanup()
        super().closeEvent(e)
        if self.controller is not None:
            self.controller.editor_closed(self)


def add_to_archive(archive: str, paths: list[str]) -> None:
    """Añade archivos a un ZIP o 7Z existente (copia de seguridad hasta que termina bien)."""
    fmt = ops.format_of(archive)
    _base, items = ops._gather(paths)
    tmp = archive + ".bak"
    import shutil

    shutil.copy2(archive, tmp)
    try:
        if fmt == "zip":
            import zipfile

            with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as z:
                existing = set(z.namelist())
                for p, name, _size in items:
                    if name not in existing:
                        z.write(p, name)
        elif fmt == "7z":
            import py7zr

            with py7zr.SevenZipFile(archive, "a") as z:
                for p, name, _size in items:
                    if not name.endswith("/"):
                        z.write(p, name)
        else:
            raise ArchiveError("Solo se pueden añadir archivos a ZIP y 7Z.")
    except Exception as e:
        os.replace(tmp, archive)
        if isinstance(e, ArchiveError):
            raise
        raise ArchiveError(f"No se pudieron añadir los archivos: {e}") from e
    os.remove(tmp)


def open_manager(path: str, controller=None) -> ArchiveManager:
    w = ArchiveManager(path, controller)
    w.resize(980, 640)
    w.show()
    w.raise_()
    w.activateWindow()
    return w
