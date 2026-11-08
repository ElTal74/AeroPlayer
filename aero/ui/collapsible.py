"""Sección plegable: título con flecha; el contenido se muestra al pulsarlo (opciones avanzadas)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLayout, QToolButton, QVBoxLayout, QWidget


class Collapsible(QWidget):
    def __init__(self, title: str, content: QLayout | QWidget, expanded: bool = False, parent=None):
        super().__init__(parent)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setStyleSheet("QToolButton { border: none; padding: 2px 0; font-weight: 600; }")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.body = content if isinstance(content, QWidget) else QWidget()
        if not isinstance(content, QWidget):
            self.body.setLayout(content)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.body)
        self.toggle.toggled.connect(self._sync)
        self._sync(expanded)

    def _sync(self, on: bool):
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.body.setVisible(on)
