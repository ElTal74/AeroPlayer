"""Captura de la página del reproductor con letra sincronizada (revisión visual).

Uso: python tools/devrun.py run letra -- .venv/Scripts/python.exe tools/lyrics_shot.py <salida.png> [visualizador]
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["AERO_DATA_DIR"] = tempfile.mkdtemp(prefix="aero_letra_")
os.environ["AERO_NO_TUTORIAL"] = "1"
os.environ["AERO_NO_UPDATES"] = "1"
OUT = sys.argv[1]
VIZ = len(sys.argv) > 2

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setStyle("Fusion")
from aero.core.config import Settings  # noqa: E402
from aero.core.db import Database  # noqa: E402
from aero.i18n import set_language  # noqa: E402
from aero.ui.controller import AppController  # noqa: E402
from aero.ui.main_window import apply_theme  # noqa: E402

set_language("es-ES")
s = Settings()
s.set("tutorial_done", True)
s.set("visualizer_enabled", VIZ)
apply_theme(app, s)
ctl = AppController(app, s, Database())
d = Path(tempfile.mkdtemp())
song = d / "Pulso Aero.flac"
shutil.copy(ROOT / "tests" / "media" / "pulso.flac", song)
(d / "Pulso Aero.lrc").write_text(
    "[00:00.00]Cristal y cielo azul\n[00:01.20]Burbujas que suben despacio\n"
    "[00:02.40]La música entra por la ventana\n[00:03.60]Y el agua brilla al sol\n"
    "[00:05.00]Una línea bastante más larga para comprobar que el texto se reparte en dos renglones\n"
    "[00:06.50]Fin del estribillo\n", encoding="utf-8")


def go():
    w = ctl.show_main()
    w.resize(1280, 780)
    w.play([str(song)], 0)
    w.navigate("player")
    QTimer.singleShot(3000, shot)


def shot():
    from shot_util import save

    save(ctl.main, OUT)
    print("captura", OUT, flush=True)
    os._exit(0)


QTimer.singleShot(300, go)
app.exec()
