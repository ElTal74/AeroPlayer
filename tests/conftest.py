import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MEDIA = ROOT / "tests" / "media"


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Cada prueba usa su propia carpeta de datos: nunca toca la configuración real del usuario."""
    monkeypatch.setenv("AERO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AERO_NO_UPDATES", "1")      # las pruebas nunca consultan GitHub por su cuenta
    yield


@pytest.fixture(autouse=True)
def no_motion_rest(request):
    """El reposo del fondo animado depende de si alguien toca el ratón (GetLastInputInfo) o de la batería: durante
    una compilación larga nadie lo toca y algunas pruebas crean su propio controlador con el reposo activado."""
    yield
    if "qapp" in request.fixturenames or "controller" in request.fixturenames:
        from aero.ui.perf import auto_tuner

        auto_tuner().set_rest_enabled(False)


@pytest.fixture(scope="session")
def qapp():
    # Plataforma nativa: "offscreen" no tiene fuentes y falsearía las pruebas de PDF.
    if os.name != "nt":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from aero.i18n import set_language

    # Las pruebas comprueban los textos de origen (español); el idioma predeterminado de la app es el inglés.
    set_language("es-ES")
    from aero.ui.perf import auto_tuner

    # El reposo (equipo sin usar o con batería) pararía el fondo animado a mitad de una prueba.
    auto_tuner().set_rest_enabled(False)
    yield app
    # Cierre ordenado: ventanas cerradas y sin tareas en hilos antes de que termine el intérprete (si no, el
    # proceso puede abortar al salir aunque todas las pruebas hayan pasado).
    from aero.ui.async_util import shutdown

    for w in QApplication.topLevelWidgets():
        w.hide()
        w.deleteLater()
    app.processEvents()
    shutdown(15000)
    app.processEvents()


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    """Medios de prueba generados con FFmpeg (libres de derechos)."""
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg no está disponible")
    d = tmp_path_factory.mktemp("media")

    def ff(*args):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)

    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-metadata", "title=Tono", "-metadata", "artist=Prueba",
       "-metadata", "album=Álbum Ñ", str(d / "tono.mp3"))
    ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=2", "-f", "lavfi", "-i",
       "sine=frequency=330:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
       str(d / "clip.mkv"))
    ff("-f", "lavfi", "-i", "testsrc=size=200x120", "-frames:v", "1", str(d / "img.png"))
    (d / "dañado.mp4").write_bytes(b"\x00garbage" * 200)
    return d


@pytest.fixture()
def controller(qapp, media):
    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.ui.controller import AppController
    from aero.ui.main_window import apply_theme

    s = Settings()
    s.set("quicklook_enabled", False)
    s.set("tutorial_done", True)
    s.set("motion_rest", False)
    s.set("language", "es-ES")
    db = Database()
    apply_theme(qapp, s)
    ctl = AppController(qapp, s, db)
    ctl.quit = lambda: None  # en pruebas no se cierra la aplicación de Qt
    yield ctl
    from PySide6.QtCore import QThreadPool

    if ctl.main is not None and "library" in ctl.main.pages:
        ctl.main.pages["library"].stop_scan()
    QThreadPool.globalInstance().waitForDone(5000)      # sin tareas a medias al cerrar (fallo intermitente)
    qapp.processEvents()
    for w in list(ctl.media_windows):
        w.close()
    if ctl.main is not None:
        ctl.main.quitting = True
        ctl.main.close()
    qapp.processEvents()


def _qt_messages(mode, ctx, msg):
    if "_mf" not in msg:
        sys.stderr.write(f"[Qt {mode.name}] {msg}\n")
        sys.stderr.flush()


try:
    from PySide6.QtCore import qInstallMessageHandler

    qInstallMessageHandler(_qt_messages)
except ImportError:  # pragma: no cover
    pass
