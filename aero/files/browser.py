"""Explorador compartido de carpetas y comprimidos (Quick Look, biblioteca «Archivos» y visor).

* Cuadrícula o lista, buscar, filtrar por tipo, ordenar, seleccionar varios.
* Lista virtualizada (`QListView` con tamaños uniformes): miles de elementos sin coste.
* Miniaturas solo de lo que se ve, como mucho dos a la vez y en segundo plano, con caché limitada.
* Comprimidos: se navega por dentro sin extraer; abrir un elemento extrae solo ese a una carpeta temporal.
"""

from __future__ import annotations

import datetime as dt
import os
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QFileSystemWatcher, QModelIndex, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QImageReader, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QLineEdit, QListView, QStackedWidget, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from aero import files
from aero.files import shell
from aero.core.formats import KIND_LABELS, human_size
from aero.core.tasks import tasks
from aero.ui import icons
from aero.ui.async_util import run_async
from aero.ui.glass import IconButton, Spinner, h_layout, label, tm, v_layout
from aero.i18n import tr

ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1
GRID = QSize(124, 132)
ROW_H = 34
THUMB = 76


def _load_thumb(path: str, side: int) -> QImage:
    """Hilo de trabajo: lee la imagen ya reducida (el decodificador no crea la imagen completa si puede)."""
    r = QImageReader(path)
    r.setAutoTransform(True)
    s = r.size()
    if s.isValid() and (s.width() > side or s.height() > side):
        r.setScaledSize(s.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
    img = r.read()
    if img.isNull():
        raise ValueError(r.errorString())
    return img


class ThumbCache:
    """Miniaturas bajo demanda: LIFO (lo último visible primero).

    Cuántas se cargan a la vez, cuántas se guardan en memoria y su tamaño salen del perfil de rendimiento
    (`background`, `thumb_cache`, `thumbs`); al cambiar el tamaño se descartan las de otro tamaño.
    """

    MAX = 400
    BUSY = 2

    def __init__(self, owner: QWidget, on_ready):
        self.owner, self.on_ready = owner, on_ready
        self.cache: OrderedDict[str, QPixmap | None] = OrderedDict()
        self.pending: list[str] = []
        self.busy = 0
        self.side = THUMB * 2

    @staticmethod
    def limits() -> tuple[int, int, int]:
        q = tm().quality
        return (max(THUMB, int(q.get("thumbs", THUMB * 2))), max(50, int(q.get("thumb_cache", ThumbCache.MAX))),
                max(1, min(4, int(q.get("background", ThumbCache.BUSY)))))

    def get(self, path: str) -> QPixmap | None:
        side = self.limits()[0]
        if side != self.side:   # el perfil cambió el tamaño: las guardadas ya no sirven
            self.side = side
            self.cache.clear()
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.cache[path]
        if path not in self.pending:
            self.pending.append(path)
            self._pump()
        return None

    def clear(self):
        self.pending.clear()
        self.cache.clear()

    def _pump(self):
        side, _keep, busy = self.limits()
        while self.busy < busy and self.pending:
            path = self.pending.pop()
            self.busy += 1
            # La ruta y el tamaño se fijan ya: la tarea se ejecuta más tarde, cuando el bucle ha avanzado.
            tasks().submit(lambda p=path, s=side: _load_thumb(p, s), "background", lambda img, p=path: self._done(p, img),
                           lambda _e, p=path: self._done(p, None), self.owner)

    def _done(self, path: str, img: QImage | None):
        self.busy -= 1
        self.cache[path] = QPixmap.fromImage(img) if img is not None else None
        keep = self.limits()[1]
        while len(self.cache) > keep:
            self.cache.popitem(last=False)
        self.on_ready(path)
        self._pump()


class ShellIconCache:
    """Iconos reales de los programas y accesos directos (el de la aplicación instalada), pedidos al shell en
    tandas cortas sin congelar la vista; se muestran dentro de la baldosa de aplicación de AERO. El resto de
    archivos usa solo los iconos de categoría de AERO (`aero.ui.file_icons`). También guarda si un programa trae la
    marca «descargado de Internet» para señalarlo."""

    BATCH_MS = 12

    def __init__(self, on_ready):
        self.on_ready = on_ready
        self.icons: dict[str, QIcon | None] = {}
        self.types: dict[str, str] = {}
        self.risky: dict[str, bool] = {}
        self.queue: dict[str, tuple[str, bool]] = {}
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(0)
        self.timer.timeout.connect(self._work)

    def key(self, e: files.FileEntry) -> str:
        return shell.icon_key(e.inner or e.path, e.is_dir) if not e.inner else \
            ("<dir>" if e.is_dir else shell.ext_of(e.inner) or "<none>")

    def get(self, e: files.FileEntry) -> QIcon | None:
        if e.inner or category(e) not in ("app", "shortcut"):
            return None
        k = self.key(e)
        if k in self.icons:
            return self.icons[k]
        if not e.inner and k not in self.queue:
            self.queue[k] = (e.path, e.is_dir)
            if not self.timer.isActive():
                self.timer.start()
        return None

    def type_of(self, e: files.FileEntry) -> str:
        return self.types.get(self.key(e), "")

    def risky_of(self, e: files.FileEntry) -> bool:
        # Por archivo (no por extensión): dos .bat pueden venir de sitios distintos
        if e.inner or e.is_dir:
            return False
        if e.path not in self.risky:
            self.risky[e.path] = shell.is_runnable(e.path) and shell.from_internet(e.path)
        return self.risky[e.path]

    def clear(self):
        self.queue.clear()

    def _work(self):
        import time

        end = time.perf_counter() + self.BATCH_MS / 1000
        done = False
        while self.queue and time.perf_counter() < end:
            k, (path, is_dir) = next(iter(self.queue.items()))
            del self.queue[k]
            try:
                ic = shell.shell_icon(path)
                self.icons[k] = None if ic.isNull() else ic
            except (OSError, RuntimeError):
                self.icons[k] = None
            done = True
        if self.queue:
            self.timer.start()
        if done:
            self.on_ready()


class EntryModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[files.FileEntry] = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return e.name
        if role == ENTRY_ROLE:
            return e
        if role == Qt.ItemDataRole.ToolTipRole:
            if not e.inner and shell.is_shortcut(e.path):
                t = shell.resolve_shortcut(e.path)
                dest = t.path or t.url
                return f"{e.name}\n→ {dest}" if dest else e.name
            return e.name
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return f"{e.name}, {type_label(e)}"
        return None

    def row_of(self, path: str) -> int:
        for i, e in enumerate(self.rows):
            if e.path == path and not e.inner:
                return i
        return -1


def category(e: files.FileEntry) -> str:
    """Categoría visual de la entrada (calculada al listar; si no, por la extensión)."""
    if e.category:
        return e.category
    from aero.core.filetypes import by_extension

    return by_extension(e.inner or e.name, e.is_dir)


def warning_text(w: str) -> str:
    """Avisos del lector de comprimidos (texto de origen en español) en el idioma de la interfaz."""
    import re

    if w.startswith("Etiqueta: "):
        return tr("Etiqueta: {label}", label=w[len("Etiqueta: "):])
    m = re.fullmatch(r"Se muestran los primeros ([\d.]+) elementos\.", w)
    if m:
        return tr("Se muestran los primeros {n} elementos.", n=m.group(1))
    return tr(w)


def type_label(e: files.FileEntry) -> str:
    """«Vídeo · MKV», «Aplicación · EXE», «Carpeta»: categoría en el idioma de AERO y la extensión."""
    from aero.core.filetypes import CATEGORIES

    base = tr(CATEGORIES.get(category(e), "Archivo"))
    ext = e.ext[1:].upper() if not e.is_dir and e.ext else ""
    return f"{base} · {ext}" if ext else base


class EntryDelegate(QStyledItemDelegate):
    """Dibuja elementos en cuadrícula (icono o miniatura y nombre) o en filas (nombre, tipo, tamaño, fecha)."""

    def __init__(self, browser: "FolderBrowser"):
        super().__init__(browser)
        self.b = browser

    def sizeHint(self, option, index):
        return GRID if self.b.grid_mode else QSize(max(200, self.b.view.viewport().width() - 4), ROW_H)

    def _icon(self, p: QPainter, e: files.FileEntry, box: QRectF, accent: str) -> None:
        """Icono de categoría de AERO (con el icono real del programa dentro si es una aplicación o un acceso
        directo) y sus distintivos."""
        from aero.ui import file_icons

        side = int(box.width())
        dpr = self.b.devicePixelRatioF()
        cat = category(e)
        inner = None
        if cat in ("app", "shortcut"):
            ic = self.b.shell_icons.get(e)
            inner = ic.pixmap(QSize(int(side * 0.6), int(side * 0.6)), dpr) if ic is not None else None
        pm = file_icons.pixmap(cat, side, dpr, tm().theme.dark, inner)
        p.drawPixmap(box, pm, QRectF(pm.rect()))
        if e.inner:
            return
        badge = max(10.0, box.width() * 0.36)
        if shell.is_shortcut(e.path):
            # Flecha de acceso directo, como en el Explorador
            b = QRectF(box.left(), box.bottom() - badge, badge, badge)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawRoundedRect(b, 3, 3)
            ar = icons.pixmap("external", "#1c5fb8", int(badge))
            p.drawPixmap(b.adjusted(1, 1, -1, -1), ar, QRectF(ar.rect()))
        if self.b.shell_icons.risky_of(e):
            # Programa descargado de Internet: se avisará antes de ejecutarlo
            b = QRectF(box.right() - badge, box.bottom() - badge, badge, badge)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#f2b233"))
            p.drawEllipse(b)
            p.setPen(QColor("#2a1d00"))
            f = QFont(p.font())
            f.setBold(True)
            f.setPixelSize(int(badge * 0.8))
            p.setFont(f)
            p.drawText(b, Qt.AlignmentFlag.AlignCenter, "!")

    def _thumb(self, e: files.FileEntry) -> QPixmap | None:
        if e.kind == "image" and not e.inner and not e.is_dir:
            return self.b.thumbs.get(e.path)
        return None

    def paint(self, p: QPainter, option, index):
        t = tm().theme
        e: files.FileEntry = index.data(ENTRY_ROLE)
        r = QRectF(option.rect)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if hover or sel:
            box = QPainterPath()
            box.addRoundedRect(r.adjusted(2.5, 1.5, -2.5, -1.5), 10, 10)
            c = QColor(t.accent if sel else "#ffffff")
            c.setAlphaF(0.22 if sel else (0.07 if t.dark else 0.30))
            p.fillPath(box, c)
            if sel:
                c.setAlphaF(0.7)
                p.setPen(QPen(c, 1))
                p.drawPath(box)
        accent = t.accent if e.is_dir else t.text2
        if self.b.grid_mode:
            area = QRectF(r.center().x() - THUMB / 2, r.top() + 8, THUMB, THUMB)
            pm = self._thumb(e)
            if pm is not None and not pm.isNull():
                fit = QSize(pm.width(), pm.height()).scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio)
                tr = QRectF(area.center().x() - fit.width() / 2, area.center().y() - fit.height() / 2,
                            fit.width(), fit.height())
                clip = QPainterPath()
                clip.addRoundedRect(tr, 6, 6)
                p.save()
                p.setClipPath(clip)
                p.drawPixmap(tr, pm, QRectF(pm.rect()))
                p.restore()
                p.setPen(QPen(QColor(255, 255, 255, 90), 1))
                p.drawPath(clip)
            else:
                self._icon(p, e, QRectF(area.center().x() - 24, area.center().y() - 24, 48, 48), accent)
            if e.locked:
                lk = icons.pixmap("lock", t.text, 16)
                p.drawPixmap(QRectF(area.right() - 14, area.bottom() - 16, 16, 16), lk, QRectF(lk.rect()))
            f = QFont(option.font)
            f.setPointSizeF(9)
            p.setFont(f)
            p.setPen(QColor(t.text))
            tr = QRectF(r.left() + 6, area.bottom() + 6, r.width() - 12, 34)
            fm = p.fontMetrics()
            # Dos líneas como máximo: la segunda se recorta con «…»
            words = e.name
            first = fm.elidedText(words, Qt.TextElideMode.ElideNone, int(tr.width()))
            if fm.horizontalAdvance(words) <= tr.width():
                p.drawText(tr, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, words)
            else:
                cut = len(words)
                while cut > 1 and fm.horizontalAdvance(words[:cut]) > tr.width():
                    cut -= 1
                first = words[:cut]
                second = fm.elidedText(words[cut:], Qt.TextElideMode.ElideMiddle, int(tr.width()))
                p.drawText(QRectF(tr.left(), tr.top(), tr.width(), 16), Qt.AlignmentFlag.AlignHCenter, first)
                p.drawText(QRectF(tr.left(), tr.top() + 16, tr.width(), 16), Qt.AlignmentFlag.AlignHCenter, second)
        else:
            self._icon(p, e, QRectF(r.left() + 11, r.center().y() - 10, 20, 20), accent)
            f = QFont(option.font)
            f.setPointSizeF(9.5)
            p.setFont(f)
            fm = p.fontMetrics()
            w = r.width()
            cols = [(w * 0.50, e.name, t.text, Qt.AlignmentFlag.AlignLeft),
                    (w * 0.18, type_label(e), t.text2,
                     Qt.AlignmentFlag.AlignLeft),
                    (w * 0.12, "" if e.is_dir else human_size(e.size), t.text2, Qt.AlignmentFlag.AlignRight),
                    (w * 0.20 - 52, dt.datetime.fromtimestamp(e.mtime).strftime("%d/%m/%Y %H:%M") if e.mtime else "",
                     t.text2, Qt.AlignmentFlag.AlignRight)]
            x = r.left() + 40
            for cw, text, col, al in cols:
                p.setPen(QColor(col))
                p.drawText(QRectF(x, r.top(), cw - 12, r.height()), al | Qt.AlignmentFlag.AlignVCenter,
                           fm.elidedText(text, Qt.TextElideMode.ElideMiddle, int(cw - 12)))
                x += cw
            if e.locked:
                lk = icons.pixmap("lock", t.text2, 14)
                p.drawPixmap(QRectF(r.left() + 26, r.center().y() + 1, 12, 12), lk, QRectF(lk.rect()))
        p.restore()


class FolderBrowser(QWidget):
    """Navegador de una carpeta o de un comprimido.

    Señales: `open_requested(path)` con una ruta real lista para abrir (los elementos de un comprimido se
    extraen antes, de uno en uno); `location_changed()`; `preview_requested(path)` (Espacio).
    """

    open_requested = Signal(str)
    preview_requested = Signal(str)
    location_changed = Signal()
    action_requested = Signal(str, list)  # acción del menú contextual (extraer, comprimir, convertir…), rutas

    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self.compact = compact
        self.grid_mode = True
        self.root = ""            # carpeta o comprimido raíz (no se sube por encima)
        self.cwd = ""             # carpeta actual o prefijo dentro del comprimido
        self.archive = None       # ArchiveInfo
        self.workspace = None     # carpeta temporal de vistas previas
        self.entries: list[files.FileEntry] = []
        self._token = 0
        self.thumbs = ThumbCache(self, self._thumb_ready)
        self.shell_icons = ShellIconCache(lambda: self.view.viewport().update())
        # Cambios en la carpeta abierta (renombrar en lote, copias nuevas, otros programas): se relee sola.
        self.watcher = QFileSystemWatcher(self)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(400)
        self._reload_timer.timeout.connect(self._reload)
        self.watcher.directoryChanged.connect(lambda _p: self._reload_timer.start())

        self.btn_up = IconButton("up", tr("Carpeta superior (Retroceso)"), 18)
        self.btn_up.clicked.connect(self.go_up)
        self.title = label("", "h3")
        self.meta = label("", "caption")
        self.meta.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Buscar"))
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(220)
        self.search.textChanged.connect(self._refresh)
        self.filter = QComboBox()
        for key, (text, _k) in files.FILTERS.items():
            self.filter.addItem(tr(text), key)
        self.filter.currentIndexChanged.connect(self._refresh)
        self.sort = QComboBox()
        for key, text in files.SORTS.items():
            self.sort.addItem(tr(text), key)
        self.sort.currentIndexChanged.connect(self._refresh)
        self.btn_order = IconButton("sort", tr("Orden ascendente o descendente"), 18)
        self.btn_order.setCheckable(True)
        self.btn_order.toggled.connect(self._refresh)
        self.btn_view = IconButton("list", tr("Ver como lista"), 18)
        self.btn_view.clicked.connect(lambda: self.set_grid(not self.grid_mode))
        for w in (self.filter, self.sort):
            w.setAccessibleName("Filtrar" if w is self.filter else "Ordenar")

        self.model = EntryModel(self)
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(EntryDelegate(self))
        self.view.setUniformItemSizes(True)
        # Colocación por tandas: con miles de elementos la interfaz no se queda esperando a toda la cuadrícula.
        self.view.setLayoutMode(QListView.LayoutMode.Batched)
        self.view.setBatchSize(300)
        self.view.setMouseTracking(True)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setFrameShape(QListView.Shape.NoFrame)
        self.view.setStyleSheet("QListView { background: transparent; }")
        self.view.activated.connect(self._activate)
        self.view.doubleClicked.connect(self._activate)
        self.view.installEventFilter(self)
        if not compact:
            self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.view.customContextMenuRequested.connect(self._context_menu)
        self.set_grid(True)

        self.state = QStackedWidget()
        self.message = label("", "muted", wrap=True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spinner = Spinner(36)
        loading = QWidget()
        loading.setLayout(v_layout(None, h_layout(None, self.spinner, None), None))
        msg = QWidget()
        msg.setLayout(v_layout(None, self.message, None, margins=(30, 0, 30, 0)))
        self.state.addWidget(self.view)
        self.state.addWidget(loading)
        self.state.addWidget(msg)
        self.status = label("", "caption")

        if compact:
            self.title.hide()  # en Quick Look el nombre ya está en la barra superior
        head = h_layout(self.btn_up, spacing=8)
        head.addLayout(v_layout(self.title, self.meta, spacing=0), 1)
        tools_row = h_layout(self.search, self.filter, self.sort, self.btn_order, self.btn_view, None, spacing=6)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addLayout(head)
        lay.addLayout(tools_row)
        lay.addWidget(self.state, 1)
        lay.addWidget(self.status)

    # ------------------------------------------------------------------ ubicación
    def set_root(self, path: str) -> None:
        """Abre una carpeta o un comprimido como raíz."""
        from aero import archive

        path = os.path.abspath(path)
        # Un comprimido extraído de otro (ZIP dentro de ZIP) vive en la carpeta temporal: no se borra aún.
        nested = self.workspace is not None and Path(path).is_relative_to(self.workspace.dir)
        if nested:
            self._token += 1
            self.thumbs.clear()
        else:
            self.cleanup()
        self.root = path
        self.archive = None
        self.entries = []
        self.model.set_rows([])  # nada de filas de la ubicación anterior mientras se lee la nueva
        self.search.clear()
        if os.path.isdir(self.root):
            self._go(self.root)
            return
        self._loading()
        token = self._token
        run_async(lambda: archive.read_archive(path), lambda info: token == self._token and self._archive_ready(info),
                  lambda err: token == self._token and self._fail(err), self)

    def _archive_ready(self, info):
        self.archive = info
        self._go("")

    def location(self) -> tuple[str, str]:
        return self.root, self.cwd

    def restore(self, root: str, cwd: str) -> None:
        if root == self.root and (self.archive is not None or os.path.isdir(root)):
            self._go(cwd)
        else:
            self.set_root(root)

    def _go(self, cwd: str) -> None:
        self.cwd = cwd
        self.thumbs.clear()
        self._token += 1
        token = self._token
        self._watch("" if self.archive is not None else cwd)
        if self.archive is not None:
            self._listed(files.archive_entries(self.archive, cwd), token)
            return
        self._loading()
        run_async(lambda: files.list_dir(cwd), lambda rows: self._listed(rows, token),
                  lambda err: token == self._token and self._fail(err), self)

    def _watch(self, folder: str) -> None:
        old = self.watcher.directories()
        if old and old != [folder]:
            self.watcher.removePaths(old)
        if folder and folder not in self.watcher.directories():
            self.watcher.addPath(folder)

    def _reload(self) -> None:
        """Vuelve a leer la carpeta actual sin vaciar la vista ni perder la selección."""
        if self.archive is not None or not self.cwd or not os.path.isdir(self.cwd):
            return
        token = self._token
        selected = {e.path for e in self.selected_entries() if e is not None}
        cwd = self.cwd

        def done(rows):
            if token != self._token or cwd != self.cwd:
                return
            scroll = self.view.verticalScrollBar().value()
            self.entries = rows
            self._update_header()
            self._refresh()
            self.view.verticalScrollBar().setValue(scroll)
            for r in range(self.model.rowCount()):
                idx = self.model.index(r, 0)
                e = idx.data(ENTRY_ROLE)
                if e is not None and e.path in selected:
                    self.view.selectionModel().select(idx, self.view.selectionModel().SelectionFlag.Select)

        run_async(lambda: files.list_dir(cwd), done, None, self)

    def _loading(self):
        self.state.setCurrentIndex(1)
        self.spinner.show()

    def _listed(self, rows, token):
        if token != self._token:
            return
        self.entries = rows
        self.state.setCurrentIndex(0)
        self._update_header()
        self._refresh()
        self.btn_up.setEnabled(self._can_go_up())
        self.location_changed.emit()

    def _fail(self, err):
        msg = str(err) if err.__class__.__name__ in ("ArchiveError", "PasswordRequired", "UnsafeEntry") else (
            "No tienes permiso para abrir esta carpeta." if isinstance(err, PermissionError) else
            "La carpeta ya no existe." if isinstance(err, FileNotFoundError) else f"No se pudo leer: {err}")
        self.message.setText(msg)
        self.entries = []
        self.model.set_rows([])
        self.state.setCurrentIndex(2)
        self.title.setText(Path(self.root).name or self.root)
        self.meta.setText("")

    def _can_go_up(self) -> bool:
        if self.archive is not None:
            return bool(self.cwd)
        return os.path.normcase(os.path.abspath(self.cwd)) != os.path.normcase(self.root)

    def go_up(self):
        if not self._can_go_up():
            return
        if self.archive is not None:
            self._go(self.cwd.rsplit("/", 1)[0] if "/" in self.cwd else "")
        else:
            self._go(os.path.dirname(self.cwd))

    def _update_header(self):
        if self.archive is not None:
            name = Path(self.root).name
            self.title.setText(name if not self.cwd else self.cwd.rsplit("/", 1)[-1])
            info = self.archive
            st = files.immediate_stats(self.entries)
            parts = [f"{info.fmt}", tr("{files} en total", files=files.count(len(info.files), "file")),
                     tr("{size} sin comprimir", size=human_size(info.total_size))]
            if self.cwd:
                parts.insert(0, f"{name} › {self.cwd.replace('/', ' › ')}")
            self.meta.setText(" · ".join(parts) + self._kinds_text(st))
            self.status.setText("  ".join("⚠ " + warning_text(w) for w in info.warnings))
            return
        st = files.immediate_stats(self.entries)
        self.title.setText(Path(self.cwd).name or self.cwd)
        try:
            mod = dt.datetime.fromtimestamp(os.path.getmtime(self.cwd)).strftime("%d/%m/%Y %H:%M")
        except OSError:
            mod = ""
        base = f"{files.count(st.files, 'file')} · {files.count(st.dirs, 'folder')} · " + tr("modificada {date}", date=mod)
        self.meta.setText(base + tr(" · calculando tamaño…") + self._kinds_text(st))
        self.status.setText("")
        token, cwd = self._token, self.cwd
        tasks().submit(lambda: files.folder_stats(cwd), "background",
                       lambda s: token == self._token and self.meta.setText(
                           base + tr(" · {v0}{v1} en total", v0='más de ' if not s.complete else '', v1=human_size(s.size))
                           + self._kinds_text(st)), None, self)

    @staticmethod
    def _kinds_text(st) -> str:
        top = sorted(((n, k) for k, n in (st.kinds or {}).items()), reverse=True)[:4]
        from aero.core.filetypes import CATEGORIES

        def name(k):
            return tr("Otros") if k == "unknown" else tr(CATEGORIES.get(k) or KIND_LABELS.get(k) or "Otros")

        from aero.i18n import language

        keep = language().startswith("de")        # en alemán los sustantivos van en mayúscula
        return ("\n" + " · ".join(f"{n} {name(k) if keep else name(k).lower()}" for n, k in top)) if top else ""

    # ------------------------------------------------------------------ vista
    def set_grid(self, on: bool) -> None:
        self.grid_mode = on
        v = self.view
        if on:
            v.setViewMode(QListView.ViewMode.IconMode)
            v.setFlow(QListView.Flow.LeftToRight)
            v.setWrapping(True)
            v.setResizeMode(QListView.ResizeMode.Adjust)
            v.setGridSize(GRID)
            v.setSpacing(0)
        else:
            v.setViewMode(QListView.ViewMode.ListMode)
            v.setFlow(QListView.Flow.TopToBottom)
            v.setWrapping(False)
            v.setGridSize(QSize())
            v.setSpacing(0)
        v.setMovement(QListView.Movement.Static)
        self.btn_view.set_icon_name("list" if on else "grid")
        self.btn_view.setToolTip(tr("Ver como lista") if on else tr("Ver como cuadrícula"))
        v.doItemsLayout()

    def _refresh(self):
        rows = files.apply_view(self.entries, self.search.text(), self.filter.currentData() or "all",
                                self.sort.currentData() or "name", self.btn_order.isChecked())
        self.model.set_rows(rows)
        if rows:
            self.view.setCurrentIndex(self.model.index(0))
            self.view.clearSelection()

    def _thumb_ready(self, path: str):
        i = self.model.row_of(path)
        if i >= 0:
            idx = self.model.index(i)
            self.model.dataChanged.emit(idx, idx)

    def selected_entries(self) -> list[files.FileEntry]:
        return [i.data(ENTRY_ROLE) for i in sorted(self.view.selectionModel().selectedIndexes(), key=lambda i: i.row())]

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self.grid_mode:
            self.view.doItemsLayout()

    # ------------------------------------------------------------------ abrir
    def eventFilter(self, obj, ev):
        if obj is self.view and ev.type() == ev.Type.KeyPress:
            if ev.key() == Qt.Key.Key_Backspace:
                self.go_up()
                return True
            if ev.key() == Qt.Key.Key_Space and not self.compact:
                e = self.view.currentIndex().data(ENTRY_ROLE)
                if e is not None and not e.inner:
                    self.preview_requested.emit(e.path)
                    return True
        return super().eventFilter(obj, ev)

    def _context_menu(self, pos):
        """Clic derecho: las mismas acciones que el menú «AERO Player» del Explorador."""
        from PySide6.QtWidgets import QMenu

        from aero.core import shellmenu
        from aero.core.tools import reveal_in_explorer

        index = self.view.indexAt(pos)
        if not index.isValid():
            return  # clic en un hueco vacío: sin menú (como el Explorador)
        if not self.view.selectionModel().isSelected(index):
            self.view.setCurrentIndex(index)
        sel = [e for e in self.selected_entries() if e is not None]
        if not sel:
            return
        m = QMenu(self)
        col = tm().theme.accent

        from aero.i18n import tr

        def act(icon, text, fn):
            m.addAction(icons.icon(icon, col, 18), tr(text), fn)

        one = sel[0]
        if self.archive is not None:
            act("open", tr("Abrir"), lambda: self._activate(self.view.currentIndex()))
            act("drop", tr("Extraer los seleccionados en…"),
                lambda: self.action_requested.emit("extract_members", [self.root, *[e.inner for e in sel]]))
            m.exec(self.view.viewport().mapToGlobal(pos))
            return
        paths = [e.path for e in sel]
        exts = {e.ext if not e.name.lower().endswith(".tar.gz") else ".tar.gz" for e in sel if not e.is_dir}
        files_only = all(not e.is_dir for e in sel)
        act("open", tr("Abrir"), lambda: self._activate(self.view.currentIndex()))
        if len(sel) == 1 and not one.is_dir:
            runnable = shell.is_runnable(one.path) or (shell.is_shortcut(one.path) and
                                                       shell.resolve_shortcut(one.path).runnable)
            if runnable:
                act("play", tr("Ejecutar…"), lambda: self._confirm_run(one.path, shell.resolve_shortcut(one.path)
                                                                     if shell.is_shortcut(one.path) else None)
                    and self._launch(one.path))
                act("lock", tr("Ejecutar como administrador…"),
                    lambda: self._confirm_run(one.path, None) and self._launch(one.path, admin=True))
            elif not shell.is_shortcut(one.path):
                act("external", tr("Abrir con la aplicación de Windows"), lambda: self._windows_open(one.path))
                act("more", tr("Abrir con…"), lambda: shell.open_with(one.path))
            if shell.is_shortcut(one.path):
                t = shell.resolve_shortcut(one.path)
                if t.path and t.exists:
                    act("folder", tr("Abrir la ubicación del destino"), lambda: reveal_in_explorer(t.path))
            act("eye", tr("Vista rápida"), lambda: self.preview_requested.emit(one.path))
        act("external", tr("Mostrar en el Explorador"), lambda: reveal_in_explorer(one.path))
        if files_only and exts <= shellmenu.EDITABLE:
            act("edit", "Editar", lambda: self.action_requested.emit("edit", paths))
        if files_only and exts <= shellmenu.ARCHIVES:
            m.addSeparator()
            act("drop", tr("Extraer aquí"), lambda: self.action_requested.emit("extract_here", paths))
            act("files", tr("Extraer en una carpeta con su nombre"),
                lambda: self.action_requested.emit("extract_folder", paths))
            act("open", tr("Extraer en…"), lambda: self.action_requested.emit("extract_to", paths))
        if len(sel) == 1 and not one.is_dir:
            from aero.archive import disc

            if disc.can_mount(one.path):
                m.addSeparator()
                act("drop", tr("Montar en Windows"), lambda: self._mount(one.path))
                act("eject", tr("Desmontar"), lambda: self._unmount(one.path))
        m.addSeparator()
        act("archive", tr("Comprimir en ZIP"), lambda: self.action_requested.emit("compress_zip", paths))
        act("archive", tr("Comprimir…"), lambda: self.action_requested.emit("compress", paths))
        if files_only and exts <= shellmenu.CONVERTIBLE:
            act("convert", tr("Convertir…"), lambda: self.action_requested.emit("convert", paths))
        if files_only:
            m.addSeparator()
            act("edit", tr("Cambiar nombre…") if len(sel) == 1 else tr("Cambiar nombre en lote…"),
                lambda: self.action_requested.emit("batch_rename", paths))
            if all(e.kind == "image" for e in sel):
                act("image", tr("Redimensionar fotos…") if len(sel) > 1 else tr("Redimensionar…"),
                    lambda: self.action_requested.emit("batch_resize", paths))
        m.exec(self.view.viewport().mapToGlobal(pos))

    def _activate(self, index):
        e: files.FileEntry = index.data(ENTRY_ROLE)
        if e is None:
            return
        if e.is_dir:
            self._go(e.inner if e.inner or self.archive is not None else e.path)
            return
        if not e.inner:
            self.open_entry(e.path)
            return
        self._extract(e)

    # ------------------------------------------------------------------ programas, accesos directos y Windows
    def open_entry(self, path: str) -> None:
        """Doble clic o Intro. Nada se ejecuta sin una confirmación explícita."""
        if shell.is_shortcut(path):
            t = shell.resolve_shortcut(path)
            if t.path and t.is_dir:
                self._go(t.path)                     # acceso directo a una carpeta: se entra en ella
                return
            if t.url and not t.path:
                if self._confirm_run(path, t, link=True):
                    shell.open_default(path)
                return
            if t.path and t.exists and not t.runnable:
                self.open_requested.emit(t.path)     # acceso directo a un documento: se abre en AERO
                return
            if self._confirm_run(path, t):
                self._launch(path)
            return
        if path.lower().endswith(".torrent"):
            from aero.torrent.ui import open_torrent

            open_torrent(path, self.window())
            return
        if shell.is_runnable(path):
            if self._confirm_run(path, None):
                self._launch(path)
            return
        from aero.core.formats import kind_of

        if kind_of(path) == "unknown" and shell.has_association(path):
            self._windows_open(path)                 # tipo que AERO no abre: su aplicación de Windows
            return
        self.open_requested.emit(path)

    def _confirm_run(self, path: str, target, link: bool = False) -> bool:
        from PySide6.QtWidgets import QMessageBox

        name = Path(path).name
        if link:
            title, text = tr("Abrir enlace"), tr("¿Abrir «{name}» en el navegador?\n{url}", name=name, url=target.url)
        else:
            title = tr("Ejecutar programa")
            dest = target.path if target is not None and target.path else path
            text = tr("¿Ejecutar «{name}»?", name=name)
            if dest != path:
                text += "\n" + tr("Destino: {path}", path=dest)
        warn = shell.warning_for(path, target)
        box = QMessageBox(QMessageBox.Icon.Warning if warn else QMessageBox.Icon.Question, title, text,
                          parent=self)
        if warn:
            box.setInformativeText(warn)
        ok = box.addButton(tr("Abrir") if link else tr("Ejecutar"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(None if warn else ok)  # con advertencia, Intro no ejecuta
        box.exec()
        return box.clickedButton() is ok

    # ------------------------------------------------------------------ imágenes de disco
    def _mount(self, path: str) -> None:
        """Monta la imagen con Windows (a petición del usuario) y entra en la unidad."""
        from aero.archive import disc

        self.status.setText(tr("Montando «{name}»…", name=Path(path).name))
        run_async(lambda: disc.mounted_drive(path) or disc.mount(path),
                  lambda drive: (self.status.setText(tr("Montada en {drive}", drive=drive)), self.set_root(drive + "\\")),
                  lambda e: self.status.setText(tr("No se pudo montar: {e}", e=tr(str(e)))), self)

    def _unmount(self, path: str) -> None:
        from aero.archive import disc

        run_async(lambda: disc.unmount(path), lambda _r: self.status.setText(tr("Imagen desmontada")),
                  lambda e: self.status.setText(tr("No se pudo desmontar: {e}", e=e)), self)

    def _launch(self, path: str, admin: bool = False) -> None:
        try:
            shell.run(path, admin)
            self.status.setText(tr("Abierto: {name}", name=Path(path).name))
        except OSError as err:
            # p. ej. el usuario canceló el aviso de Windows (UAC o SmartScreen): no es un fallo de AERO
            self.status.setText(tr("No se abrió «{name}»: {err}", name=Path(path).name, err=err.strerror or err))

    def _windows_open(self, path: str) -> None:
        try:
            shell.open_default(path)
        except OSError as err:
            self.status.setText(tr("No se abrió «{name}»: {err}", name=Path(path).name, err=err.strerror or err))

    def _extract(self, e: files.FileEntry):
        from aero import archive

        info = self.archive
        if info is None:
            return
        entry = next((x for x in info.entries if x.name == e.inner), None)
        if entry is None:
            return
        try:
            archive.check_entry(entry)
        except archive.ArchiveError as err:
            self.status.setText(f"⚠ {err}")
            return
        if self.workspace is None:
            self.workspace = archive.Workspace()
        ws = self.workspace
        self.status.setText(tr("Abriendo {name}…", name=e.name))
        token = self._token
        run_async(lambda: archive.extract_entry(info, entry, ws),
                  lambda out: token == self._token and (self.status.setText(""), self.open_requested.emit(str(out))),
                  lambda err: token == self._token and self.status.setText(f"⚠ {err}"), self)

    def cleanup(self) -> None:
        """Libera la caché y borra lo extraído para previsualizar."""
        self._token += 1
        self.thumbs.clear()
        self._watch("")
        if self.workspace is not None:
            self.workspace.cleanup()
            self.workspace = None
