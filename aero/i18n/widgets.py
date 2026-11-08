"""Red de seguridad de la traducción: traduce los textos fijos de un árbol de widgets ya construido.

Lo normal es que cada texto pase por `tr()` al crearse. Algunos llegan por variables (tablas de herramientas,
nombres de transiciones, ayudas de deslizadores…); si el texto es una clave del catálogo, aquí se cambia por su
traducción. Solo toca textos que son exactamente una clave (nunca datos del usuario que no lo sean) y es
idempotente: un texto ya traducido no es una clave y se deja igual.

Se aplica al mostrar cada ventana por primera vez (`GlassWindow`) y a cada apartado de la ventana principal al
crearse. `tools/i18n_screens.py` comprueba que no quede nada en español en ninguna pantalla.
"""

from __future__ import annotations

from aero import i18n


def _t(text: str) -> str | None:
    """Traducción si `text` es una clave con traducción distinta; si no, None (no se cambia)."""
    if not text or i18n.language() == i18n.SOURCE:
        return None
    s = text.strip()
    out = i18n._lookup(s)
    if isinstance(out, list):
        out = out[0]
    if out == s or "{" in out:
        return None   # sin traducción, o plantilla con marcadores (la pone su código con tr(…, valores))
    return text.replace(s, out)


def translate_tree(root) -> int:
    """Traduce texto, ayuda, nombre accesible y textos marcadores de `root` y sus descendientes."""
    from PySide6.QtWidgets import (QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit, QListWidget,
                                   QTabBar, QTabWidget, QWidget)

    if i18n.language() == i18n.SOURCE:
        return 0
    n = 0

    def fix(get, set_):
        nonlocal n
        try:
            new = _t(get())
        except RuntimeError:
            return
        if new is not None:
            set_(new)
            n += 1

    for w in [root, *root.findChildren(QWidget)]:
        fix(w.toolTip, w.setToolTip)
        fix(w.accessibleName, w.setAccessibleName)
        if w.isWindow():
            fix(w.windowTitle, w.setWindowTitle)
        if isinstance(w, QLabel):
            if not w.textFormat() == 1:    # Qt.RichText: los textos con formato llegan ya traducidos
                fix(w.text, w.setText)
        elif isinstance(w, QAbstractButton):
            fix(w.text, w.setText)
        elif isinstance(w, QLineEdit):
            fix(w.placeholderText, w.setPlaceholderText)
        elif isinstance(w, QComboBox):
            for i in range(w.count()):
                fix(lambda i=i: w.itemText(i), lambda v, i=i: w.setItemText(i, v))
        elif isinstance(w, QTabBar):
            for i in range(w.count()):
                fix(lambda i=i: w.tabText(i), lambda v, i=i: w.setTabText(i, v))
                fix(lambda i=i: w.tabToolTip(i), lambda v, i=i: w.setTabToolTip(i, v))
        elif isinstance(w, QTabWidget):
            for i in range(w.count()):
                fix(lambda i=i: w.tabText(i), lambda v, i=i: w.setTabText(i, v))
        elif isinstance(w, QGroupBox):
            fix(w.title, w.setTitle)
        elif isinstance(w, QListWidget):
            for i in range(w.count()):
                it = w.item(i)
                fix(it.toolTip, it.setToolTip)
        for act in w.actions():
            fix(act.text, act.setText)
            fix(act.toolTip, act.setToolTip)
    return n
