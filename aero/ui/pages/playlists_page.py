"""Listas de reproducción, favoritos e historial. Importa/exporta M3U8."""

from __future__ import annotations

import os
import random
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QInputDialog, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QVBoxLayout, QWidget)

from aero.core import tools
from aero.core.formats import is_media
from aero.ui.glass import GlassPanel, IconButton, h_layout, label, tm
from aero.i18n import ntr, tr

FAV, HISTORY = -1, -2


class _ItemList(QListWidget):
    """Lista de la derecha: vacía, explica cómo llenarla en lugar de quedarse en blanco."""

    def __init__(self):
        super().__init__()
        self.empty = ("", "", "")         # icono, título, explicación

    def paintEvent(self, e):
        super().paintEvent(e)
        icon_name, title, text = self.empty
        if self.count() or not title:
            return
        from PySide6.QtGui import QColor, QPainter

        from aero.ui import icons

        th = tm().theme
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.viewport().rect()
        p.setOpacity(0.85)
        p.drawPixmap(r.center().x() - 22, r.center().y() - 70, icons.pixmap(icon_name, th.accent, 44))
        p.setOpacity(1.0)
        f = p.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(th.text))
        p.drawText(r.adjusted(24, 0, -24, -10), Qt.AlignmentFlag.AlignCenter, title)
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() - 2)
        p.setFont(f)
        p.setPen(QColor(th.text2))
        p.drawText(r.adjusted(40, r.height() // 2 + 18, -40, 0),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, text)
        p.end()


def read_m3u(path: str) -> list[str]:
    base = Path(path).parent
    out = []
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", "replace")
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        p = Path(s)
        if not p.is_absolute():
            p = base / p
        out.append(str(p))
    return out


def write_m3u(path: str, items: list[str]) -> None:
    lines = ["#EXTM3U"] + [os.path.abspath(p) for p in items]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


class PlaylistsPage(QWidget):
    play_paths = Signal(list, int)
    message = Signal(str, str)

    def __init__(self, db, engine, parent=None):
        super().__init__(parent)
        self.db = db
        self.engine = engine
        left = GlassPanel(radius=22)
        self.lists = QListWidget()
        self.lists.currentItemChanged.connect(lambda *_: self._load_items())
        new_btn = IconButton("plus", tr("Nueva lista"), 18)
        imp_btn = IconButton("open", tr("Importar M3U/M3U8"), 18)
        ren_btn = IconButton("edit", "Renombrar", 18)
        del_btn = IconButton("trash", tr("Eliminar lista"), 18)
        new_btn.clicked.connect(self._new)
        imp_btn.clicked.connect(self._import)
        ren_btn.clicked.connect(self._rename)
        del_btn.clicked.connect(self._delete)
        save_queue = IconButton("list_add", tr("Guardar la cola como lista"), 18)
        save_queue.clicked.connect(self.save_queue)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(18, 16, 12, 14)
        ll.addLayout(h_layout(new_btn, imp_btn, ren_btn, del_btn, None, save_queue, spacing=2))
        ll.addWidget(self.lists, 1)
        left.setFixedWidth(300)

        right = GlassPanel(radius=22)
        self.title = label("", "h2")
        self.count = label("", "caption")
        self.items = _ItemList()
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.items.itemDoubleClicked.connect(lambda it: self._play(self.items.row(it)))
        self.items.model().rowsMoved.connect(lambda *_: self._save_order())
        self.items.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.items.customContextMenuRequested.connect(self._menu)
        play = IconButton("play", tr("Reproducir"), 18)
        play.clicked.connect(lambda: self._play(0))
        shuf = IconButton("shuffle", tr("Aleatorio"), 18)
        shuf.clicked.connect(lambda: self._play(0, True))
        self.export_btn = IconButton("external", tr("Exportar M3U8"), 18)
        self.export_btn.clicked.connect(self._export)
        self.remove_btn = IconButton("trash", tr("Quitar seleccionados"), 18)
        self.remove_btn.clicked.connect(self._remove_selected)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(22, 16, 16, 14)
        rl.addLayout(h_layout(self.title, None, self.remove_btn, self.export_btn, shuf, play))
        rl.addWidget(self.count)
        rl.addWidget(self.items, 1)

        self.setLayout(h_layout(left, right, spacing=12))
        self.refresh()

    def refresh(self):
        cur = self._current_id()
        self.lists.blockSignals(True)
        self.lists.clear()
        t = tm().theme
        for pid, name, ic in ((FAV, "Favoritos", "heart_fill"), (HISTORY, "Historial", "clock")):
            it = QListWidgetItem(tm().icon(ic, 18), tr(name))
            it.setData(Qt.ItemDataRole.UserRole, pid)
            self.lists.addItem(it)
        for r in self.db.playlists():
            it = QListWidgetItem(tm().icon("playlists", 18), f"{r['name']}  ({r['n']})")
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.lists.addItem(it)
        _ = t
        self.lists.blockSignals(False)
        for i in range(self.lists.count()):
            if self.lists.item(i).data(Qt.ItemDataRole.UserRole) == cur:
                self.lists.setCurrentRow(i)
                break
        else:
            self.lists.setCurrentRow(0)
        self._load_items()

    def _current_id(self):
        it = self.lists.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else FAV

    def _paths(self) -> list[str]:
        pid = self._current_id()
        if pid == FAV:
            return self.db.favorites()
        if pid == HISTORY:
            return [r["path"] for r in self.db.recently_played(200)]
        return self.db.playlist_items(pid)

    def _load_items(self):
        pid = self._current_id()
        paths = self._paths()
        it = self.lists.currentItem()
        self.title.setText(it.text().split("  (")[0] if it else "")
        self.items.clear()
        for p in paths:
            li = QListWidgetItem(Path(p).stem)
            li.setToolTip(p)
            li.setData(Qt.ItemDataRole.UserRole, p)
            if not os.path.exists(p):
                li.setText(Path(p).stem + tr("   (no encontrado)"))
            self.items.addItem(li)
        user = pid > 0
        self.items.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove if user
                                   else QAbstractItemView.DragDropMode.NoDragDrop)
        self.remove_btn.setVisible(pid != HISTORY)
        self.count.setText(ntr("{n} elemento", "{n} elementos", len(paths)))
        if pid == FAV:
            self.items.empty = ("heart", tr("Aún no tienes favoritos"),
                                tr("Pulsa el corazón de la barra del reproductor y la canción o el vídeo aparecerá aquí."))
        elif pid == HISTORY:
            self.items.empty = ("clock", tr("El historial está vacío"),
                                tr("Aquí aparecerá lo que reproduzcas, para volver a ello cuando quieras."))
        else:
            self.items.empty = ("list_add", tr("Esta lista está vacía"),
                                tr("En la biblioteca, clic derecho › «Añadir a una lista…» para llenarla."))
        self.items.viewport().update()
        self.items.setToolTip(tr("Arrastra para reordenar") if user else "")

    def _play(self, start: int, shuffle: bool = False):
        paths = [p for p in self._paths() if os.path.exists(p) and is_media(p)]
        if not paths:
            self.message.emit(tr("No hay elementos reproducibles en esta lista."), "error")
            return
        if shuffle:
            random.shuffle(paths)
            start = 0
        self.play_paths.emit(paths, max(0, min(start, len(paths) - 1)))

    def _save_order(self):
        pid = self._current_id()
        if pid > 0:
            self.db.set_playlist_items(pid, [self.items.item(i).data(Qt.ItemDataRole.UserRole)
                                             for i in range(self.items.count())])

    def _remove_selected(self):
        pid = self._current_id()
        sel = {self.items.row(i) for i in self.items.selectedItems()}
        if not sel:
            return
        if pid == FAV:
            for r in sel:
                self.db.set_favorite(self.items.item(r).data(Qt.ItemDataRole.UserRole), False)
        elif pid > 0:
            keep = [self.items.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.items.count()) if i not in sel]
            self.db.set_playlist_items(pid, keep)
        self.refresh()

    def _menu(self, pos):
        it = self.items.itemAt(pos)
        if not it:
            return
        path = it.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        m.addAction(tr("Reproducir desde aquí"), lambda: self._play(self.items.row(it)))
        m.addAction(tr("Añadir a la cola"), lambda: self.engine.enqueue([path]))
        m.addAction(tr("Mostrar en el Explorador"), lambda: tools.reveal_in_explorer(path))
        m.exec(self.items.viewport().mapToGlobal(pos))

    def _new(self):
        name, ok = QInputDialog.getText(self, tr("Nueva lista"), tr("Nombre de la lista:"))
        if ok and name.strip():
            self.db.create_playlist(name.strip())
            self.refresh()

    def _rename(self):
        pid = self._current_id()
        if pid <= 0:
            return
        cur = self.lists.currentItem().text().split("  (")[0]
        name, ok = QInputDialog.getText(self, tr("Renombrar lista"), tr("Nuevo nombre:"), text=cur)
        if ok and name.strip():
            self.db.rename_playlist(pid, name.strip())
            self.refresh()

    def _delete(self):
        pid = self._current_id()
        if pid <= 0:
            return
        name = self.lists.currentItem().text().split("  (")[0]
        if QMessageBox.question(self, tr("Eliminar lista"), tr("¿Eliminar la lista «{name}»? Los archivos no se borran.", name=name)) \
                == QMessageBox.StandardButton.Yes:
            self.db.delete_playlist(pid)
            self.refresh()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Importar lista"), "", "Listas (*.m3u *.m3u8)")
        if not path:
            return
        try:
            items = read_m3u(path)
        except OSError as e:
            self.message.emit(tr("No se pudo leer la lista: {e}", e=e), "error")
            return
        self.db.create_playlist(Path(path).stem, items)
        self.refresh()
        self.message.emit(tr("Lista importada con {v0} elementos.", v0=len(items)), "ok")

    def _export(self):
        paths = self._paths()
        if not paths:
            return
        name = self.title.text() or "lista"
        dst, _ = QFileDialog.getSaveFileName(self, tr("Exportar lista"), f"{name}.m3u8", "M3U8 (*.m3u8)")
        if dst:
            try:
                write_m3u(dst, paths)
                self.message.emit(tr("Lista exportada."), "ok")
            except OSError as e:
                self.message.emit(tr("No se pudo exportar: {e}", e=e), "error")

    def save_queue(self):
        if not self.engine.queue:
            self.message.emit(tr("La cola está vacía."), "error")
            return
        name, ok = QInputDialog.getText(self, tr("Guardar cola"), tr("Nombre de la lista:"))
        if ok and name.strip():
            self.db.create_playlist(name.strip(), list(self.engine.queue))
            self.refresh()
            self.message.emit(tr("Lista guardada."), "ok")

    def choose_and_add(self, paths: list[str]):
        """Diálogo para añadir rutas a una lista existente o nueva."""
        lists = self.db.playlists()
        names = [r["name"] for r in lists] + ["➕ Nueva lista…"]
        choice, ok = QInputDialog.getItem(self, tr("Añadir a una lista"), tr("Lista:"), names, 0, False)
        if not ok:
            return
        if choice == names[-1]:
            name, ok = QInputDialog.getText(self, tr("Nueva lista"), tr("Nombre de la lista:"))
            if ok and name.strip():
                self.db.create_playlist(name.strip(), paths)
        else:
            pid = lists[names.index(choice)]["id"]
            self.db.append_to_playlist(pid, paths)
        self.refresh()
        self.message.emit(tr("{v0} elementos añadidos.", v0=len(paths)), "ok")
