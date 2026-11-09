"""Instalador y desinstalador con el aspecto de AERO Player: ventana de cristal, burbujas y temas.

El trabajo pesado (extraer, registrar) se hace en un hilo de Python sin objetos de Qt; la ventana lee el
avance de una cola con un temporizador.
"""

from __future__ import annotations

import math
import os
import queue
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QRadialGradient
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QTextBrowser, QVBoxLayout, QWidget)

from aero import APP_NAME, __version__
from aero.i18n import tr
from aero.installer import core
from aero.ui import icons
from aero.ui.glass import FadeStack, GlassPanel, h_layout, label, make_app_icon, paint_bubble, tm
from aero.ui.glasswindow import DragArea, GlassWindow

FEATURES = [
    ("music", "Música y vídeo con visualizadores"),
    ("image", "Imágenes, PDF y documentos"),
    ("archive", "Extrae y comprime ZIP, 7Z y RAR"),
    ("convert", "Convierte entre formatos"),
    ("edit", "Editores de documentos e imágenes"),
    ("star", "Temas y fondos a tu gusto"),
]
TIPS = [
    "Haz clic derecho en un comprimido del Explorador › AERO Player › Extraer aquí.",
    "Pulsa V mientras suena música para ver el visualizador.",
    "En Ajustes › Apariencia puedes crear tus propios temas con el Estudio de temas.",
    "Activa la Vista rápida y pulsa Espacio en el Explorador para previsualizar archivos.",
    "Arrastra archivos al Conversor para convertir muchos a la vez.",
    "Con «Crear» en Inicio empiezas un documento, una hoja o un proyecto de vídeo.",
]


# ---------------------------------------------------------------------------------------------- tema
def apply_theme(key: str, motion: bool = True) -> None:
    """Aplica un tema prediseñado al instalador (con las burbujas en movimiento, como en la aplicación)."""
    import copy

    from aero.ui.style import AeroStyle, sync_palette
    from aero.ui.theme import PRESETS, build_qss, theme_from_spec

    app = QApplication.instance()
    key = key if key in PRESETS else "burbuja"
    spec = copy.deepcopy(PRESETS[key])
    if motion and float(spec["motion"]["speed"]) <= 0:
        spec["motion"]["speed"] = 0.35
    tm().apply(theme_from_spec(key, spec), 0.6, "blur", 0.45, False)
    from aero.ui import corners

    corners.install(app)
    if not isinstance(app.style(), AeroStyle):
        app._aero_style = AeroStyle()
        app.setStyle(app._aero_style)
    sync_palette(app)
    app.setStyleSheet(build_qss(tm().theme, False))


# ---------------------------------------------------------------------------------------------- piezas
class HeroLogo(QWidget):
    """Logotipo con halo y burbujas que suben despacio a su alrededor."""

    def __init__(self, size: int = 230, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.icon = make_app_icon(256)
        self._t0 = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self.setAccessibleName(APP_NAME)

    def showEvent(self, e):
        super().showEvent(e)
        if not tm().reduce_motion:
            self._timer.start(33)

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        t = tm().theme
        w, h = self.width(), self.height()
        c = QPointF(w / 2, h / 2)
        tt = time.perf_counter() - self._t0
        pulse = 0.5 + 0.5 * math.sin(tt * 1.4)
        halo = QRadialGradient(c, w * 0.5)
        col = QColor(t.accent)
        col.setAlphaF(0.30 + 0.12 * pulse)
        halo.setColorAt(0, col)
        col.setAlphaF(0.0)
        halo.setColorAt(1, col)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, w * 0.5, h * 0.5)
        s = w * 0.56
        bob = math.sin(tt * 1.1) * 4
        p.drawPixmap(QRectF(c.x() - s / 2, c.y() - s / 2 + bob, s, s), self.icon, QRectF(self.icon.rect()))
        for i in range(7):
            ph = (tt * (0.10 + 0.03 * i) + i / 7) % 1.0
            x = w * (0.12 + 0.76 * ((i * 0.37) % 1.0)) + math.sin(tt * 1.5 + i) * 6
            y = h * (1.0 - ph)
            r = 5 + (i % 3) * 4
            fade = math.sin(ph * math.pi)
            paint_bubble(p, QPointF(x, y), r, QColor(t.accent), fill=0.05, rim=0.9 * fade)
        p.end()


class CheckBubble(QWidget):
    """Burbuja con una marca de verificación para la pantalla final."""

    def __init__(self, ok: bool = True, parent=None):
        super().__init__(parent)
        self.ok = ok
        self.setFixedSize(150, 150)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = tm().theme
        c = QPointF(self.width() / 2, self.height() / 2)
        color = QColor(t.accent if self.ok else "#ff7a8a")
        paint_bubble(p, c, 62, color, fill=0.30, rim=1.0)
        pm = icons.pixmap("check" if self.ok else "close", "#ffffff", 64)
        p.drawPixmap(QRectF(c.x() - 32, c.y() - 32, 64, 64), pm, QRectF(pm.rect()))
        p.end()


class FeatureIcon(QLabel):
    """Icono de una función; su color sigue al tema elegido en el instalador."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.setFixedSize(20, 20)
        self.refresh()
        tm().changed.connect(self.refresh)

    def refresh(self):
        self.setPixmap(icons.pixmap(self.name, tm().theme.accent, 18))


def feature_grid() -> QGridLayout:
    grid = QGridLayout()
    grid.setHorizontalSpacing(18)
    grid.setVerticalSpacing(8)
    for i, (ic, text) in enumerate(FEATURES):
        icon = FeatureIcon(ic)
        grid.addLayout(h_layout(icon, label(text), None, spacing=8), i // 2, i % 2)  # label() traduce
    return grid


# ---------------------------------------------------------------------------------------------- ventana
class InstallerWindow(GlassWindow):
    def __init__(self, payload_dir: Path | None, opts: "core.Options | None" = None):
        super().__init__(resizable=False)
        self.payload_dir_ = payload_dir
        self.setWindowTitle(tr("Instalar {app}", app=APP_NAME))
        self.setWindowIcon(QIcon(make_app_icon(256)))
        self.setFixedSize(900, 570)
        self.payload: core.Payload | None = None
        self.payload_error = ""
        try:
            if payload_dir is None:
                raise FileNotFoundError(tr("no se encontró el paquete de instalación"))
            self.payload = core.Payload.load(payload_dir)
        except (OSError, ValueError, KeyError) as e:
            self.payload_error = str(e)
        self.version = self.payload.version if self.payload else __version__
        self.existing = core.find_existing()
        self.opts = opts or core.Options()
        if opts is None and self.existing is not None:
            self.opts.target = self.existing.folder
        self._chosen_theme = core.current_theme() or "burbuja"
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()
        self.installed: Path | None = None
        self._tip = 0

        bar = DragArea()
        bar.setFixedHeight(44)
        logo = QLabel()
        logo.setPixmap(make_app_icon(64).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))
        self.header = label(self._title_text(), "h3")
        self.buttons_ = self.window_buttons(maximize=False)
        bar.setLayout(h_layout(16, logo, 8, self.header, None, self.buttons_, spacing=0, margins=(0, 6, 8, 0)))

        self.stack = FadeStack()
        self.page_welcome = self._welcome()
        self.page_options = self._options()
        self.page_progress = self._progress()
        self.page_done = self._done()
        for pg in (self.page_welcome, self.page_options, self.page_progress, self.page_done):
            self.stack.addWidget(pg)

        lay = QVBoxLayout(self.backdrop)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(bar)
        body = QVBoxLayout()
        body.setContentsMargins(18, 6, 18, 18)
        body.addWidget(self.stack, 1)
        lay.addLayout(body, 1)

        self._poll = QTimer(self)
        self._poll.setInterval(60)
        self._poll.timeout.connect(self._drain)
        self._tips = QTimer(self)
        self._tips.setInterval(4500)
        self._tips.timeout.connect(self._next_tip)

    def _title_text(self) -> str:
        if self.existing is not None:
            return f"Actualizar {APP_NAME}"
        return f"Instalar {APP_NAME}"

    # ------------------------------------------------------------------ páginas
    def _welcome(self) -> QWidget:
        page = QWidget()
        panel = GlassPanel(radius=18)
        hero = HeroLogo(230)
        name = label(APP_NAME, "h1")
        f = QFont(name.font())
        f.setPointSizeF(26)
        name.setFont(f)
        ver = label(tr("Versión {v}", v=self.version), "accent")
        if self.existing is not None and self.existing.version:
            ver.setText(tr("Versión instalada {old}  →  nueva {new}", old=self.existing.version, new=self.version))
        desc = label(tr("Reproduce, abre, edita, convierte y comprime tus archivos desde un solo lugar."), "muted",
                     wrap=True)
        self.install_btn = QPushButton(tr("Actualizar" if self.existing is not None else "Instalar"))
        self.install_btn.setProperty("kind", "primary")
        self.install_btn.setMinimumSize(150, 40)
        self.install_btn.clicked.connect(self.start_install)
        custom = QPushButton(tr("Personalizar…"))
        custom.setMinimumHeight(40)
        custom.clicked.connect(lambda: self.stack.fade_to(1))
        self.where = label("", "caption")
        lic = QPushButton(tr("Licencia GPL v3"))
        from aero.i18n import LANGUAGES, language

        self.lang = QComboBox()
        for code, lang_name in LANGUAGES.items():
            self.lang.addItem(lang_name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(language())))
        self.lang.setToolTip(tr("Idioma de la instalación y de AERO Player"))
        self.lang.setAccessibleName(tr("Idioma"))
        self.lang.currentIndexChanged.connect(self._language_changed)
        lic.setProperty("kind", "flat")
        lic.clicked.connect(self._show_license)
        right = QVBoxLayout()
        right.setSpacing(8)
        right.addStretch(1)
        right.addWidget(name)
        right.addWidget(ver)
        right.addSpacing(4)
        right.addWidget(desc)
        right.addSpacing(10)
        right.addLayout(feature_grid())
        right.addSpacing(18)
        right.addLayout(h_layout(self.install_btn, custom, None, spacing=10))
        right.addStretch(1)
        inner = h_layout(hero, 18, spacing=0)
        inner.addLayout(right, 1)
        outer_v = QVBoxLayout(panel)
        outer_v.setContentsMargins(18, 18, 22, 12)
        outer_v.addLayout(inner, 1)
        outer_v.addLayout(h_layout(self.where, None, self.lang, lic, spacing=8))
        if self.payload is None:
            self.install_btn.setEnabled(False)
            custom.setEnabled(False)
            self.where.setText(tr("No se puede instalar: {e}.", e=self.payload_error))
        else:
            self._update_where()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(panel)
        return page

    def _language_changed(self, *_):
        """Se vuelve a construir la ventana en el idioma elegido (se conserva lo ya elegido)."""
        from aero.i18n import set_language

        code = self.lang.currentData()
        set_language(code)
        self.opts.language = code
        w = InstallerWindow(self.payload_dir_, self.opts)
        w.quit_on_close, self.quit_on_close = self.quit_on_close, False
        w.move(self.pos())
        w.show()
        self._replaced = True
        self.close()

    def _update_where(self):
        target = core.safe_target(self.opts.target)
        size = (self.payload.total if self.payload else 0) / (1024 * 1024)
        self.where.setText(tr("Se instalará en {path}  ·  {mb} MB  ·  no necesita permisos de administrador",
                             path=target, mb=f"{size:.0f}"))
        self.where.setToolTip(str(target))

    def _options(self) -> QWidget:
        from aero.ui.tutorial import ThemePicker

        page = QWidget()
        panel = GlassPanel(radius=18)
        self.folder = QLineEdit(str(self.opts.target))
        self.folder.textChanged.connect(self._folder_changed)
        browse = QPushButton(tr("Examinar…"))
        browse.clicked.connect(self._browse)
        self.cb_start = QCheckBox(tr("Acceso en el menú Inicio"))
        self.cb_start.setChecked(True)
        self.cb_desktop = QCheckBox(tr("Acceso directo en el escritorio"))
        self.cb_ctx = QCheckBox(tr("Menú «AERO Player» en el clic derecho"))
        self.cb_ctx.setToolTip(tr("Extraer, comprimir y convertir desde el Explorador de Windows"))
        self.cb_ctx.setChecked(True)
        self.cb_assoc = QCheckBox(tr("Aparecer en «Abrir con» para tus archivos"))
        self.cb_assoc.setChecked(True)
        self.cb_assoc.setToolTip(tr("Aparecerá en «Abrir con» y en Aplicaciones predeterminadas. Windows te deja "
                                 "elegir; AERO Player nunca se impone."))
        if self.existing is not None:
            links = core.shortcut_paths()
            self.cb_desktop.setChecked(links["desktop"].exists())
        picker = ThemePicker(self._chosen_theme, self._pick_theme, columns=4)
        install = QPushButton(tr("Actualizar" if self.existing is not None else "Instalar"))
        install.setProperty("kind", "primary")
        install.setMinimumSize(150, 38)
        install.clicked.connect(self.start_install)
        back = QPushButton(tr("Atrás"))
        back.setMinimumHeight(38)
        back.clicked.connect(lambda: self.stack.fade_to(0))
        col = QVBoxLayout()
        col.setSpacing(8)
        col.addWidget(label(tr("Personaliza la instalación"), "h2"))
        col.addWidget(label(tr("Carpeta"), "h3"))
        col.addLayout(h_layout(self.folder, browse, spacing=6))
        col.addSpacing(4)
        col.addWidget(label(tr("Integración con Windows"), "h3"))
        for cb in (self.cb_start, self.cb_desktop, self.cb_ctx, self.cb_assoc):
            col.addWidget(cb)
        col.addSpacing(6)
        col.addWidget(label(tr("Todo se instala solo para tu usuario y se puede cambiar después en Ajustes. Tus datos "
                            "nunca se borran."), "caption", wrap=True))
        col.addStretch(1)
        side = QVBoxLayout()
        side.setSpacing(8)
        side.addWidget(label(tr("Tu tema"), "h2"))
        hint = label(tr("Así se verá AERO Player al abrirlo. Puedes cambiarlo cuando quieras."), "muted", wrap=True)
        hint.setMaximumWidth(4 * 86)
        side.addWidget(hint)
        side.addWidget(picker)
        side.addStretch(1)
        top = h_layout(spacing=26)
        top.addLayout(col, 1)
        top.addLayout(side)
        v = QVBoxLayout(panel)
        v.setContentsMargins(26, 20, 26, 18)
        v.addLayout(top, 1)
        v.addLayout(h_layout(None, back, install, spacing=10))
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        return page

    def _progress(self) -> QWidget:
        page = QWidget()
        panel = GlassPanel(radius=18)
        self.prog_title = label(tr("Instalando AERO Player…"), "h2")
        self.pct = label("0 %", "h1")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.current = label("", "caption")
        self.current.setMinimumWidth(10)
        self.tip = label("", "muted", wrap=True)
        self.tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v = QVBoxLayout(panel)
        v.setContentsMargins(60, 24, 60, 30)
        v.setSpacing(10)
        v.addWidget(HeroLogo(170), 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self.prog_title, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self.pct, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self.bar)
        v.addWidget(self.current)
        v.addStretch(1)
        v.addWidget(label(tr("¿Sabías que…?"), "accent"), 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self.tip)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        return page

    def _done(self) -> QWidget:
        page = QWidget()
        panel = GlassPanel(radius=18)
        self.done_icon = CheckBubble(True)
        self.done_title = label(tr("¡AERO Player está listo!"), "h1")
        self.done_text = label("", "muted", wrap=True)
        self.done_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cb_launch = QCheckBox(tr("Abrir AERO Player ahora"))
        self.cb_launch.setChecked(True)
        self.finish = QPushButton(tr("Finalizar"))
        self.finish.setProperty("kind", "primary")
        self.finish.setMinimumSize(160, 40)
        self.finish.clicked.connect(self._finish)
        self.retry = QPushButton(tr("Reintentar"))
        self.retry.setMinimumHeight(40)
        self.retry.clicked.connect(self.start_install)
        self.retry.hide()
        v = QVBoxLayout(panel)
        v.setContentsMargins(60, 30, 60, 30)
        v.setSpacing(10)
        v.addStretch(1)
        v.addWidget(self.done_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self.done_title, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self.done_text)
        v.addSpacing(8)
        v.addWidget(self.cb_launch, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(8)
        v.addLayout(h_layout(None, self.retry, self.finish, None, spacing=10))
        v.addStretch(1)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        return page

    # ------------------------------------------------------------------ acciones
    def _pick_theme(self, key: str):
        self._chosen_theme = key
        self.opts.theme = key
        apply_theme(key)

    def _folder_changed(self, text: str):
        self.opts.target = Path(text.strip() or str(core.default_dir()))
        self._update_where()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("Carpeta de instalación"), self.folder.text())
        if d:
            self.folder.setText(str(core.safe_target(d)))

    def _show_license(self):
        from PySide6.QtWidgets import QDialog

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Licencia de AERO Player"))
        dlg.resize(640, 520)
        txt = QTextBrowser()
        txt.setPlainText(_read_license())
        ok = QPushButton(tr("Cerrar"))
        ok.clicked.connect(dlg.accept)
        v = QVBoxLayout(dlg)
        v.addWidget(txt)
        v.addLayout(h_layout(None, ok))
        dlg.exec()

    def start_install(self):
        if self.payload is None or (self._worker is not None and self._worker.is_alive()):
            return
        self.opts.start_menu = self.cb_start.isChecked()
        self.opts.desktop = self.cb_desktop.isChecked()
        self.opts.context_menu = self.cb_ctx.isChecked()
        self.opts.associations = self.cb_assoc.isChecked()
        target = core.safe_target(self.opts.target)
        if core.is_running(target):
            core.request_quit()  # se cierra como con «Salir»; el hilo espera a que termine
        self.retry.hide()
        self.buttons_.close_btn.setEnabled(False)
        self.prog_title.setText(tr("Actualizando AERO Player…" if self.existing is not None else
                                   "Instalando AERO Player…"))
        self.stack.fade_to(2)
        self._next_tip()
        self._tips.start()
        self._poll.start()
        payload, opts, q = self.payload, self.opts, self._queue

        def work():
            try:
                folder = core.install(payload, opts, lambda f, text: q.put(("progress", f, text)))
                q.put(("done", str(folder), ""))
            except Exception as e:  # noqa: BLE001 - se muestra al usuario
                q.put(("error", 0.0, str(e) or e.__class__.__name__))

        self._worker = threading.Thread(target=work, name="aero-install", daemon=True)
        self._worker.start()

    def _drain(self):
        last = None
        while True:
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                break
            if msg[0] == "progress":
                last = msg
            elif msg[0] == "done":
                self._finished(Path(msg[1]))
                return
            else:
                self._failed(msg[2])
                return
        if last is not None:
            f = max(0.0, min(1.0, float(last[1])))
            self.bar.setValue(int(f * 1000))
            self.pct.setText(f"{f * 100:.0f} %")
            fm = self.current.fontMetrics()
            self.current.setText(fm.elidedText(str(last[2]), Qt.TextElideMode.ElideMiddle, self.current.width()))

    def _next_tip(self):
        self.tip.setText(tr(TIPS[self._tip % len(TIPS)]))
        self._tip += 1

    def _finished(self, folder: Path):
        self._poll.stop()
        self._tips.stop()
        self.installed = folder
        self.buttons_.close_btn.setEnabled(True)
        self.done_icon.ok = True
        self.done_title.setText(tr("¡AERO Player está listo!"))
        self.done_text.setText(tr("La primera vez que lo abras te enseñará sus funciones con un tutorial breve "
                                  "(puedes saltarlo). Tus ajustes y bibliotecas se conservan siempre."))
        self.cb_launch.show()
        self.finish.setText(tr("Finalizar"))
        self.stack.fade_to(3)

    def _failed(self, message: str):
        self._poll.stop()
        self._tips.stop()
        self.buttons_.close_btn.setEnabled(True)
        self.done_icon.ok = False
        self.done_icon.update()
        self.done_title.setText(tr("No se pudo completar la instalación"))
        self.done_text.setText(message)
        self.cb_launch.hide()
        self.retry.show()
        self.finish.setText(tr("Cerrar"))
        self.stack.fade_to(3)

    def _finish(self):
        if self.installed is not None and self.cb_launch.isChecked():
            core.run_app(self.installed, wait=False)
        self.close()

    def closeEvent(self, e):
        if self._worker is not None and self._worker.is_alive():
            e.ignore()  # no se interrumpe a medias: dejaría la instalación incompleta
            return
        super().closeEvent(e)
        QApplication.instance().quit()


def _read_license() -> str:
    for base in (Path(getattr(sys, "_MEIPASS", "")), Path(__file__).resolve().parents[2], core.default_dir()):
        p = base / "LICENSE"
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    return "AERO Player se distribuye bajo la licencia GNU GPL v3 (https://www.gnu.org/licenses/gpl-3.0.html)."


# ---------------------------------------------------------------------------------------------- desinstalar
class UninstallWindow(GlassWindow):
    def __init__(self, folder: Path):
        super().__init__(resizable=False)
        self.folder = folder
        self.setWindowTitle(tr("Desinstalar {app}", app=APP_NAME))
        self.setWindowIcon(QIcon(make_app_icon(256)))
        self.setFixedSize(560, 380)
        bar = DragArea()
        bar.setFixedHeight(44)
        self.buttons_ = self.window_buttons(maximize=False)
        bar.setLayout(h_layout(16, label(tr("Desinstalar {app}", app=APP_NAME), "h3"), None, self.buttons_, spacing=0,
                               margins=(0, 6, 8, 0)))
        panel = GlassPanel(radius=18)
        self.icon = HeroLogo(130)
        self.title = label(tr("¿Quieres desinstalar {app}?", app=APP_NAME), "h2")
        self.text = label(tr("Se quitarán el programa, sus accesos directos, el menú del clic derecho y su registro "
                          "en Windows.\nTus ajustes, bibliotecas, listas y archivos se conservan."), "muted", wrap=True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.wipe = QCheckBox(tr("Borrar también mis ajustes, bibliotecas y listas de AERO Player"))
        self.wipe.setToolTip(tr("Tus fotos, música, vídeos y documentos nunca se borran"))
        self.go = QPushButton(tr("Desinstalar"))
        self.go.setProperty("kind", "primary")
        self.go.setMinimumSize(140, 38)
        self.go.clicked.connect(self.run)
        self.cancel = QPushButton(tr("Cancelar"))
        self.cancel.setMinimumHeight(38)
        self.cancel.clicked.connect(self.close)
        v = QVBoxLayout(panel)
        v.setContentsMargins(30, 14, 30, 20)
        v.setSpacing(8)
        v.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self.text)
        v.addStretch(1)
        v.addWidget(self.wipe, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addLayout(h_layout(None, self.cancel, self.go, None, spacing=10))
        lay = QVBoxLayout(self.backdrop)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(bar)
        body = QVBoxLayout()
        body.setContentsMargins(16, 4, 16, 16)
        body.addWidget(panel, 1)
        lay.addLayout(body, 1)

    def run(self):
        self.go.setEnabled(False)
        self.cancel.setEnabled(False)
        self.title.setText(tr("Desinstalando…"))
        QApplication.processEvents()
        uninstall(self.folder, wipe_settings=self.wipe.isChecked())
        self.wipe.setEnabled(False)
        self.title.setText(tr("{app} se ha desinstalado", app=APP_NAME))
        self.text.setText(tr("Gracias por usarlo. Tus archivos siguen en su sitio.") if not self.wipe.isChecked()
                          else tr("Gracias por usarlo. Se han borrado también tus ajustes."))
        self.go.hide()
        self.cancel.setText(tr("Cerrar"))
        self.cancel.setEnabled(True)


def uninstall(folder: Path, wipe_settings: bool = False) -> None:
    core.request_quit()  # por si hay otra ventana de AERO Player abierta (en la bandeja, por ejemplo)
    core.unregister_everything(folder)
    if wipe_settings:
        core.remove_user_settings()
    core.schedule_removal(folder, os.getpid())


# ---------------------------------------------------------------------------------------------- arranque
def payload_dir() -> Path | None:
    for base in (os.environ.get("AERO_PAYLOAD"), getattr(sys, "_MEIPASS", None) and
                 os.path.join(sys._MEIPASS, "payload"),
                 Path(__file__).resolve().parents[2] / "build" / "payload"):
        if base and (Path(base) / "manifest.json").is_file():
            return Path(base)
    return None


def _app() -> QApplication:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AeroPlayer.Setup")
        except (OSError, AttributeError):
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    font = QFont("Segoe UI Variable Text")
    font.setPointSizeF(10)
    app.setFont(font)
    return app


def main_install() -> int:
    app = _app()
    from aero.i18n import DEFAULT_LANGUAGE, set_language

    set_language(core.current_setting("language") or DEFAULT_LANGUAGE)
    apply_theme(core.current_theme() or "burbuja")
    w = InstallerWindow(payload_dir())
    w.show()
    return app.exec()


def main_update() -> int:
    """Actualización desde AERO Player (`setup.exe --update`): sin asistente, conservando las opciones de la
    instalación y los datos; al terminar se vuelve a abrir AERO Player. Si algo falla, se abre el asistente."""
    import threading

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

    from aero.i18n import DEFAULT_LANGUAGE, set_language, tr

    app = _app()
    set_language(core.current_setting("language") or DEFAULT_LANGUAGE)
    apply_theme(core.current_theme() or "burbuja")
    payload = payload_dir()
    if payload is None:
        return main_install()
    pl = core.Payload.load(payload)
    opts = core.options_for_update(core.find_existing())
    w = QWidget()
    w.setWindowTitle(tr("Actualizando {app}", app=APP_NAME))
    title = QLabel(tr("Actualizando {app} a la versión {v}…", app=APP_NAME, v=pl.version))
    status = QLabel("")
    bar = QProgressBar()
    bar.setRange(0, 1000)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(24, 22, 24, 22)
    lay.addWidget(title)
    lay.addWidget(bar)
    lay.addWidget(status)
    w.resize(460, 140)
    w.show()
    state = {"p": 0.0, "msg": "", "done": False, "error": None}

    def work():
        try:
            core.install(pl, opts, lambda f, m: state.update(p=f, msg=m))
        except Exception as e:  # noqa: BLE001 - cualquier fallo: se muestra el asistente completo
            state["error"] = e
        state["done"] = True

    threading.Thread(target=work, daemon=True).start()
    result = {"code": 0}

    def tick():
        bar.setValue(int(state["p"] * 1000))
        status.setText(tr(state["msg"]) if state["msg"] else "")
        if not state["done"]:
            return
        timer.stop()
        w.close()
        if state["error"] is not None:
            result["code"] = 1
            iw = InstallerWindow(payload)
            iw.show()
            return
        core.run_app(opts.target, wait=False)          # se vuelve a abrir AERO Player, ya actualizado
        app.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    app.exec()
    return result["code"]


def main_uninstall(quiet: bool = False) -> int:
    from aero.i18n import DEFAULT_LANGUAGE, set_language

    set_language(core.current_setting("language") or DEFAULT_LANGUAGE)
    folder = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else core.default_dir()
    app = _app()
    if quiet:
        uninstall(folder)
        return 0
    apply_theme(core.current_theme() or "burbuja")
    w = UninstallWindow(folder)
    w.show()
    w.destroyed.connect(app.quit)
    w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    return app.exec()

