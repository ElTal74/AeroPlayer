"""Recorrido visual con capturas REALES de pantalla (incluye lo que hay detrás de las ventanas transparentes).

Uso: python tools/visual_check.py <carpeta_salida>
Coloca una ventana de franjas de colores detrás para demostrar la transparencia y captura con `mss`.
"""

from __future__ import annotations

import os
os.environ.setdefault("AERO_NO_UPDATES", "1")   # sin consultar GitHub durante las comprobaciones
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
OUT.mkdir(parents=True, exist_ok=True)
os.environ["AERO_DATA_DIR"] = tempfile.mkdtemp(prefix="aero_vis_")
os.environ["AERO_NO_TUTORIAL"] = "1"  # el tutorial de bienvenida taparía la ventana
M = ROOT / "tests" / "media"

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

app = QApplication([])
app.setStyle("Fusion")
from aero.core.config import Settings  # noqa: E402
from aero.core.db import Database  # noqa: E402
from aero.ui.controller import AppController  # noqa: E402
from aero.ui.main_window import apply_theme  # noqa: E402


class Stripes(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        cols = ["#ff2d55", "#ffcc00", "#34c759", "#007aff", "#af52de", "#ff9500"]
        for i in range(16):
            p.fillRect(i * self.width() // 16, 0, self.width() // 16 + 1, self.height(), QColor(cols[i % 6]))
        p.setFont(QFont("Segoe UI", 54, QFont.Weight.Bold))
        p.setPen(Qt.GlobalColor.white)
        for y in range(0, self.height(), 260):
            p.drawText(0, y, self.width(), 200, Qt.AlignmentFlag.AlignCenter, "ESCRITORIO DETRÁS")


bg = Stripes()
bg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
scr = app.primaryScreen().availableGeometry()
if os.environ.get("AERO_DEV_SCREEN"):           # `devrun.py run … --visible`: en el monitor secundario
    from PySide6.QtCore import QRect

    scr = QRect(*map(int, os.environ["AERO_DEV_SCREEN"].split(",")))
bg.setGeometry(scr)
if not os.environ.get("AERO_DEVRUN") or os.environ.get("AERO_DEV_SCREEN"):
    bg.show()

settings = Settings()
settings.set("library_folders", [str(M)])
settings.set("quicklook_enabled", False)
db = Database()
apply_theme(app, settings)
ctl = AppController(app, settings, db)
errors: list = []
log: list[str] = []


def pin(win):
    """Solo para la prueba: mantener la ventana encima para que otras aplicaciones no la tapen."""
    if not win.testAttribute(Qt.WidgetAttribute.WA_WState_Created) or not (win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
        win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        win.show()
        app.processEvents()
    ov = getattr(win, "overlay", None)
    if ov is not None and not (ov.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
        ov.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        win._layout_overlays()
        ov.show()
        ov.raise_()
        app.processEvents()


HIDDEN = bool(os.environ.get("AERO_DEVRUN")) and not os.environ.get("AERO_DEV_SCREEN")


def grab(win, name):
    if HIDDEN:
        # Escritorio de desarrollo oculto (tools/devrun.py): Windows no deja copiar su pantalla, así que se guarda
        # lo que dibuja la propia ventana. Sirve para revisar la interfaz; la transparencia real sobre el fondo
        # se comprueba con `devrun.py run … --visible` (segundo monitor).
        app.processEvents()
        win.grab().save(str(OUT / f"{name}.png"))
        g = win.frameGeometry()
        log.append(f"{name}: {g.width()}x{g.height()} (ventana)")
        print("shot", name, g.width(), g.height(), flush=True)
        return
    import mss
    import mss.tools

    pin(win)
    win.raise_()
    win.activateWindow()
    app.processEvents()
    g = win.frameGeometry()
    r = win.devicePixelRatioF()
    with mss.MSS() as s:
        im = s.grab({"left": int(g.x() * r) - 24, "top": int(g.y() * r) - 24,
                     "width": int(g.width() * r) + 48, "height": int(g.height() * r) + 48})
        mss.tools.to_png(im.rgb, im.size, output=str(OUT / f"{name}.png"))
    log.append(f"{name}: {g.width()}x{g.height()} en ({g.x()},{g.y()})")
    print("shot", name, g.width(), g.height(), flush=True)


steps = []


def step(ms, fn):
    steps.append((ms, fn))


state = {}
step(300, lambda: state.update(main=ctl.show_main()))
step(400, lambda: (state["main"].resize(1280, 780), state["main"].move(scr.x() + 60, scr.y() + 40),
                   state["main"].page("library").scan()))
step(2500, lambda: grab(state["main"], "A1_inicio"))
step(100, lambda: state["main"].navigate("library"))
step(500, lambda: grab(state["main"], "A2_biblioteca"))
step(100, lambda: state["main"].page("library").tabs.setCurrentIndex(3))
step(800, lambda: grab(state["main"], "A2b_albumes"))
step(100, lambda: state["main"].page("library").tabs.setCurrentIndex(2))
step(500, lambda: grab(state["main"], "A3_series"))
step(100, lambda: state["main"].page("library")._open_group(state["main"].page("library").groups.item(0)))
step(500, lambda: grab(state["main"], "A4_temporadas"))
step(100, lambda: state["main"].play([str(M / "pulso.flac")], 0))
step(100, lambda: state["main"].navigate("player"))
step(2200, lambda: grab(state["main"], "A5_reproductor"))
step(100, lambda: (state["main"].engine.stop(), state["main"].navigate("converter")))
step(500, lambda: grab(state["main"], "A6_conversor"))
step(100, lambda: state["main"].navigate("settings"))
step(600, lambda: grab(state["main"], "A7_ajustes"))
step(100, lambda: state["main"].page("settings").open_category("playback"))
step(600, lambda: grab(state["main"], "A7b_visualizadores"))
step(100, lambda: (setattr(state["main"].page("home").tiles[0].light, "value", 1.0), state["main"].navigate("home")))
step(500, lambda: grab(state["main"], "A7c_hover_baldosa"))
step(100, lambda: setattr(state["main"].page("home").tiles[0].light, "value", 0.0))
for _key in ("nature", "cielo", "aqua", "zen"):
    step(100, lambda k=_key: settings.set("theme", k))
    step(700, lambda k=_key: grab(state["main"], f"A7t_tema_{k}"))
step(100, lambda: settings.set("theme", "burbuja"))
step(100, lambda: state["main"].navigate("playlists"))
step(500, lambda: grab(state["main"], "A8_listas"))
step(100, lambda: (state["main"].navigate("home"), settings.set("glass_mode", "clear")))
step(700, lambda: grab(state["main"], "A9_transparente"))
step(100, lambda: settings.set("glass_mode", "opaque"))
step(700, lambda: grab(state["main"], "A10_opaco"))
step(100, lambda: (settings.set("glass_mode", "blur"), state["main"].hide()))
step(200, lambda: state.update(w=ctl.open_media_window(str(M / "foto.jpg"))))
step(1200, lambda: grab(state["w"], "B1_imagen_800x500"))
step(100, lambda: (state["w"].close(), state.update(w=ctl.open_media_window(str(M / "grande.jpg")))))
step(1800, lambda: grab(state["w"], "B2_imagen_4000x3000"))
step(100, lambda: (state["w"].close(), state.update(w=ctl.open_media_window(str(M / "clip.mkv")))))
step(2500, lambda: grab(state["w"], "B3_video_16x9"))
step(100, lambda: state["w"].wake())
step(300, lambda: grab(state["w"], "B3b_video_controles"))
step(100, lambda: (state["w"].close(), state.update(w=ctl.open_media_window(str(M / "vertical.mp4")))))
step(2500, lambda: grab(state["w"], "B4_video_vertical"))
step(100, lambda: (state["w"].close(), state.update(w=ctl.open_media_window(str(M / "pulso.flac")))))
step(2200, lambda: grab(state["w"], "B5_audio"))
step(100, lambda: (state["w"].close(), ctl.show_quicklook(str(M / "pulso.flac"))))
step(2000, lambda: grab(ctl.quicklook, "C0_quicklook_audio"))
step(100, lambda: (ctl.quicklook.close_preview(), ctl.show_quicklook(str(M / "foto.jpg"))))
step(400, lambda: grab(ctl.quicklook, "C0b_quicklook_imagen_controles"))
step(2400, lambda: grab(ctl.quicklook, "C0c_quicklook_imagen_reposo"))
step(100, lambda: (ctl.quicklook.close_preview(), state.update(w=ctl.open_media_window(str(M / "doc.pdf")))))
step(1500, lambda: grab(state["w"], "B6_pdf"))
step(100, lambda: (ctl.show_quicklook(str(M / "datos.xlsx")), state["w"].close()))
step(1500, lambda: grab(ctl.quicklook, "C1_quicklook_xlsx"))
step(100, lambda: ctl.quicklook.close_preview())


def _sample_folder():
    """Carpeta con un archivo de cada categoría para ver la familia de iconos AERO."""
    d = Path(tempfile.mkdtemp(prefix="aero_iconos_"))
    names = ["Vacaciones.mp4", "Concierto.mkv", "Canción.mp3", "Podcast.flac", "Playa.jpg", "Logo.png", "Informe.docx",
             "Cuentas.xlsx", "Charla.pptx", "Contrato.pdf", "Fotos.zip", "Copia.7z", "Instalador.exe", "Atajo.url",
             "Ajustes.ini", "Letra.ttf", "script.py", "Linux.iso", "Juego.cue", "Película.torrent", "misterio.xyz"]
    for n in names:
        (d / n).write_bytes(b"x")
    (d / "Proyectos").mkdir()
    return d


def _torrent_dialog():
    from aero.torrent import metainfo
    from aero.torrent.ui import TorrentDialog

    t = metainfo.parse(metainfo.make([("Serie/Capítulo 1.mkv", b"v" * 90_000), ("Serie/Capítulo 2.mkv", b"v" * 80_000),
                                      ("Serie/Subtítulos/es.srt", b"s" * 900), ("LEEME.txt", b"t" * 300)],
                                     "Serie de prueba", 16384, "udp://tracker.example:1337/announce"))
    dlg = TorrentDialog(t)
    dlg.move(scr.x() + 120, scr.y() + 80)
    dlg.show()
    state["td"] = dlg
    return dlg


step(100, lambda: (state["main"].show(), state["main"].page("files").browse(str(_sample_folder())),
                   state["main"].navigate("files")))
step(1500, lambda: grab(state["main"], "D1_archivos_iconos_cuadricula"))
step(100, lambda: state["main"].page("files").browser.set_grid(False))
step(800, lambda: grab(state["main"], "D2_archivos_iconos_lista"))
step(100, lambda: (settings.set("theme", "cielo")))
step(900, lambda: grab(state["main"], "D3_archivos_iconos_tema_claro"))
step(100, lambda: (settings.set("theme", "burbuja"), state["main"].page("files").browser.set_grid(True)))
step(300, lambda: _torrent_dialog())
step(900, lambda: grab(state["td"], "E1_torrent_dialogo"))
step(100, lambda: (state["td"].close(), state.update(dw=__import__("aero.torrent.ui", fromlist=["x"]).show_downloads())))
step(700, lambda: grab(state["dw"], "E2_descargas"))
step(100, lambda: (state["dw"].close(), state["main"].navigate("settings"),
                   state["main"].page("settings").open_category("downloads")))
step(700, lambda: grab(state["main"], "E3_ajustes_descargas"))
step(300, lambda: (Path(OUT / "geometrias.txt").write_text("\n".join(log), encoding="utf-8"), ctl.quit()))


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


sys.excepthook = lambda *a: (traceback.print_exception(*a), errors.append("hook"))
run()
app.exec()
print("ERRORS", errors)
