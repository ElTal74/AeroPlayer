"""Búsqueda universal (Ctrl+K): herramientas, ajustes, biblioteca, recientes, tareas y archivos de tus carpetas.

* Lo interno (herramientas, ajustes, biblioteca indexada con FTS5, recientes, historial de tareas) responde al
  instante en el hilo principal: son consultas en memoria o en SQLite con índice.
* Los archivos se buscan por nombre, en segundo plano, solo dentro de las carpetas que el usuario añadió a la
  biblioteca o a «Archivos» (nunca se indexa nada que no haya elegido). Cada tecla cancela la búsqueda anterior.
"""

from __future__ import annotations

import os
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QButtonGroup, QFrame, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from aero.ui.glass import h_layout, label, tm
from aero.i18n import tr

FILTERS = [("all", "Todo"), ("tool", "Herramientas"), ("setting", "Ajustes"), ("library", "Biblioteca"),
           ("recent", "Recientes"), ("file", "Archivos"), ("task", "Tareas")]
MAX_FILES = 120


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


@dataclass
class Result:
    kind: str
    title: str
    subtitle: str
    icon: str
    action: tuple          # ("page", key) | ("tool", key) | ("setting", key) | ("open", path) | ("reveal", path)


def tools_index() -> list[Result]:
    from aero.ui.main_window import PAGES
    from aero.ui.pages.home_page import HomePage

    out = [Result("tool", t, "Sección", ic, ("page", k)) for k, t, ic in PAGES]
    out.append(Result("tool", "Abrir un archivo", "Ctrl+O", "open", ("open_dialog", "")))
    out.append(Result("tool", "Descargas BitTorrent", "Torrents", "download", ("downloads", "")))
    for item in HomePage.CREATE_MENU:
        if item:
            ic, text, key = item
            out.append(Result("tool", text.rstrip("…"), "Crear", ic, ("tool", key)))
    return out


def settings_index(main) -> list[tuple[Result, str]]:
    from aero.ui.pages.settings_page import CATEGORIES

    sp = main.pages.get("settings")
    words = getattr(sp, "_index", {}) if sp is not None else {}
    return [(Result("setting", title, desc, icon, ("setting", key)), words.get(key, fold(title + " " + desc)))
            for key, title, icon, desc in CATEGORIES]


def search_files(roots: list[str], query: str, stop: threading.Event, limit: int = MAX_FILES) -> list[str]:
    """Nombres que contienen todas las palabras (sin tildes ni mayúsculas). Hilo de trabajo."""
    from aero.core import native

    nc = native.core()
    if nc is not None:
        return nc.search(list(roots), query, stop, limit)    # Rust, sin el GIL: la interfaz no se resiente
    return search_files_py(roots, query, stop, limit)


def search_files_py(roots: list[str], query: str, stop: threading.Event, limit: int = MAX_FILES) -> list[str]:
    words = fold(query).split()
    out: list[str] = []
    for root in roots:
        for dirpath, dirs, files in os.walk(root):
            if stop.is_set():
                return out
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("$RECYCLE.BIN", "node_modules")]
            for name in files + dirs:
                f = fold(name)
                if all(w in f for w in words):
                    out.append(os.path.join(dirpath, name))
                    if len(out) >= limit:
                        return out
    return out


class CommandPalette(QFrame):
    files_found = Signal(int, list)

    def __init__(self, main):
        super().__init__(main, Qt.WindowType.Popup)
        self.main = main
        self.setObjectName("Palette")
        self.setFixedSize(640, 460)
        t = tm().theme
        self.setStyleSheet(f"#Palette {{ background: {t.solid}; border: 1px solid rgba(255,255,255,45); "
                           f"border-radius: 12px; }}")
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("Busca herramientas, ajustes, música, vídeos, archivos…"))
        self.edit.addAction(tm().icon("search", 16), QLineEdit.ActionPosition.LeadingPosition)
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(lambda _t: self._debounce.start())
        self.edit.returnPressed.connect(self._activate_current)
        self.group = QButtonGroup(self)
        chips = h_layout(spacing=4)
        self.filter = "all"
        for key, text in FILTERS:
            b = QPushButton(tr(text))
            b.setCheckable(True)
            b.setChecked(key == "all")
            b.setProperty("kind", "flat")
            b.clicked.connect(lambda _c=False, k=key: self._set_filter(k))
            self.group.addButton(b)
            chips.addWidget(b)
        chips.addStretch(1)
        self.list = QListWidget()
        self.list.setIconSize(QSize(18, 18))
        self.list.itemActivated.connect(self._activate)
        self.status = label("", "caption")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 10)
        lay.setSpacing(8)
        lay.addWidget(self.edit)
        lay.addLayout(chips)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.status)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(140)
        self._debounce.timeout.connect(self.refresh)
        self._gen = 0
        self._stop = threading.Event()
        self.files_found.connect(self._files_ready)

    # ------------------------------------------------------------------ apertura
    def popup(self):
        g = self.main.geometry()
        self.move(g.x() + (g.width() - self.width()) // 2, g.y() + 70)
        self.show()
        self.edit.setFocus()
        self.edit.selectAll()
        self.refresh()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.list.currentRow() + (1 if e.key() == Qt.Key.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
        else:
            super().keyPressEvent(e)

    def _set_filter(self, key: str):
        self.filter = key
        self.refresh()

    # ------------------------------------------------------------------ resultados
    def _roots(self) -> list[str]:
        roots = list(self.main.settings.get("library_folders") or [])
        try:
            roots += [d["path"] for d in self.main.db.library_folders()]
        except Exception:  # noqa: BLE001 - base de datos antigua sin tabla de carpetas
            pass
        return [r for r in dict.fromkeys(roots) if os.path.isdir(r)]

    def results(self, query: str) -> list[Result]:
        q = fold(query.strip())
        words = q.split()
        out: list[Result] = []

        def ok(text: str) -> bool:
            f = fold(text)
            return all(w in f for w in words)

        want = self.filter
        if want in ("all", "tool"):
            out += [r for r in tools_index() if not words or ok(r.title + " " + r.subtitle)]
        if want in ("all", "setting"):
            out += [r for r, idx in settings_index(self.main) if not words or all(w in idx for w in words)]
        if words and want in ("all", "library"):
            for row in self.main.db.query_media(search=query.strip(), limit=40):
                kind = row["kind"]
                sub = " · ".join(x for x in (row["artist"], row["album"]) if x) or row["path"]
                out.append(Result("library", row["title"] or row["name"], sub, "music" if kind == "audio" else "video",
                                  ("open", row["path"])))
        if want in ("all", "recent"):
            for row in self.main.db.recents(40):
                p = row["path"]
                if (not words or ok(Path(p).name)) and os.path.exists(p):
                    out.append(Result("recent", Path(p).name, p, "clock", ("open", p)))
        if want in ("all", "task"):
            from aero.core import activity as act

            for a in act.activities().history[:60]:
                if not words or ok(a.name):
                    out.append(Result("task", a.name, f"{tr(act.KIND_LABELS.get(a.kind, ''))} · "
                                                      f"{act.STATE_LABELS.get(a.state, '')}", "tasks",
                                      ("reveal", a.result) if a.result else ("tasks", "")))
        return out

    def refresh(self):
        query = self.edit.text()
        self.list.clear()
        for r in self.results(query):
            self._add(r)
        self._gen += 1
        self._stop.set()
        self._stop = threading.Event()
        roots = self._roots()
        if query.strip() and self.filter in ("all", "file") and len(query.strip()) >= 2 and roots:
            self.status.setText(tr("Buscando en {v0} carpetas…", v0=len(roots)))
            gen, stop = self._gen, self._stop
            signal = self.files_found

            def work():
                signal.emit(gen, search_files(roots, query, stop))

            threading.Thread(target=work, name="aero-search", daemon=True).start()
        else:
            self.status.setText("" if roots else tr("Para buscar archivos, añade carpetas en Biblioteca o Archivos"))
        if self.list.count():
            self.list.setCurrentRow(0)

    def _files_ready(self, gen: int, paths: list):
        if gen != self._gen:
            return
        from aero.core.filetypes import by_extension

        for p in paths:
            self._add(Result("file", Path(p).name, str(Path(p).parent),
                             "cat:" + by_extension(p, os.path.isdir(p)), ("open", p)))
        self.status.setText(f"{len(paths)} archivos" + (tr(" (se muestran los primeros)") if len(paths) >= MAX_FILES else ""))
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)

    def _add(self, r: Result):
        labels = dict(FILTERS)
        title, sub_ = tr(r.title), tr(r.subtitle) if r.kind in ("tool", "setting") else r.subtitle
        if r.icon.startswith("cat:"):
            # Archivos: icono de categoría de AERO, el mismo que en «Archivos»
            from aero.ui.file_icons import pixmap as cat_pixmap

            ic = QIcon(cat_pixmap(r.icon[4:], 18, self.devicePixelRatioF(), tm().theme.dark))
        else:
            ic = tm().icon(r.icon, 18)
        it = QListWidgetItem(ic, f"{title}\n{sub_}" if sub_ else title)
        it.setToolTip(f"{labels.get(r.kind, '')}: {r.subtitle}")
        it.setData(Qt.ItemDataRole.UserRole, r.action)
        self.list.addItem(it)

    def _activate_current(self):
        it = self.list.currentItem()
        if it is not None:
            self._activate(it)

    def _activate(self, it: QListWidgetItem):
        kind, arg = it.data(Qt.ItemDataRole.UserRole)
        m = self.main
        self.hide()
        if kind == "page":
            m.navigate(arg)
        elif kind == "tool":
            m.run_tool(arg)
        elif kind == "open_dialog":
            m.open_dialog()
        elif kind == "setting":
            m.navigate("settings")
            m.page("settings").open_category(arg)
        elif kind == "open":
            if os.path.isfile(arg):
                m.open_paths([arg])
            else:
                m.page("files").browse(arg)
                m.navigate("files")
        elif kind == "reveal":
            from aero.core import tools

            tools.reveal_in_explorer(arg)
        elif kind == "downloads":
            from aero.torrent.ui import show_downloads

            show_downloads()
        elif kind == "tasks":
            m.tasks_btn.show_popup()
