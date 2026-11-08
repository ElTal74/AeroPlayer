"""Interfaz de BitTorrent: diálogo al abrir un .torrent y ventana de descargas.

Reglas (también en docs/TORRENTS.md):
* Abrir un .torrent solo lee sus metadatos. La descarga empieza únicamente al pulsar «Descargar», después de ver
  los archivos, elegirlos y elegir la carpeta de destino.
* Lo descargado nunca se abre ni se ejecuta; al terminar solo se ofrece abrir la carpeta.
* Con BitTorrent desactivado en Ajustes no se crea el motor (ni hilo ni conexiones).
* Al cerrar AERO Player las descargas se detienen; no sigue nada en segundo plano.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from aero.core.formats import human_size, human_time
from aero.i18n import tr
from aero.torrent import metainfo
from aero.ui.glass import h_layout, label
from aero.ui.glasswindow import TrDialog

LEGAL = ("La descarga empieza solo cuando pulses «Descargar». Mientras dure, tu dirección IP es visible para los "
         "demás participantes. Descarga solo contenido que tengas derecho a obtener. AERO Player no abre ni ejecuta "
         "nada de lo descargado.")


_settings = None


def bind_settings(settings) -> None:
    """Lo llama el controlador. Al desactivar BitTorrent se detienen las descargas y el motor."""
    global _settings
    _settings = settings

    def changed(key):
        if key == "torrent_enabled" and not settings.get("torrent_enabled") and TorrentManager._inst is not None:
            TorrentManager._inst.stop_all()

    settings.changed.connect(changed)


def enabled() -> bool:
    return True if _settings is None else bool(_settings.get("torrent_enabled"))


def default_folder() -> str:
    saved = _settings.get("torrent_folder") if _settings is not None else ""
    if saved and os.path.isdir(saved):
        return saved
    d = Path.home() / "Downloads"
    return str(d if d.is_dir() else Path.home())


# --------------------------------------------------------------------------- coordinador
class TorrentManager(QObject):
    """Lleva las descargas en la interfaz: las registra en el centro de tareas y refresca su avance."""

    changed = Signal()
    _inst: "TorrentManager | None" = None

    def __init__(self):
        super().__init__()
        self.items: list[dict] = []          # {dl, aid, path, last}
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        self.window: DownloadsWindow | None = None

    @classmethod
    def instance(cls) -> "TorrentManager":
        if cls._inst is None:
            cls._inst = TorrentManager()
        return cls._inst

    def find(self, t: metainfo.Torrent, dest: str):
        dest = os.path.abspath(dest)
        for it in self.items:
            d = it["dl"]
            if d.t.info_hash == t.info_hash and d.dest == dest and d.state not in ("done", "cancelled", "error"):
                return it
        return None

    def add(self, t: metainfo.Torrent, dest: str, selected: set[int]):
        from aero.core.activity import activities
        from aero.torrent import get_engine

        it = self.find(t, dest)
        if it is not None:
            return it["dl"]
        dl = get_engine().add(t, dest, selected)
        it = {"dl": dl, "aid": "", "last": ""}
        it["aid"] = activities().start(t.name, "torrent", cancel=lambda: self.cancel(dl))
        self.items.append(it)
        self.timer.start()
        self.changed.emit()
        return dl

    def _item(self, dl):
        return next((it for it in self.items if it["dl"] is dl), None)

    def pause(self, dl):
        dl.pause()
        QTimer.singleShot(300, self._tick)

    def resume(self, dl):
        from aero.core.activity import activities

        it = self._item(dl)
        if it is not None and not it["aid"]:
            it["aid"] = activities().start(dl.t.name, "torrent", cancel=lambda: self.cancel(dl))
        dl.start()
        self.timer.start()

    def cancel(self, dl):
        dl.cancel(remove_partial=True)
        QTimer.singleShot(400, self._tick)

    def remove(self, dl):
        it = self._item(dl)
        if it is not None and dl.state in ("done", "cancelled", "error", "paused"):
            if dl.state == "paused":
                self.cancel(dl)
            self.items.remove(it)
            self.changed.emit()

    def active(self) -> int:
        return sum(1 for it in self.items if it["dl"].state in ("checking", "connecting", "downloading"))

    def _tick(self):
        from aero.core.activity import CANCELLED, DONE, ERROR, activities

        for it in self.items:
            d = it["dl"]
            s = d.snapshot()
            if not it["aid"]:
                continue
            if s.state in ("done", "error", "cancelled"):
                state = {"done": DONE, "error": ERROR, "cancelled": CANCELLED}[s.state]
                activities().finish(it["aid"], state, result=d.storage.final[min(d.selected)]
                                    if s.state == "done" else "", error=message_text(s.message) if s.state == "error" else "")
                it["aid"] = ""
            else:
                activities().update(it["aid"], s.progress, status_text(s))
        if not self.active():
            self.timer.stop()
        self.changed.emit()

    def stop_all(self):
        """Pausa todo (sin borrar nada) y apaga el motor: no queda ningún hilo ni conexión."""
        from aero import torrent

        torrent.shutdown()
        self._tick()

    def shutdown(self):
        self.timer.stop()
        from aero import torrent

        torrent.shutdown()


def status_text(s) -> str:
    st = tr(STATE_TEXT.get(s.state, s.state))
    if s.state == "downloading":
        extra = f"{human_size(s.rate)}/s"
        if s.eta:
            extra += " · " + tr("quedan {t}", t=human_time(s.eta))
        return f"{st} · {extra}"
    if s.state == "connecting":
        return f"{st} · " + tr("{n} conocidos", n=s.known)
    return st


# Avisos del motor (que no conoce el idioma de la interfaz)
_MESSAGES = ("Este torrent no tiene trackers: sin DHT no se pueden encontrar pares.",
             "El tracker no conoce pares para este torrent ahora mismo.")
_TRACKER_FAIL = "No se pudo contactar con el tracker: "


def message_text(m: str) -> str:
    if m in _MESSAGES:
        return tr(m)
    if m.startswith(_TRACKER_FAIL):
        return tr("No se pudo contactar con el tracker: {e}", e=m[len(_TRACKER_FAIL):])
    return m


STATE_TEXT = {"checking": "Comprobando", "connecting": "Buscando pares", "downloading": "Descargando",
              "paused": "En pausa", "done": "Completado", "error": "Error", "cancelled": "Cancelado"}


# --------------------------------------------------------------------------- abrir un .torrent
def open_torrent(path: str, parent=None) -> None:
    try:
        t = metainfo.load(path)
    except (metainfo.TorrentError, OSError) as e:
        QMessageBox.warning(parent, tr("Archivo .torrent"), tr("No se pudo leer «{name}»: {e}",
                                                                 name=Path(path).name, e=e))
        return
    dlg = TorrentDialog(t, path, parent)
    if dlg.exec() == TorrentDialog.DialogCode.Accepted:
        dest = dlg.dest.text().strip()
        if _settings is not None:
            _settings.set("torrent_folder", dest)
        TorrentManager.instance().add(t, dest, dlg.selected())
        show_downloads()


def show_downloads():
    m = TorrentManager.instance()
    if m.window is None:
        m.window = DownloadsWindow(m)
    m.window.show()
    m.window.raise_()
    m.window.activateWindow()
    return m.window


class TorrentDialog(TrDialog):
    """Muestra qué contiene el torrent antes de nada. Descargar exige elegir archivos y carpeta."""

    def __init__(self, t: metainfo.Torrent, path: str = "", parent=None):
        super().__init__(parent)
        self.t = t
        self.setWindowTitle(tr("Torrent: {name}", name=t.name))
        title = label(t.name, "title", wrap=True)
        facts = [ntr_files(len(t.files)), human_size(t.total),
                 tr("{n} piezas de {size}", n=len(t.pieces), size=human_size(t.piece_length))]
        if t.private:
            facts.append(tr("privado"))
        info = label(" · ".join(facts), "muted", wrap=True)
        extra = []
        if t.created_by:
            extra.append(tr("Creado con {app}", app=t.created_by))
        if t.created:
            extra.append(t.created.strftime("%d/%m/%Y %H:%M"))
        if t.trackers:
            extra.append(tr("{n} trackers", n=len(t.trackers)) if len(t.trackers) != 1 else tr("1 tracker"))
        meta = label(" · ".join(extra), "caption", wrap=True)
        meta.setVisible(bool(extra))
        comment = label(t.comment[:500], "caption", wrap=True)
        comment.setVisible(bool(t.comment))
        comment.setTextFormat(Qt.TextFormat.PlainText)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Nombre"), tr("Tamaño")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setUniformRowHeights(True)
        self._leaves: list[tuple[QTreeWidgetItem, int]] = []
        self._fill()
        self.tree.itemChanged.connect(lambda *_: self._recount_later())
        all_btn = QPushButton(tr("Todo"))
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = QPushButton(tr("Nada"))
        none_btn.clicked.connect(lambda: self._set_all(False))
        self.count = label("", "muted")

        self.dest = QLineEdit(default_folder())
        browse = QPushButton(tr("Examinar…"))
        browse.clicked.connect(self._browse)
        self.dest.textChanged.connect(lambda _t: self._recount_later())

        warn = []
        if not t.trackers:
            warn.append(tr("Este torrent no tiene trackers. AERO Player no usa DHT, así que no podrá encontrar "
                           "pares."))
        risky = [f.path for f in t.files if os.path.splitext(f.path)[1].lower() in RISKY]
        if risky:
            warn.append(tr("Contiene programas o scripts ({n}). No se ejecutarán; ábrelos solo si confías en el "
                           "origen.", n=len(risky)))
        self.warn = label("\n".join(warn), "caption", wrap=True)
        self.warn.setVisible(bool(warn))
        self.legal = label(LEGAL, "caption", wrap=True)
        self.problem = label("", "caption", wrap=True)

        self.ok = QPushButton(tr("Descargar"))
        self.ok.setProperty("kind", "primary")
        self.ok.clicked.connect(self.accept)
        cancel = QPushButton(tr("Cancelar"))
        cancel.clicked.connect(self.reject)
        self.ok.setDefault(False)
        cancel.setDefault(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(8)
        for w in (title, info, meta, comment):
            lay.addWidget(w)
        lay.addWidget(self.tree, 1)
        lay.addLayout(h_layout(all_btn, none_btn, None, self.count, spacing=6))
        row = QHBoxLayout()
        row.addWidget(label(tr("Guardar en")))
        row.addWidget(self.dest, 1)
        row.addWidget(browse)
        lay.addLayout(row)
        lay.addWidget(self.warn)
        lay.addWidget(self.legal)
        lay.addWidget(self.problem)
        lay.addLayout(h_layout(None, cancel, self.ok))
        self.resize(640, 560)
        self._recount()

    def _fill(self):
        from aero.ui.file_icons import icon_for

        self.tree.setUpdatesEnabled(False)
        folders: dict[str, QTreeWidgetItem] = {}
        flags = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        root_parent = self.tree.invisibleRootItem()
        for i, f in enumerate(self.t.files):
            parts = f.path.split("/")
            parent = root_parent
            for k in range(len(parts) - 1):
                key = "/".join(parts[:k + 1])
                node = folders.get(key)
                if node is None:
                    node = QTreeWidgetItem(parent, [parts[k], ""])
                    node.setFlags(flags | Qt.ItemFlag.ItemIsAutoTristate)
                    node.setCheckState(0, Qt.CheckState.Checked)
                    node.setIcon(0, icon_for(key, 18, is_dir=True))
                    folders[key] = node
                parent = node
            leaf = QTreeWidgetItem(parent, [parts[-1], human_size(f.length)])
            leaf.setFlags(flags)
            leaf.setCheckState(0, Qt.CheckState.Checked)
            leaf.setIcon(0, icon_for(parts[-1], 18, is_dir=False))
            leaf.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._leaves.append((leaf, i))
        if len(folders) < 50:
            self.tree.expandAll()
        self.tree.setUpdatesEnabled(True)

    def _set_all(self, on: bool):
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        self.tree.blockSignals(True)
        for k in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(k).setCheckState(0, state)
        for leaf, _i in self._leaves:
            leaf.setCheckState(0, state)
        self.tree.blockSignals(False)
        self._recount()

    def selected(self) -> set[int]:
        return {i for leaf, i in self._leaves if leaf.checkState(0) == Qt.CheckState.Checked}

    def _recount_later(self):
        if not getattr(self, "_pending", False):
            self._pending = True
            QTimer.singleShot(0, self._recount)

    def _recount(self):
        self._pending = False
        sel = self.selected()
        size = sum(self.t.files[i].length for i in sel)
        self.count.setText(tr("{n} de {total} archivos · {size}", n=len(sel), total=len(self.t.files),
                              size=human_size(size)))
        problem = ""
        dest = self.dest.text().strip()
        if not enabled():
            problem = tr("BitTorrent está desactivado en Ajustes › Descargas. Puedes ver el contenido, pero no "
                         "descargarlo.")
        elif not sel:
            problem = tr("Elige al menos un archivo.")
        elif not dest or not os.path.isabs(dest):
            problem = tr("Elige una carpeta de destino.")
        else:
            probe = dest
            while probe and not os.path.isdir(probe):
                parent = os.path.dirname(probe)
                if parent == probe:
                    break
                probe = parent
            try:
                free = shutil.disk_usage(probe).free
                if free < size:
                    problem = tr("No hay espacio suficiente: hacen falta {need} y quedan {free}.",
                                 need=human_size(size), free=human_size(free))
            except OSError:
                problem = tr("La carpeta de destino no está disponible.")
        self.problem.setText(problem)
        self.problem.setVisible(bool(problem))
        self.ok.setEnabled(not problem)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("Carpeta de destino"), self.dest.text())
        if d:
            self.dest.setText(os.path.normpath(d))


RISKY = {".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".js", ".jse", ".wsf", ".lnk", ".pif",
         ".reg", ".hta", ".cpl", ".jar"}


def ntr_files(n: int) -> str:
    from aero.i18n import ntr

    return ntr("{n} archivo", "{n} archivos", n)


# --------------------------------------------------------------------------- ventana de descargas
class DownloadsWindow(TrDialog):
    COLS = ("Nombre", "Estado", "Progreso", "Tamaño", "Velocidad", "Pares")

    def __init__(self, manager: TorrentManager):
        super().__init__(None, Qt.WindowType.Window)
        self.m = manager
        self.setWindowTitle(tr("Descargas BitTorrent"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr(c) for c in self.COLS])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, len(self.COLS)):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setColumnWidth(2, 140)
        self.tree.itemSelectionChanged.connect(self._buttons)
        self.empty = label(tr("No hay descargas. Abre un archivo .torrent para empezar."), "muted", wrap=True)
        self.b_pause = QPushButton(tr("Pausar"))
        self.b_resume = QPushButton(tr("Reanudar"))
        self.b_cancel = QPushButton(tr("Cancelar descarga"))
        self.b_folder = QPushButton(tr("Abrir carpeta"))
        self.b_remove = QPushButton(tr("Quitar de la lista"))
        self.b_pause.clicked.connect(lambda: self._each(self.m.pause))
        self.b_resume.clicked.connect(lambda: self._each(self.m.resume))
        self.b_cancel.clicked.connect(self._cancel)
        self.b_folder.clicked.connect(self._folder)
        self.b_remove.clicked.connect(lambda: self._each(self.m.remove))
        self.info = label("", "caption", wrap=True)
        self.info.setText(tr("Sin DHT ni enlaces magnet; no se abre ningún puerto. Al cerrar AERO Player las "
                             "descargas se detienen: vuelve a abrir el .torrent con la misma carpeta para continuar."))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.empty)
        lay.addLayout(h_layout(self.b_pause, self.b_resume, self.b_cancel, None, self.b_folder, self.b_remove,
                               spacing=6))
        lay.addWidget(self.info)
        self.resize(820, 380)
        self._rows: dict[int, QTreeWidgetItem] = {}
        manager.changed.connect(self.refresh)
        self.refresh()

    def _selected(self):
        ids = {id(it) for it in self.tree.selectedItems()}
        return [it["dl"] for it in self.m.items if id(self._rows.get(id(it["dl"]))) in ids]

    def _each(self, fn):
        for dl in self._selected():
            fn(dl)
        self.refresh()

    def _cancel(self):
        sel = [d for d in self._selected() if d.state not in ("done", "cancelled")]
        if not sel:
            return
        r = QMessageBox.question(self, tr("Cancelar descarga"),
                                 tr("¿Cancelar la descarga? Se borrarán los archivos incompletos (.aeropart) que "
                                    "haya creado; lo ya completado se queda."))
        if r == QMessageBox.StandardButton.Yes:
            for d in sel:
                self.m.cancel(d)

    def _folder(self):
        from aero.core import tools

        for dl in self._selected()[:1]:
            root = dl.dest if dl.t.single else os.path.join(dl.dest, dl.t.name)
            tools.open_with_default(root if os.path.isdir(root) else dl.dest)

    def _buttons(self):
        sel = self._selected()
        st = {d.state for d in sel}
        self.b_pause.setEnabled(bool(st & {"checking", "connecting", "downloading"}))
        self.b_resume.setEnabled(bool(st & {"paused", "error"}))
        self.b_cancel.setEnabled(bool(st - {"done", "cancelled"}))
        self.b_folder.setEnabled(bool(sel))
        self.b_remove.setEnabled(bool(st & {"done", "cancelled", "error", "paused"}))

    def refresh(self):
        alive = set()
        for it in self.m.items:
            d = it["dl"]
            alive.add(id(d))
            row = self._rows.get(id(d))
            if row is None:
                row = QTreeWidgetItem(self.tree, [d.t.name] + [""] * (len(self.COLS) - 1))
                from aero.ui.file_icons import icon_for

                row.setIcon(0, icon_for(d.t.name + ".torrent", 18, is_dir=False))
                bar = QProgressBar()
                bar.setRange(0, 1000)
                bar.setTextVisible(True)
                self.tree.setItemWidget(row, 2, bar)
                self._rows[id(d)] = row
            s = d.snapshot()
            msg = message_text(s.message)
            row.setText(1, tr(STATE_TEXT.get(s.state, s.state)) + (f" — {msg}" if msg else ""))
            row.setToolTip(1, msg)
            bar = self.tree.itemWidget(row, 2)
            bar.setValue(int(s.progress * 1000))
            bar.setFormat(f"{s.progress * 100:.1f} %")
            row.setText(3, f"{human_size(s.done)} / {human_size(s.total)}")
            row.setText(4, f"{human_size(s.rate)}/s" if s.state == "downloading" else "")
            row.setText(5, f"{s.peers} ({s.known})" if s.state in ("connecting", "downloading") else "")
        for key in [k for k in self._rows if k not in alive]:
            row = self._rows.pop(key)
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(row))
        self.empty.setVisible(not self.m.items)
        self._buttons()


__all__ = ["TorrentDialog", "DownloadsWindow", "TorrentManager", "open_torrent", "show_downloads"]
