"""Paneles «Transiciones» y «Efectos» del editor de vídeo: miniaturas reales y arrastrar y soltar.

Las miniaturas de los efectos y las animaciones de las transiciones se generan con el mismo motor de la
exportación (FFmpeg) sobre una imagen de muestra, en segundo plano y una sola vez (caché en disco). Así lo que
se ve en la biblioteca es exactamente lo que se aplicará.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QIcon, QImage, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QComboBox, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from aero.editors.video import effects as fx
from aero.i18n import tr

MIME_FX = "application/x-aero-effect"
MIME_TR = "application/x-aero-transition"
THUMB = QSize(112, 63)


def _cache() -> Path:
    from aero.core.paths import cache_dir

    d = cache_dir() / "fx"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sample_image(which: str = "a") -> str:
    """Imagen de muestra dibujada por código (cielo, sol, colinas) para las miniaturas."""
    path = _cache() / f"sample_{which}.png"
    if path.exists():
        return str(path)
    img = QImage(320, 180, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    sky = QLinearGradient(0, 0, 0, 180)
    if which == "a":
        sky.setColorAt(0, QColor("#2f7dd6"))
        sky.setColorAt(1, QColor("#ffd59a"))
        hills, sun = QColor("#2f8a4a"), QColor("#fff2b3")
    else:
        sky.setColorAt(0, QColor("#5b2a86"))
        sky.setColorAt(1, QColor("#ff8a5c"))
        hills, sun = QColor("#1f3d5a"), QColor("#ffe0a3")
    p.fillRect(img.rect(), sky)
    g = QRadialGradient(220, 70, 40)
    g.setColorAt(0, sun)
    g.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(img.rect(), g)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(hills)
    p.drawEllipse(-60, 120, 260, 140)
    p.setBrush(hills.darker(120))
    p.drawEllipse(140, 130, 260, 120)
    p.end()
    img.save(str(path))
    return str(path)


def _ffmpeg() -> str | None:
    from aero.core import tools

    return tools.find_tool("ffmpeg")


def effect_thumbnail(effect_id: str) -> str | None:
    """PNG con el efecto aplicado a la muestra (hilo de trabajo)."""
    ff = _ffmpeg()
    if ff is None:
        return None
    chain = fx.chain_for([fx.new_instance(effect_id)])
    key = hashlib.md5(",".join(chain).encode()).hexdigest()[:10]
    out = _cache() / f"fx_{effect_id}_{key}.png"
    if out.exists():
        return str(out)
    vf = ",".join(chain + [f"scale={THUMB.width() * 2}:{THUMB.height() * 2}"])
    src = sample_image("a")
    # Los efectos temporales necesitan algunos fotogramas: se genera un vídeo corto de la imagen
    r = subprocess.run([ff, "-v", "error", "-y", "-loop", "1", "-t", "0.4", "-r", "10", "-i", src, "-vf", vf,
                        "-frames:v", "1", str(out)], capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=0x08000000 if os.name == "nt" else 0, timeout=60)
    return str(out) if r.returncode == 0 and out.exists() else None


def transition_frames(tid: str, n: int = 12) -> list[str]:
    """Fotogramas de la transición entre dos muestras, generados con el motor de exportación."""
    from aero.editors.video.export import build_command
    from aero.editors.video.project import Clip, Project, Track

    ff = _ffmpeg()
    if ff is None:
        return []
    folder = _cache() / f"tr_{tid}"
    frames = sorted(folder.glob("f*.png")) if folder.exists() else []
    if len(frames) >= n:
        return [str(f) for f in frames]
    folder.mkdir(exist_ok=True)
    p = Project(THUMB.width() * 2, THUMB.height() * 2, 10.0)
    p.tracks = [Track("video", "V1"), Track("audio", "A1")]
    a = Clip(src=sample_image("a"), kind="image", out_s=1.0, has_audio=False)
    b = Clip(src=sample_image("b"), kind="image", out_s=1.6, has_audio=False, transition=tid, transition_d=0.8)
    p.add_clip(p.tracks[0], a)
    p.add_clip(p.tracks[0], b)
    tmp = folder / "clip.mp4"
    args, _t, temps = build_command(p, str(tmp), "mp4", "h264", 30, 64, start=0.6, end=2.0, fast=True, ffmpeg=ff)
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=0x08000000 if os.name == "nt" else 0, timeout=120)
    for t in temps:
        try:
            os.remove(t)
        except OSError:
            pass
    if r.returncode != 0:
        return []
    subprocess.run([ff, "-v", "error", "-y", "-i", str(tmp), "-vf", f"fps={n / 1.4:.3f}", str(folder / "f%02d.png")],
                   capture_output=True, stdin=subprocess.DEVNULL,
                   creationflags=0x08000000 if os.name == "nt" else 0, timeout=60)
    tmp.unlink(missing_ok=True)
    return [str(f) for f in sorted(folder.glob("f*.png"))]


def _middle(frames: list[str]) -> str | None:
    return frames[len(frames) // 2] if frames else None


class _DragList(QListWidget):
    def __init__(self, mime: str):
        super().__init__()
        self.mime = mime
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(THUMB)
        self.setGridSize(QSize(THUMB.width() + 16, THUMB.height() + 40))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setWordWrap(True)
        self.setDragEnabled(True)
        self.setSpacing(4)

    def startDrag(self, actions):
        it = self.currentItem()
        if it is None:
            return
        md = QMimeData()
        md.setData(self.mime, it.data(Qt.ItemDataRole.UserRole).encode())
        d = QDrag(self)
        d.setMimeData(md)
        d.setPixmap(it.icon().pixmap(THUMB))
        d.exec(Qt.DropAction.CopyAction)


class FxLibrary(QWidget):
    """Una lista (transiciones o efectos) con búsqueda, categoría y aplicación por doble clic o arrastre."""
    apply = Signal(str)

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Buscar"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.cat = QComboBox()
        self.cat.addItem(tr("Todas las categorías"), "")
        if kind == "effects":
            for c in fx.CATEGORIES:
                if any(e.category == c for e in fx.EFFECTS.values()):
                    self.cat.addItem(c, c)
        self.cat.currentIndexChanged.connect(self._filter)
        self.cat.setVisible(kind == "effects")
        self.list = _DragList(MIME_FX if kind == "effects" else MIME_TR)
        self.list.itemDoubleClicked.connect(lambda it: self.apply.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.list.currentItemChanged.connect(self._preview)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.search)
        lay.addWidget(self.cat)
        lay.addWidget(self.list, 1)
        self._frames: list[QPixmap] = []
        self._frame_i = 0
        self._anim_item: QListWidgetItem | None = None
        self._anim = QTimer(self)
        self._anim.setInterval(110)
        self._anim.timeout.connect(self._step)
        source = fx.EFFECTS if kind == "effects" else fx.TRANSITIONS
        from aero.ui.glass import tm

        icon = tm().icon("effects" if kind == "effects" else "transition", 28)
        for key, item in source.items():
            it = QListWidgetItem(icon, tr(item.name))
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setData(Qt.ItemDataRole.UserRole + 1, getattr(item, "category", ""))
            it.setToolTip(f"{tr(item.name)}\n{tr(item.desc)}\n" + tr("Arrástralo a la línea de tiempo o haz doble clic"))
            it.setSizeHint(QSize(THUMB.width() + 12, THUMB.height() + 36))
            self.list.addItem(it)
        self._thumbs_started = False

    def showEvent(self, e):
        super().showEvent(e)
        if not self._thumbs_started:
            self._thumbs_started = True
            self._load_thumbs()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._anim.stop()

    def _load_thumbs(self):
        from aero.core.tasks import tasks

        for i in range(self.list.count()):
            it = self.list.item(i)
            key = it.data(Qt.ItemDataRole.UserRole)
            job = (lambda k=key: effect_thumbnail(k)) if self.kind == "effects" else \
                (lambda k=key: _middle(transition_frames(k)))
            tasks().submit(job, "background", lambda path, row=i: self._set_icon(row, path), None, self)

    def _set_icon(self, row: int, path: str | None):
        it = self.list.item(row)
        if it is not None and path:
            it.setIcon(QIcon(QPixmap(path)))

    def _filter(self, *_):
        q = self.search.text().strip().lower()
        cat = self.cat.currentData()
        for i in range(self.list.count()):
            it = self.list.item(i)
            ok = (not q or q in it.text().lower() or q in it.toolTip().lower()) and \
                (not cat or it.data(Qt.ItemDataRole.UserRole + 1) == cat)
            it.setHidden(not ok)

    def _preview(self, cur, _prev):
        """Al elegir una transición se reproduce su animación en la propia miniatura."""
        self._anim.stop()
        if self._anim_item is not None and self._frames:
            self._anim_item.setIcon(QIcon(self._frames[len(self._frames) // 2]))
        self._frames, self._anim_item = [], None
        if cur is None or self.kind != "transitions":
            return
        from aero.core.tasks import tasks

        key = cur.data(Qt.ItemDataRole.UserRole)
        tasks().submit(lambda k=key: transition_frames(k), "background",
                       lambda paths, it=cur: self._start_anim(it, paths), None, self)

    def _start_anim(self, item, paths):
        if not paths or self.list.currentItem() is not item:
            return
        self._frames = [QPixmap(p) for p in paths]
        self._anim_item, self._frame_i = item, 0
        self._anim.start()

    def _step(self):
        if not self._frames or self._anim_item is None:
            self._anim.stop()
            return
        self._anim_item.setIcon(QIcon(self._frames[self._frame_i % len(self._frames)]))
        self._frame_i += 1
