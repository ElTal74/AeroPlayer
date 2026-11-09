"""Panel de letras: la línea que suena resaltada y centrada, con desplazamiento suave.

Clic en una línea sincronizada: la canción salta a ese momento. Las letras sin marcas de tiempo se muestran
como texto que se puede desplazar.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QStackedLayout, QTextBrowser, QWidget

from aero.i18n import tr
from aero.ui.glass import tm

GAP = 10.0


class _SyncedView(QWidget):
    seek_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lines: list[tuple[int, str]] = []
        self.current = -1
        self._scroll = 0.0                  # posición (en líneas, puede ser fraccionaria) que queda centrada
        self._heights: list[float] = []
        self._tops: list[float] = []
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_scroll)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _font(self, current: bool) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF(max(10.0, self.font().pointSizeF() * (1.45 if current else 1.2)))
        f.setBold(current)
        return f

    def set_lines(self, lines):
        self.lines = list(lines)
        self.current = -1
        self._scroll = 0.0
        self._layout()
        self.update()

    def _layout(self):
        width = max(60.0, self.width() - 24.0)
        fm = QFontMetricsF(self._font(True))
        self._heights, self._tops = [], []
        y = 0.0
        flags = int(Qt.AlignmentFlag.AlignHCenter) | int(Qt.TextFlag.TextWordWrap)
        for _ms, text in self.lines:
            h = fm.boundingRect(QRectF(0, 0, width, 10000), flags, text or " ").height()
            self._tops.append(y)
            self._heights.append(h)
            y += h + GAP

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout()

    def _set_scroll(self, v):
        self._scroll = float(v)
        self.update()

    def set_index(self, i: int):
        if i == self.current:
            return
        self.current = i
        self._anim.stop()
        self._anim.setStartValue(self._scroll)
        self._anim.setEndValue(float(max(0, i)))
        self._anim.start()

    def _offset(self) -> float:
        """Desplazamiento vertical para que la línea `_scroll` quede al 42 % de la altura."""
        if not self._tops:
            return 0.0
        i = int(self._scroll)
        frac = self._scroll - i
        i = min(i, len(self._tops) - 1)
        y = self._tops[i] + self._heights[i] / 2
        if frac and i + 1 < len(self._tops):
            y2 = self._tops[i + 1] + self._heights[i + 1] / 2
            y += (y2 - y) * frac
        return self.height() * 0.42 - y

    def paintEvent(self, _e):
        if not self.lines:
            return
        th = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        off = self._offset()
        width = self.width() - 24.0
        flags = int(Qt.AlignmentFlag.AlignHCenter) | int(Qt.TextFlag.TextWordWrap)
        for i, ((_ms, text), top, h) in enumerate(zip(self.lines, self._tops, self._heights, strict=True)):
            y = top + off
            if y + h < 0 or y > self.height():
                continue
            cur = i == self.current
            dist = abs(i - self._scroll)
            p.setOpacity(1.0 if cur else max(0.28, 0.85 - dist * 0.12))
            p.setFont(self._font(cur))
            p.setPen(QColor(th.accent if cur else th.text))
            p.drawText(QRectF(12, y, width, h), flags, text or "♪")
        p.end()

    def _line_at(self, y: float) -> int:
        off = self._offset()
        for i, (top, h) in enumerate(zip(self._tops, self._heights, strict=True)):
            if top + off <= y <= top + off + h + GAP:
                return i
        return -1

    def mouseReleaseEvent(self, e):
        i = self._line_at(e.position().y())
        if 0 <= i < len(self.lines) and self.lines[i][0] >= 0:
            self.seek_requested.emit(self.lines[i][0])

    def wheelEvent(self, e):
        # La rueda mueve la vista un momento; al cambiar de línea vuelve a seguir la canción
        steps = -e.angleDelta().y() / 120.0
        self._anim.stop()
        self._scroll = max(0.0, min(len(self.lines) - 1.0, self._scroll + steps))
        self.update()


class LyricsPanel(QWidget):
    seek_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lyrics = None
        self.synced = _SyncedView()
        self.synced.seek_requested.connect(self.seek_requested)
        self.plain = QTextBrowser()
        self.plain.setOpenLinks(False)
        self.plain.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.plain.setStyleSheet("background: transparent;")
        self._stack = QStackedLayout(self)
        self._stack.addWidget(self.synced)
        self._stack.addWidget(self.plain)
        self.setMinimumWidth(240)
        self.setAccessibleName(tr("Letra"))

    def set_lyrics(self, ly) -> None:
        self.lyrics = ly
        if ly is None:
            self.synced.set_lines([])
            self.plain.clear()
            return
        if ly.synced:
            self.synced.set_lines(ly.lines)
            self._stack.setCurrentWidget(self.synced)
        else:
            self.plain.setPlainText(ly.text)
            self._stack.setCurrentWidget(self.plain)

    def set_position(self, ms: int) -> None:
        if self.lyrics is not None and self.lyrics.synced and self.isVisible():
            self.synced.set_index(self.lyrics.index_at(ms))
