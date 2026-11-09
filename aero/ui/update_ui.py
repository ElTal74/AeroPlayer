"""Interfaz de las actualizaciones (ver aero/core/updater.py).

Al iniciar (como mucho una vez al día y si está activado en Ajustes) se consulta GitHub en segundo plano. Si hay
una versión nueva aparece un aviso y un diálogo con sus novedades: «Actualizar ahora» descarga el instalador,
comprueba su SHA-256 y lo ejecuta en modo actualización; AERO Player se cierra y vuelve a abrirse ya actualizado.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout

from aero import APP_NAME, __version__
from aero.core import updater
from aero.i18n import tr
from aero.ui.glass import label
from aero.ui.glasswindow import TrDialog

_open: list = []       # diálogos abiertos (uno a la vez)


def error_text(msg: str) -> str:
    """Errores del actualizador (texto de origen en español) en el idioma de la interfaz."""
    head, _, rest = msg.partition(": ")
    if head == "No se pudo descargar" and rest:
        return tr("No se pudo descargar: {e}", e=rest)
    if msg.startswith("GitHub respondió"):
        return tr("GitHub respondió {e}", e=msg.split(" ")[-1])
    return tr(msg)


class UpdateDialog(TrDialog):
    def __init__(self, rel: updater.Release, settings, controller=None, parent=None):
        super().__init__(parent)
        self.rel, self.settings, self.controller = rel, settings, controller
        self.setWindowTitle(tr("Actualización disponible"))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        head = label(tr("{app} {v} ya está aquí", app=APP_NAME, v=rel.version), "title", wrap=True)
        sub = label(tr("Tienes la versión {v}. Tus ajustes, bibliotecas y proyectos se conservan.", v=__version__),
                    "muted", wrap=True)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(rel.notes[:20000] or tr("Sin notas de la versión."))
        self.notes.setMinimumHeight(220)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        self.status = label("", "caption", wrap=True)
        self.btn_update = QPushButton(tr("Actualizar ahora") if updater.can_install() else tr("Ir a la descarga"))
        self.btn_update.setProperty("kind", "primary")
        self.btn_update.clicked.connect(self._update)
        self.btn_later = QPushButton(tr("Más tarde"))
        self.btn_later.clicked.connect(self.reject)
        self.btn_skip = QPushButton(tr("Omitir esta versión"))
        self.btn_skip.setProperty("kind", "flat")
        self.btn_skip.clicked.connect(self._skip)
        row = QHBoxLayout()
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        row.addWidget(self.btn_later)
        row.addWidget(self.btn_update)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)
        lay.addWidget(head)
        lay.addWidget(sub)
        lay.addWidget(QLabel(tr("Novedades")))
        lay.addWidget(self.notes, 1)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        lay.addLayout(row)
        self.resize(560, 480)
        self._state = None
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._tick)
        # método y no lambda con `self`: sin ciclo de referencias que el recolector rompa en mal momento
        self.finished.connect(self._forget)

    def _forget(self, *_):
        if self in _open:
            _open.remove(self)

    def _skip(self):
        self.settings.set("update_skip", self.rel.version)
        self.reject()

    def _update(self):
        if not updater.can_install():
            from aero.core import tools

            tools.open_with_default(self.rel.page)
            self.accept()
            return
        self.btn_update.setEnabled(False)
        self.btn_skip.setEnabled(False)
        self.btn_later.setText(tr("Cancelar"))
        self.bar.show()
        self.status.setText(tr("Descargando {name}…", name=self.rel.setup_name))
        # El hilo no toca objetos de Qt: deja el avance en un diccionario que lee el temporizador.
        state = {"done": 0, "total": self.rel.setup_size, "path": None, "error": None, "cancel": False, "end": False}
        self._state = state
        rel = self.rel

        def work():
            try:
                state["path"] = updater.download(rel, lambda d, t: state.update(done=d, total=t),
                                                 lambda: state["cancel"])
            except Exception as e:  # noqa: BLE001
                state["error"] = str(e)
            state["end"] = True

        threading.Thread(target=work, name="aero-update", daemon=True).start()
        self._timer.start()

    def _tick(self):
        st = self._state
        if st["total"]:
            self.bar.setValue(int(st["done"] / st["total"] * 1000))
        if not st["end"]:
            return
        self._timer.stop()
        if st["error"]:
            self.status.setText(tr("No se pudo actualizar: {e}", e=error_text(st["error"])))
            self.btn_update.setEnabled(True)
            self.btn_update.setText(tr("Reintentar"))
            self.btn_later.setText(tr("Más tarde"))
            return
        self.status.setText(tr("Comprobado. Instalando y reiniciando {app}…", app=APP_NAME))
        try:
            updater.launch_installer(st["path"])
        except Exception as e:  # noqa: BLE001
            self.status.setText(tr("No se pudo actualizar: {e}", e=e))
            return
        QTimer.singleShot(400, self._quit_app)

    def _quit_app(self):
        if self.controller is not None and hasattr(self.controller, "quit"):
            self.controller.quit()
        else:
            from PySide6.QtWidgets import QApplication

            QApplication.quit()

    def reject(self):
        if self._state and not self._state["end"]:
            self._state["cancel"] = True
        super().reject()


def show_update(rel: updater.Release, settings, controller=None, parent=None) -> UpdateDialog:
    for d in list(_open):
        d.raise_()
        d.activateWindow()
        return d
    dlg = UpdateDialog(rel, settings, controller, parent)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)      # Qt lo libera al cerrarlo, no el recolector
    _open.append(dlg)
    dlg.show()
    dlg.raise_()
    return dlg


def check_in_background(settings, on_result, force: bool = False, owner=None) -> None:
    """Consulta GitHub sin bloquear la interfaz. `on_result(release | None, error | None)` en el hilo principal.

    Si `owner` (un widget) se destruye antes de la respuesta, el resultado se descarta."""
    from aero.ui.async_util import run_async

    if not force and not updater.due(settings):
        return

    def done(rel):
        settings.set("update_last_check", time.time())
        on_result(rel, None)

    run_async(updater.check, done, lambda e: on_result(None, str(e)), owner)


def startup_check(controller) -> None:
    """Comprobación al iniciar: si hay versión nueva (y no la omitió el usuario), aviso y diálogo."""
    settings = controller.settings

    def result(rel, _err):
        if rel is None or rel.version == settings.get("update_skip"):
            return
        main = controller.main
        if main is not None:
            main.notify(tr("Hay una versión nueva: {app} {v}", app=APP_NAME, v=rel.version), "info")
        show_update(rel, settings, controller, main)

    check_in_background(settings, result, owner=controller.main)


# ----------------------------------------------------------------------------- novedades tras actualizar

def changelog_section(version: str) -> str:
    """Texto de `## <versión>` del CHANGELOG incluido en el programa (vacío si no está)."""
    import re
    import sys
    from pathlib import Path

    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        text = (base / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(rf"^## {re.escape(version)}(?![\d.]).*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


class WhatsNewDialog(TrDialog):
    def __init__(self, version: str, notes: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Novedades"))
        head = label(tr("Novedades de {app} {v}", app=APP_NAME, v=version), "title", wrap=True)
        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setMarkdown(notes)
        ok = QPushButton(tr("¡A disfrutarlo!"))
        ok.setProperty("kind", "primary")
        ok.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(ok)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.addWidget(head)
        lay.addWidget(body, 1)
        lay.addLayout(row)
        self.resize(560, 460)


def whats_new(controller) -> WhatsNewDialog | None:
    """Tras una actualización, una vez: qué ha cambiado. En la primera instalación no se muestra."""
    s = controller.settings
    seen = s.get("seen_version") or ""
    s.set("seen_version", __version__)
    if not seen or not updater.is_newer(__version__, seen):
        return None
    notes = changelog_section(__version__)
    if not notes:
        return None
    dlg = WhatsNewDialog(__version__, notes, controller.main)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dlg.show()
    return dlg
