"""Página «Archivos»: biblioteca de carpetas personales como tarjetas, al estilo de los álbumes.

Cada carpeta es una referencia a su ubicación original: AERO Player guarda el nombre visual, la descripción,
la portada, el color, el favorito, el orden y la ordenación del contenido en su base de datos. Nunca mueve,
copia ni borra archivos.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QModelIndex, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QStandardItem,
                           QStandardItemModel)
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QColorDialog, QFileDialog, QInputDialog, QLineEdit,
                               QListView, QMenu, QMessageBox, QPushButton, QStackedWidget, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from aero import files
from aero.core import tools
from aero.ui import icons
from aero.core.tasks import tasks
from aero.ui.glass import IconButton, h_layout, label, tm, v_layout
from aero.i18n import tr

FOLDER_ROLE = Qt.ItemDataRole.UserRole + 1
CARD = QSize(184, 236)
COVER = 152
COLORS = [("Turquesa", "#2bb3c0"), ("Azul cielo", "#3b8fe0"), ("Verde hoja", "#4caf6a"), ("Ámbar", "#e0a32e"),
          ("Coral", "#e0675a"), ("Lavanda", "#8f7ae0"), ("Grafito", "#5f6b7a")]


class FolderDelegate(QStyledItemDelegate):
    """Portada (imagen propia o carpeta teñida con su color), nombre y una línea de información."""

    def __init__(self, page: "FilesPage"):
        super().__init__(page)
        self.page = page

    def sizeHint(self, option, index):
        return CARD

    def paint(self, p: QPainter, option, index):
        t = tm().theme
        d = index.data(FOLDER_ROLE) or {}
        r = QRectF(option.rect)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if hover or sel:
            card = QPainterPath()
            card.addRoundedRect(r.adjusted(4.5, 2.5, -4.5, -2.5), 14, 14)
            c = QColor(t.accent if sel else "#ffffff")
            c.setAlphaF(0.20 if sel else (0.08 if t.dark else 0.35))
            p.fillPath(card, c)
        cover = QRectF(r.center().x() - COVER / 2 + 0.5, r.top() + 10.5, COVER - 1, COVER - 1)
        path = QPainterPath()
        path.addRoundedRect(cover, 14, 14)
        p.save()
        p.setClipPath(path)
        pm = self.page.cover_pixmap(d)
        base = QColor(d.get("color") or t.accent)
        if pm is not None:
            src = QRectF(pm.rect())
            side = min(src.width(), src.height())
            p.drawPixmap(cover, pm, QRectF(src.center().x() - side / 2, src.center().y() - side / 2, side, side))
        else:
            g = QLinearGradient(cover.topLeft(), cover.bottomRight())
            g.setColorAt(0, base.lighter(125))
            g.setColorAt(1, base.darker(135))
            p.fillRect(cover, g)
            ic = icons.pixmap("folder", "#ffffff", 64)
            p.setOpacity(0.92)
            p.drawPixmap(QRectF(cover.center().x() - 32, cover.center().y() - 34, 64, 64), ic, QRectF(ic.rect()))
            p.setOpacity(1.0)
        gloss = QLinearGradient(0, cover.top(), 0, cover.top() + cover.height() * 0.45)
        gloss.setColorAt(0, QColor(255, 255, 255, 60 if hover else 38))
        gloss.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(cover.left(), cover.top(), cover.width(), cover.height() * 0.45), gloss)
        p.restore()
        # Franja de color propio también sobre las portadas con imagen
        if d.get("color") and pm is not None:
            band = QPainterPath()
            band.addRoundedRect(QRectF(cover.left() + 10, cover.bottom() - 7, cover.width() - 20, 3), 1.5, 1.5)
            p.fillPath(band, base)
        edge = QColor(t.accent) if (hover or sel) else QColor(255, 255, 255, 110 if t.dark else 200)
        p.setPen(QPen(edge, 1))
        p.drawPath(path)
        if d.get("favorite"):
            st = icons.pixmap("star", "#ffd75e", 18)
            p.drawPixmap(QRectF(cover.right() - 26, cover.top() + 8, 18, 18), st, QRectF(st.rect()))
        missing = not os.path.isdir(d.get("path", ""))
        f = QFont(option.font)
        f.setPointSizeF(10)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(t.text))
        fm = p.fontMetrics()
        tw = int(r.width() - 20)
        name = d.get("title") or Path(d.get("path", "")).name or d.get("path", "")
        p.drawText(QRectF(r.left() + 10, cover.bottom() + 10, tw, 20), Qt.AlignmentFlag.AlignHCenter,
                   fm.elidedText(name, Qt.TextElideMode.ElideRight, tw))
        f.setWeight(QFont.Weight.Normal)
        f.setPointSizeF(8.8)
        p.setFont(f)
        p.setPen(QColor("#ff8a7a") if missing else QColor(t.text2))
        sub = "No se encuentra la carpeta" if missing else (d.get("description") or self.page.summary(d["path"]))
        p.drawText(QRectF(r.left() + 10, cover.bottom() + 30, tw, 18), Qt.AlignmentFlag.AlignHCenter,
                   p.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, tw))
        p.restore()


class FolderList(QListView):
    """Cuadrícula de carpetas que se reordena arrastrando."""

    reordered = Signal()

    def dropEvent(self, e):
        super().dropEvent(e)
        # La fila de origen se elimina al terminar el arrastre: se lee el orden en la siguiente vuelta.
        QTimer.singleShot(0, self.reordered.emit)


class FilesPage(QWidget):
    open_file = Signal(str)        # abrir en el visor de AERO Player
    preview = Signal(str)          # vista rápida
    message = Signal(str, str)
    action = Signal(str, list)     # extraer, comprimir, convertir… (lo ejecuta el controlador)

    def __init__(self, db, settings, parent=None):
        super().__init__(parent)
        self.db, self.s = db, settings
        self._covers: dict[str, QPixmap | None] = {}
        self._summary: dict[str, str] = {}
        self.only_favs = False

        add = QPushButton(tr("Añadir carpeta"))
        add.setProperty("kind", "primary")
        add.setIcon(tm().icon("plus", 18))
        add.clicked.connect(self.add_folder_dialog)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Buscar carpetas"))
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self.refresh)
        seg = QButtonGroup(self)
        self.seg_all = QPushButton(tr("Todas"))
        self.seg_fav = QPushButton(tr("Favoritas"))
        for i, b in enumerate((self.seg_all, self.seg_fav)):
            b.setCheckable(True)
            b.setProperty("kind", "flat")
            seg.addButton(b, i)
        self.seg_all.setChecked(True)
        seg.idClicked.connect(lambda i: (setattr(self, "only_favs", i == 1), self.refresh()))

        self.model = QStandardItemModel(self)
        self.view = FolderList()
        self.view.setModel(self.model)
        self.view.setItemDelegate(FolderDelegate(self))
        self.view.setViewMode(QListView.ViewMode.IconMode)
        self.view.setResizeMode(QListView.ResizeMode.Adjust)
        self.view.setGridSize(CARD)
        self.view.setUniformItemSizes(True)
        self.view.setMouseTracking(True)
        self.view.setMovement(QListView.Movement.Static)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setFrameShape(QListView.Shape.NoFrame)
        self.view.setStyleSheet("QListView { background: transparent; }")
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.activated.connect(lambda i: self.open_folder(i.data(FOLDER_ROLE)["path"]))
        self.view.doubleClicked.connect(lambda i: self.open_folder(i.data(FOLDER_ROLE)["path"]))
        self.view.reordered.connect(self._save_order)
        self.view.setAccessibleName(tr("Carpetas de la biblioteca"))

        empty_btn = QPushButton(tr("Añadir una carpeta"))
        empty_btn.setProperty("kind", "primary")
        empty_btn.clicked.connect(self.add_folder_dialog)
        ic = label("")
        ic.setPixmap(icons.pixmap("files", tm().theme.text2, 56))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t1 = label(tr("Organiza tus carpetas"), "h3")
        t1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t2 = label(tr("Añade carpetas de documentos, fotos o proyectos. Se quedan donde están: AERO Player solo "
                   "guarda cómo quieres verlas."), "muted", wrap=True)
        t2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t2.setMaximumWidth(420)
        self.empty = QWidget()
        self.empty.setLayout(v_layout(None, ic, 6, t1, h_layout(None, t2, None), 12, h_layout(None, empty_btn, None),
                                      None))

        from aero.files.browser import FolderBrowser

        self.browser = FolderBrowser()
        self.browser.open_requested.connect(self.open_file)
        self.browser.preview_requested.connect(self.preview)
        self.browser.action_requested.connect(self.action)
        self.browser.sort.currentIndexChanged.connect(self._remember_sort)
        back = QPushButton(tr("Biblioteca"))
        back.setIcon(tm().icon("back", 18))
        back.setProperty("kind", "flat")
        back.clicked.connect(self.show_library)
        reveal = IconButton("external", tr("Abrir en el Explorador de Windows"), 18)
        reveal.clicked.connect(lambda: self.browser.cwd and tools.open_with_default(self.browser.cwd))
        inside = QWidget()
        inside.setLayout(v_layout(h_layout(back, None, reveal), self.browser, spacing=6))
        self.inside = inside

        lib = QWidget()
        self.lib_stack = QStackedWidget()
        self.lib_stack.addWidget(self.view)
        self.lib_stack.addWidget(self.empty)
        lib.setLayout(v_layout(h_layout(self.seg_all, self.seg_fav, 12, self.search, None, add, spacing=4),
                               self.lib_stack, spacing=12))
        self.stack = QStackedWidget()
        self.stack.addWidget(lib)
        self.stack.addWidget(inside)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self._current: dict | None = None
        self.refresh()

    # ------------------------------------------------------------------ datos
    def refresh(self):
        text = self.search.text().strip().lower()
        rows = self.db.library_folders()
        self.model.clear()
        for d in rows:
            name = d["title"] or Path(d["path"]).name
            if self.only_favs and not d["favorite"]:
                continue
            if text and text not in name.lower() and text not in d["description"].lower():
                continue
            it = QStandardItem(name)
            it.setData(d, FOLDER_ROLE)
            it.setToolTip(d["path"])
            it.setDropEnabled(False)
            self.model.appendRow(it)
            if d["path"] not in self._summary:
                self._count(d["path"])
        filtered = bool(text) or self.only_favs
        # Con filtros activos el orden no se puede cambiar (faltarían carpetas)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop if filtered
                                  else QAbstractItemView.DragDropMode.InternalMove)
        self.lib_stack.setCurrentWidget(self.view if rows else self.empty)

    def summary(self, path: str) -> str:
        return self._summary.get(path, "")

    def _count(self, path: str):
        self._summary[path] = "…"

        def done(entries):
            st = files.immediate_stats(entries)
            parts = [files.count(n, k) for n, k in ((st.files, "file"), (st.dirs, "folder")) if n]
            self._summary[path] = " · ".join(parts) or tr("Vacía")
            self.view.viewport().update()

        tasks().submit(lambda: files.list_dir(path), "background", done,
                       lambda _e: self._summary.__setitem__(path, ""), self)

    def cover_pixmap(self, d: dict) -> QPixmap | None:
        c = d.get("cover") or ""
        if not c:
            return None
        if c not in self._covers:
            pm = QPixmap(c)
            self._covers[c] = None if pm.isNull() else pm.scaled(COVER * 2, COVER * 2,
                                                                  Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                                  Qt.TransformationMode.SmoothTransformation)
        return self._covers[c]

    def _save_order(self):
        paths = [self.model.item(i).data(FOLDER_ROLE)["path"] for i in range(self.model.rowCount())
                 if self.model.item(i) is not None]
        self.db.reorder_folders(paths)
        self.refresh()

    def _find(self, path: str) -> dict | None:
        return next((d for d in self.db.library_folders() if d["path"] == path), None)

    # ------------------------------------------------------------------ acciones
    def add_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, tr("Añadir carpeta a la biblioteca"))
        if d:
            self.add_folder(d)

    def add_folder(self, path: str) -> bool:
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return False
        if not self.db.add_folder(path):
            self.message.emit(tr("Esa carpeta ya está en la biblioteca"), "info")
            return False
        self.refresh()
        return True

    def open_folder(self, path: str):
        d = self._find(path)
        if d is None:
            return
        if not os.path.isdir(path):
            self.message.emit(tr("No se encuentra la carpeta: puede que se haya movido o esté en una unidad desconectada"),
                              "error")
            return
        self._current = d
        b = self.browser
        b.set_root(path)
        i = b.sort.findData(d.get("sort") or "name")
        b.sort.blockSignals(True)
        b.sort.setCurrentIndex(max(0, i))
        b.sort.blockSignals(False)
        self.stack.setCurrentWidget(self.inside)

    def browse(self, path: str):
        """Explorar una carpeta que no está en la biblioteca (p. ej. desde Quick Look)."""
        d = self._find(os.path.abspath(path))
        if d is not None:
            self.open_folder(d["path"])
            return
        self._current = None
        self.browser.set_root(path)
        self.stack.setCurrentWidget(self.inside)

    def show_library(self):
        self.browser.cleanup()
        self._current = None
        self.stack.setCurrentIndex(0)
        self.refresh()

    def _remember_sort(self):
        if self._current is not None:
            self.db.update_folder(self._current["path"], sort=self.browser.sort.currentData())

    def _menu(self, pos):
        idx: QModelIndex = self.view.indexAt(pos)
        if not idx.isValid():
            m = QMenu(self)
            m.addAction(tm().icon("plus", 18), tr("Añadir carpeta…"), self.add_folder_dialog)
            m.exec(self.view.viewport().mapToGlobal(pos))
            return
        d = idx.data(FOLDER_ROLE)
        path = d["path"]
        m = QMenu(self)
        m.addAction(tm().icon("files", 18), tr("Abrir"), lambda: self.open_folder(path))
        m.addAction(tm().icon("external", 18), tr("Abrir en el Explorador de Windows"), lambda: tools.open_with_default(path))
        m.addAction(tm().icon("star", 18), tr("Quitar de favoritos") if d["favorite"] else tr("Añadir a favoritos"),
                    lambda: self._set(path, favorite=0 if d["favorite"] else 1))
        m.addSeparator()
        m.addAction(tm().icon("edit", 18), tr("Cambiar nombre…"), lambda: self.rename(path))
        m.addAction(tm().icon("image", 18), tr("Editar portada y descripción…"), lambda: self.edit(path))
        m.addAction(tm().icon("image", 18), tr("Cambiar imagen…"), lambda: self.change_image(path))
        colors = m.addMenu(tr("Color"))
        for name, hexc in COLORS:
            pm = QPixmap(14, 14)
            pm.fill(QColor(hexc))
            colors.addAction(pm, name, lambda c=hexc: self._set(path, color=c))
        colors.addSeparator()
        colors.addAction(tr("Personalizado…"), lambda: self._pick_color(path))
        colors.addAction(tr("Predeterminado"), lambda: self._set(path, color=""))
        sort = m.addMenu(tr("Ordenar contenido por"))
        for key, text in files.SORTS.items():
            a = sort.addAction(tr(text), lambda k=key: self._set(path, sort=k))
            a.setCheckable(True)
            a.setChecked((d.get("sort") or "name") == key)
        order = m.addMenu(tr("Posición"))
        order.addAction(tr("Mover al principio"), lambda: self._move(path, 0))
        order.addAction(tr("Mover al final"), lambda: self._move(path, -1))
        m.addSeparator()
        m.addAction(tm().icon("trash", 18), tr("Quitar de la biblioteca…"), lambda: self.remove(path))
        m.exec(self.view.viewport().mapToGlobal(pos))

    def _set(self, path: str, **fields):
        self.db.update_folder(path, **fields)
        self.refresh()

    def _pick_color(self, path: str):
        d = self._find(path) or {}
        c = QColorDialog.getColor(QColor(d.get("color") or tm().theme.accent), self, "Color de la carpeta")
        if c.isValid():
            self._set(path, color=c.name())

    def _move(self, path: str, where: int):
        paths = [d["path"] for d in self.db.library_folders()]
        paths.remove(path)
        paths.insert(len(paths) if where < 0 else where, path)
        self.db.reorder_folders(paths)
        self.refresh()

    def rename(self, path: str):
        d = self._find(path) or {}
        current = d.get("title") or Path(path).name
        text, ok = QInputDialog.getText(self, tr("Cambiar nombre"),
                                        tr("Nombre en AERO Player (la carpeta del disco no cambia):"), text=current)
        if ok:
            text = text.strip()
            self._set(path, title="" if text == Path(path).name else text)

    def _save_cover_image(self, path: str, img) -> str:
        from aero.ui.pages.albums import save_cover

        return save_cover(img, "folder:" + path)

    def change_image(self, path: str):
        from aero.ui.pages.albums import load_image

        f, _ = QFileDialog.getOpenFileName(self, tr("Imagen de la carpeta"), path,
                                           "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if f:
            img = load_image(f)
            if not img.isNull():
                side = min(img.width(), img.height())
                sq = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
                self._set(path, cover=self._save_cover_image(path, sq))

    def edit(self, path: str):
        from aero.ui.pages.albums import AlbumEditDialog, load_image

        d = self._find(path) or {}
        current = load_image(d["cover"]) if d.get("cover") else None
        info = {"title": d.get("title") or Path(path).name, "artist": d.get("description", ""),
                "detected_artist": "Descripción breve (opcional)"}
        dlg = AlbumEditDialog(Path(path).name, info, None, current, self,
                              texts={"window": "Editar carpeta", "second": "Descripción", "restore": "Quitar portada",
                                     "note": "Se guarda en AERO Player. La carpeta y sus archivos no se modifican."})
        if not dlg.exec():
            return
        res = dlg.result()
        fields = {"title": res["title"], "description": res["artist"]}
        if res["cover"] == "":
            fields["cover"] = ""
        elif res["cover"] is not None:
            fields["cover"] = self._save_cover_image(path, res["cover"])
        self._set(path, **fields)

    def remove(self, path: str, confirm: bool = True):
        d = self._find(path) or {}
        name = d.get("title") or Path(path).name
        if confirm:
            box = QMessageBox(QMessageBox.Icon.Question, "Quitar de la biblioteca",
                              f"¿Quitar «{name}» de la biblioteca?\n\nSolo se quita de AERO Player: la carpeta y sus "
                              "archivos se quedan en el disco tal como están.", parent=self)
            ok = box.addButton(tr("Quitar de la biblioteca"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("Cancelar"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not ok:
                return
        self.db.remove_folder(path)
        self._summary.pop(path, None)
        self.refresh()
