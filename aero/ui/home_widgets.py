"""Escritorio de widgets de Inicio: tarjetas con la información del equipo, personalizables.

* El usuario puede añadir, quitar, ocultar, cambiar de tamaño (pequeño / ancho), elegir qué datos se ven
  y reordenar arrastrando. Todo se guarda en los ajustes (`home_widgets`).
* Los datos vienen de `aero.core.sysinfo` en un hilo: los fijos una vez; los vivos cada 2 s solo mientras
  Inicio está a la vista (5 s con la ventana en segundo plano; nada si está minimizada u oculta).
* Lo que Windows no expone (temperaturas, en la mayoría de equipos) se muestra como «No disponible».
"""

from __future__ import annotations

import copy
import weakref
from collections import deque

from PySide6.QtCore import QMimeData, QObject, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QScrollArea, QToolButton, QWidget

from aero.core.formats import human_size
from aero.ui import icons
from aero.ui.glass import tm
from aero.i18n import ntr, tr

MIME = "application/x-aero-widget"
CELL_W, CELL_H, GAP = 236, 168, 12
HISTORY = 40

# tipo → (título, icono, campos opcionales {clave: texto})
TYPES: dict[str, tuple[str, str, dict[str, str]]] = {
    "cpu": ("Procesador", "speed", {"model": "Modelo", "cores": "Núcleos e hilos", "temp": "Temperatura",
                                    "graph": "Gráfico"}),
    "gpu": ("Tarjeta gráfica", "image", {"model": "Modelo", "vram": "Memoria de vídeo", "temp": "Temperatura",
                                         "graph": "Gráfico"}),
    "ram": ("Memoria RAM", "grid", {"free": "Disponible", "graph": "Gráfico"}),
    "storage": ("Almacenamiento", "folder", {"labels": "Nombre del disco"}),
    "display": ("Pantalla", "fullscreen", {"refresh": "Frecuencia", "count": "Pantallas conectadas"}),
    "os": ("Sistema", "aero", {"build": "Versión", "arch": "Arquitectura"}),
    "board": ("Placa base", "settings", {"bios": "BIOS"}),
    "mouse": ("Ratón", "select", {}),
    "keyboard": ("Teclado", "keyboard", {}),
    "battery": ("Batería", "speed", {"time": "Tiempo restante"}),
    "recent": ("Recientes", "clock", {}),
    "tasks": ("Tareas", "tasks", {}),
}

DEFAULT_LAYOUT = [
    {"type": "cpu", "size": "small"}, {"type": "gpu", "size": "small"}, {"type": "ram", "size": "small"},
    {"type": "storage", "size": "wide"}, {"type": "display", "size": "small"}, {"type": "os", "size": "small"},
    {"type": "board", "size": "small"}, {"type": "mouse", "size": "small"}, {"type": "keyboard", "size": "small"},
    {"type": "battery", "size": "small"}, {"type": "recent", "size": "small"}, {"type": "tasks", "size": "small"},
]


def default_layout(has_battery: bool) -> list[dict]:
    out = []
    for d in DEFAULT_LAYOUT:
        if d["type"] == "battery" and not has_battery:
            continue
        out.append({**d, "hidden": False, "fields": list(TYPES[d["type"]][2])})
    return out


def normalize(layout) -> list[dict] | None:
    if not isinstance(layout, list):
        return None
    out = []
    seen = set()
    for d in layout:
        if not isinstance(d, dict) or d.get("type") not in TYPES or d["type"] in seen:
            continue
        seen.add(d["type"])
        fields = [f for f in d.get("fields", list(TYPES[d["type"]][2])) if f in TYPES[d["type"]][2]]
        out.append({"type": d["type"], "size": "wide" if d.get("size") == "wide" else "small",
                    "hidden": bool(d.get("hidden")), "fields": fields})
    return out


# ---------------------------------------------------------------------------------------------- datos
class HardwareService(QObject):
    """Recoge los datos en segundo plano y avisa a las tarjetas. Una instancia para toda la aplicación."""
    static_ready = Signal()
    updated = Signal()
    _inst: "HardwareService | None" = None

    def __init__(self):
        super().__init__()
        self.static = None
        self.live = None
        self.disks: list = []
        self.cpu_temp = None
        self.cpu_hist: deque = deque(maxlen=HISTORY)
        self.gpu_hist: deque = deque(maxlen=HISTORY)
        self.ram_hist: deque = deque(maxlen=HISTORY)
        self._users: weakref.WeakSet = weakref.WeakSet()
        self._busy = False
        self._sampler = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._ticks = 0

    @classmethod
    def instance(cls) -> "HardwareService":
        if cls._inst is None:
            cls._inst = HardwareService()
        return cls._inst

    def subscribe(self, owner: QWidget, on: bool) -> None:
        (self._users.add if on else self._users.discard)(owner)
        if self._users and self.static is None and not self._busy:
            self._load_static()
        if self._users and not self._timer.isActive():
            self._timer.start(2000)
            QTimer.singleShot(150, self._tick)
        elif not self._users:
            self._timer.stop()


    def _load_static(self):
        from aero.core import sysinfo
        from aero.ui.async_util import run_async

        self._busy = True

        def job():
            info = sysinfo.static_info()
            return info, sysinfo.disks(), sysinfo.cpu_temperature()

        def done(res):
            self._busy = False
            self.static, self.disks, self.cpu_temp = res
            self.static_ready.emit()
            self.updated.emit()

        run_async(job, done, lambda _e: setattr(self, "_busy", False), self)

    def _tick(self):
        from aero.core import sysinfo
        from aero.ui.async_util import run_async

        from PySide6.QtWidgets import QApplication

        try:
            seen = [w for w in list(self._users) if w.isVisible() and not w.window().isMinimized()]
        except RuntimeError:
            seen = []
        if not seen:
            return  # minimizada u oculta: no se consulta nada
        # Con la aplicación en segundo plano basta con actualizar cada 5 s
        self._timer.setInterval(2000 if QApplication.activeWindow() is not None else 5000)
        if self._sampler is None:
            self._sampler = sysinfo.Sampler()
        sampler = self._sampler
        self._ticks += 1
        refresh_disks = self._ticks % 15 == 0

        def job():
            return sampler.sample(), (sysinfo.disks() if refresh_disks else None)

        def done(res):
            live, disks = res
            self.live = live
            if disks is not None:
                self.disks = disks
            if live.cpu is not None:
                self.cpu_hist.append(live.cpu)
            if live.gpu is not None:
                self.gpu_hist.append(live.gpu)
            if live.ram_total:
                self.ram_hist.append(100 * (1 - live.ram_free / live.ram_total))
            self.updated.emit()

        run_async(job, done, lambda _e: None, self)


# ---------------------------------------------------------------------------------------------- pintado
def _gb(n: int | None) -> str:
    return human_size(n) if n else "—"


def paint_ring(p: QPainter, rect: QRectF, value: float | None, color: str, text: str, sub: str = ""):
    t = tm().theme
    pen_w = max(6.0, rect.width() * 0.09)
    r = rect.adjusted(pen_w / 2, pen_w / 2, -pen_w / 2, -pen_w / 2)
    track = QColor(t.text)
    track.setAlphaF(0.12)
    p.setPen(QPen(track, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(r, 0, 360 * 16)
    if value is not None:
        c = QColor(color)
        if value > 85:
            c = QColor("#ff7a8a")
        p.setPen(QPen(c, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 90 * 16, -int(360 * 16 * max(0.0, min(100.0, value)) / 100))
    p.setPen(QColor(t.text))
    f = QFont(p.font())
    f.setPointSizeF(max(9.0, rect.width() * 0.17))
    f.setWeight(QFont.Weight.DemiBold)
    p.setFont(f)
    p.drawText(rect.adjusted(0, -6 if sub else 0, 0, -6 if sub else 0), Qt.AlignmentFlag.AlignCenter, text)
    if sub:
        f.setPointSizeF(max(7.0, rect.width() * 0.08))
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        c = QColor(t.text2)
        p.setPen(c)
        p.drawText(rect.adjusted(0, rect.height() * 0.32, 0, 0), Qt.AlignmentFlag.AlignCenter, sub)


def paint_spark(p: QPainter, rect: QRectF, values, color: str):
    vals = list(values)
    if len(vals) < 2:
        return
    path = QPainterPath()
    n = HISTORY - 1
    for i, v in enumerate(vals[-HISTORY:]):
        x = rect.left() + rect.width() * (i + HISTORY - len(vals)) / n
        y = rect.bottom() - rect.height() * max(0.0, min(100.0, v)) / 100
        path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
    c = QColor(color)
    p.setPen(QPen(c, 1.6))
    p.drawPath(path)
    fill = QPainterPath(path)
    fill.lineTo(rect.right(), rect.bottom())
    fill.lineTo(rect.left() + rect.width() * (HISTORY - len(vals)) / n, rect.bottom())
    fill.closeSubpath()
    c.setAlphaF(0.15)
    p.fillPath(fill, c)


def paint_bar(p: QPainter, rect: QRectF, frac: float, color: str):
    t = tm().theme
    track = QColor(t.text)
    track.setAlphaF(0.12)
    path = QPainterPath()
    path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    p.fillPath(path, track)
    w = rect.width() * max(0.0, min(1.0, frac))
    if w > 0:
        c = QColor("#ff7a8a" if frac > 0.9 else color)
        fp = QPainterPath()
        fp.addRoundedRect(QRectF(rect.left(), rect.top(), max(rect.height(), w), rect.height()),
                          rect.height() / 2, rect.height() / 2)
        p.fillPath(fp, c)


# ---------------------------------------------------------------------------------------------- tarjeta
class WidgetCard(QWidget):
    menu_requested = Signal(object, QPoint)

    def __init__(self, conf: dict, parent=None):
        super().__init__(parent)
        self.conf = conf
        self.svc = HardwareService.instance()
        # La tarjeta se dibuja en una imagen que solo se rehace cuando cambian sus datos o el tema: el fondo animado
        # pasa por detrás muchas veces por segundo y antes la redibujaba entera (textos, anillos, gráficas) cada vez.
        self._cache: QPixmap | None = None
        self._cache_key = None
        self.svc.updated.connect(self.invalidate)
        tm().changed.connect(self.invalidate)
        if conf["type"] == "tasks":
            from aero.core import activity as act

            act.activities().changed.connect(self.invalidate)
        self._press: QPoint | None = None
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.menu_requested.emit(self, self.mapToGlobal(pos)))
        self.setToolTip(tr("Arrastra para mover · clic derecho para opciones"))
        self.setAccessibleName(tr(TYPES[conf["type"]][0]))
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    @property
    def kind(self) -> str:
        return self.conf["type"]

    def has(self, field: str) -> bool:
        return field in self.conf.get("fields", [])

    # -- arrastrar para reordenar
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() < 8:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME, self.kind.encode())
        drag.setMimeData(mime)
        pm = self.grab()
        drag.setPixmap(pm)
        drag.setHotSpot(self._press)
        self._press = None
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        self._press = None

    # -- pintado
    def invalidate(self, *_a):
        self._cache = None
        self.update()

    def paintEvent(self, e):
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if self._cache is None or self._cache_key != key:
            pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            self._render(q)
            q.end()
            self._cache, self._cache_key = pm, key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._cache)
        p.end()

    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)

    def _render(self, p: QPainter):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = tm().theme
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        from aero.ui.corners import RADII

        path.addRoundedRect(r, RADII["card"], RADII["card"])
        bg = QColor(t.glass)
        bg.setAlphaF(0.07 if t.dark else 0.42)
        p.fillPath(path, bg)
        edge = QColor("#ffffff")
        edge.setAlphaF(0.16 if t.dark else 0.65)
        p.setPen(QPen(edge, 1))
        p.drawPath(path)
        title, icon, _f = TYPES[self.kind]
        p.drawPixmap(14, 12, icons.pixmap(icon, t.accent, 16))
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(t.text2))
        p.drawText(QRectF(36, 9, r.width() - 46, 22), Qt.AlignmentFlag.AlignVCenter, tr(title))
        body = QRectF(14, 38, r.width() - 28, r.height() - 50)
        getattr(self, f"_paint_{self.kind}")(p, body)

    def _lines(self, p: QPainter, rect: QRectF, lines: list[tuple[str, str]], big: bool = False):
        """Pares (texto, rol) uno debajo de otro; rol: big | text | muted."""
        t = tm().theme
        y = rect.top()
        for text, role in lines:
            f = QFont(self.font())
            if role == "big":
                f.setPointSizeF(16)
                f.setWeight(QFont.Weight.DemiBold)
                h = 30
            else:
                f.setPointSizeF(9)
                h = 18
            p.setFont(f)
            p.setPen(QColor(t.text if role != "muted" else t.text2))
            fm = p.fontMetrics()
            p.drawText(QRectF(rect.left(), y, rect.width(), h), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width())))
            y += h
            if y > rect.bottom():
                break

    def _gauge_card(self, p, rect, value, ring_text, sub, lines, hist):
        t = tm().theme
        size = min(rect.height() - (24 if hist is not None else 0), 92.0)
        ring = QRectF(rect.left(), rect.top(), size, size)
        paint_ring(p, ring, value, t.accent, ring_text, sub)
        self._lines(p, QRectF(ring.right() + 12, rect.top() + 4, rect.right() - ring.right() - 12, size), lines)
        if hist is not None:
            paint_spark(p, QRectF(rect.left(), rect.bottom() - 20, rect.width(), 20), hist, t.accent2)

    def _temp(self, value) -> tuple[str, str]:
        return (f"{value:.0f} °C" if value is not None else tr("Temp.: no disponible"), "muted")

    def _paint_cpu(self, p, rect):
        s, live = self.svc.static, self.svc.live
        cpu = live.cpu if live else None
        lines = []
        if self.has("model"):
            lines.append((s.cpu_model if s else "…", "text"))
        if self.has("cores") and s:
            lines.append((tr("{c} núcleos · {t} hilos", c=s.cpu_cores, t=s.cpu_threads), "muted"))
        if self.has("temp"):
            lines.append(self._temp(self.svc.cpu_temp))
        self._gauge_card(p, rect, cpu, f"{cpu:.0f}%" if cpu is not None else "—", tr("uso"), lines,
                         self.svc.cpu_hist if self.has("graph") else None)

    def _paint_gpu(self, p, rect):
        s, live = self.svc.static, self.svc.live
        g = live.gpu if live else None
        gpu = s.gpus[0] if s and s.gpus else None
        lines = []
        if self.has("model"):
            lines.append((gpu.name if gpu else ("…" if s is None else tr("No disponible")), "text"))
        if self.has("vram"):
            used = live.gpu_mem if live else None
            total = gpu.vram if gpu else 0
            lines.append((tr("VRAM {u} de {t}", u=_gb(used), t=_gb(total)) if total else f"VRAM {_gb(used)}", "muted"))
        if self.has("temp"):
            lines.append(self._temp(None))  # Windows no expone la temperatura de la GPU de forma estándar
        self._gauge_card(p, rect, g, f"{g:.0f}%" if g is not None else "—", tr("uso"), lines,
                         self.svc.gpu_hist if self.has("graph") else None)

    def _paint_ram(self, p, rect):
        live = self.svc.live
        if live and live.ram_total:
            used = live.ram_total - live.ram_free
            pct = 100 * used / live.ram_total
            lines = [(tr("{u} de {t}", u=_gb(used), t=_gb(live.ram_total)), "text")]
            if self.has("free"):
                lines.append((tr("Disponible {v}", v=_gb(live.ram_free)), "muted"))
        else:
            pct, lines = None, [("…", "muted")]
        self._gauge_card(p, rect, pct, f"{pct:.0f}%" if pct is not None else "—", tr("en uso"), lines,
                         self.svc.ram_hist if self.has("graph") else None)

    def _paint_storage(self, p, rect):
        t = tm().theme
        disks = self.svc.disks
        if not disks:
            self._lines(p, rect, [("…" if self.svc.static is None else "No disponible", "muted")])
            return
        row = max(30.0, min(40.0, rect.height() / max(1, len(disks))))
        y = rect.top()
        f = QFont(self.font())
        f.setPointSizeF(9)
        p.setFont(f)
        for d in disks:
            if y + row > rect.bottom() + 6:
                break
            used = d.total - d.free
            name = d.root.rstrip("\\") + (f" {d.label}" if self.has("labels") and d.label else "")
            p.setPen(QColor(t.text))
            fm = p.fontMetrics()
            p.drawText(QRectF(rect.left(), y, rect.width() * 0.55, 16), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(name, Qt.TextElideMode.ElideRight, int(rect.width() * 0.55)))
            p.setPen(QColor(t.text2))
            p.drawText(QRectF(rect.left(), y, rect.width(), 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       tr("{f} libres de {t}", f=_gb(d.free), t=_gb(d.total)))
            paint_bar(p, QRectF(rect.left(), y + 19, rect.width(), 6), used / d.total if d.total else 0, t.accent)
            y += row

    def _paint_display(self, p, rect):
        screens = QGuiApplication.screens()
        if not screens:
            self._lines(p, rect, [(tr("No disponible"), "muted")])
            return
        main = QGuiApplication.primaryScreen() or screens[0]
        g = main.geometry()
        dpr = main.devicePixelRatio()
        lines = [(f"{round(g.width() * dpr)} × {round(g.height() * dpr)}", "big")]
        if self.has("refresh"):
            lines.append((tr("{hz} Hz · escala {s} %", hz=f"{main.refreshRate():.0f}", s=f"{dpr * 100:.0f}"), "text"))
        if self.has("count"):
            n = len(screens)
            lines.append((ntr("{n} pantalla conectada", "{n} pantallas conectadas", n), "muted"))
        self._lines(p, rect, lines)

    def _paint_os(self, p, rect):
        s = self.svc.static
        if s is None:
            self._lines(p, rect, [("…", "muted")])
            return
        lines = [(s.os_name, "big")]
        if self.has("build"):
            lines.append((s.os_build, "text"))
        if self.has("arch"):
            lines.append((s.arch, "muted"))
        self._lines(p, rect, lines)

    def _paint_board(self, p, rect):
        s = self.svc.static
        if s is None:
            self._lines(p, rect, [("…", "muted")])
            return
        parts = s.board.split(" ", 1)
        lines = [(parts[-1] if len(parts) > 1 else s.board, "big"), (parts[0] if len(parts) > 1 else "", "text")]
        if self.has("bios") and s.bios:
            lines.append((f"BIOS {s.bios}", "muted"))
        self._lines(p, rect, [x for x in lines if x[0]])

    def _paint_devices(self, p, rect, names: list[str], noun: str):
        if self.svc.static is None:
            self._lines(p, rect, [("…", "muted")])
            return
        if not names:
            self._lines(p, rect, [(tr("No disponible"), "muted")])
            return
        total = sum(int(n.rsplit("×", 1)[1]) if "×" in n else 1 for n in names)
        lines = [(ntr("{n} " + noun, "{n} " + noun + "s", total), "big")] + [(n, "muted") for n in names[:3]]
        self._lines(p, rect, lines)

    def _paint_mouse(self, p, rect):
        self._paint_devices(p, rect, self.svc.static.mice if self.svc.static else [], "dispositivo")

    def _paint_keyboard(self, p, rect):
        self._paint_devices(p, rect, self.svc.static.keyboards if self.svc.static else [], "teclado")

    def _rows(self) -> list[tuple[str, str, str]]:
        """(texto, detalle, ruta o acción) de las tarjetas con lista."""
        import os

        if self.kind == "recent":
            db = getattr(self.window(), "db", None)
            if db is None:
                return []
            out = []
            for r in db.recents(12):
                if os.path.exists(r["path"]):
                    out.append((os.path.basename(r["path"]), os.path.dirname(r["path"]), r["path"]))
                if len(out) == 4:
                    break
            return out
        from aero.core import activity as act

        rows = [(a.name, tr(act.KIND_LABELS.get(a.kind, "")) + (f" · {a.progress * 100:.0f} %" if a.progress else ""),
                 "tasks") for a in act.activities().active.values()]
        rows += [(a.name, f"{tr(act.KIND_LABELS.get(a.kind, ''))} · {tr(act.STATE_LABELS[a.state])}", "tasks")
                 for a in act.activities().history[:4]]
        return rows[:4]

    def _paint_list(self, p, rect, empty: str):
        t = tm().theme
        rows = self._rows()
        self._hits = []
        if not rows:
            self._lines(p, rect, [(tr(empty), "muted")])
            return
        y = rect.top()
        for text, sub_, target in rows:
            r = QRectF(rect.left(), y, rect.width(), 28)
            f = QFont(self.font())
            f.setPointSizeF(9)
            p.setFont(f)
            p.setPen(QColor(t.text))
            fm = p.fontMetrics()
            p.drawText(QRectF(r.left(), r.top(), r.width(), 15), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(text, Qt.TextElideMode.ElideMiddle, int(r.width())))
            f.setPointSizeF(7.5)
            p.setFont(f)
            p.setPen(QColor(t.text2))
            p.drawText(QRectF(r.left(), r.top() + 14, r.width(), 13), Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(sub_, Qt.TextElideMode.ElideMiddle, int(r.width())))
            self._hits.append((r.translated(0, 0), target))
            y += 29

    def _paint_recent(self, p, rect):
        self._paint_list(p, rect, "Lo que abras aparecerá aquí.")

    def _paint_tasks(self, p, rect):
        self._paint_list(p, rect, "Aún no hay tareas")

    def mouseDoubleClickEvent(self, e):
        for r, target in getattr(self, "_hits", []):
            if r.contains(e.position()):
                win = self.window()
                if target == "tasks" and hasattr(win, "tasks_btn"):
                    win.tasks_btn.show_popup()
                elif hasattr(win, "open_paths"):
                    win.open_paths([target])
                return

    def _paint_battery(self, p, rect):
        live = self.svc.live
        b = live.battery if live else None
        if live is not None and b is None:
            self._lines(p, rect, [(tr("Sin batería"), "big"), (tr("Este equipo funciona con corriente."), "muted")])
            return
        if b is None:
            self._lines(p, rect, [("…", "muted")])
            return
        lines = [(tr("Cargando" if b.plugged else "Con batería"), "text")]
        if self.has("time") and b.seconds_left:
            h, m = divmod(b.seconds_left // 60, 60)
            lines.append((tr("Quedan {h} h {m} min", h=h, m=f"{m:02d}"), "muted"))
        self._gauge_card(p, rect, float(b.percent), f"{b.percent}%", "", lines, None)


# ---------------------------------------------------------------------------------------------- tablero
class WidgetBoard(QWidget):
    """Tarjetas en una cuadrícula que se adapta al ancho; pequeñas (1 celda) o anchas (2)."""
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setAcceptDrops(True)
        self.cards: dict[str, WidgetCard] = {}
        self._drop_hint: QRectF | None = None
        self.layout_conf = normalize(settings.get("home_widgets")) if settings.get("home_widgets_custom") else None
        self.svc = HardwareService.instance()
        if self.layout_conf is None:
            from aero.core import sysinfo

            self.layout_conf = default_layout(sysinfo.battery() is not None)
        self._build()

    # -- datos
    def save(self):
        self.settings.set("home_widgets", copy.deepcopy(self.layout_conf))
        self.settings.set("home_widgets_custom", True)
        self.changed.emit()

    def visible_conf(self) -> list[dict]:
        return [c for c in self.layout_conf if not c["hidden"]]

    def _build(self):
        for c in list(self.cards.values()):
            c.deleteLater()
        self.cards.clear()
        for conf in self.visible_conf():
            card = WidgetCard(conf, self)
            card.menu_requested.connect(self._card_menu)
            card.show()
            self.cards[conf["type"]] = card
        self._relayout()

    def reset(self):
        from aero.core import sysinfo

        self.layout_conf = default_layout(sysinfo.battery() is not None)
        self.save()
        self._build()

    def add(self, kind: str):
        for c in self.layout_conf:
            if c["type"] == kind:
                c["hidden"] = False
                break
        else:
            self.layout_conf.append({"type": kind, "size": "small", "hidden": False,
                                     "fields": list(TYPES[kind][2])})
        self.save()
        self._build()

    def remove(self, kind: str):
        self.layout_conf = [c for c in self.layout_conf if c["type"] != kind]
        self.save()
        self._build()

    def hide_widget(self, kind: str):
        for c in self.layout_conf:
            if c["type"] == kind:
                c["hidden"] = True
        self.save()
        self._build()

    def set_size(self, kind: str, size: str):
        for c in self.layout_conf:
            if c["type"] == kind:
                c["size"] = size
        self.save()
        self._relayout()

    def toggle_field(self, kind: str, field: str):
        for c in self.layout_conf:
            if c["type"] == kind:
                c["fields"] = [f for f in c["fields"] if f != field] if field in c["fields"] else \
                    c["fields"] + [field]
        self.save()
        self.cards[kind].invalidate()

    def move(self, kind: str, before: str | None):
        conf = next(c for c in self.layout_conf if c["type"] == kind)
        self.layout_conf.remove(conf)
        idx = next((i for i, c in enumerate(self.layout_conf) if c["type"] == before), len(self.layout_conf))
        self.layout_conf.insert(idx, conf)
        self.save()
        self._relayout()

    # -- colocación
    def columns(self) -> int:
        return max(2, (self.width() + GAP) // (CELL_W + GAP))

    def _slots(self) -> list[tuple[str, QRectF]]:
        cols = self.columns()
        cw = (self.width() - GAP * (cols - 1)) / cols
        # Primer hueco libre (en orden de lectura) donde quepa cada tarjeta: sin huecos al mezclar tamaños.
        taken: set[tuple[int, int]] = set()
        out = []
        for conf in self.visible_conf():
            span = min(cols, 2 if conf["size"] == "wide" else 1)
            row = 0
            while True:
                col = next((c for c in range(cols - span + 1)
                            if all((row, c + k) not in taken for k in range(span))), None)
                if col is not None:
                    break
                row += 1
            taken.update((row, col + k) for k in range(span))
            out.append((conf["type"], QRectF(col * (cw + GAP), row * (CELL_H + GAP), cw * span + GAP * (span - 1),
                                             CELL_H)))
        return out

    def _relayout(self):
        slots = self._slots()
        for kind, r in slots:
            if kind in self.cards:
                self.cards[kind].setGeometry(r.toRect())
        bottom = max((r.bottom() for _k, r in slots), default=0)
        self.setMinimumHeight(int(bottom) + 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def sizeHint(self):
        return QSize(CELL_W * 4, self.minimumHeight())

    # -- visibilidad: los datos solo se piden con el tablero a la vista
    def showEvent(self, e):
        super().showEvent(e)
        self.svc.subscribe(self, True)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.svc.subscribe(self, False)

    # -- arrastrar y soltar
    def _target(self, pos: QPointF) -> str | None:
        for kind, r in self._slots():
            if r.contains(pos):
                return kind
        return None

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dropEvent(self, e):
        kind = bytes(e.mimeData().data(MIME)).decode()
        target = self._target(e.position())
        if kind in TYPES and target != kind:
            self.move(kind, target)
        e.acceptProposedAction()

    # -- menús
    def _card_menu(self, card: WidgetCard, gpos: QPoint):
        kind = card.kind
        m = QMenu(self)
        size = m.addMenu(tr("Tamaño"))
        for key, text in (("small", "Pequeño"), ("wide", "Ancho")):
            a = size.addAction(text)
            a.setCheckable(True)
            a.setChecked(card.conf["size"] == key)
            a.triggered.connect(lambda _c=False, k=key: self.set_size(kind, k))
        fields = TYPES[kind][2]
        if fields:
            show = m.addMenu(tr("Mostrar"))
            for key, text in fields.items():
                a = show.addAction(text)
                a.setCheckable(True)
                a.setChecked(card.has(key))
                a.triggered.connect(lambda _c=False, f=key: self.toggle_field(kind, f))
        m.addSeparator()
        m.addAction(tr("Ocultar"), lambda: self.hide_widget(kind))
        m.addAction(tr("Quitar"), lambda: self.remove(kind))
        m.exec(gpos)

    def add_menu(self, parent: QWidget) -> QMenu:
        m = QMenu(parent)
        shown = {c["type"] for c in self.visible_conf()}
        for kind, (title, icon, _f) in TYPES.items():
            if kind in shown:
                continue
            m.addAction(icons.icon(icon, tm().theme.accent, 16), title, lambda k=kind: self.add(k))
        if m.isEmpty():
            a = m.addAction(tr("Ya están todos"))
            a.setEnabled(False)
        m.addSeparator()
        m.addAction(tr("Restaurar la distribución predeterminada"), self.reset)
        return m


class WidgetArea(QWidget):
    """Cabecera («Tu equipo», añadir, mostrar u ocultar) y el tablero dentro de un área con desplazamiento."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        from aero.ui.glass import h_layout, label

        self.settings = settings
        self.board = WidgetBoard(settings)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.board)
        self.title = label(tr("Tu equipo"), "h3")
        self.add_btn = QToolButton()
        self.add_btn.setText(tr("Añadir"))
        self.add_btn.setIcon(tm().icon("plus", 16))
        self.add_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.add_btn.setToolTip(tr("Añadir widgets o restaurar la distribución"))
        self.add_btn.clicked.connect(lambda: self.board.add_menu(self).exec(
            self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft())))
        self.toggle_btn = QToolButton()
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_btn.clicked.connect(self._toggle)
        from PySide6.QtWidgets import QVBoxLayout

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addLayout(h_layout(self.title, None, self.add_btn, self.toggle_btn, spacing=4))
        lay.addWidget(self.scroll, 1)
        self._sync()

    def _toggle(self):
        self.settings.set("home_widgets_visible", not self.settings.get("home_widgets_visible"))
        self._sync()

    def _sync(self):
        on = bool(self.settings.get("home_widgets_visible"))
        self.scroll.setVisible(on)
        self.add_btn.setVisible(on)
        self.toggle_btn.setText(tr("Ocultar" if on else "Mostrar widgets"))
        self.toggle_btn.setIcon(tm().icon("eye", 16))

