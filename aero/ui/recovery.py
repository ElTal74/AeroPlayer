"""Recuperar el trabajo sin guardar que dejaron los editores tras un cierre inesperado."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from aero.ui.glasswindow import TrDialog
from aero.core import drafts
from aero.i18n import ntr, tr
from aero.ui.glass import h_layout, label


class RecoveryDialog(TrDialog):
    def __init__(self, items: list[drafts.Draft], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Recuperar trabajo sin guardar"))
        self.setMinimumWidth(520)
        self.items = items
        self.choice = "later"
        self.list = QListWidget()
        for d in items:
            when = dt.datetime.fromtimestamp(d.saved).strftime("%d/%m/%Y %H:%M") if d.saved else ""
            it = QListWidgetItem(f"{d.title or tr('Sin título')} — {tr(drafts.KINDS.get(d.kind, d.kind))} · {when}")
            it.setToolTip(d.source or tr("Aún no se había guardado"))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(it)
        text = label(ntr("AERO Player se cerró sin guardar {n} trabajo. Puedes recuperarlo tal como estaba hace un "
                         "momento.", "AERO Player se cerró sin guardar {n} trabajos. Puedes recuperarlos tal como "
                         "estaban hace un momento.", len(items)), wrap=True)
        rec = QPushButton(tr("Recuperar"))
        rec.setProperty("kind", "primary")
        rec.clicked.connect(lambda: self._done("recover"))
        drop = QPushButton(tr("Descartar"))
        drop.setToolTip(tr("Borra estos borradores. Tus archivos no se tocan."))
        drop.clicked.connect(lambda: self._done("discard"))
        later = QPushButton(tr("Más tarde"))
        later.clicked.connect(lambda: self._done("later"))
        lay = QVBoxLayout(self)
        lay.addWidget(label(tr("Recuperar trabajo sin guardar"), "h3"))
        lay.addWidget(text)
        lay.addWidget(self.list, 1)
        lay.addLayout(h_layout(drop, None, later, rec))

    def _done(self, choice: str):
        self.choice = choice
        self.accept()

    def selected(self) -> list[drafts.Draft]:
        return [d for i, d in enumerate(self.items) if self.list.item(i).checkState() == Qt.CheckState.Checked]


def recover(controller, d: drafts.Draft) -> bool:
    """Abre el borrador en su editor como trabajo sin guardar, ligado otra vez a su archivo original."""
    from pathlib import Path

    from PySide6.QtCore import QTimer

    path = str(d.path)
    src = d.source or ""
    if d.kind == "paint":
        w = controller.open_paint(path)
        if not w.doc.path or Path(w.doc.path) != d.path:
            return False
        w.doc.path = src
        w.doc.dirty = True
        w._sync()
    elif d.kind == "video":
        w = controller.open_video_editor()
        w.load_project(path)
        w.project_path = src if src.lower().endswith(d.ext) else ""
        w.project.path = w.project_path
        w.dirty = True
        w._sync()
    elif d.kind == "image":
        w = controller.open_image_editor(path)
        w.project_path = src if src.lower().endswith(d.ext) else ""
        if src:
            w.path = src

        def mark(tries: int = 100):
            try:
                if w.doc is None:
                    if tries:
                        QTimer.singleShot(100, lambda: mark(tries - 1))
                    return
                w.doc.path = src or w.doc.path
                w.doc.dirty = True
                w._sync_title()
            except RuntimeError:  # la ventana se cerró antes de terminar de cargar
                pass

        mark()
    else:
        return False
    return True


def offer(controller, parent=None) -> None:
    """Si quedaron borradores de una sesión cerrada de golpe, pregunta qué hacer con ellos."""
    items = drafts.pending()
    if not items:
        return
    dlg = RecoveryDialog(items, parent)
    dlg.exec()
    if dlg.choice == "later":
        return
    for d in dlg.selected():
        if dlg.choice == "recover":
            try:
                if not recover(controller, d):
                    continue
            except Exception:  # noqa: BLE001 - un borrador dañado no debe impedir abrir los demás
                continue
        if dlg.choice == "discard" or d.kind != "image":
            drafts.discard(d)
        else:
            # El editor de imágenes lee el borrador en segundo plano: se borra cuando ya está abierto.
            from PySide6.QtCore import QTimer

            QTimer.singleShot(5000, lambda d=d: drafts.discard(d))
