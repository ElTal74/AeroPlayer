"""Galería de temas y editor de temas personalizados.

* Galería: tarjetas con vista previa real (el mismo render del fondo), selección con vista previa grande
  antes de aplicar, temas propios con duplicar / editar / eliminar / importar / exportar.
* Editor: colores, materiales (brillo, cristal, bordes, sombras), elementos decorativos con cantidad y
  tamaño, movimiento, composición e imagen de fondo propia. La vista previa se actualiza en vivo
  (renderizado pequeño y diferido, nunca sobre la ventana real).
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSlider,
                               QSpinBox, QToolButton, QVBoxLayout, QWidget)

from aero.ui.glasswindow import TrDialog
from aero.ui import icons
from aero.ui.glass import HoverLight, defer_paint, h_layout, label, paint_bubble, render_background, tm
from aero.ui.theme import (DECO_KEYS, DECO_LABELS, DIRECTIONS, LAYOUTS, PRESETS, normalize_spec, theme_from_spec)
from aero.i18n import tr

EXPORT_TAG = "aero_player_theme"


# ---------------------------------------------------------------------------------------------- vista previa
def render_preview(spec: dict, w: int, h: int, key: str = "preview") -> QPixmap:
    """Miniatura fiel del tema: fondo con su decoración y una ventana de muestra con cristal y botones."""
    t = theme_from_spec(key, spec)
    img = render_background(t, w, h, 0.92)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Panel de cristal de muestra
    panel = QRectF(w * 0.08 + 0.5, h * 0.16 + 0.5, w * 0.84, h * 0.62)
    path = QPainterPath()
    path.addRoundedRect(panel, 10, 10)
    g = QLinearGradient(0, panel.top(), 0, panel.bottom())
    a = 0.10 + 0.25 * float(t.spec.get("glass", 0.5)) if t.dark else 0.45 + 0.3 * float(t.spec.get("glass", 0.5))
    g.setColorAt(0, QColor(255, 255, 255, int(255 * min(1.0, a * 1.3))))
    g.setColorAt(1, QColor(255, 255, 255, int(255 * a * 0.7)))
    p.fillPath(path, g)
    p.setPen(QPen(QColor(255, 255, 255, int(90 + 120 * float(t.spec.get("edge", 0.6)))), 1))
    p.drawPath(path)
    # Texto simulado
    p.setPen(Qt.PenStyle.NoPen)
    tc = QColor(t.text)
    for i, frac in enumerate((0.42, 0.30, 0.36)):
        tc.setAlpha(200 if i == 0 else 110)
        p.setBrush(tc)
        p.drawRoundedRect(QRectF(panel.left() + 12, panel.top() + 12 + i * 11, panel.width() * frac, 5), 2.5, 2.5)
    # Botón de gel y burbuja de reproducción
    btn = QRectF(panel.left() + 12, panel.bottom() - 26, panel.width() * 0.34, 16)
    bp = QPainterPath()
    bp.addRoundedRect(btn, 8, 8)
    bg = QLinearGradient(0, btn.top(), 0, btn.bottom())
    bg.setColorAt(0, QColor(t.accent).lighter(130))
    bg.setColorAt(1, QColor(t.accent2))
    p.fillPath(bp, bg)
    p.setPen(QPen(QColor(255, 255, 255, 200), 1))
    p.drawPath(bp)
    paint_bubble(p, QPointF(panel.right() - 24, panel.bottom() - 20), 12, QColor(t.accent), fill=0.25, rim=1.0)
    p.end()
    return QPixmap.fromImage(img)


class ThemeCard(QToolButton):
    """Tarjeta de la galería: miniatura, nombre y marcas de «activo»."""
    chosen = Signal(str)
    applied = Signal(str)

    W, H = 168, 104

    def __init__(self, key: str, spec: dict, parent=None):
        super().__init__(parent)
        self.key, self.spec = key, spec
        self.active = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.W + 12, self.H + 36)
        self.setToolTip(spec.get("name", key))
        self.setAccessibleName(f"Tema {spec.get('name', key)}")
        self.light = HoverLight(self)
        self._pix = None          # la miniatura se renderiza al mostrarse, una tarjeta por vuelta del bucle
        self._queued = False
        self.clicked.connect(lambda: self.chosen.emit(self.key))

    def _ensure(self):
        self._queued = False
        if self._pix is None:
            self._pix = render_preview(self.spec, self.W * 2, self.H * 2, self.key)
            self._pix.setDevicePixelRatio(2.0)
            self.update()

    def mouseDoubleClickEvent(self, e):
        self.applied.emit(self.key)

    def paintEvent(self, e):
        t = tm().theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(6.5, 4.5, self.W - 1, self.H - 1)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.save()
        p.setClipPath(path)
        if self._pix is None:
            if not self._queued:
                self._queued = True
                defer_paint(self._ensure)
            p.fillPath(path, QColor(t.bg[0][1]))
        else:
            p.drawPixmap(r, self._pix, QRectF(self._pix.rect()))
        if self.light.value > 0.01:
            p.fillPath(path, QColor(255, 255, 255, int(28 * self.light.value)))
        p.restore()
        sel = self.isChecked()
        edge = QColor(t.accent) if sel else QColor(255, 255, 255, int(110 + 100 * self.light.value))
        p.setPen(QPen(edge, 2 if sel else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        if self.active:
            paint_bubble(p, QPointF(r.right() - 13, r.top() + 13), 8, QColor(t.accent2), fill=0.6, rim=1.0)
            pm = icons.pixmap("check", "#ffffff", 10)
            p.drawPixmap(QRectF(r.right() - 18, r.top() + 8, 10, 10), pm, QRectF(pm.rect()))
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        f.setBold(sel or self.active)
        p.setFont(f)
        p.setPen(QColor(t.text))
        name = p.fontMetrics().elidedText(self.spec.get("name", self.key), Qt.TextElideMode.ElideRight, self.W)
        p.drawText(QRectF(6, self.H + 8, self.W, 22), Qt.AlignmentFlag.AlignCenter, name)


class ValueSlider(QWidget):
    """Deslizador con valor visible y editable (teclado o escribiendo). Emite como mucho un cambio por
    fotograma mientras se arrastra, de modo que la ventana nunca se bloquea."""
    changed = Signal(float)

    def __init__(self, value: float, tip: str = "", parent=None, minimum: int = 0, maximum: int = 100,
                 suffix: str = " %"):
        super().__init__(parent)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setPageStep(10)
        self.slider.setSingleStep(1)
        self.slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.slider.setToolTip(tip)
        self.slider.setAccessibleName(tip)
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(74)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.spin.setAccessibleName(tip)
        self.spin.setKeyboardTracking(False)
        self.set_value(value)
        self._pending = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._flush)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)

    def value(self) -> float:
        return self.slider.value() / 100

    def set_value(self, v: float) -> None:
        iv = int(round(float(v) * 100))
        for w in (self.slider, self.spin):
            w.blockSignals(True)
            w.setValue(iv)
            w.blockSignals(False)

    def _from_slider(self, v: int):
        self.spin.blockSignals(True)
        self.spin.setValue(v)
        self.spin.blockSignals(False)
        self._pending = v / 100
        if not self._timer.isActive():
            self._timer.start()

    def _from_spin(self, v: int):
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self._pending = v / 100
        self._flush()

    def _flush(self):
        if self._pending is not None:
            v, self._pending = self._pending, None
            self.changed.emit(v)


class ColorButton(QPushButton):
    """Botón con una muestra de color redonda; abre el selector de color."""
    picked = Signal(str)

    def __init__(self, text: str, color: str, parent=None):
        super().__init__(text, parent)
        self.color = color
        self.setIconSize(QSize(16, 16))
        self.clicked.connect(self._pick)
        self._paint_icon()

    def set_color(self, c: str):
        self.color = c
        self._paint_icon()

    def _paint_icon(self):
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(self.color))
        p.setPen(QPen(QColor(255, 255, 255, 220), 2))
        p.drawEllipse(QRectF(2, 2, 28, 28))
        p.end()
        pm.setDevicePixelRatio(2.0)
        self.setIcon(pm)

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, "Elegir color")
        if c.isValid():
            self.set_color(c.name())
            self.picked.emit(c.name())


# ---------------------------------------------------------------------------------------------- editor
class ThemeEditor(TrDialog):
    """Constructor de temas: todo lo que define un tema, con vista previa en vivo."""

    def __init__(self, spec: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Editar tema"))
        self.setMinimumSize(900, 640)
        self.spec = normalize_spec(spec)
        self.preview = QLabel()
        self.preview.setFixedSize(400, 250)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._render)

        form = QWidget()
        col = QVBoxLayout(form)
        col.setContentsMargins(0, 0, 10, 0)
        col.setSpacing(10)
        self.name = QLineEdit(self.spec["name"])
        self.name.setPlaceholderText(tr("Nombre del tema"))
        self.name.textChanged.connect(lambda v: self._set("name", v.strip() or "Mi tema"))
        col.addWidget(label("Nombre", "h3"))
        col.addWidget(self.name)

        col.addWidget(label("Colores", "h3"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        for i, (key, text) in enumerate((("bg1", "Fondo 1"), ("bg2", "Fondo 2"), ("bg3", "Fondo 3"),
                                         ("accent", "Principal"), ("accent2", "Secundario"),
                                         ("highlight", "Reflejos"))):
            b = ColorButton(text, self.spec[key])
            b.picked.connect(lambda c, k=key: self._set(k, c))
            grid.addWidget(b, i // 3, i % 3)
        col.addLayout(grid)
        light = QCheckBox(tr("Cristal claro (texto oscuro)"))
        light.setChecked(self.spec["light"])
        light.toggled.connect(lambda on: self._set("light", on))
        col.addWidget(light)

        col.addWidget(label("Materiales", "h3"))
        mats = QGridLayout()
        mats.setHorizontalSpacing(12)
        for i, (key, text) in enumerate((("glow", "Brillos"), ("glass", "Cristal de los paneles"),
                                         ("edge", "Bordes"), ("shadow", "Sombras"))):
            vs = ValueSlider(self.spec[key], text)
            vs.changed.connect(lambda v, k=key: self._set(k, v))
            mats.addWidget(label(text, "muted"), i, 0)
            mats.addWidget(vs, i, 1)
        col.addLayout(mats)

        col.addWidget(label(tr("Elementos decorativos"), "h3"))
        deco = QGridLayout()
        deco.setHorizontalSpacing(12)
        deco.addWidget(label("Cantidad", "caption"), 0, 1)
        deco.addWidget(label(tr("Tamaño"), "caption"), 0, 2)
        self._deco_rows = {}
        for i, key in enumerate(DECO_KEYS, start=1):
            d = self.spec["deco"][key]
            cb = QCheckBox(DECO_LABELS[key])
            cb.setChecked(bool(d["on"]))
            amount = ValueSlider(d["amount"], f"Cantidad de {DECO_LABELS[key].lower()}")
            size = ValueSlider(d["size"] / 2, f"Tamaño de {DECO_LABELS[key].lower()}")
            cb.toggled.connect(lambda on, k=key: self._deco(k, "on", on))
            amount.changed.connect(lambda v, k=key: self._deco(k, "amount", v))
            size.changed.connect(lambda v, k=key: self._deco(k, "size", max(0.2, v * 2)))
            deco.addWidget(cb, i, 0)
            deco.addWidget(amount, i, 1)
            deco.addWidget(size, i, 2)
        col.addLayout(deco)

        col.addWidget(label(tr("Movimiento y composición"), "h3"))
        motion = QGridLayout()
        motion.setHorizontalSpacing(12)
        speed = ValueSlider(self.spec["motion"]["speed"], "Velocidad del movimiento (0 = quieto)")
        speed.changed.connect(lambda v: self._motion("speed", v))
        direction = QComboBox()
        for k, v in DIRECTIONS.items():
            direction.addItem(v, k)
        direction.setCurrentIndex(max(0, direction.findData(self.spec["motion"]["dir"])))
        direction.currentIndexChanged.connect(lambda _i: self._motion("dir", direction.currentData()))
        layout = QComboBox()
        for k, v in LAYOUTS.items():
            layout.addItem(v, k)
        layout.setCurrentIndex(max(0, layout.findData(self.spec["layout"])))
        layout.currentIndexChanged.connect(lambda _i: self._set("layout", layout.currentData()))
        motion.addWidget(label("Velocidad", "muted"), 0, 0)
        motion.addWidget(speed, 0, 1, 1, 3)
        motion.addWidget(label(tr("Dirección"), "muted"), 1, 0)
        motion.addWidget(direction, 1, 1)
        motion.addWidget(label(tr("Distribución"), "muted"), 1, 2)
        motion.addWidget(layout, 1, 3)
        col.addLayout(motion)

        col.addWidget(label("Fondo", "h3"))
        self.img_label = label(Path(self.spec["image"]).name if self.spec["image"] else tr("Sin imagen"), "muted")
        pick = QPushButton(tr("Elegir imagen…"))
        pick.clicked.connect(self._pick_image)
        clear = QPushButton(tr("Quitar"))
        clear.setProperty("kind", "flat")
        clear.clicked.connect(lambda: (self._set("image", ""), self.img_label.setText(tr("Sin imagen"))))
        img_op = ValueSlider(self.spec["image_opacity"], "Opacidad de la imagen")
        img_op.changed.connect(lambda v: self._set("image_opacity", v))
        col.addLayout(h_layout(pick, clear, self.img_label, None))
        col.addLayout(h_layout(label("Opacidad", "muted"), img_op, spacing=12))
        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(form)
        ok = QPushButton(tr("Guardar"))
        ok.setProperty("kind", "primary")
        ok.clicked.connect(self.accept)
        cancel = QPushButton(tr("Cancelar"))
        cancel.clicked.connect(self.reject)
        side = QVBoxLayout()
        side.addWidget(label(tr("Vista previa"), "h3"))
        side.addWidget(self.preview)
        side.addWidget(label(tr("Los elementos móviles se animan en la ventana real; aquí se ven quietos."),
                             "caption", wrap=True))
        side.addStretch(1)
        side.addLayout(h_layout(None, cancel, ok))
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)
        root.addWidget(scroll, 1)
        root.addLayout(side)
        self._render()

    def _set(self, key, value):
        self.spec[key] = value
        self._timer.start()

    def _deco(self, key, field, value):
        self.spec["deco"][key][field] = value
        self._timer.start()

    def _motion(self, field, value):
        self.spec["motion"][field] = value
        self._timer.start()

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Imagen de fondo"), "",
                                              "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._set("image", path)
            self.img_label.setText(Path(path).name)

    def _render(self):
        pm = render_preview(self.spec, 800, 500)
        pm.setDevicePixelRatio(2.0)
        self.preview.setPixmap(pm)

    def result_spec(self) -> dict:
        return normalize_spec(self.spec)


# ---------------------------------------------------------------------------------------------- galería
class ThemeGallery(QWidget):
    """Galería: tarjetas de temas, vista previa grande y acciones sobre el seleccionado."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.selected = settings.get("theme")
        self.cards: dict[str, ThemeCard] = {}
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        self.big = QLabel()
        self.big.setFixedSize(300, 186)
        self.big_name = label("", "h3")
        self.big_info = label("", "caption", wrap=True)
        self.apply_btn = QPushButton(tr("Aplicar"))
        self.apply_btn.setProperty("kind", "primary")
        self.apply_btn.clicked.connect(lambda: self.apply(self.selected))
        self.dup_btn = QPushButton(tr("Duplicar y editar"))
        self.dup_btn.clicked.connect(self._duplicate)
        self.edit_btn = QPushButton(tr("Editar"))
        self.edit_btn.clicked.connect(self._edit)
        self.del_btn = QPushButton(tr("Eliminar"))
        self.del_btn.setProperty("kind", "danger")
        self.del_btn.clicked.connect(self._delete)
        self.export_btn = QPushButton(tr("Exportar…"))
        self.export_btn.setProperty("kind", "flat")
        self.export_btn.clicked.connect(self._export)
        imp = QPushButton(tr("Importar…"))
        imp.setProperty("kind", "flat")
        imp.clicked.connect(self._import)
        new = QPushButton(tr("Nuevo tema"))
        new.clicked.connect(self._new)
        side = QVBoxLayout()
        side.setSpacing(8)
        side.addWidget(self.big)
        side.addWidget(self.big_name)
        side.addWidget(self.big_info)
        side.addLayout(h_layout(self.apply_btn, self.dup_btn))
        side.addLayout(h_layout(self.edit_btn, self.del_btn, None))
        side.addLayout(h_layout(new, imp, self.export_btn, None))
        side.addStretch(1)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)
        root.addWidget(self.grid_host, 1, Qt.AlignmentFlag.AlignTop)
        root.addLayout(side)
        self.grid_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.rebuild()

    # ------------------------------------------------------------------ datos
    def specs(self) -> dict[str, dict]:
        out = {k: v for k, v in PRESETS.items()}
        for tid, spec in (self.s.get("user_themes") or {}).items():
            out[f"user:{tid}"] = normalize_spec(spec)
        return out

    def rebuild(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.cards.clear()
        specs = self.specs()
        cols = 4
        for i, (key, spec) in enumerate(specs.items()):
            c = ThemeCard(key, spec)
            c.chosen.connect(self.select)
            c.applied.connect(self.apply)
            c.active = key == self.s.get("theme")
            self.cards[key] = c
            self.grid.addWidget(c, i // cols, i % cols)
        if self.selected not in specs:
            self.selected = self.s.get("theme") if self.s.get("theme") in specs else "burbuja"
        self.select(self.selected)

    def select(self, key: str):
        self.selected = key
        for k, c in self.cards.items():
            c.setChecked(k == key)
        spec = self.specs().get(key, PRESETS["burbuja"])
        pm = render_preview(spec, 600, 372, key)
        pm.setDevicePixelRatio(2.0)
        self.big.setPixmap(pm)
        self.big_name.setText(spec.get("name", key))
        on = [DECO_LABELS[k] for k in DECO_KEYS if spec["deco"][k]["on"] and k != "sun"]
        moving = float(spec["motion"]["speed"]) > 0
        self.big_info.setText((", ".join(on) if on else tr("Sin decoración")) + (tr(" · con movimiento") if moving else ""))
        user = key.startswith("user:")
        self.edit_btn.setVisible(user)
        self.del_btn.setVisible(user)
        self.export_btn.setEnabled(True)
        is_active = key == self.s.get("theme")
        self.apply_btn.setEnabled(not is_active)
        self.apply_btn.setText("Activo" if is_active else "Aplicar")

    def apply(self, key: str):
        self.s.set("theme", key)
        for k, c in self.cards.items():
            c.active = k == key
            c.update()
        self.select(key)

    # ------------------------------------------------------------------ acciones
    def _save_user(self, tid: str, spec: dict):
        themes = dict(self.s.get("user_themes") or {})
        themes[tid] = spec
        self.s.set("user_themes", themes)

    def _edit_dialog(self, spec: dict) -> dict | None:
        dlg = ThemeEditor(spec, self)
        return dlg.result_spec() if dlg.exec() else None

    def _new(self):
        base = copy.deepcopy(PRESETS["burbuja"])
        base["name"] = "Mi tema"
        self._create(base)

    def _duplicate(self):
        spec = copy.deepcopy(self.specs().get(self.selected, PRESETS["burbuja"]))
        spec["name"] = f"{spec.get('name', 'Tema')} (copia)"
        self._create(spec)

    def _create(self, spec: dict):
        out = self._edit_dialog(spec)
        if out is None:
            return
        tid = uuid.uuid4().hex[:10]
        self._save_user(tid, out)
        self.selected = f"user:{tid}"
        self.rebuild()
        self.apply(self.selected)

    def _edit(self):
        if not self.selected.startswith("user:"):
            return
        tid = self.selected[5:]
        out = self._edit_dialog(self.specs()[self.selected])
        if out is None:
            return
        self._save_user(tid, out)
        self.rebuild()

    def _delete(self):
        if not self.selected.startswith("user:"):
            return
        name = self.specs()[self.selected].get("name", "")
        if QMessageBox.question(self, tr("Eliminar tema"), tr("¿Eliminar el tema «{name}»?", name=name)) != \
                QMessageBox.StandardButton.Yes:
            return
        themes = dict(self.s.get("user_themes") or {})
        themes.pop(self.selected[5:], None)
        if self.s.get("theme") == self.selected:
            self.s.set("theme", "burbuja")
        self.s.set("user_themes", themes)
        self.selected = self.s.get("theme")
        self.rebuild()

    def _export(self):
        spec = self.specs().get(self.selected)
        if spec is None:
            return
        name = "".join(c if c.isalnum() or c in " -_" else "_" for c in spec.get("name", "tema")).strip() or "tema"
        path, _ = QFileDialog.getSaveFileName(self, tr("Exportar tema"), f"{name}.aerotheme.json",
                                              "Tema de AERO Player (*.json)")
        if path:
            Path(path).write_text(json.dumps({EXPORT_TAG: 1, "spec": spec}, ensure_ascii=False, indent=2),
                                  encoding="utf-8")

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Importar tema"), "", "Tema de AERO Player (*.json)")
        if not path:
            return
        try:
            spec = import_theme(path)
        except ValueError as e:
            QMessageBox.warning(self, tr("Importar tema"), str(e))
            return
        tid = uuid.uuid4().hex[:10]
        self._save_user(tid, spec)
        self.selected = f"user:{tid}"
        self.rebuild()


def import_theme(path: str) -> dict:
    """Lee un tema exportado. Valida la estructura y descarta cualquier clave desconocida."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"No se pudo leer el archivo: {e}") from e
    if not isinstance(data, dict) or EXPORT_TAG not in data or not isinstance(data.get("spec"), dict):
        raise ValueError("El archivo no es un tema de AERO Player.")
    return normalize_spec(data["spec"])
