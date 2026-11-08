"""Ajustes › Rendimiento y calidad visual.

Perfiles predefinidos (Ahorro de recursos, Equilibrado, Alto rendimiento, Máxima calidad), Personalizado y los
que guarde el usuario (crear, duplicar, renombrar, eliminar y elegir). Cada efecto se ajusta por separado;
hardware detectado con perfil recomendado y optimización automática. Los perfiles nunca quitan funciones:
cambian cómo se dibujan los efectos, cuánta memoria usan las miniaturas y cuánto trabajo va a la vez.

Al elegir o editar un perfil se escribe `quality_profile` / `quality_custom` / `quality_user` en los ajustes y
el controlador aplica el resultado al momento (`apply_quality`): fondo, visualizador, cristal, tareas, etc.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QGridLayout, QInputDialog, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from aero.core import quality
from aero.i18n import tr
from aero.ui.glass import h_layout, label

# (clave, texto, mínimo %, máximo %) — valores mostrados en porcentaje
PERCENT = [("bubbles", "Burbujas", 0, 150), ("clouds", "Nubes", 0, 150), ("particles", "Partículas", 0, 150),
           ("decor", "Decoración (césped, sol)", 0, 100), ("reflections", "Reflejos y ondas", 0, 100),
           ("shadows", "Sombras", 0, 100), ("anim_speed", "Velocidad de las animaciones", 25, 200)]
COUNTS = [("fps", "Fotogramas por segundo del fondo", " fps"), ("max_moving", "Elementos en movimiento", ""),
          ("thumbs", "Tamaño de las miniaturas", " px"),
          ("thumb_cache", "Miniaturas guardadas en memoria", ""),
          ("background", "Tareas en segundo plano a la vez", ""),
          ("heavy", "Tareas pesadas a la vez (conversiones…)", "")]
CHECKS = [("motion", "Fondo animado"), ("blur", "Desenfoque de Windows"), ("transitions", "Transiciones"),
          ("ambient", "Color de la portada en el cristal"), ("proxies", "Editor de vídeo con proxies")]
VIZ = [("low", "Sencillo"), ("normal", "Normal"), ("high", "Detallado")]
BUILTIN = ("ultra", "balanced", "performance", "high", "custom")


class PerformanceSettings(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        from aero.ui.pages.theme_studio import ValueSlider

        self.s = settings
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.hw_text = label("", "caption", wrap=True)
        self.rec_btn = QPushButton(tr("Usar el recomendado"))
        self.rec_btn.setProperty("kind", "flat")
        self.rec_btn.clicked.connect(lambda: self._choose(self._recommended))
        hw_row = h_layout(spacing=12)
        hw_row.addWidget(self.hw_text, 1)
        hw_row.addWidget(self.rec_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(hw_row)

        self.active = label("", "h3")
        self.active.setAccessibleName(tr("Perfil activo"))
        lay.addWidget(self.active)

        self.group = QButtonGroup(self)
        self.group.setExclusive(False)   # con un perfil propio activo no hay ninguno predefinido marcado
        self.buttons: dict[str, QPushButton] = {}
        row = h_layout(spacing=4)
        for key in BUILTIN:
            b = QPushButton(tr(quality.PROFILE_NAMES[key]))
            b.setCheckable(True)
            b.setProperty("kind", "flat")
            b.clicked.connect(lambda _c=False, k=key: self._choose(k))
            self.group.addButton(b)
            self.buttons[key] = b
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        mine_row = h_layout(spacing=4)
        self.mine = QComboBox()
        self.mine.setAccessibleName(tr("Mis perfiles"))
        self.mine.setMinimumWidth(200)
        self.mine.activated.connect(self._pick_mine)
        mine_row.addWidget(self.mine)
        self.new_btn = self._flat(tr("Nuevo…"), self._save_as, tr("Guarda los valores actuales como un perfil nuevo"))
        self.dup_btn = self._flat(tr("Duplicar"), self._duplicate, tr("Copia el perfil activo con otro nombre"))
        self.ren_btn = self._flat(tr("Renombrar…"), self._rename)
        self.delete = self._flat(tr("Eliminar"), self._delete)
        for b in (self.new_btn, self.dup_btn, self.ren_btn, self.delete):
            mine_row.addWidget(b)
        mine_row.addStretch(1)
        lay.addLayout(mine_row)
        lay.addWidget(label(tr("Los perfiles no quitan funciones: cambian cómo se dibujan los efectos y cuánto trabajo "
                            "se hace a la vez."), "caption", wrap=True))
        # Ajuste fino en un panel que se despliega a petición. Si el perfil activo es predefinido, el primer
        # cambio pasa a «Personalizado»; si es uno propio, se guarda en ese perfil.
        self.more = QPushButton(tr("Ajustar cada efecto"))
        self.more.setProperty("kind", "flat")
        self.more.setCheckable(True)
        self.detail = QWidget()
        detail = QVBoxLayout(self.detail)
        detail.setContentsMargins(0, 4, 0, 0)
        detail.setSpacing(10)
        self.detail.hide()
        self.more.toggled.connect(lambda on: (self.detail.setVisible(on), self.more.setText(
            tr("Ocultar el ajuste fino") if on else tr("Ajustar cada efecto"))))

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        self.sliders: dict[str, ValueSlider] = {}
        for i, (key, text, lo, hi) in enumerate(PERCENT):
            vs = ValueSlider(0.5, tr(text), minimum=lo, maximum=hi)
            vs.changed.connect(lambda v, k=key: self._edit(k, v))
            grid.addWidget(label(text, "muted"), i, 0)
            grid.addWidget(vs, i, 1)
            self.sliders[key] = vs
        self.spins: dict[str, QSpinBox] = {}
        base = len(PERCENT)
        for i, (key, text, suffix) in enumerate(COUNTS):
            sp = QSpinBox()
            lo, hi = quality.RANGES[key]
            sp.setRange(int(lo), int(hi))
            if suffix:
                sp.setSuffix(tr(suffix))
            if key == "thumb_cache":
                sp.setSingleStep(50)
            sp.setAccessibleName(tr(text))
            sp.setKeyboardTracking(False)
            sp.valueChanged.connect(lambda v, k=key: self._edit(k, v))
            grid.addWidget(label(text, "muted"), base + i, 0)
            grid.addWidget(sp, base + i, 1, Qt.AlignmentFlag.AlignLeft)
            self.spins[key] = sp
        self.viz = QComboBox()
        for key, text in VIZ:
            self.viz.addItem(tr(text), key)
        self.viz.setAccessibleName(tr("Detalle del visualizador"))
        self.viz.currentIndexChanged.connect(lambda _i: self._edit("viz", self.viz.currentData()))
        r = base + len(COUNTS)
        grid.addWidget(label(tr("Detalle del visualizador"), "muted"), r, 0)
        grid.addWidget(self.viz, r, 1, Qt.AlignmentFlag.AlignLeft)
        detail.addLayout(grid)
        self.checks: dict[str, QCheckBox] = {}
        crow = h_layout(spacing=20)
        for key, text in CHECKS:
            cb = QCheckBox(tr(text))
            cb.toggled.connect(lambda on, k=key: self._edit(k, on))
            crow.addWidget(cb)
            self.checks[key] = cb
        crow.addStretch(1)
        detail.addLayout(crow)

        self.auto = QCheckBox(tr("Optimización automática"))
        self.auto.setToolTip(tr("Reduce los efectos si el equipo va muy cargado y los recupera poco a poco. "
                                "Solo mide mientras algo se anima."))
        self.auto.setChecked(bool(settings.get("quality_auto")))
        self.auto.toggled.connect(lambda on: settings.set("quality_auto", on))
        self.auto_state = label("", "caption")
        lay.addLayout(h_layout(self.auto, self.auto_state, None, self.more, spacing=12))
        lay.addWidget(self.detail)

        from aero.ui.perf import auto_tuner

        auto_tuner().step_changed.connect(lambda _s: self._show_auto())
        settings.changed.connect(lambda k: k.startswith("quality_") and not self._loading and self.load())
        self._detect()
        self.load()

    def _flat(self, text: str, fn, tip: str = "") -> QPushButton:
        b = QPushButton(text)
        b.setProperty("kind", "flat")
        if tip:
            b.setToolTip(tip)
        b.clicked.connect(lambda: fn())
        return b

    # ------------------------------------------------------------------ hardware
    def _detect(self):
        from aero.core.hardware import detect, recommend

        hw = detect()
        scr = self.screen()
        if scr is not None:
            g = scr.geometry()
            hw.screen = (int(g.width() * scr.devicePixelRatio()), int(g.height() * scr.devicePixelRatio()))
        self._recommended, why = recommend(hw)
        self.hw_text.setText(tr("Este equipo: {hw}.\nRecomendado: {p}. {why}", hw=hw.summary(),
                                p=tr(quality.PROFILE_NAMES[self._recommended]), why=tr(why)))

    # ------------------------------------------------------------------ estado
    def current(self) -> str:
        return self.s.get("quality_profile") or quality.DEFAULT

    def _user(self) -> dict:
        return dict(self.s.get("quality_user") or {})

    def load(self):
        self._loading = True
        cur = self.current()
        own = cur.startswith("user:") and cur[5:] in self._user()
        for key, b in self.buttons.items():
            b.setChecked(cur == key)
        self.active.setText(tr("Perfil activo: {p}", p=cur[5:] if own else tr(quality.profile_label(cur))))
        user = self._user()
        self.mine.clear()
        self.mine.addItem(tr("Mis perfiles") if user else tr("Sin perfiles guardados"), "")
        for name in sorted(user, key=str.lower):
            self.mine.addItem(name, "user:" + name)
        self.mine.setCurrentIndex(max(0, self.mine.findData(cur)))
        self.delete.setEnabled(own)
        self.ren_btn.setEnabled(own)
        q = quality.resolve(self.s)
        for k, vs in self.sliders.items():
            vs.set_value(q[k])
        for k, sp in self.spins.items():
            sp.blockSignals(True)
            sp.setValue(int(q[k]))
            sp.blockSignals(False)
        self.viz.blockSignals(True)
        self.viz.setCurrentIndex(max(0, self.viz.findData(q["viz"])))
        self.viz.blockSignals(False)
        for k, cb in self.checks.items():
            cb.blockSignals(True)
            cb.setChecked(bool(q[k]))
            cb.blockSignals(False)
        self._show_auto()
        self._loading = False

    def _show_auto(self):
        from aero.ui.perf import auto_tuner

        t = auto_tuner()
        self.auto_state.setText("" if not t.enabled else
                                (tr("Calidad completa") if t.step == 0 else tr("Efectos reducidos (nivel {n})",
                                                                                  n=t.step)))

    # ------------------------------------------------------------------ acciones
    def _choose(self, key: str):
        if key == "custom" and not self.s.get("quality_custom"):
            # Primera vez: «Personalizado» parte de lo que se estaba usando, no de valores sueltos.
            self.s.set("quality_custom", quality.resolve(self.s))
        self.s.set("quality_profile", key)
        self.load()   # botones y valores al día aunque el perfil no cambie (p. ej. al pulsar el mismo)

    def _pick_mine(self, _i):
        key = self.mine.currentData()
        if key:
            self._choose(key)

    def _edit(self, key: str, value):
        if self._loading:
            return
        cur = self.current()
        values = quality.resolve(self.s)
        values[key] = value
        values = quality.normalize(values)
        if cur.startswith("user:") and cur[5:] in self._user():
            user = self._user()
            user[cur[5:]] = values
            self.s.set("quality_user", user)
        else:
            self.s.set("quality_custom", values)
            if cur != "custom":
                self.s.set("quality_profile", "custom")

    def _ask_name(self, title: str, text: str = "") -> str:
        name, ok = QInputDialog.getText(self, title, tr("Nombre del perfil:"), text=text)
        name = name.strip()[:40] if ok else ""
        if name and name in self._user() and name != text:
            QMessageBox.warning(self, title, tr("Ya hay un perfil con ese nombre."))
            return ""
        return name

    def _save_as(self):
        name = self._ask_name(tr("Guardar perfil"))
        if name:
            user = self._user()
            user[name] = quality.resolve(self.s)
            self.s.set("quality_user", user)
            self.s.set("quality_profile", "user:" + name)

    def _duplicate(self):
        base = quality.profile_label(self.current())
        if not self.current().startswith("user:"):
            base = tr(base)
        name = self._ask_name(tr("Duplicar perfil"), tr("{p} (copia)", p=base))
        if name:
            user = self._user()
            user[name] = quality.resolve(self.s)
            self.s.set("quality_user", user)
            self.s.set("quality_profile", "user:" + name)

    def _rename(self):
        cur = self.current()
        if not cur.startswith("user:"):
            return
        old = cur[5:]
        name = self._ask_name(tr("Renombrar perfil"), old)
        if name and name != old:
            user = self._user()
            user[name] = user.pop(old)
            self.s.set("quality_user", user)
            self.s.set("quality_profile", "user:" + name)

    def _delete(self):
        cur = self.current()
        if cur.startswith("user:"):
            user = self._user()
            values = user.pop(cur[5:], None)
            if values is not None:
                self.s.set("quality_custom", values)   # se sigue viendo igual, ahora como «Personalizado»
            self.s.set("quality_profile", "custom")
            self.s.set("quality_user", user)
