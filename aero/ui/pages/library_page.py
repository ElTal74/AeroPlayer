"""Biblioteca: canciones, vídeos, álbumes, artistas y carpetas con búsqueda instantánea y paginación."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialogButtonBox, QFileDialog, QFormLayout, QHeaderView,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton,
                               QStackedWidget, QTabBar, QTableView, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from aero.ui.glasswindow import TrDialog
from aero.core import tools
from aero.core.db import Database
from aero.core.formats import human_size, human_time
from aero.core.metadata import FIELD_LABELS, read_cover, read_editable, write_tags, read_tags
from aero.core.scanner import LibraryScanner
from aero.ui import icons
from aero.ui.async_util import run_async
from aero.ui.glass import IconButton, Spinner, h_layout, label, tm, v_layout
from aero.i18n import tr

PAGE = 400
AUDIO_COLS = [("title", "Título"), ("artist", "Artista"), ("album", "Álbum"), ("duration", "Duración"),
              ("ext", "Formato"), ("size", "Tamaño")]
VIDEO_COLS = [("title", "Nombre"), ("folder", "Carpeta"), ("duration", "Duración"), ("ext", "Formato"),
              ("size", "Tamaño"), ("mtime", "Modificado")]


class MediaModel(QAbstractTableModel):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.rows: list = []
        self.total = 0
        self.cols = AUDIO_COLS
        self.filters: dict = {}
        self.order, self.desc = "title", False

    def set_query(self, kind: str, search: str = "", **filters):
        self.beginResetModel()
        self.cols = AUDIO_COLS if kind == "audio" else VIDEO_COLS
        self.filters = {"kind": kind, "search": search, **filters}
        self.total = self.db.count_media(**self.filters)
        self.rows = self.db.query_media(**self.filters, order=self.order, desc=self.desc, limit=PAGE, offset=0)
        self.endResetModel()

    def refresh(self):
        if self.filters:
            self.set_query(**self.filters)

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        key = self.cols[column][0]
        self.order = {"ext": "kind", "folder": "name"}.get(key, key)
        self.desc = order == Qt.SortOrder.DescendingOrder
        self.refresh()

    def canFetchMore(self, parent=QModelIndex()):
        return not parent.isValid() and len(self.rows) < self.total

    def fetchMore(self, parent=QModelIndex()):
        more = self.db.query_media(**self.filters, order=self.order, desc=self.desc, limit=PAGE, offset=len(self.rows))
        if not more:
            self.total = len(self.rows)
            return
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows) + len(more) - 1)
        self.rows.extend(more)
        self.endInsertRows()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.cols)

    def headerData(self, s, o, role=Qt.ItemDataRole.DisplayRole):
        if o == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.cols[s][1]
        return None

    def data(self, idx, role=Qt.ItemDataRole.DisplayRole):
        r = self.rows[idx.row()]
        key = self.cols[idx.column()][0]
        if role == Qt.ItemDataRole.ToolTipRole:
            return r["path"]
        if role == Qt.ItemDataRole.TextAlignmentRole and key in ("duration", "size"):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if key == "title":
            return r["title"] or r["name"]
        if key == "duration":
            return human_time(r["duration"]) if r["duration"] else ""
        if key == "size":
            return human_size(r["size"] or 0)
        if key == "ext":
            return (r["ext"] or "").upper().lstrip(".")
        if key == "folder":
            return Path(r["folder"] or "").name
        if key == "mtime":
            from datetime import datetime

            return datetime.fromtimestamp(r["mtime"] or 0).strftime("%d/%m/%Y")
        return r[key] or ""

    def path_at(self, row: int) -> str:
        return self.rows[row]["path"]


class TagDialog(TrDialog):
    def __init__(self, path: str, values: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Editar etiquetas · {v0}", v0=Path(path).name))
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        self.edits = {}
        for k, v in values.items():
            e = QLineEdit(v)
            self.edits[k] = e
            form.addRow(FIELD_LABELS.get(k, k) + ":", e)
        note = label(tr("Los cambios se escriben en el archivo original."), "caption")
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> dict:
        return {k: e.text().strip() for k, e in self.edits.items()}


class LibraryPage(QWidget):
    play_paths = Signal(list, int)
    enqueue_paths = Signal(list, bool)
    convert_paths = Signal(list)
    add_to_playlist = Signal(list)
    message = Signal(str, str)

    def __init__(self, db: Database, settings, parent=None):
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.scanner: LibraryScanner | None = None
        panel = QWidget()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(panel)

        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Buscar"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(tm().icon("search", 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setMinimumWidth(260)
        self.add_btn = IconButton("plus", tr("Añadir carpeta"), 18)
        self.scan_btn = IconButton("refresh", tr("Escanear la biblioteca"), 18)
        self.pause_btn = IconButton("pause_small", tr("Pausar escaneo"), 16)
        self.cancel_btn = IconButton("close", tr("Detener escaneo"), 16)
        self.spinner = Spinner(22)
        self.scan_label = label("", "caption")
        for w in (self.pause_btn, self.cancel_btn, self.spinner):
            w.hide()
        self.stats = label("", "caption")
        self.stats.hide()
        self.search.hide()  # la búsqueda vive en la barra superior de la ventana
        header = h_layout(None, self.spinner, self.scan_label, self.pause_btn,
                          self.cancel_btn, self.search, self.add_btn, self.scan_btn, spacing=8)

        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        for t in ("Canciones", "Vídeos", "Series", "Álbumes", "Artistas", "Carpetas"):
            self.tabs.addTab(tr(t))
        self.back_btn = QPushButton("←")
        self.back_btn.setProperty("kind", "flat")
        self.back_btn.hide()
        self.crumb = label("", "h3")
        self.play_all = IconButton("play", tr("Reproducir todo"), 18)
        self.shuffle_all = IconButton("shuffle", tr("Reproducir en aleatorio"), 18)

        self.model = MediaModel(db, self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.doubleClicked.connect(self._activate)
        self.table.setWordWrap(False)

        self.groups = QListWidget()
        self.groups.setViewMode(QListWidget.ViewMode.IconMode)
        self.groups.setIconSize(QSize(150, 150))
        self.groups.setGridSize(QSize(176, 214))
        self.groups.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.groups.setMovement(QListWidget.Movement.Static)
        self.groups.setWordWrap(True)
        self.groups.setUniformItemSizes(True)
        self.groups.itemActivated.connect(self._open_group)
        self.groups.setMouseTracking(True)
        self.groups.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.groups.customContextMenuRequested.connect(self._group_menu)
        from aero.ui.pages.albums import AlbumDelegate

        self._default_delegate = self.groups.itemDelegate()
        self._album_delegate = AlbumDelegate(self.groups)

        self.empty = QWidget()
        empty_btn = QPushButton(tr("Añadir carpeta"))
        empty_btn.setProperty("kind", "primary")
        empty_btn.clicked.connect(self._add_folder)
        ic = label()
        ic.setPixmap(icons.pixmap("library", tm().theme.text2, 56))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setLayout(v_layout(None, ic, 14, h_layout(None, empty_btn, None), None))

        self.body = QStackedWidget()
        self.body.addWidget(self.table)
        self.body.addWidget(self.groups)
        self.body.addWidget(self.empty)
        self.episodes = QTreeWidget()
        self.episodes.setHeaderLabels([tr("Episodio"), tr("Estado")])
        self.episodes.setColumnWidth(0, 520)
        self.episodes.setIconSize(QSize(18, 18))
        self.episodes.setRootIsDecorated(True)
        self.episodes.itemActivated.connect(self._play_episode)
        self.body.addWidget(self.episodes)
        self.series_show: str | None = None
        self._series: dict = {}

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        lay.addLayout(header)
        lay.addLayout(h_layout(self.tabs, None, self.back_btn, self.crumb, 10, self.play_all, self.shuffle_all))
        lay.addWidget(self.body, 1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.tabs.currentChanged.connect(lambda _i: self._reset_group())
        self.add_btn.clicked.connect(self._add_folder)
        self.scan_btn.clicked.connect(self.scan)
        self.pause_btn.clicked.connect(self._pause)
        self.cancel_btn.clicked.connect(lambda: self.scanner and self.scanner.cancel())
        self.back_btn.clicked.connect(self._reset_group)
        self.play_all.clicked.connect(lambda: self._play_all(False))
        self.shuffle_all.clicked.connect(lambda: self._play_all(True))
        self.group_filter: dict | None = None
        self._cover_token = 0
        self.refresh()

    # ------------------------------------------------------------------ datos
    def refresh(self):
        s = self.search.text().strip()
        tab = self.tabs.currentIndex()
        st = self.db.library_stats()
        self.setToolTip(tr("{v0} canciones · {v1} vídeos · {v2} · {v3}", v0=st['audio'], v1=st['video'], v2=human_time(st['duration']), v3=human_size(st['size'])))
        if st["audio"] + st["video"] == 0 and not s:
            self.body.setCurrentWidget(self.empty)
            self.play_all.hide()
            self.shuffle_all.hide()
            return
        if tab == 2:
            self._show_series(s)
            return
        if tab in (0, 1) or self.group_filter is not None:
            kind = "video" if tab == 1 else "audio"
            if self.group_filter is not None and tab == 5:
                kind = None
            self.model.set_query(kind, s, **(self.group_filter or {}))
            self.body.setCurrentWidget(self.table)
            hdr = self.table.horizontalHeader()
            widths = [320, 200, 220, 80, 70, 90] if self.model.cols is AUDIO_COLS else [380, 200, 80, 70, 90, 100]
            for i, w in enumerate(widths):
                hdr.resizeSection(i, w)
            self.play_all.show()
            self.shuffle_all.show()
        else:
            self._fill_groups(tab, s)
            self.body.setCurrentWidget(self.groups)
            self.play_all.hide()
            self.shuffle_all.hide()

    def _set_group_mode(self, albums: bool):
        from aero.ui.pages.albums import CARD_H, CARD_W

        self.groups.setItemDelegate(self._album_delegate if albums else self._default_delegate)
        self.groups.setGridSize(QSize(CARD_W + 8, CARD_H + 4) if albums else QSize(176, 214))

    def _fill_groups(self, tab: int, search: str):
        from aero.ui.pages.albums import ALBUM_ROLE

        self.groups.clear()
        self._cover_token += 1
        token = self._cover_token
        t = tm().theme
        self._set_group_mode(tab == 3)
        if tab == 3:
            rows = self.db.albums(search)
            infos = self.db.album_infos()
            jobs = []
            for r in rows:
                album = r["album"] or ""
                info = infos.get(album, {})
                name = info.get("title") or album or "Sin álbum"
                artist = info.get("artist") or r["artist"] or ""
                it = QListWidgetItem(name)
                it.setData(Qt.ItemDataRole.UserRole, {"album": album})
                it.setData(ALBUM_ROLE, {"title": name, "artist": artist, "album": album, "n": r["n"],
                                        "detected_artist": r["artist"] or ""})
                it.setToolTip(tr("{name}\n{v1} · {v2} pistas · {v3}", name=name, v1=artist or 'Artista desconocido', v2=r['n'], v3=human_time(r['duration'] or 0)))
                self.groups.addItem(it)
                jobs.append((info.get("cover") or "", r["sample"]))
            self._load_covers(jobs[:600], token)
        elif tab == 4:
            for r in self.db.artists(search):
                it = QListWidgetItem(QIcon(icons.pixmap("star", t.accent, 64)), r['artist'] or 'Artista desconocido')
                it.setToolTip(tr("{v0} pistas · {v1} álbumes", v0=r['n'], v1=r['albums']))
                it.setData(Qt.ItemDataRole.UserRole, {"artist": r["artist"]})
                self.groups.addItem(it)
        else:
            for r in self.db.folders(search):
                it = QListWidgetItem(QIcon(icons.pixmap("folder", t.accent, 64)), Path(r['folder']).name)
                it.setToolTip(f"{r['folder']}\n{r['n']} archivos")
                it.setData(Qt.ItemDataRole.UserRole, {"folder": r["folder"]})
                self.groups.addItem(it)

    def _load_covers(self, jobs: list[tuple[str, str]], token: int):
        """Carga en segundo plano la portada personalizada (si existe) o la incluida en el primer archivo."""
        def work():
            out = []
            for i, (custom, sample) in enumerate(jobs):
                img = QImage(custom) if custom else QImage()
                if img.isNull():
                    data = read_cover(sample)
                    img = QImage.fromData(data) if data else QImage()
                if not img.isNull():
                    out.append((i, img.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                              Qt.TransformationMode.SmoothTransformation)))
            return out

        def done(res):
            if token != self._cover_token:
                return
            for i, img in res:
                it = self.groups.item(i)
                if it is not None:
                    it.setData(Qt.ItemDataRole.DecorationRole, QPixmap.fromImage(img))

        run_async(work, done, None, self)

    # ------------------------------------------------------------------ series
    def _show_series(self, search: str):
        from aero.core.series import group_series

        self._series = group_series(self.db.all_paths("video", search))
        self.play_all.hide()
        self.shuffle_all.hide()
        if self.series_show and self.series_show in self._series:
            self._fill_episodes(self.series_show)
            self.body.setCurrentWidget(self.episodes)
            return
        self.groups.clear()
        self._set_group_mode(False)
        watched = self.db.watched()
        for show, eps in self._series.items():
            seen = sum(1 for e in eps if e.path in watched)
            seasons = len({e.season for e in eps})
            it = QListWidgetItem(QIcon(icons.pixmap("series", tm().theme.accent, 64)), show)
            it.setToolTip(tr("{seasons} temporadas · {v1} episodios · {seen} vistos", seasons=seasons, v1=len(eps), seen=seen))
            it.setData(Qt.ItemDataRole.UserRole, {"series": show})
            self.groups.addItem(it)
        self.body.setCurrentWidget(self.groups)

    def _fill_episodes(self, show: str):
        eps = self._series.get(show, [])
        watched = self.db.watched([e.path for e in eps])
        pos = self.db.positions_for([e.path for e in eps])
        self.episodes.clear()
        seasons: dict[int, QTreeWidgetItem] = {}
        t = tm().theme
        for e in eps:
            parent = seasons.get(e.season)
            if parent is None:
                parent = QTreeWidgetItem([f"Temporada {e.season}", ""])
                self.episodes.addTopLevelItem(parent)
                parent.setExpanded(True)
                seasons[e.season] = parent
            title = f"{e.episode:02d} · {e.title}" if e.title else f"Episodio {e.episode}"
            state = "Visto" if e.path in watched else (f"Seguir en {human_time(pos[e.path] / 1000)}"
                                                       if e.path in pos else "")
            it = QTreeWidgetItem([title, state])
            ic = "check" if e.path in watched else ("continue" if e.path in pos else "play")
            it.setIcon(0, icons.icon(ic, t.accent if ic != "play" else t.text2, 18))
            it.setData(0, Qt.ItemDataRole.UserRole, e.path)
            it.setToolTip(0, e.path)
            parent.addChild(it)
        self.crumb.setText(show)
        self.back_btn.show()

    def _play_episode(self, item: QTreeWidgetItem, _col: int = 0):
        from aero.core.series import episodes_from

        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.play_paths.emit(episodes_from(path, self._series.get(self.series_show, [])), 0)

    def _open_group(self, it: QListWidgetItem):
        data = it.data(Qt.ItemDataRole.UserRole)
        if "series" in data:
            self.series_show = data["series"]
            self.refresh()
            return
        self.group_filter = data
        self.crumb.setText(it.text())
        self.back_btn.show()
        self.refresh()

    def _reset_group(self):
        self.group_filter = None
        self.series_show = None
        self.back_btn.hide()
        self.crumb.setText("")
        self.refresh()

    # ------------------------------------------------------------------ álbumes
    def _album_paths(self, album: str) -> list[str]:
        return self.db.all_paths("audio", album=album, order="album")

    def _group_menu(self, pos):
        it = self.groups.itemAt(pos)
        if it is None or self.tabs.currentIndex() != 3:
            return
        self.groups.setCurrentItem(it)
        album = it.data(Qt.ItemDataRole.UserRole)["album"]
        paths = self._album_paths(album)
        m = QMenu(self)
        m.addAction(tm().icon("play", 16), tr("Reproducir álbum"), lambda: self.play_paths.emit(paths, 0))
        m.addAction(tm().icon("queue", 16), tr("Añadir a la cola"), lambda: self.enqueue_paths.emit(paths, False))
        m.addAction(tm().icon("list_add", 16), tr("Añadir a una lista…"), lambda: self.add_to_playlist.emit(paths))
        m.addSeparator()
        m.addAction(tm().icon("info", 16), tr("Ver información"), lambda: self._album_info(it))
        m.addAction(tm().icon("edit", 16), tr("Editar álbum…"), lambda: self._edit_album(it))
        m.addSeparator()
        m.addAction(tm().icon("trash", 16), tr("Eliminar de la biblioteca…"), lambda: self._remove_album(it))
        self._last_menu = m
        m.exec(self.groups.viewport().mapToGlobal(pos))

    def _album_info(self, it: QListWidgetItem):
        from aero.ui.pages.albums import ALBUM_ROLE, AlbumInfoDialog

        d = it.data(ALBUM_ROLE)
        AlbumInfoDialog(d["title"], d["artist"], self.db.album_details(d["album"]),
                        it.data(Qt.ItemDataRole.DecorationRole), self).exec()

    def _edit_album(self, it: QListWidgetItem):
        from aero.ui.pages.albums import ALBUM_ROLE, AlbumEditDialog, load_image

        d = it.data(ALBUM_ROLE)
        album = d["album"]
        info = self.db.album_info(album)
        original = QImage()
        for path in self._album_paths(album)[:3]:
            data = read_cover(path)
            if data:
                original = QImage.fromData(data)
                if not original.isNull():
                    break
        current = load_image(info["cover"]) if info.get("cover") else None
        dlg = AlbumEditDialog(album, {**info, "detected_artist": d.get("detected_artist", "")},
                              original if not original.isNull() else None,
                              current if current is not None and not current.isNull() else None, self)
        if dlg.exec():
            self.apply_album_edit(album, dlg.result())

    def apply_album_edit(self, album: str, res: dict):
        """Guarda nombre, artista y portada personalizados (solo en la base de datos de AERO Player)."""
        from aero.ui.pages.albums import save_cover

        info = self.db.album_info(album)
        cover = info.get("cover", "")
        if res.get("cover") == "":
            cover = ""
        elif res.get("cover") is not None and not res["cover"].isNull():
            cover = save_cover(res["cover"], album)
        self.db.set_album_info(album, res.get("title", ""), res.get("artist", ""), cover)
        self.refresh()
        self.message.emit(tr("Álbum actualizado."), "ok")

    def _remove_album(self, it: QListWidgetItem):
        from PySide6.QtWidgets import QMessageBox

        from aero.ui.pages.albums import ALBUM_ROLE

        d = it.data(ALBUM_ROLE)
        paths = self._album_paths(d["album"])
        box = QMessageBox(self)
        box.setWindowTitle(tr("Eliminar álbum"))
        box.setText(tr("«{v0}» · {v1} pistas", v0=d['title'], v1=len(paths)))
        box.setInformativeText(tr("«Quitar de la biblioteca» solo lo oculta en AERO Player; tus archivos no se tocan."))
        hide = box.addButton(tr("Quitar de la biblioteca"), QMessageBox.ButtonRole.AcceptRole)
        trash = box.addButton(tr("Mover archivos a la Papelera…"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(hide)
        box.exec()
        if box.clickedButton() is hide:
            self.db.hide_paths(paths)
            self.refresh()
            self.message.emit(tr("Álbum quitado de la biblioteca. Los archivos siguen en su sitio."), "ok")
        elif box.clickedButton() is trash:
            self._trash_files(paths, d["title"])

    def _trash_files(self, paths: list[str], title: str):
        """Borrado físico: siempre a la Papelera de reciclaje y tras una segunda confirmación explícita."""
        from PySide6.QtCore import QFile
        from PySide6.QtWidgets import QMessageBox

        r = QMessageBox.warning(
            self, tr("Mover a la Papelera"),
            tr("Se moverán {v0} archivos de «{title}» a la Papelera de reciclaje de Windows.\nPodrás recuperarlos desde la Papelera. ¿Continuar?", v0=len(paths), title=title),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Yes:
            return
        moved, failed = [], []
        for p in paths:
            ok = QFile.moveToTrash(p)
            ok = ok[0] if isinstance(ok, tuple) else bool(ok)
            (moved if ok else failed).append(p)
        self.db.remove_paths(moved)
        self.refresh()
        if failed:
            self.message.emit(tr("{v0} movidos a la Papelera; {v1} no se pudieron mover.", v0=len(moved), v1=len(failed)), "error")
        else:
            self.message.emit(tr("{v0} archivos movidos a la Papelera.", v0=len(moved)), "ok")

    # ------------------------------------------------------------------ acciones
    def _selected_paths(self) -> list[str]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.path_at(r) for r in rows]

    def _activate(self, idx):
        f = self.model.filters
        paths = self.db.all_paths(**f, order=self.model.order, desc=self.model.desc)
        path = self.model.path_at(idx.row())
        self.play_paths.emit(paths, paths.index(path) if path in paths else 0)

    def _play_all(self, shuffle: bool):
        f = self.model.filters
        paths = self.db.all_paths(**f, order=self.model.order, desc=self.model.desc)
        if shuffle:
            import random

            random.shuffle(paths)
        if paths:
            self.play_paths.emit(paths, 0)

    def _menu(self, pos):
        paths = self._selected_paths()
        if not paths:
            return
        m = QMenu(self)
        m.addAction(tm().icon("play", 16), "Reproducir", lambda: self.play_paths.emit(paths, 0))
        m.addAction(tr("Reproducir a continuación"), lambda: self.enqueue_paths.emit(paths, True))
        m.addAction(tm().icon("queue", 16), tr("Añadir a la cola"), lambda: self.enqueue_paths.emit(paths, False))
        m.addAction(tm().icon("list_add", 16), tr("Añadir a una lista…"), lambda: self.add_to_playlist.emit(paths))
        fav = self.db.is_favorite(paths[0])
        m.addAction(tm().icon("heart", 16), tr("Quitar de favoritos") if fav else tr("Añadir a favoritos"),
                    lambda: [self.db.set_favorite(p, not fav) for p in paths])
        m.addSeparator()
        if len(paths) == 1:
            m.addAction(tm().icon("tag", 16), tr("Editar etiquetas…"), lambda: self._edit_tags(paths[0]))
        m.addAction(tm().icon("convert", 16), tr("Convertir…"), lambda: self.convert_paths.emit(paths))
        m.addAction(tm().icon("folder", 16), tr("Mostrar en el Explorador"), lambda: tools.reveal_in_explorer(paths[0]))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _edit_tags(self, path: str):
        values = read_editable(path)
        if values is None:
            self.message.emit(tr("Este formato no admite edición de etiquetas."), "error")
            return
        dlg = TagDialog(path, values, self)
        if dlg.exec():
            try:
                write_tags(path, dlg.values())
            except ValueError as e:
                self.message.emit(str(e), "error")
                return
            row = dict(self.db.media_by_path(path) or {})
            if row:
                row.update(read_tags(path))
                self.db.upsert_media([row])
            self.model.refresh()
            self.message.emit(tr("Etiquetas guardadas."), "ok")

    # ------------------------------------------------------------------ escaneo
    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Añadir carpeta a la biblioteca"))
        if not folder:
            return
        folders = list(self.settings.get("library_folders"))
        if folder not in folders:
            folders.append(folder)
            self.settings.set("library_folders", folders)
        self.scan()

    def scan(self):
        if self.scanner is not None and self.scanner.isRunning():
            return
        folders = self.settings.get("library_folders")
        if not folders:
            self._add_folder()
            return
        self.scanner = LibraryScanner(folders, self.settings.get("library_excludes"), self.db.path, self)
        self.scanner.progress.connect(lambda n, _p: self.scan_label.setText(tr("{n} archivos revisados", n=n)))
        self.scanner.finished_scan.connect(self._scan_done)
        self.scanner.failed.connect(lambda m: self.message.emit(tr("Error al escanear: {m}", m=m), "error"))
        for w in (self.pause_btn, self.cancel_btn, self.spinner):
            w.show()
        self.scan_btn.setEnabled(False)
        self.scan_label.setText(tr("Escaneando…"))
        self.scanner.start()

    def _pause(self):
        if not self.scanner:
            return
        if self.scanner.paused:
            self.scanner.resume()
            self.pause_btn.set_icon_name("pause_small")
            self.spinner.show()
        else:
            self.scanner.pause()
            self.pause_btn.set_icon_name("play")
            self.spinner.hide()
            self.scan_label.setText(tr("En pausa"))

    def _scan_done(self, changed: int, removed: int):
        for w in (self.pause_btn, self.cancel_btn, self.spinner):
            w.hide()
        self.scan_btn.setEnabled(True)
        self.scan_label.setText("")
        self.pause_btn.set_icon_name("pause_small")
        self.message.emit(tr("Biblioteca actualizada: {changed} nuevos o modificados, {removed} eliminados.", changed=changed, removed=removed), "ok")
        self.refresh()

    def stop_scan(self):
        if self.scanner is not None and self.scanner.isRunning():
            self.scanner.cancel()
            self.scanner.wait(3000)

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()
