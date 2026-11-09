"""Imágenes de la web (website/assets): logo, iconos de categoría y capturas de la aplicación.

Uso (siempre en el escritorio oculto):
    python tools/devrun.py run web -- .venv/Scripts/python.exe tools/site_assets.py

Las capturas se hacen con datos de prueba y sin el widget «Tu equipo» (no se publica nada del ordenador de quien
las genera). Idioma de las capturas: el primer argumento (es-ES por defecto).
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
OUT = ROOT / "website" / "assets"
ICONS = OUT / "iconos"
ICONS.mkdir(parents=True, exist_ok=True)
os.environ["AERO_DATA_DIR"] = tempfile.mkdtemp(prefix="aero_web_")
os.environ["AERO_NO_TUTORIAL"] = "1"
LANG = sys.argv[1] if len(sys.argv) > 1 else "es-ES"
# carpeta de la web para cada idioma de la aplicación
SITE_CODE = {"es-ES": "es", "en": "en", "de": "de", "it": "it", "pt-BR": "pt", "ru": "ru", "zh-CN": "zh"}[LANG]
SHOTS = OUT / "capturas" / SITE_CODE
SHOTS.mkdir(parents=True, exist_ok=True)
M = ROOT / "tests" / "media"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setStyle("Fusion")
from aero.core.config import Settings  # noqa: E402
from aero.core.db import Database  # noqa: E402
from aero.i18n import set_language  # noqa: E402
from aero.ui.controller import AppController  # noqa: E402
from aero.ui.main_window import apply_theme  # noqa: E402

# ---------------------------------------------------------------- logo e iconos
from aero.ui import file_icons  # noqa: E402
from aero.ui.glass import make_app_icon  # noqa: E402

make_app_icon(512).save(str(OUT / "logo.png"))
make_app_icon(64).save(str(OUT / "favicon.png"))
for cat in file_icons.PALETTE:
    file_icons.pixmap(cat, 128, 1.0, dark=False).save(str(ICONS / f"{cat}.png"))

# ---------------------------------------------------------------- capturas
set_language(LANG)
settings = Settings()
settings.set("language", LANG)
settings.set("library_folders", [str(M)])
settings.set("quicklook_enabled", False)
settings.set("tutorial_done", True)
settings.set("home_widgets_visible", False)       # sin datos del equipo
settings.set("motion_rest", False)
apply_theme(app, settings)
ctl = AppController(app, settings, Database())
errors: list = []
steps: list = []
state: dict = {}


def step(ms, fn):
    steps.append((ms, fn))


def shot(w, name):
    app.processEvents()
    from shot_util import save

    save(w, str(SHOTS / f"{name}.png"))
    print("captura", name, flush=True)


# nombres de la carpeta de ejemplo en cada idioma: carpeta, subcarpetas y archivos (las extensiones se añaden)
SAMPLE = {
    "es": ("Mis archivos", ["Proyectos", "Música"],
           ["Vacaciones en la playa", "Concierto", "Canción favorita", "Podcast", "Atardecer", "Logo", "Informe anual",
            "Presupuesto", "Presentación", "Contrato", "Fotos del viaje", "Copia de seguridad", "Linux", "Película",
            "Instalador", "script", "Tipografía"]),
    "en": ("My files", ["Projects", "Music"],
           ["Beach holiday", "Concert", "Favourite song", "Podcast", "Sunset", "Logo", "Annual report", "Budget",
            "Presentation", "Contract", "Trip photos", "Backup", "Linux", "Movie", "Installer", "script", "Typeface"]),
    "de": ("Meine Dateien", ["Projekte", "Musik"],
           ["Strandurlaub", "Konzert", "Lieblingslied", "Podcast", "Sonnenuntergang", "Logo", "Jahresbericht", "Budget",
            "Präsentation", "Vertrag", "Reisefotos", "Sicherung", "Linux", "Film", "Installer", "script", "Schriftart"]),
    "it": ("I miei file", ["Progetti", "Musica"],
           ["Vacanze al mare", "Concerto", "Canzone preferita", "Podcast", "Tramonto", "Logo", "Relazione annuale",
            "Budget", "Presentazione", "Contratto", "Foto del viaggio", "Backup", "Linux", "Film", "Installer", "script",
            "Carattere"]),
    "pt": ("Meus arquivos", ["Projetos", "Música"],
           ["Férias na praia", "Show", "Música favorita", "Podcast", "Pôr do sol", "Logo", "Relatório anual",
            "Orçamento", "Apresentação", "Contrato", "Fotos da viagem", "Backup", "Linux", "Filme", "Instalador",
            "script", "Fonte"]),
    "ru": ("Мои файлы", ["Проекты", "Музыка"],
           ["Отпуск на море", "Концерт", "Любимая песня", "Подкаст", "Закат", "Логотип", "Годовой отчёт", "Бюджет",
            "Презентация", "Договор", "Фото из поездки", "Резервная копия", "Linux", "Фильм", "Установщик", "script",
            "Шрифт"]),
    "zh": ("我的文件", ["项目", "音乐"],
           ["海滩假期", "音乐会", "最爱的歌", "播客", "日落", "标志", "年度报告", "预算", "演示文稿", "合同", "旅行照片",
            "备份", "Linux", "电影", "安装程序", "script", "字体"]),
}
EXTS = [".mp4", ".mkv", ".mp3", ".flac", ".jpg", ".png", ".docx", ".xlsx", ".pptx", ".pdf", ".zip", ".7z", ".iso",
        ".torrent", ".msi", ".py", ".ttf"]


def sample_folder():
    title, folders, names = SAMPLE[SITE_CODE]
    d = Path(tempfile.mkdtemp(prefix="aero_web_files_")) / title    # sin sufijo aleatorio en el nombre visible
    d.mkdir()
    for n, ext in zip(names, EXTS, strict=True):
        (d / (n + ext)).write_bytes(b"x")
    for f in folders:
        (d / f).mkdir()
    return d


step(300, lambda: state.update(main=ctl.show_main()))
step(400, lambda: (state["main"].resize(1280, 780), state["main"].page("library").scan()))
step(2500, lambda: shot(state["main"], "inicio"))
step(100, lambda: state["main"].navigate("library"))
step(800, lambda: shot(state["main"], "biblioteca"))
step(100, lambda: state["main"].play([str(M / "pulso.flac")], 0))
step(100, lambda: state["main"].navigate("player"))
step(2500, lambda: shot(state["main"], "reproductor"))
step(100, lambda: (state["main"].engine.stop(), state["main"].page("files").browse(str(sample_folder())),
                   state["main"].navigate("files")))
step(1500, lambda: shot(state["main"], "archivos"))
step(100, lambda: state["main"].open_paths([str(M / "foto.jpg")]))
step(1500, lambda: shot(state["main"], "visor"))
step(100, lambda: state["main"].navigate("converter"))
step(800, lambda: shot(state["main"], "conversor"))
step(100, lambda: (settings.set("theme", "nature"), state["main"].navigate("home")))
step(1200, lambda: shot(state["main"], "tema_naturaleza"))
step(100, lambda: (settings.set("theme", "burbuja"), state.update(ve=ctl.open_video_editor())))
step(2000, lambda: (state["ve"].resize(1280, 780), shot(state["ve"], "editor_video")))
step(100, lambda: (state["ve"].close(), state.update(paint=ctl.open_paint(""))))
step(1500, lambda: (state["paint"].resize(1200, 760), shot(state["paint"], "paint")))
step(300, lambda: (state["paint"].close(), print("ERRORS", errors, flush=True), os._exit(0)))


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
print("ERRORS", errors)
