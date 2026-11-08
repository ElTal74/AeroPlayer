"""Tutorial de bienvenida: recorrido guiado por la aplicación la primera vez que se abre (se puede saltar).

Una capa sobre la ventana principal oscurece todo menos la zona de la que se habla («foco») y muestra una
tarjeta con la explicación. Cada paso puede llevar a una página y añadir un elemento propio (elegir tema,
maqueta del menú del clic derecho). Se vuelve a ver desde Ajustes › Inicio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import (QEasingCurve, QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation,
                            Signal)
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QGridLayout, QHBoxLayout, QPushButton, QToolButton, QVBoxLayout,
                               QWidget)

from aero.ui import icons
from aero.ui.glass import GlassPanel, h_layout, label, tm
from aero.i18n import tr

PAD = 8          # margen del foco alrededor de la zona resaltada
CARD_W = 460

# Temas que se ofrecen en el paso «Hazlo tuyo» (todos los demás están en Ajustes › Apariencia).
TUTORIAL_THEMES = ("burbuja", "aero", "cielo", "nature", "aurora", "espacio_negro", "cosmos", "nebulosa", "tropical",
                   "tropical_atardecer")
SHORT_NAMES = {"espacio_negro": "Espacio", "tropical_atardecer": "Atardecer"}
TOUR_KEYS = (Qt.Key.Key_Escape, Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter,
             Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)


@dataclass
class Step:
    title: str
    text: str
    page: str | None = None                        # página a la que se navega antes de mostrar el paso
    target: Callable[[QWidget], QWidget | QRect | None] | None = None
    extra: Callable[["Tutorial"], QWidget] | None = None


def _tiles_rect(win) -> QRect | None:
    home = win.pages.get("home")
    if home is None or not getattr(home, "tiles", None):
        return None
    r = QRect()
    for t in home.tiles:
        r = r.united(QRect(t.mapTo(win, QPoint(0, 0)), t.size()))
    return r


def _widgets_rect(win) -> QRect | None:
    home = win.pages.get("home")
    area = getattr(home, "widgets", None)
    if area is None or not area.isVisible():
        return None
    return QRect(area.mapTo(win, QPoint(0, 0)), area.size())


STEPS: list[Step] = [
    Step("Te damos la bienvenida a AERO Player",
         "Música, vídeo, imágenes, PDF, documentos, comprimidos y conversión en una sola aplicación."
         "\n\nEn un minuto te enseñamos lo principal. Puedes saltarte el tutorial cuando "
         "quieras y volver a verlo en Ajustes."),
    Step("Muévete por la aplicación",
         "Esta barra lleva a cada sección: Inicio, Biblioteca, Archivos, Reproductor, Visor, Conversor, Listas y "
         "Ajustes. También puedes usar Ctrl+1 … Ctrl+8.", "home", lambda w: w.rail),
    Step("Empieza desde Inicio",
         "Abre cualquier archivo (o arrástralo a la ventana), crea documentos, hojas, presentaciones o proyectos de "
         "vídeo con «Crear», y activa la Vista rápida para previsualizar archivos desde el Explorador.",
         "home", _tiles_rect),
    Step("Tu equipo de un vistazo",
         "Procesador, gráfica, memoria, discos y más. Arrastra las tarjetas para ordenarlas; con el clic derecho "
         "cambias su tamaño o lo que muestran, y con «Añadir» pones o quitas widgets.",
         "home", _widgets_rect),
    Step("Tu biblioteca",
         "Añade tus carpetas de música y vídeo y AERO Player las organiza por álbum, artista y serie. Busca en ella "
         "desde la barra de arriba (Ctrl+F).", "library", lambda w: w.stage),
    Step("Reproductor y visualizadores",
         "Vídeo con subtítulos y pistas de audio, cola de reproducción y visualizadores para la música. Pulsa V "
         "para el visualizador y F11 para la pantalla completa.", "player", lambda w: w.stage),
    Step("Archivos y comprimidos",
         "Explora tus carpetas, previsualiza y abre lo que quieras. Con el clic derecho puedes extraer, comprimir "
         "(ZIP, 7Z, RAR, TAR) y convertir.", "files", lambda w: w.stage),
    Step("También desde Windows",
         "Haz clic derecho sobre cualquier archivo o carpeta del Explorador y busca «AERO Player»: extraer aquí, "
         "extraer en…, comprimir y convertir sin abrir la aplicación.\n\nEn Windows 11 está dentro de «Mostrar más "
         "opciones» (o Mayús+F10).", None, None, lambda t: ContextMenuMock()),
    Step("Convierte lo que sea",
         "Vídeo, audio, imágenes, PDF y documentos de Office a otros formatos, por lotes y sin tocar los "
         "originales. Arrastra los archivos aquí o usa «Convertir…» en el clic derecho.",
         "converter", lambda w: w.stage),
    Step("Hazlo tuyo",
         "Elige un tema ahora mismo; cambia al instante. En Ajustes › Apariencia tienes todos, el Estudio de temas "
         "para crear los tuyos (colores, burbujas, estrellas, planetas, imagen de fondo…) y la transparencia "
         "del cristal.", None, None, lambda t: ThemePicker(t.settings.get("theme"), lambda k: t.settings.set("theme", k))),
    Step("Ajustes a tu medida",
         "Cada apartado a un clic en la barra lateral, y un buscador para ir directo a lo que quieras cambiar. "
         "Desde aquí también puedes volver a ver este tutorial.",
         "settings", lambda w: w.rail.buttons.get("settings")),
    Step("¡Todo listo!",
         "Disfruta de AERO Player. Si necesitas algo, pasa el ratón por encima de los botones: todos explican lo "
         "que hacen.", "home"),
]


class ThemePicker(QWidget):
    """Miniaturas de algunos temas; un clic aplica el tema al momento (también lo usa el instalador)."""
    picked = Signal(str)

    def __init__(self, current: str, on_pick: Callable[[str], None] | None = None, parent=None, columns: int = 5):
        super().__init__(parent)
        from aero.ui.pages.theme_studio import render_preview
        from aero.ui.theme import PRESETS

        if on_pick is not None:
            self.picked.connect(on_pick)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QToolButton] = {}
        for i, key in enumerate(TUTORIAL_THEMES):
            spec = PRESETS[key]
            b = QToolButton()
            b.setCheckable(True)
            b.setChecked(key == current)
            b.setIcon(QIcon(render_preview(spec, 140, 88, key)))
            b.setIconSize(QSize(70, 44))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setText(SHORT_NAMES.get(key, spec["name"].replace("Frutiger ", "")))
            b.setToolTip(spec["name"])
            b.setAccessibleName(f"Tema {spec['name']}")
            b.setFixedSize(QSize(80, 72))
            font = b.font()
            font.setPointSizeF(8.5)
            b.setFont(font)
            b.clicked.connect(lambda _c=False, k=key: self.picked.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            grid.addWidget(b, i // columns, i % columns)


class ContextMenuMock(QWidget):
    """Dibujo del menú contextual del Explorador con el submenú de AERO Player (solo ilustrativo)."""

    ITEMS = ("Abrir", "Abrir con", "AERO Player", "Compartir", "Copiar como ruta", "Propiedades")
    SUB = ("Extraer aquí", "Extraer en una carpeta", "Extraer en…", "Comprimir en ZIP", "Comprimir en 7Z",
           "Convertir…")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(206)
        self.setAccessibleName(tr("Ejemplo del menú del clic derecho con AERO Player"))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = tm().theme
        dark = t.dark
        bg = QColor("#2b2b2b" if dark else "#f9f9f9")
        fg = QColor("#f2f2f2" if dark else "#1b1b1b")
        border = QColor(255, 255, 255, 40) if dark else QColor(0, 0, 0, 40)
        hi = QColor(t.accent)
        hi.setAlpha(70)
        row = 24

        def menu(x: float, y: float, w: float, items, active: int, arrow: int | None):
            r = QRectF(x, y, w, len(items) * row + 8)
            path = QPainterPath()
            path.addRoundedRect(r, 8, 8)
            p.fillPath(path, bg)
            p.setPen(QPen(border, 1))
            p.drawPath(path)
            for i, text in enumerate(items):
                ry = y + 4 + i * row
                if i == active:
                    hp = QPainterPath()
                    hp.addRoundedRect(QRectF(x + 4, ry, w - 8, row), 5, 5)
                    p.fillPath(hp, hi)
                if items is self.ITEMS and text == "AERO Player":
                    p.drawPixmap(int(x + 10), int(ry + 4), icons.pixmap("aero", t.accent, 16))
                p.setPen(fg)
                p.drawText(QRectF(x + 32, ry, w - 44, row), Qt.AlignmentFlag.AlignVCenter, text)
                if i == arrow:
                    p.drawPixmap(int(x + w - 22), int(ry + 5), icons.pixmap("right", fg.name(), 14))

        w = self.width()
        mw = min(190.0, w * 0.46)
        menu(2, 6, mw, self.ITEMS, 2, 2)
        menu(mw - 6, 6 + row * 2 - 4, min(200.0, w - mw + 2), self.SUB, 0, None)
        p.end()


class TutorialCard(GlassPanel):
    """Tarjeta del paso actual: casi opaca para que se lea bien sobre la capa oscurecida."""

    def __init__(self, parent=None):
        super().__init__(parent, radius=16, strong=True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self.radius, self.radius)
        c = QColor(tm().theme.solid)
        c.setAlphaF(0.94)
        p.fillPath(path, c)
        p.end()
        super().paintEvent(e)


class Dots(QWidget):
    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self.count, self.index = count, 0
        self.setFixedSize(count * 14, 12)

    def set_index(self, i: int):
        self.index = i
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        t = tm().theme
        for i in range(self.count):
            c = QColor(t.accent if i == self.index else t.text)
            c.setAlphaF(1.0 if i == self.index else 0.25)
            p.setBrush(c)
            r = 4.0 if i == self.index else 3.0
            p.drawEllipse(QRectF(i * 14 + 7 - r, 6 - r, r * 2, r * 2))
        p.end()


class Tutorial(QWidget):
    """Capa del tutorial sobre la ventana principal."""
    finished = Signal(bool)  # True si se completó, False si se saltó

    def __init__(self, win, settings):
        super().__init__(win)
        self.win, self.settings = win, settings
        self.steps = STEPS
        self.index = -1
        self._hole = QRectF()
        self._extra: QWidget | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(tr("Tutorial de AERO Player"))

        self.card = TutorialCard(self)
        self.card.setFixedWidth(CARD_W)
        self.step_label = label("", "caption")
        self.title = label("", "h2", wrap=True)
        self.text = label("", wrap=True)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.extra_box = QVBoxLayout()
        self.extra_box.setContentsMargins(0, 4, 0, 4)
        self.dots = Dots(len(self.steps))
        self.skip = QPushButton(tr("Saltar tutorial"))
        self.skip.setProperty("kind", "flat")
        self.skip.clicked.connect(lambda: self.close_tutorial(False))
        self.back = QPushButton(tr("Anterior"))
        self.back.clicked.connect(self.prev)
        self.next_btn = QPushButton(tr("Siguiente"))
        self.next_btn.setProperty("kind", "primary")
        self.next_btn.clicked.connect(self.next)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(8)
        lay.addLayout(h_layout(self.step_label, None, self.dots))
        lay.addWidget(self.title)
        lay.addWidget(self.text)
        lay.addLayout(self.extra_box)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        bottom.addWidget(self.skip)
        bottom.addStretch(1)
        bottom.addWidget(self.back)
        bottom.addWidget(self.next_btn)
        lay.addSpacing(4)
        lay.addLayout(bottom)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(380)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_hole)
        win.installEventFilter(self)
        # Las teclas del recorrido tienen prioridad sobre los atajos de la ventana (Esc, flechas, Intro)
        QApplication.instance().installEventFilter(self)
        tm().changed.connect(self.update)
        self.setGeometry(win.rect())

    # ------------------------------------------------------------------ recorrido
    def start(self):
        self.show()
        self.raise_()
        self.go(0)
        self.setFocus()

    def go(self, i: int):
        i = max(0, min(len(self.steps) - 1, i))
        self.index = i
        st = self.steps[i]
        if st.page:
            self.win.navigate(st.page)
        last = i == len(self.steps) - 1
        self.step_label.setText(tr("Paso {i} de {n}", i=i + 1, n=len(self.steps)))
        self.title.setText(tr(st.title))
        self.text.setText(tr(st.text))
        self.dots.set_index(i)
        self.back.setEnabled(i > 0)
        self.skip.setVisible(not last)
        self.next_btn.setText(tr("Empezar" if last else ("Comenzar" if i == 0 else "Siguiente")))
        if self._extra is not None:
            self.extra_box.removeWidget(self._extra)
            self._extra.hide()
            self._extra.deleteLater()
            self._extra = None
        if st.extra is not None:
            self._extra = st.extra(self)
            self.extra_box.addWidget(self._extra)
        self._fit_card()
        self.next_btn.setFocus()
        # La página puede tardar un instante en colocarse (se construye o hace el fundido): se mide después.
        QTimer.singleShot(60, self._relayout)

    def next(self):
        if self.index >= len(self.steps) - 1:
            self.close_tutorial(True)
        else:
            self.go(self.index + 1)

    def prev(self):
        if self.index > 0:
            self.go(self.index - 1)

    def close_tutorial(self, completed: bool):
        self.settings.set("tutorial_done", True)
        self.win.removeEventFilter(self)
        QApplication.instance().removeEventFilter(self)
        self.hide()
        self.finished.emit(completed)
        self.deleteLater()

    # ------------------------------------------------------------------ colocación
    def _target_rect(self) -> QRectF:
        st = self.steps[self.index] if 0 <= self.index < len(self.steps) else None
        if st is None or st.target is None:
            return QRectF()
        try:
            tgt = st.target(self.win)
        except (AttributeError, KeyError, RuntimeError):
            return QRectF()
        if isinstance(tgt, QWidget):
            if not tgt.isVisible():
                return QRectF()
            tgt = QRect(tgt.mapTo(self.win, QPoint(0, 0)), tgt.size())
        if not isinstance(tgt, QRect) or tgt.isEmpty():
            return QRectF()
        return QRectF(tgt).adjusted(-PAD, -PAD, PAD, PAD)

    def _relayout(self):
        if self.index < 0:
            return
        self.setGeometry(self.win.rect())
        target = self._target_rect()
        start = self._hole if not self._hole.isNull() else (
            QRectF(target.center(), target.center()) if not target.isNull() else QRectF())
        if tm().reduce_motion or start.isNull() or target.isNull():
            self._anim.stop()
            self._set_hole(target)
        else:
            self._anim.stop()
            self._anim.setStartValue(start)
            self._anim.setEndValue(target)
            self._anim.start()
        self._place_card(target)

    def _set_hole(self, r):
        self._hole = QRectF(r) if r is not None else QRectF()
        self.update()

    def _fit_card(self):
        # Con texto que se parte en varias líneas, la altura depende del ancho: se calcula para el ancho fijo.
        lay = self.card.layout()
        lay.activate()
        self.card.setFixedHeight(max(lay.totalMinimumSize().height(), lay.totalHeightForWidth(CARD_W)))

    def _place_card(self, target: QRectF):
        self._fit_card()
        cw, ch = self.card.width(), self.card.height()
        W, H = self.width(), self.height()
        m = 18
        if target.isNull():
            x, y = (W - cw) / 2, (H - ch) / 2
        elif target.right() + m + cw <= W - m:            # a la derecha
            x, y = target.right() + m, target.center().y() - ch / 2
        elif target.left() - m - cw >= m:                  # a la izquierda
            x, y = target.left() - m - cw, target.center().y() - ch / 2
        elif target.bottom() + m + ch <= H - m:            # debajo
            x, y = target.center().x() - cw / 2, target.bottom() + m
        elif target.top() - m - ch >= m:                   # encima
            x, y = target.center().x() - cw / 2, target.top() - m - ch
        else:                                              # zona grande: dentro, abajo a la derecha
            x, y = target.right() - cw - 24, target.bottom() - ch - 24
        x = max(m, min(W - cw - m, x))
        y = max(m, min(H - ch - m, y))
        self.card.move(int(x), int(y))
        self.card.raise_()

    # ------------------------------------------------------------------ eventos
    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self.win and t in (QEvent.Type.Resize, QEvent.Type.WindowStateChange):
            QTimer.singleShot(0, self._relayout)
        elif t == QEvent.Type.ShortcutOverride and self.isVisible() and isinstance(obj, QWidget) and                 (obj is self or self.isAncestorOf(obj)) and ev.key() in TOUR_KEYS:
            ev.accept()  # así llega como pulsación normal al recorrido y no dispara el atajo
            return True
        return False

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_PageDown):
            self.next()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            self.prev()
        elif k == Qt.Key.Key_Escape:
            self.close_tutorial(False)
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        e.accept()  # la capa bloquea la aplicación mientras dura el recorrido

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = tm().theme
        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        if not self._hole.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(self._hole, 14, 14)
            dim = dim.subtracted(hole)
        p.fillPath(dim, QColor(0, 6, 20, 150 if t.dark else 120))
        if not self._hole.isNull():
            glow = QColor(t.accent)
            for width, alpha in ((7, 0.12), (4, 0.25), (1.6, 0.95)):
                glow.setAlphaF(alpha)
                p.setPen(QPen(glow, width))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(self._hole, 14, 14)
        p.end()
