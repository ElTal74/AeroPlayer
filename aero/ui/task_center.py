"""Panel del centro de tareas: operaciones en curso (con avance real y cancelar) e historial reciente."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QFrame, QLabel, QProgressBar, QPushButton, QScrollArea, QToolButton, QVBoxLayout,
                               QWidget)

from aero.core import activity as act
from aero.ui.glass import IconButton, h_layout, label, tm, v_layout
from aero.i18n import tr

STATE_ICONS = {act.DONE: "check", act.ERROR: "info", act.CANCELLED: "close", act.RUNNING: "clock"}


def _ago(t: float) -> str:
    d = time.time() - t
    if d < 60:
        return "ahora"
    if d < 3600:
        return f"hace {int(d // 60)} min"
    if d < 86400:
        return f"hace {int(d // 3600)} h"
    return time.strftime("%d/%m %H:%M", time.localtime(t))


def _dur(s: float) -> str:
    s = int(s)
    return f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s"


class _Row(QWidget):
    def __init__(self, a: act.Activity, center: act.ActivityCenter):
        super().__init__()
        t = tm().theme
        ic = QLabel()
        from aero.ui import icons

        color = {act.ERROR: "#ff7a8a", act.DONE: t.accent}.get(a.state, t.text2)
        ic.setPixmap(icons.pixmap(STATE_ICONS.get(a.state, "clock"), color, 18))
        ic.setFixedSize(20, 20)
        name = label(a.name)
        name.setToolTip(a.name)
        kind = tr(act.KIND_LABELS.get(a.kind, ""))
        if a.state == act.RUNNING:
            sub = f"{kind} · {a.detail}" if a.detail else kind
            sub += f" · {_dur(a.elapsed)}"
        else:
            sub = f"{kind} · {tr(act.STATE_LABELS[a.state])} · {_ago(a.finished or a.started)} · {_dur(a.elapsed)}"
            if a.error:
                sub += f"\n{a.error}"
        info = label(sub, "caption", wrap=True)
        col = v_layout(name, info, spacing=1)
        right = []
        if a.state == act.RUNNING:
            bar = QProgressBar()
            bar.setTextVisible(False)
            if a.progress is None:
                bar.setRange(0, 0)  # avance desconocido: indicador honesto, sin porcentaje inventado
            else:
                bar.setRange(0, 1000)
                bar.setValue(int(a.progress * 1000))
            col.addWidget(bar)
            if center.can_cancel(a.id):
                b = IconButton("close", tr("Cancelar"), 14, button=28)
                b.clicked.connect(lambda: center.cancel(a.id))
                right.append(b)
        elif a.result and os.path.exists(a.result):
            b = IconButton("folder", tr("Mostrar el resultado"), 14, button=28)
            from aero.core import tools

            b.clicked.connect(lambda: tools.reveal_in_explorer(a.result))
            right.append(b)
        lay = h_layout(ic, spacing=8, margins=(4, 4, 4, 4))
        lay.addLayout(col, 1)
        for b in right:
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        self.setLayout(lay)


class TaskCenter(QFrame):
    """Ventana emergente anclada al botón de la barra superior."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("TaskCenter")
        self.setFixedSize(420, 480)
        t = tm().theme
        self.setStyleSheet(f"#TaskCenter {{ background: {t.solid}; border: 1px solid rgba(255,255,255,40); "
                           f"border-radius: 10px; }}")
        self.center = act.activities()
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.body)
        clear = QPushButton(tr("Vaciar historial"))
        clear.setProperty("kind", "flat")
        clear.clicked.connect(self.center.clear_history)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.addLayout(h_layout(label("Tareas", "h3"), None, clear))
        lay.addWidget(scroll, 1)
        self.center.changed.connect(self.refresh)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)  # el tiempo transcurrido de lo que sigue en marcha
        self._tick.timeout.connect(lambda: self.center.active and self.refresh())
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self._tick.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._tick.stop()

    def refresh(self):
        while self.body_lay.count():
            it = self.body_lay.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        active, history = list(self.center.active.values()), self.center.history[:60]
        if active:
            self.body_lay.addWidget(label(tr("En curso"), "muted"))
            for a in active:
                self.body_lay.addWidget(_Row(a, self.center))
        self.body_lay.addWidget(label("Recientes" if history else tr("Aún no hay tareas"), "muted"))
        for a in history:
            self.body_lay.addWidget(_Row(a, self.center))
        self.body_lay.addStretch(1)


class TaskButton(QToolButton):
    """Botón de la barra superior con el número de tareas en curso."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.center = act.activities()
        self.setIcon(tm().icon("tasks", 18))
        self.setIconSize(QSize(18, 18))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(tr("Tareas"))
        self.popup: TaskCenter | None = None
        self.clicked.connect(self.show_popup)
        self.center.changed.connect(self._sync)
        self._sync()

    def _sync(self):
        n = len(self.center.active)
        self.setText(f" {n}" if n else "")
        self.setToolTip(tr("Tareas: {n} en curso", n=n) if n else tr("Tareas e historial"))

    def show_popup(self):
        if self.popup is None:
            self.popup = TaskCenter(self)
        self.popup.refresh()
        g = self.mapToGlobal(self.rect().bottomRight())
        self.popup.move(g.x() - self.popup.width(), g.y() + 6)
        self.popup.show()
