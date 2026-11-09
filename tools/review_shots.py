"""Capturas de revisión (escritorio oculto): cada sección y editor con contenido, para revisar la interfaz.

Uso: python tools/devrun.py run revision -- .venv/Scripts/python.exe tools/review_shots.py <carpeta> [idioma]
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AERO_NO_UPDATES", "1")
os.environ["AERO_DATA_DIR"] = tempfile.mkdtemp(prefix="aero_rev_")
os.environ["AERO_NO_TUTORIAL"] = "1"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
OUT.mkdir(parents=True, exist_ok=True)
LANG = sys.argv[2] if len(sys.argv) > 2 else "es-ES"
M = ROOT / "tests" / "media"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from aero.core.config import Settings  # noqa: E402
from aero.core.db import Database  # noqa: E402
from aero.i18n import set_language  # noqa: E402
from aero.ui.controller import AppController  # noqa: E402
from aero.ui.main_window import apply_theme  # noqa: E402

set_language(LANG)
s = Settings()
s.set("language", LANG)
s.set("library_folders", [str(M)])
s.set("tutorial_done", True)
s.set("quicklook_enabled", False)
s.set("home_widgets_visible", False)
apply_theme(app, s)
ctl = AppController(app, s, Database())
st: dict = {}
steps: list = []
errors: list = []


def step(ms, fn):
    steps.append((ms, fn))


def shot(w, name):
    app.processEvents()
    from shot_util import save

    save(w, str(OUT / f"{name}.png"))
    print("captura", name, flush=True)


def main():
    return st["main"]


step(300, lambda: st.update(main=ctl.show_main()))
step(300, lambda: (main().resize(1320, 820), main().page("library").scan()))
step(2500, lambda: shot(main(), "01_inicio"))
for i, key in enumerate(["library", "files", "player", "converter", "playlists", "settings", "viewer"]):
    step(150, lambda k=key: main().navigate(k))
    step(900, lambda k=key, n=i: shot(main(), f"02_{n}_{k}"))
step(100, lambda: main().convert([str(M / "clip.mkv"), str(M / "pulso.flac"), str(M / "foto.jpg")]))
step(1200, lambda: shot(main(), "03_conversor_con_archivos"))
for cat in ["appearance", "playback", "files", "convert", "performance", "about"]:
    step(150, lambda c=cat: (main().navigate("settings"), main().page("settings").open_category(c)))
    step(700, lambda c=cat: shot(main(), f"04_ajustes_{c}"))
step(100, lambda: (main().navigate("library"), main().page("library").tabs.setCurrentIndex(3)))
step(800, lambda: shot(main(), "05_biblioteca_albumes"))
step(100, lambda: st.update(ve=ctl.open_video_editor()))
step(1500, lambda: (st["ve"].resize(1440, 900), st["ve"].add_media([str(M / "clip.mkv"), str(M / "pulso.flac")])
                    if hasattr(st["ve"], "add_media") else None))
step(2500, lambda: shot(st["ve"], "06_editor_video"))
step(100, lambda: (st["ve"].close(), st.update(ie=ctl.open_image_editor(str(M / "foto.jpg")))))
step(2000, lambda: shot(st["ie"], "07_editor_imagen"))
step(100, lambda: (st["ie"].close(), st.update(p=ctl.open_paint(""))))
step(1500, lambda: shot(st["p"], "08_paint"))
step(100, lambda: (st["p"].close(), st.update(d=ctl.open_document_editor())))
step(1500, lambda: shot(st["d"], "09_documento"))
step(100, lambda: (st["d"].close(), st.update(h=ctl.open_sheet_editor())))
step(1500, lambda: shot(st["h"], "10_hoja"))
step(100, lambda: (st["h"].close(), st.update(mw=ctl.open_media_window(str(M / "foto.jpg")))))
step(1500, lambda: shot(st["mw"], "11_visor_foto"))
step(300, lambda: (print("ERRORS", errors, flush=True), os._exit(0)))


def run(i=0):
    if i >= len(steps):
        return
    ms, fn = steps[i]

    def go():
        try:
            fn()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            errors.append(i)
        run(i + 1)

    QTimer.singleShot(ms, go)


run()
app.exec()
