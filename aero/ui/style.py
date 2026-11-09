"""Estilo de dibujo propio (QProxyStyle sobre Fusion) para los controles estándar de Qt.

Por qué existe: las hojas de estilo de Qt dibujan los bordes redondeados centrados en el límite del píxel
(líneas de 1 px repartidas entre dos píxeles, curvas dentadas) y no permiten un borde uniforme con brillo
de gel. Aquí todos los botones, campos, pestañas, menús, deslizadores y descripciones emergentes se pintan
con el mismo trazo: rectángulos alineados a medio píxel, suavizado, un borde continuo en todo el perímetro
y el anillo de foco dibujado *hacia dentro* (nunca se recorta).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QRadialGradient
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QMenu, QProxyStyle, QPushButton, QSlider, QStyle,
                               QStyleFactory, QStyleOptionMenuItem, QTabBar, QWidget)

# Radios del sistema visual (en píxeles lógicos): un solo juego para toda la aplicación.
R_BUTTON = 12
R_FIELD = 12
R_MENU = 12
R_ITEM = 8


def _a(color, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def crisp(rect) -> QRectF:
    """Rectángulo con el trazo de 1 px centrado en el píxel (línea nítida, no repartida en dos)."""
    return QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)


def rounded(r: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    rad = min(radius, r.height() / 2, r.width() / 2)
    path.addRoundedRect(r, rad, rad)
    return path


def paint_glass_button(p: QPainter, rect, *, hover=False, pressed=False, checked=False, focus=False,
                       enabled=True, kind: str = "", radius: float = R_BUTTON) -> None:
    """Botón de cristal/gel: relleno con casquete brillante, borde uniforme y brillo de acento al pasar."""
    from aero.ui.glass import tm

    t, g = tm().theme, tm().glass
    dark = t.dark
    r = crisp(rect)
    path = rounded(r, radius)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not enabled:
        p.setOpacity(p.opacity() * 0.45)        # desactivado: se nota que no se puede pulsar
        hover = pressed = False
    if kind == "flat" and not (hover or pressed or checked):
        if focus:
            p.setPen(QPen(_a(t.accent, 0.9), 1))
            p.drawPath(rounded(r.adjusted(1, 1, -1, -1), radius - 1))
        p.restore()
        return
    accent = QColor(t.accent)
    if kind == "primary" or checked:
        k = 0.95 if kind == "primary" else 0.45
        top = _a(accent.lighter(130), k * (1.0 if hover else 0.9))
        bottom = _a(QColor(t.accent2), k * 0.75)
    elif dark:
        base = 0.16 if hover else 0.10
        top, bottom = _a("#ffffff", base + 0.06), _a("#ffffff", base * 0.45)
    else:
        top, bottom = _a("#ffffff", 0.98 if hover else 0.88), _a("#e6f4ff", 0.85 if hover else 0.70)
    if pressed:
        top, bottom = bottom, top
    fill = QLinearGradient(0, r.top(), 0, r.bottom())
    fill.setColorAt(0, top)
    fill.setColorAt(1, bottom)
    p.fillPath(path, fill)
    if hover and not pressed:
        # Luz de acento que «sube» desde la base: el botón se ilumina en lugar de crecer.
        glow = QRadialGradient(QPointF(r.center().x(), r.bottom() + r.height() * 0.2), r.width() * 0.6)
        glow.setColorAt(0, _a(accent, 0.40 if dark else 0.30))
        glow.setColorAt(1, _a(accent, 0.0))
        p.fillPath(path, glow)
    # Casquete brillante (gel): mitad superior, recortado por la propia forma.
    cap_r = QRectF(r.left() + 1.5, r.top() + 1.5, r.width() - 3, r.height() * 0.48)
    cap = QLinearGradient(0, cap_r.top(), 0, cap_r.bottom())
    shine = (0.30 if dark else 0.75) * (0.55 if pressed else 1.0) * (0.6 + 0.4 * g.glow)
    cap.setColorAt(0, _a("#ffffff", shine))
    cap.setColorAt(1, _a("#ffffff", 0.0))
    p.fillPath(rounded(cap_r, max(2.0, radius - 1.5)), cap)
    # Borde continuo en todo el perímetro (mismo color arriba y abajo).
    if kind == "danger" and hover:
        edge = QColor("#ff6b81")
    elif hover or checked:
        edge = _a(accent, 0.95) if kind != "primary" else _a("#ffffff", 0.95)
    else:
        edge = _a("#ffffff", (0.42 if dark else 0.95) * (0.5 + 0.5 * g.edge))
    if not enabled:
        edge = _a(edge, edge.alphaF() * 0.45)
    p.setPen(QPen(edge, 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    # Brillo interior fino, también continuo: da volumen sin oscurecer ningún lado.
    p.setPen(QPen(_a("#ffffff", 0.16 if dark else 0.55), 1))
    p.drawPath(rounded(r.adjusted(1, 1, -1, -1), radius - 1))
    if focus:
        p.setPen(QPen(_a(t.accent, 1.0), 1.5))
        p.drawPath(rounded(r.adjusted(1.75, 1.75, -1.75, -1.75), radius - 1.75))
    p.restore()


def paint_field(p: QPainter, rect, *, focus=False, hover=False, enabled=True, radius: float = R_FIELD) -> None:
    """Campo de texto: cristal hundido con borde uniforme; con foco, borde de acento interior."""
    from aero.ui.glass import tm

    t = tm().theme
    r = crisp(rect)
    path = rounded(r, radius)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if tm().glass.solid and not t.dark:
        p.fillPath(path, QColor(t.solid))
    else:
        p.fillPath(path, _a("#ffffff", (0.07 if t.dark else 0.72) + (0.03 if hover else 0.0)))
    edge = _a(t.accent, 1.0) if focus else _a("#ffffff" if t.dark else "#0a3a66", 0.30 if t.dark else 0.24)
    p.setPen(QPen(edge, 1))
    p.drawPath(path)
    if focus:
        p.setPen(QPen(_a(t.accent, 0.45), 1))
        p.drawPath(rounded(r.adjusted(1, 1, -1, -1), radius - 1))
    p.restore()


def paint_popup(p: QPainter, rect, radius: float = R_MENU) -> None:
    """Fondo de menús y descripciones: cristal denso con borde de luz uniforme."""
    from aero.ui.glass import tm

    t = tm().theme
    r = crisp(rect)
    path = rounded(r, radius)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    p.fillRect(QRectF(rect), Qt.GlobalColor.transparent)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    g = QLinearGradient(0, r.top(), 0, r.bottom())
    base = QColor(t.solid)
    g.setColorAt(0, _a(base.lighter(125 if t.dark else 100), 0.97))
    g.setColorAt(1, _a(base, 0.97))
    p.fillPath(path, g)
    p.setPen(QPen(_a("#ffffff", 0.30 if t.dark else 0.95), 1))
    p.drawPath(path)
    p.setPen(QPen(_a("#ffffff", 0.08 if t.dark else 0.5), 1))
    p.drawPath(rounded(r.adjusted(1, 1, -1, -1), radius - 1))
    p.restore()


def paint_slider_handle(p: QPainter, c: QPointF, rad: float, *, hover=False, pressed=False, focus=False) -> None:
    """Asa de deslizador: burbuja perfectamente circular (centro y radio en coordenadas reales)."""
    from aero.ui.glass import paint_bubble, tm

    t = tm().theme
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_a("#000000", 0.18))
    p.drawEllipse(QPointF(c.x(), c.y() + 1), rad, rad)
    body = QRadialGradient(QPointF(c.x() - rad * 0.3, c.y() - rad * 0.35), rad * 1.3)
    body.setColorAt(0, _a("#ffffff", 0.98))
    body.setColorAt(0.55, _a("#ffffff", 0.80 if not pressed else 0.65))
    body.setColorAt(1, _a(t.accent, 0.85))
    p.setBrush(body)
    p.drawEllipse(c, rad, rad)
    paint_bubble(p, c, rad, QColor(t.accent), fill=0.10, rim=0.9 if hover else 0.7)
    if focus:
        p.setPen(QPen(_a(t.accent, 1.0), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, rad - 2.2, rad - 2.2)
    p.restore()


class AeroStyle(QProxyStyle):
    """Dibuja los controles estándar con el lenguaje visual de AERO Player."""

    def __init__(self):
        super().__init__(QStyleFactory.create("Fusion"))

    # ------------------------------------------------------------------ preparación de widgets
    def polish(self, arg):
        r = super().polish(arg)
        if isinstance(arg, QWidget):
            w = arg
            if isinstance(w, (QPushButton, QComboBox, QTabBar, QSlider)):
                w.setAttribute(Qt.WidgetAttribute.WA_Hover)
            # Menús, desplegables y descripciones: ventanas emergentes con esquinas de verdad transparentes
            # (si no, Windows rellena las esquinas del rectángulo y se ven picos oscuros).
            if isinstance(w, QMenu) or w.inherits("QComboBoxPrivateContainer") or w.inherits("QTipLabel"):
                if not w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
                    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                    w.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
                    w.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        return r

    # ------------------------------------------------------------------ medidas
    def pixelMetric(self, m, opt=None, w=None):
        PM = QStyle.PixelMetric
        if m == PM.PM_SliderLength:
            return 18
        if m == PM.PM_SliderThickness:
            return 22
        if m == PM.PM_SliderControlThickness:
            return 18
        if m in (PM.PM_MenuPanelWidth,):
            return 1
        if m in (PM.PM_MenuHMargin, PM.PM_MenuVMargin):
            return 5
        if m == PM.PM_DefaultFrameWidth and isinstance(w, QMenu):
            return 1
        if m == PM.PM_ButtonShiftHorizontal or m == PM.PM_ButtonShiftVertical:
            return 0
        if m == PM.PM_TabBarTabHSpace:
            return 30
        if m == PM.PM_TabBarTabVSpace:
            return 14
        if m == PM.PM_ToolTipLabelFrameWidth:
            return 7
        return super().pixelMetric(m, opt, w)

    def sizeFromContents(self, ct, opt, size, w=None):
        CT = QStyle.ContentsType
        s = super().sizeFromContents(ct, opt, size, w)
        if ct == CT.CT_PushButton:
            return QSize(max(s.width() + 12, 72 if opt.text else s.width()), max(s.height(), 34))
        if ct == CT.CT_LineEdit:
            return QSize(s.width(), max(s.height(), 34))
        if ct == CT.CT_ComboBox:
            return QSize(s.width() + 14, max(s.height(), 34))
        if ct == CT.CT_SpinBox:
            return QSize(s.width(), max(s.height(), 34))
        if ct == CT.CT_MenuItem:
            if opt.menuItemType == QStyleOptionMenuItem.MenuItemType.Separator:
                return QSize(s.width(), 11)
            return QSize(s.width() + 18, max(s.height(), 30))
        if ct == CT.CT_TabBarTab:
            return QSize(s.width(), max(s.height(), 32))
        return s

    def styleHint(self, hint, opt=None, w=None, ret=None):
        SH = QStyle.StyleHint
        if hint == SH.SH_Menu_Mask or hint == SH.SH_ToolTip_Mask:
            return 0
        if hint == SH.SH_ComboBox_Popup:
            return 1  # el desplegable usa el mismo panel que los menús
        return super().styleHint(hint, opt, w, ret)

    # ------------------------------------------------------------------ primitivas
    def drawPrimitive(self, el, opt, p, w=None):
        PE = QStyle.PrimitiveElement
        st = opt.state
        S = QStyle.StateFlag
        if el == PE.PE_PanelButtonCommand:
            kind = str(w.property("kind") or "") if w is not None else ""
            paint_glass_button(p, opt.rect, hover=bool(st & S.State_MouseOver), pressed=bool(st & S.State_Sunken),
                               checked=bool(st & S.State_On), focus=bool(st & S.State_HasFocus)
                               and bool(st & S.State_KeyboardFocusChange), enabled=bool(st & S.State_Enabled),
                               kind=kind)
            return
        if el == PE.PE_PanelButtonTool:
            if st & (S.State_MouseOver | S.State_Sunken | S.State_On):
                paint_glass_button(p, opt.rect, hover=bool(st & S.State_MouseOver), pressed=bool(st & S.State_Sunken),
                                   checked=bool(st & S.State_On))
            return
        if el == PE.PE_FrameFocusRect:
            return  # el foco se dibuja dentro de cada control
        if el in (PE.PE_PanelLineEdit, PE.PE_FrameLineEdit):
            if w is not None and isinstance(w.parentWidget(), (QComboBox, QAbstractSpinBox)):
                return  # el control contenedor ya dibuja el campo
            if el == PE.PE_PanelLineEdit:
                paint_field(p, opt.rect, focus=bool(st & S.State_HasFocus), hover=bool(st & S.State_MouseOver),
                            enabled=bool(st & S.State_Enabled))
            return
        if el in (PE.PE_PanelMenu, PE.PE_FrameMenu):
            if el == PE.PE_PanelMenu:
                paint_popup(p, opt.rect)
            return
        if el == PE.PE_PanelTipLabel:
            paint_popup(p, opt.rect, 9)
            return
        if el == PE.PE_FrameTabBarBase:
            return
        if el == PE.PE_IndicatorArrowDown and w is not None and isinstance(w, QComboBox):
            self._chevron(p, QRectF(opt.rect), opt.palette.color(QPalette.ColorRole.Text))
            return
        super().drawPrimitive(el, opt, p, w)

    @staticmethod
    def _chevron(p: QPainter, r: QRectF, color: QColor):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(_a(color, 0.75), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        c = r.center()
        path = QPainterPath()
        path.moveTo(c.x() - 4, c.y() - 2)
        path.lineTo(c.x(), c.y() + 2)
        path.lineTo(c.x() + 4, c.y() - 2)
        p.drawPath(path)
        p.restore()

    # ------------------------------------------------------------------ controles
    def drawControl(self, el, opt, p, w=None):
        CE = QStyle.ControlElement
        S = QStyle.StateFlag
        st = opt.state
        if el == CE.CE_TabBarTabShape:
            sel = bool(st & S.State_Selected)
            hover = bool(st & S.State_MouseOver)
            if sel or hover:
                r = QRect(opt.rect).adjusted(2, 3, -2, -3)
                paint_glass_button(p, r, hover=hover and not sel, checked=sel, radius=R_BUTTON)
            return
        if el == CE.CE_MenuItem:
            self._menu_item(opt, p, w)
            return
        if el == CE.CE_MenuEmptyArea:
            return
        super().drawControl(el, opt, p, w)

    def _menu_item(self, opt, p: QPainter, w):
        from aero.ui.glass import tm

        t = tm().theme
        S = QStyle.StateFlag
        r = QRectF(opt.rect)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if opt.menuItemType == QStyleOptionMenuItem.MenuItemType.Separator:
            y = int(r.center().y()) + 0.5
            p.setPen(QPen(_a(t.text, 0.14), 1))
            p.drawLine(QPointF(r.left() + 10, y), QPointF(r.right() - 10, y))
            p.restore()
            return
        enabled = bool(opt.state & S.State_Enabled)
        if opt.state & S.State_Selected and enabled:
            hl = crisp(r.adjusted(1, 1, -1, -1))
            g = QLinearGradient(0, hl.top(), 0, hl.bottom())
            g.setColorAt(0, _a(t.accent, 0.38 if t.dark else 0.28))
            g.setColorAt(1, _a(t.accent2, 0.26 if t.dark else 0.18))
            path = rounded(hl, R_ITEM)
            p.fillPath(path, g)
            p.setPen(QPen(_a("#ffffff", 0.35 if t.dark else 0.8), 1))
            p.drawPath(path)
        text_col = _a(t.text, 1.0 if enabled else 0.4)
        x = r.left() + 12
        check_w = 18
        if opt.checkType != opt.CheckType.NotCheckable:
            if opt.checked:
                pen = QPen(_a(t.accent, 1.0), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                           Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                cy = r.center().y()
                path = QPainterPath()
                path.moveTo(x, cy)
                path.lineTo(x + 4, cy + 4)
                path.lineTo(x + 11, cy - 4)
                p.drawPath(path)
            x += check_w
        if not opt.icon.isNull():
            pm = opt.icon.pixmap(16, 16, opt.icon.Mode.Normal if enabled else opt.icon.Mode.Disabled)
            p.drawPixmap(QRectF(x, r.center().y() - 8, 16, 16), pm, QRectF(pm.rect()))
            x += 24
        elif opt.maxIconWidth and opt.checkType == opt.CheckType.NotCheckable:
            x += 24
        text = opt.text
        shortcut = ""
        if "\t" in text:
            text, shortcut = text.split("\t", 1)
        p.setPen(text_col)
        p.setFont(opt.font)
        flags = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextShowMnemonic
        p.drawText(QRectF(x, r.top(), r.right() - x - 10, r.height()), flags | Qt.AlignmentFlag.AlignLeft, text)
        if shortcut:
            p.setPen(_a(t.text2, 0.9))
            p.drawText(QRectF(x, r.top(), r.right() - x - 12, r.height()), flags | Qt.AlignmentFlag.AlignRight,
                       shortcut)
        if opt.menuItemType == QStyleOptionMenuItem.MenuItemType.SubMenu:
            self._chevron_right(p, QRectF(r.right() - 18, r.top(), 12, r.height()), text_col)
        p.restore()

    @staticmethod
    def _chevron_right(p: QPainter, r: QRectF, color: QColor):
        pen = QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        c = r.center()
        path = QPainterPath()
        path.moveTo(c.x() - 2, c.y() - 4)
        path.lineTo(c.x() + 2, c.y())
        path.lineTo(c.x() - 2, c.y() + 4)
        p.drawPath(path)

    # ------------------------------------------------------------------ controles complejos
    def drawComplexControl(self, cc, opt, p, w=None):
        CC = QStyle.ComplexControl
        S = QStyle.StateFlag
        st = opt.state
        if cc == CC.CC_Slider and opt.orientation == Qt.Orientation.Horizontal:
            self._slider(opt, p, w)
            return
        if cc == CC.CC_ComboBox:
            if opt.editable:
                paint_field(p, opt.rect, focus=bool(st & S.State_HasFocus))
            else:
                paint_glass_button(p, opt.rect, hover=bool(st & S.State_MouseOver),
                                   pressed=bool(st & S.State_On),
                                   focus=bool(st & S.State_HasFocus) and bool(st & S.State_KeyboardFocusChange))
            arrow = self.subControlRect(cc, opt, QStyle.SubControl.SC_ComboBoxArrow, w)
            self._chevron(p, QRectF(arrow).adjusted(-4, 0, -4, 0), opt.palette.color(QPalette.ColorRole.ButtonText))
            return
        if cc == CC.CC_SpinBox:
            paint_field(p, opt.rect, focus=bool(st & S.State_HasFocus), hover=bool(st & S.State_MouseOver))
            return
        super().drawComplexControl(cc, opt, p, w)

    def _slider(self, opt, p: QPainter, w):
        from aero.ui.glass import tm

        t = tm().theme
        S = QStyle.StateFlag
        SC = QStyle.SubControl
        groove = QRectF(self.subControlRect(QStyle.ComplexControl.CC_Slider, opt, SC.SC_SliderGroove, w))
        handle = QRectF(self.subControlRect(QStyle.ComplexControl.CC_Slider, opt, SC.SC_SliderHandle, w))
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = groove.center().y()
        h = 6.0
        track = QRectF(groove.left() + 1, cy - h / 2, groove.width() - 2, h)
        tp = rounded(track, h / 2)
        p.fillPath(tp, _a("#ffffff" if t.dark else "#0a3a66", 0.16))
        p.setPen(QPen(_a("#ffffff" if t.dark else "#0a3a66", 0.20), 1))
        p.drawPath(rounded(crisp(track.toAlignedRect()), h / 2))
        hc = handle.center()
        if opt.upsideDown:
            fill_r = QRectF(hc.x(), track.top(), track.right() - hc.x(), h)
        else:
            fill_r = QRectF(track.left(), track.top(), max(h, hc.x() - track.left()), h)
        if opt.maximum > opt.minimum and opt.sliderPosition > opt.minimum:
            g = QLinearGradient(fill_r.topLeft(), fill_r.topRight())
            g.setColorAt(0, QColor(t.accent))
            g.setColorAt(1, QColor(t.accent2))
            fp = rounded(fill_r, h / 2)
            p.fillPath(fp, g)
            gl = QLinearGradient(0, fill_r.top(), 0, fill_r.bottom())
            gl.setColorAt(0, _a("#ffffff", 0.55))
            gl.setColorAt(0.5, _a("#ffffff", 0.0))
            p.fillPath(fp, gl)
        hover = bool(opt.activeSubControls & SC.SC_SliderHandle) and bool(opt.state & S.State_MouseOver)
        pressed = bool(opt.state & S.State_Sunken)
        rad = 8.0 if not (hover or pressed) else 9.0
        # El asa siempre cabe entera: su radio está limitado por la altura del control.
        rad = min(rad, QRectF(opt.rect).height() / 2 - 1)
        paint_slider_handle(p, QPointF(hc.x(), cy), rad, hover=hover, pressed=pressed,
                            focus=bool(opt.state & S.State_HasFocus) and bool(opt.state & S.State_KeyboardFocusChange))
        p.restore()


def install(app: QApplication) -> AeroStyle:
    style = AeroStyle()
    app.setStyle(style)
    return style


def sync_palette(app: QApplication) -> None:
    """Paleta coherente con el tema (selección, texto de menús y descripciones)."""
    from PySide6.QtWidgets import QToolTip

    from aero.ui.glass import tm

    t = tm().theme
    pal = app.palette()
    for role, col in ((QPalette.ColorRole.WindowText, t.text), (QPalette.ColorRole.Text, t.text),
                      (QPalette.ColorRole.ButtonText, t.text), (QPalette.ColorRole.ToolTipText, t.text),
                      (QPalette.ColorRole.HighlightedText, t.text), (QPalette.ColorRole.PlaceholderText, t.text2)):
        pal.setColor(role, QColor(col))
    pal.setColor(QPalette.ColorRole.Highlight, _a(t.accent, 0.35))
    # Fondo transparente por paleta (no por hoja de estilos): así los menús y campos siguen dibujándose con
    # AeroStyle y los contenedores con relleno automático no tapan el cristal.
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.AlternateBase):
        pal.setColor(role, QColor(0, 0, 0, 0))
    pal.setColor(QPalette.ColorRole.Button, QColor(t.solid))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.solid))
    app.setPalette(pal)
    QToolTip.setPalette(pal)
