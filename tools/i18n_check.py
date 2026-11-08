"""Cobertura de traducciones: recorre las pantallas principales, recoge cada texto que pasa por tr() y cuenta
cuántos tiene cada catálogo. Uso: python tools/i18n_check.py [--dump archivo.json] [--missing código]"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AERO_I18N_COLLECT"] = "1"
os.environ["AERO_DATA_DIR"] = tempfile.mkdtemp(prefix="aero_i18n_")
os.environ["AERO_NO_TUTORIAL"] = "1"

import aero  # noqa: F401,E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from aero import i18n  # noqa: E402
from aero.i18n import tr  # noqa: E402


def pump(t=0.3):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()


def collect() -> set[str]:
    import re

    from aero.core import activity as act
    from aero.core import seasons
    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.editors.video import effects as fx
    from aero.installer import ui as inst
    from aero.ui import file_actions, home_widgets, tutorial
    from aero.ui.command_palette import FILTERS
    from aero.ui.controller import AppController
    from aero.ui.main_window import PAGES, apply_theme
    from aero.ui.pages.home_page import HomePage
    from aero.ui.pages.settings_page import CATEGORIES

    for seq in ([t for _k, t, _i in PAGES], [x for c in CATEGORIES for x in c[1::3] + c[3:4]],
                [s.title for s in tutorial.STEPS], [s.text for s in tutorial.STEPS],
                [a.text for v in file_actions.BY_KIND.values() for a in v] + [a.tip for v in file_actions.BY_KIND.values()
                                                                                  for a in v],
                [i[1] for i in HomePage.CREATE_MENU if i], [t[0] for t in home_widgets.TYPES.values()],
                [e.name for e in fx.EFFECTS.values()] + [e.desc for e in fx.EFFECTS.values()],
                [t.name for t in fx.TRANSITIONS.values()] + [t.desc for t in fx.TRANSITIONS.values()],
                list(act.KIND_LABELS.values()) + list(act.STATE_LABELS.values()), [t for _k, t in FILTERS],
                inst.TIPS, [t for _i, t in inst.FEATURES],
                ["Saltar tutorial", "Anterior", "Comenzar", "Empezar", "Siguiente", "Paso {i} de {n}",
                 "Arrastra para mover · clic derecho para opciones", "Temp.: no disponible", "Tareas: {n} en curso",
                 "Tareas e historial", "Lo que abras aparecerá aquí.", "Aún no hay tareas", "Tamaño", "Mostrar",
                 "Ocultar", "Quitar", "Pequeño", "Ancho", "Restaurar la distribución predeterminada",
                 "Ya están todos", "Idioma", "Puedes ver el tutorial cuando quieras en Ajustes › Inicio",
                 "Cerrar y volver (Esc)", "Cerrar y volver", "{n} dispositivo", "{n} teclado",
                 "{n} pantalla conectada", "Buenos días", "Buenas tardes", "Buenas noches"],
                list(seasons._SEASON_WELCOME.values()),
                re.findall(r'"(Feliz[^"]+|¡[^"]+)"', Path(seasons.__file__).read_text(encoding="utf-8"))):
        for text in seq:
            tr(text)
    s = Settings()
    apply_theme(app, s)
    ctl = AppController(app, s, Database())
    win = ctl.show_main()
    for k, _t, _i in PAGES:
        win.navigate(k)
        pump(0.2)
    sp = win.page("settings")
    for i in range(sp.nav.count()):
        sp.nav.setCurrentRow(i)
    win.open_palette()
    win.cmd_palette.hide()
    win.tasks_btn.show_popup()
    win.tasks_btn.popup.hide()
    w = ctl.open_paint()
    w.doc.dirty = False
    w.close()
    ed = ctl.open_video_editor()
    ed.dirty = False
    ed.close()
    iw = inst.InstallerWindow(None)
    iw.deleteLater()
    uw = inst.UninstallWindow(Path(tempfile.mkdtemp()))
    uw.deleteLater()
    pump(0.3)
    win.quitting = True
    win.close()
    return {t for t in i18n.SEEN if t.strip() and any(c.isalpha() for c in t)}


if __name__ == "__main__":
    keys = sorted(collect())
    if "--dump" in sys.argv:
        Path(sys.argv[sys.argv.index("--dump") + 1]).write_text(json.dumps(keys, ensure_ascii=False, indent=1),
                                                                encoding="utf-8")
    print(f"Textos de la interfaz: {len(keys)}")
    for code in i18n.LANGUAGES:
        if code == i18n.SOURCE:
            continue
        i18n.catalog.cache_clear()
        cat = i18n.catalog(code)
        base = i18n.catalog(i18n.FALLBACK[code]) if code in i18n.FALLBACK else {}
        have = sum(1 for k in keys if k in cat or (code in i18n.FALLBACK and (k in base or True)))
        if code in i18n.FALLBACK:
            note = f"{len(cat)} diferencias respecto a {i18n.FALLBACK[code]} (el resto se hereda)"
            print(f"  {code}: {note}")
            continue
        print(f"  {code}: {have}/{len(keys)} ({100 * have / max(1, len(keys)):.0f} %)")
        if "--missing" in sys.argv and sys.argv[sys.argv.index("--missing") + 1] == code:
            for k in keys:
                if k not in cat:
                    print("    falta:", k)
    unused = {code: [k for k in i18n.catalog(code) if k not in keys] for code in i18n.LANGUAGES if code != "es-ES"}
    for code, ks in unused.items():
        if ks:
            print(f"  {code}: {len(ks)} claves sin uso")
