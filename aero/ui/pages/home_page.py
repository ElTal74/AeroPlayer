"""Inicio: saludo con la hora y las fechas especiales, accesos rápidos y lo último abierto."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QMenu, QToolButton, QVBoxLayout, QWidget

from aero.core.formats import KIND_LABELS, kind_of
from aero.i18n import tr
from aero.ui import icons
from aero.ui.glass import GlassPanel, HoverLight, Squish, h_layout, label, paint_bubble, tm, v_layout
from aero.ui.file_icons import icon_for


class ActionTile(QToolButton):
    """Baldosa de cristal con un orbe brillante: solo icono y una palabra.

    El hover ilumina y «eleva» la baldosa (luz de acento, borde más vivo y sombra inferior suave) sin
    agrandarla: todo se dibuja dentro de un margen interior, así el borde nunca se recorta y los vecinos
    no se mueven. Al pulsar se aplasta ligeramente hacia dentro y rebota.
    """

    MARGIN = 4

    def __init__(self, icon_name: str, title: str, tooltip: str, parent=None, compact: bool = False):
        super().__init__(parent)
        from aero.i18n import tr

        self.icon_name, self.title = icon_name, title
        self.shown_title = tr(title)
        tooltip = tr(tooltip)
        self.active = False
        self.compact = compact
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if compact:
            self.setFixedSize(124, 112)
        else:
            self.setMinimumHeight(138)
        self.setAccessibleName(self.shown_title)
        self.setToolTip(tooltip)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if not compact:
            self.setSizePolicy(self.sizePolicy().Policy.Expanding, self.sizePolicy().Policy.Fixed)
        self.light = HoverLight(self)
        self.squish = Squish(self, 0.965, 1.0)
        tm().changed.connect(self.update)

    def paintEvent(self, e):
        # En reposo se reutiliza la imagen ya dibujada: el fondo animado pasa por detrás muchas veces por segundo.
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, round(self.light.value, 3), round(self.squish.scale, 3),
               self.active, self.hasFocus(), id(tm().theme), self.shown_title)
        if getattr(self, "_cache_key", None) != key:
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

    def _render(self, p: QPainter):
        t = tm().theme
        h = self.light.value
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        s = self.squish.scale
        mid = QRectF(self.rect()).center()
        p.translate(mid)
        p.scale(s, s)
        p.translate(-mid)
        m = self.MARGIN
        r = QRectF(self.rect()).adjusted(m + 0.5, m + 0.5, -m - 0.5, -m - 0.5).translated(0, -1.5 * h)
        rad = 16 if self.compact else 18
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        # Sombra de elevación: dentro del margen, debajo de la baldosa.
        if h > 0.01:
            for i, a in ((3.0, 0.10), (1.8, 0.14)):
                sh = QPainterPath()
                sh.addRoundedRect(r.adjusted(2, i + 1, -2, i), rad, rad)
                p.fillPath(sh, QColor(0, 10, 30, int(255 * a * h)))
        base = QLinearGradient(0, r.top(), 0, r.bottom())
        if t.dark:
            base.setColorAt(0, QColor(255, 255, 255, int(44 + 22 * h)))
            base.setColorAt(1, QColor(255, 255, 255, int(12 + 8 * h)))
        else:
            base.setColorAt(0, QColor(255, 255, 255, int(205 + 40 * h)))
            base.setColorAt(1, QColor(255, 255, 255, int(110 + 30 * h)))
        p.fillPath(path, base)
        if h > 0.01 or self.active:
            glow = QRadialGradient(QPointF(r.center().x(), r.bottom() + r.height() * 0.15), r.width() * 0.65)
            ac = QColor(t.accent2 if self.active else t.accent)
            ac.setAlphaF(0.30 * max(h, 0.5 if self.active else 0.0))
            glow.setColorAt(0, ac)
            ac0 = QColor(ac)
            ac0.setAlphaF(0.0)
            glow.setColorAt(1, ac0)
            p.fillPath(path, glow)
        # Casquete brillante
        cap = QPainterPath()
        cap.addRoundedRect(QRectF(r.left() + 3, r.top() + 3, r.width() - 6, r.height() * 0.42), rad - 3, rad - 3)
        cg = QLinearGradient(0, r.top(), 0, r.top() + r.height() * 0.42)
        cg.setColorAt(0, QColor(255, 255, 255, int((140 if t.dark else 225) * (0.85 + 0.15 * h))))
        cg.setColorAt(1, QColor(255, 255, 255, 8))
        p.fillPath(cap, cg)
        # Borde continuo en todo el perímetro, mezclado hacia el acento con el hover.
        edge = QColor(255, 255, 255, 120 if t.dark else 240)
        acc = QColor(t.accent)
        k = max(h, 1.0 if (self.active or self.hasFocus()) else 0.0)
        edge = QColor(int(edge.red() + (acc.red() - edge.red()) * k), int(edge.green() + (acc.green() - edge.green()) * k),
                      int(edge.blue() + (acc.blue() - edge.blue()) * k), int(edge.alpha() + (230 - edge.alpha()) * k))
        p.setPen(QPen(edge, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        inner = QPainterPath()
        inner.addRoundedRect(r.adjusted(1, 1, -1, -1), rad - 1, rad - 1)
        p.setPen(QPen(QColor(255, 255, 255, 34 if t.dark else 120), 1))
        p.drawPath(inner)
        if self.hasFocus():
            ring = QPainterPath()
            ring.addRoundedRect(r.adjusted(2, 2, -2, -2), rad - 2, rad - 2)
            p.setPen(QPen(QColor(t.accent), 1.5))
            p.drawPath(ring)
        # Burbuja transparente con el icono dentro
        d = 46 if self.compact else 60
        cx, cy = r.center().x(), r.top() + (14 if self.compact else 16) + d / 2
        a = QColor(t.accent2 if self.active else t.accent)
        paint_bubble(p, QPointF(cx, cy), d / 2, a, fill=0.18 + 0.10 * max(h, 1.0 if self.active else 0.0), rim=1.0)
        ics = 22 if self.compact else 26
        pm = icons.pixmap(self.icon_name, "#ffffff" if t.dark else t.accent, ics)
        p.drawPixmap(QRectF(cx - ics / 2, cy - ics / 2, ics, ics), pm, QRectF(pm.rect()))
        f = p.font()
        f.setPointSizeF(9.8 if self.compact else 11)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(t.text))
        p.drawText(QRectF(r.left(), cy + d / 2 + (6 if self.compact else 8), r.width(), 22),
                   Qt.AlignmentFlag.AlignCenter, self.shown_title)
        if self.active:
            dot = QPointF(r.right() - 14, r.top() + 14)
            paint_bubble(p, dot, 5 if self.compact else 7, QColor(t.accent2), fill=0.5, rim=1.0)


class RecentChip(QToolButton):
    """Elemento reciente compacto: icono y nombre en una línea."""

    W = 196

    def __init__(self, path: str, title: str, icon, tip: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIcon(icon if not isinstance(icon, str) else icons.icon(icon, tm().theme.accent, 20))
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(self.W, 40)
        fm = self.fontMetrics()
        self.setText("  " + fm.elidedText(title, Qt.TextElideMode.ElideMiddle, self.W - 52))
        self.setToolTip(tip)
        self.setAccessibleName(title)
        self.setStyleSheet("QToolButton { text-align: left; padding-left: 10px; }")


class HomePage(QWidget):
    """Inicio minimalista: saludo, seis accesos y lo último que abriste. El resto, a un clic.

    No hay listas largas ni paneles compitiendo: los historiales completos se despliegan bajo demanda.
    """

    open_file = Signal()
    open_folder = Signal()
    go = Signal(str)
    open_path = Signal(str)
    play_path = Signal(str)
    quicklook_toggle = Signal()
    continue_watching = Signal(list, int)
    tool = Signal(str)  # acción del menú «Crear» (documento, hoja, vídeo, comprimir…)

    CREATE_MENU = [
        ("brush", "Dibujo nuevo (AERO Paint)", "paint"),
        ("text", "Documento nuevo", "new_document"),
        ("sheet", "Hoja de cálculo nueva", "new_sheet"),
        ("slides", "Presentación nueva", "new_slides"),
        ("video", "Proyecto de vídeo nuevo", "new_video"),
        None,
        ("image", "Editar una imagen…", "edit_image"),
        ("pdf", "PDF a documento editable…", "pdf_convert"),
        None,
        ("archive", "Comprimir archivos…", "compress"),
        ("drop", "Abrir o extraer un comprimido…", "open_archive"),
    ]

    def __init__(self, db, settings, parent=None):
        super().__init__(parent)
        self.db = db
        self.settings = settings
        # Saludo en peso fino y grande: jerarquía por tamaño, no por negrita.
        self.greet = label("")
        self.greet.setStyleSheet("font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 27pt;"
                                 " font-weight: 300;")
        self.subtitle = label("", "muted")
        specs = [
            ("open", "Abrir", "Abrir archivos (Ctrl+O)", self.open_file.emit),
            ("library", "Biblioteca", "Tu música y vídeos", lambda: self.go.emit("library")),
            ("files", "Archivos", "Tus carpetas y documentos", lambda: self.go.emit("files")),
            ("convert", "Convertir", "Conversor de archivos", lambda: self.go.emit("converter")),
            ("plus", "Crear", "Documentos, hojas, presentaciones, vídeo, imágenes y comprimidos", self._create_menu),
            ("eye", "Vista rápida", "Activar o desactivar la vista rápida del Explorador", self.quicklook_toggle.emit),
        ]
        self.tiles = []
        row = QHBoxLayout()
        row.setSpacing(12)
        for ic, t, tip, fn in specs:
            c = ActionTile(ic, t, tip, compact=True)
            c.clicked.connect(fn)
            row.addWidget(c)
            self.tiles.append(c)
        row.addStretch(1)
        self.quick_tile = self.tiles[-1]

        self.resume = QToolButton()
        self.resume.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resume.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.resume.setIconSize(QSize(20, 20))
        self.resume.setStyleSheet("QToolButton { text-align: left; padding: 8px 14px; }")
        self.resume.clicked.connect(self._resume)
        self.resume.hide()

        self.recent_title = label("Recientes", "h3")
        self.more = QToolButton()
        self.more.setText(tr("Ver todo"))
        self.more.setCheckable(True)
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more.setStyleSheet("QToolButton { padding: 4px 10px; }")
        self.more.toggled.connect(self._toggle_more)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(8)
        self.empty_hint = label(tr("Lo que abras aparecerá aquí."), "muted")

        # Historial completo (oculto hasta pedirlo)
        self.recent = self._list()
        self.recent.itemActivated.connect(lambda it: self.open_path.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.played = self._list()
        self.played.itemActivated.connect(lambda it: self.play_path.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.history = GlassPanel(radius=18)
        hl = QHBoxLayout(self.history)
        hl.setContentsMargins(16, 12, 10, 10)
        hl.setSpacing(16)
        hl.addLayout(v_layout(label("Abierto", "caption"), self.recent, spacing=4), 1)
        hl.addLayout(v_layout(label(tr("Escuchado y visto"), "caption"), self.played, spacing=4), 1)
        self.history.hide()

        head = QHBoxLayout()
        head.addLayout(v_layout(self.greet, self.subtitle, spacing=2), 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 14)
        lay.setSpacing(0)
        lay.addLayout(head)
        lay.addSpacing(18)
        lay.addLayout(row)
        lay.addSpacing(14)
        lay.addWidget(self.resume, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addSpacing(10)
        lay.addLayout(h_layout(self.recent_title, None, self.more))
        lay.addSpacing(8)
        lay.addLayout(self.chips)
        lay.addWidget(self.empty_hint)
        lay.addSpacing(12)
        lay.addWidget(self.history, 1)
        # Escritorio de widgets con la información del equipo (personalizable)
        from aero.ui.home_widgets import WidgetArea

        lay.addSpacing(10)
        self.widgets = WidgetArea(settings)
        self._spacer = self.widgets
        lay.addWidget(self.widgets, 1)
        self.refresh()

    def _create_menu(self):
        tile = next(t for t in self.tiles if t.title == "Crear")
        m = QMenu(self)
        col = tm().theme.accent
        for item in self.CREATE_MENU:
            if item is None:
                m.addSeparator()
                continue
            ic, text, key = item
            a = m.addAction(icons.icon(ic, col, 18), tr(text))
            a.triggered.connect(lambda _c=False, k=key: self.tool.emit(k))
        m.exec(tile.mapToGlobal(tile.rect().bottomLeft()))

    def _toggle_more(self, on: bool):
        self.history.setVisible(on)
        self._spacer.setVisible(not on)
        self.more.setText(tr("Ocultar" if on else "Ver todo"))
        if on:
            self._fill_history()

    def _list(self) -> QListWidget:
        w = QListWidget()
        w.setIconSize(QSize(20, 20))
        w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        w.customContextMenuRequested.connect(lambda pos, lw=w: self._menu(lw, pos))
        return w

    def _menu(self, lw: QListWidget, pos):
        it = lw.itemAt(pos)
        if not it or not it.data(Qt.ItemDataRole.UserRole):
            return
        path = it.data(Qt.ItemDataRole.UserRole)
        from aero.core import tools

        m = QMenu(self)
        m.addAction(tr("Abrir"), lambda: self.open_path.emit(path))
        m.addAction(tr("Mostrar en carpeta"), lambda: tools.reveal_in_explorer(path))
        m.exec(lw.viewport().mapToGlobal(pos))

    def _resume(self):
        if self._resume_path:
            from aero.core.series import folder_episodes

            self.continue_watching.emit(folder_episodes(self._resume_path), 0)

    def refresh(self, now: dt.datetime | None = None):
        from aero.core.seasons import greeting

        s = self.settings
        # Identidad visual permanente: solo el saludo según la hora, sin adornos ni felicitaciones por fechas.
        g = greeting(now or dt.datetime.now(), "none", False)
        self.greet.setText(g.title)
        self.subtitle.setText(g.subtitle)
        q = self.quick_tile
        q.active = bool(s.get("quicklook_enabled"))
        q.setToolTip(tr("Vista rápida activa · {v0}", v0=s.get('quicklook_hotkey')) if q.active
                     else tr("Activar la vista rápida del Explorador"))
        q.update()
        t = tm().theme
        while self.chips.count():
            it = self.chips.takeAt(0)
            if it.widget() is not None:
                it.widget().hide()
                it.widget().deleteLater()
        n = 0
        for r in self.db.recents(12):
            path = r["path"]
            if not os.path.exists(path):
                continue
            k = kind_of(path)
            chip = RecentChip(path, Path(path).name, icon_for(path, 20),
                              f"{tr(KIND_LABELS.get(k, ''))} · {_ago(r['opened_at'])}\n{path}")
            chip.clicked.connect(lambda _c=False, p=path: self.open_path.emit(p))
            self.chips.addWidget(chip)
            n += 1
            if n == 5:
                break
        self.chips.addStretch(1)
        self.empty_hint.setVisible(n == 0)
        self._resume_path = None
        self.resume.hide()
        for r in self.db.in_progress(8):
            if os.path.exists(r["path"]) and kind_of(r["path"]) == "video":
                self._resume_path = r["path"]
                from aero.core.formats import human_time
                from aero.core.series import parse_episode

                ep = parse_episode(r["path"])
                name = f"{ep.show} · {ep.code}" if ep else Path(r["path"]).stem
                self.resume.setIcon(icons.icon("continue", t.accent, 20))
                self.resume.setText(tr("  Continuar  ·  {name}  ·  {v1}", name=name, v1=human_time(r['position_ms'] / 1000)))
                self.resume.show()
                break
        if self.history.isVisible():
            self._fill_history()

    def _fill_history(self):
        t = tm().theme
        self.recent.clear()
        for r in self.db.recents(60):
            path = r["path"]
            k = kind_of(path)
            it = QListWidgetItem(icon_for(path, 20), Path(path).name)
            it.setData(Qt.ItemDataRole.UserRole, path)
            it.setToolTip(f"{tr(KIND_LABELS.get(k, ''))} · {_ago(r['opened_at'])}\n{path}")
            if not os.path.exists(path):
                it.setForeground(QColor(t.text2))
            self.recent.addItem(it)
        self.played.clear()
        for r in self.db.recently_played(60):
            path = r["path"]
            k = kind_of(path)
            name = r["title"] or Path(path).stem
            it = QListWidgetItem(icons.icon("video" if k == "video" else "music", t.accent2, 20),
                                 f"{name}  ·  {r['artist']}" if r["artist"] else name)
            it.setData(Qt.ItemDataRole.UserRole, path)
            it.setToolTip(f"{_ago(r['played_at'])}\n{path}")
            self.played.addItem(it)


def _ago(ts: float) -> str:
    d = dt.datetime.now() - dt.datetime.fromtimestamp(ts or 0)
    s = d.total_seconds()
    if s < 60:
        return "ahora mismo"
    if s < 3600:
        return f"hace {int(s // 60)} min"
    if s < 86400:
        return f"hace {int(s // 3600)} h"
    if s < 86400 * 7:
        return f"hace {int(s // 86400)} días"
    return dt.datetime.fromtimestamp(ts).strftime("%d/%m/%Y")
