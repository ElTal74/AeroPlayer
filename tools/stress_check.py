"""Auditoría de estabilidad: recorre toda la aplicación con archivos normales, dañados y raros.

Uso: python tools/stress_check.py [--seed N]
Registra toda excepción no capturada (también dentro de slots de Qt) y los avisos críticos de Qt. Los
diálogos modales se aceptan o cancelan solos. No mueve el ratón ni toca archivos del usuario: todo ocurre en
una carpeta temporal. Termina con «RESULTADO: N problemas».
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AERO_DATA_DIR"] = tempfile.mkdtemp(prefix="aero_stress_")
os.environ["AERO_NO_TUTORIAL"] = "1"  # el tutorial de bienvenida taparía la ventana
SEED = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 7
rnd = random.Random(SEED)

from PySide6.QtCore import QtMsgType, QTimer, qInstallMessageHandler  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox  # noqa: E402

import faulthandler  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_crash = open(os.path.join(tempfile.gettempdir(), f"aero_stress_crash_{SEED}_{os.getpid()}.txt"), "w", encoding="utf-8")
faulthandler.enable(_crash, all_threads=True)
# Diagnóstico: con --hang-dump N se vuelcan las pilas y se sale si un paso tarda más de N segundos.
HANG_DUMP = int(sys.argv[sys.argv.index("--hang-dump") + 1]) if "--hang-dump" in sys.argv else 0
app = QApplication([])
problems: list[str] = []
_plog = open(os.path.join(tempfile.gettempdir(), "aero_stress_problems.txt"), "w", encoding="utf-8")


def report(text: str):
    problems.append(text)
    _plog.write("PROBLEMA " + text + "\n")
    _plog.flush()


step_name = ["inicio"]


def hook(t, v, tb):
    report(f"[{step_name[0]}] {t.__name__}: {v}\n" + "".join(traceback.format_tb(tb)[-4:]))


sys.excepthook = hook


def qt_handler(mode, ctx, msg):
    if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg) or "Traceback" in msg:
        report(f"[{step_name[0]}] Qt: {msg}")


qInstallMessageHandler(qt_handler)

# Diálogos: nunca bloquean
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.exec = lambda self: (self.setProperty("_auto", True), 0)[1]
QDialog.exec = lambda self: (QTimer.singleShot(0, self.reject), 0)[1]
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
QInputDialog.getText = staticmethod(lambda *a, **k: ("Prueba", True))
QInputDialog.getInt = staticmethod(lambda *a, **k: (2, True))
QInputDialog.getItem = staticmethod(lambda *a, **k: ("Barras", True))
QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: ("Texto\ncon dos líneas", True))


def pump(t=0.2):
    end = time.monotonic() + t
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


def step(name):
    def deco(fn):
        def run(*a, **k):
            step_name[0] = name
            print(f"· {name}", flush=True)
            if HANG_DUMP:  # el plazo cuenta por paso, no para toda la auditoría
                faulthandler.dump_traceback_later(HANG_DUMP, file=_crash, exit=True)
            try:
                fn(*a, **k)
            except Exception as e:  # noqa: BLE001
                report(f"[{name}] {type(e).__name__}: {e}\n" + "".join(traceback.format_exc().splitlines(True)[-6:]))
            pump(0.1)
        return run
    return deco


# --------------------------------------------------------------------------- archivos de prueba
W = Path(tempfile.mkdtemp(prefix="aero_stress_files_"))
M = ROOT / "tests" / "media"


def ff(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def make_files() -> dict[str, Path]:
    f: dict[str, Path] = {}
    for src in M.iterdir():
        if src.is_file():
            dst = W / src.name
            shutil.copy(src, dst)
            f[src.name] = dst
    ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=3", "-f", "lavfi", "-i",
       "sine=frequency=300:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
       str(W / "vídeo ñ.mp4"))
    f["video"] = W / "vídeo ñ.mp4"
    weird = W / "😀 nombre muy largo con acentos áéíóú y espacios   final.png"
    shutil.copy(M / "cover.png", weird)
    f["weird"] = weird
    for name, data in (("vacio.png", b""), ("vacio.pdf", b""), ("roto.docx", b"PK\x03\x04basura"),
                       ("roto.xlsx", b"no es un xlsx"), ("roto.pptx", b"\x00\x01\x02"), ("roto.pdf", b"%PDF-1.4\n%%EOF"),
                       ("roto.zip", b"PK\x05\x06" + b"\0" * 18), ("roto.mp3", b"ID3" + b"\0" * 100),
                       ("binario.txt", bytes(range(256)) * 10), ("vacio.txt", b""), ("roto.7z", b"7z\xbc\xaf\x27\x1c"),
                       ("roto.rar", b"Rar!\x1a\x07\x00"), ("vacio.csv", b""), ("roto.odt", b"PK"),
                       ("raro.xyz", b"???")):
            (W / name).write_bytes(data)
            f[name] = W / name
    with zipfile.ZipFile(W / "bueno.zip", "w") as z:
        z.write(M / "foto.jpg", "fotos/foto.jpg")
        z.write(M / "doc.pdf", "doc.pdf")
        z.writestr("../evil.txt", "x")
        z.writestr("vacía/", "")
    f["bueno.zip"] = W / "bueno.zip"
    (W / "carpeta" / "sub").mkdir(parents=True)
    for i in range(30):
        (W / "carpeta" / f"archivo {i}.txt").write_text(str(i), encoding="utf-8")
    shutil.copy(M / "foto.jpg", W / "carpeta" / "sub" / "foto.jpg")
    f["carpeta"] = W / "carpeta"
    return f


# --------------------------------------------------------------------------- recorrido
from aero.core.config import Settings  # noqa: E402
from aero.core.db import Database  # noqa: E402
from aero.ui.controller import AppController  # noqa: E402
from aero.ui.main_window import PAGE_KEYS, apply_theme  # noqa: E402

settings = Settings()
settings.set("quicklook_enabled", False)
apply_theme(app, settings)
ctl = AppController(app, settings, Database())
ctl.quit = lambda: None
files = make_files()


@step("ventana principal y páginas")
def pages():
    win = ctl.show_main()
    for size in ((640, 420), (1920, 1080), (1100, 720)):
        win.resize(*size)
        for k in PAGE_KEYS:
            win.navigate(k)
            pump(0.15)


@step("temas y perfiles")
def themes():
    from aero.ui.theme import PRESETS

    for key in list(PRESETS)[:6]:
        settings.set("theme", key)
        pump(0.1)
    for prof in ("ultra", "high", "balanced"):
        settings.set("quality_profile", prof)
        pump(0.1)
    for mode in ("opaque", "clear", "blur"):
        settings.set("glass_mode", mode)
        pump(0.1)
    settings.set("quality_auto", True)
    settings.set("quality_auto", False)


@step("abrir cada archivo desde Windows")
def open_all():
    for name, path in sorted(files.items()):
        step_name[0] = f"abrir {name}"
        print(f"   abrir {name}", flush=True)
        ctl.open_files([str(path)])
        pump(0.6)
    for e in list(ctl.editors):
        _discard(e)
    for w in list(ctl.media_windows):
        w.close()
    pump(0.3)


def _discard(e):
    for attr in ("dirty",):
        if hasattr(e, attr):
            setattr(e, attr, False)
    if hasattr(e, "doc") and getattr(e, "doc", None) is not None and hasattr(e.doc, "dirty"):
        e.doc.dirty = False
    if hasattr(e, "text") and hasattr(e.text, "document"):
        e.text.document().setModified(False)
    e.close()


@step("vista rápida de cada archivo")
def quicklook_all():
    for name, path in sorted(files.items()):
        step_name[0] = f"quick look {name}"
        ctl.show_quicklook(str(path))
        pump(0.5)
        ql = ctl.quicklook
        if ql.kind in ("folder", "archive") and "browse" in ql._views:
            b = ql._views["browse"]
            if b.model.rowCount():
                b._activate(b.model.index(0))
                pump(0.5)
                ql.go_back()
                pump(0.3)
        ql.close_preview()
    pump(0.3)


@step("visor principal con cada archivo")
def viewer_all():
    win = ctl.show_main()
    host = win.page("viewer")
    for name, path in sorted(files.items()):
        step_name[0] = f"visor {name}"
        host.open(str(path))
        pump(0.4)
    host.clear()


@step("biblioteca de archivos")
def files_page():
    win = ctl.show_main()
    page = win.page("files")
    win.navigate("files")
    page.add_folder(str(files["carpeta"]))
    page.add_folder(str(W))
    page.add_folder(str(W / "no existe"))
    page.refresh()
    pump(0.5)
    page.open_folder(str(files["carpeta"]))
    pump(0.5)
    b = page.browser
    for f in ("image", "docs", "all"):
        b.filter.setCurrentIndex(b.filter.findData(f))
    for s in ("size", "date", "kind", "name"):
        b.sort.setCurrentIndex(b.sort.findData(s))
    b.set_grid(False)
    b.set_grid(True)
    b.search.setText("1")
    b.search.clear()
    page.show_library()
    page._set(str(W), color="#ff0000", favorite=1, title="Todo")
    page._move(str(W), 0)
    page.remove(str(W), confirm=False)


@step("editor de imágenes (operaciones al azar)")
def image_editor():
    from PySide6.QtCore import QPointF, QRect

    ed = ctl.open_image_editor(str(files["grande.jpg"]))
    end = time.monotonic() + 10
    while ed.doc is None and time.monotonic() < end:
        pump(0.1)
    d = ed.doc
    W_, H_ = d.size.width(), d.size.height()
    ops = [lambda: d.rotate90(rnd.random() < 0.5), lambda: d.flip(rnd.random() < 0.5),
           lambda: d.crop(QRect(rnd.randint(0, 50), rnd.randint(0, 50), rnd.randint(10, 400), rnd.randint(10, 400))),
           lambda: d.pixelate(QRect(0, 0, rnd.randint(1, 300), rnd.randint(1, 300)), rnd.randint(2, 40)),
           lambda: d.blur_region(QRect(10, 10, 100, 100), rnd.randint(1, 10)),
           lambda: d.straighten(rnd.uniform(-10, 10)), lambda: d.resize(rnd.randint(10, 900), rnd.randint(10, 900)),
           lambda: ed.apply_preset(rnd.choice(["Vívido", "Sepia", "Original", "Dramático"])),
           lambda: ed.set_adjust(rnd.choice(["brightness", "contrast", "blur", "sharpness", "vignette"]),
                                 rnd.uniform(-1, 1)),
           lambda: ed.undo(), lambda: ed.redo(),
           lambda: ed.canvas.place_text(QPointF(5, 5), "Hola"),
           lambda: d.add_margins(5, 5, 5, 5, ed.canvas.color),
           lambda: d.low_resolution(rnd.randint(2, 20)), lambda: d.mosaic(QRect(0, 0, 50, 50), 8)]
    for _ in range(60):
        rnd.choice(ops)()
        ed.canvas.refresh()
        ed._sync_all()
        pump(0.02)
    for cat in ("compose", "color", "pixels", "draw", "text", "layers"):
        ed.show_category(cat)
    out = W / "editada.png"
    ed.export_to(str(out), "png", 90, 0.5)
    pump(2)
    assert out.exists(), "la exportación no creó el archivo"
    _discard(ed)
    _ = (W_, H_)


@step("editor de documentos")
def doc_editor():
    from PySide6.QtGui import QTextCursor, QTextListFormat

    ed = ctl.open_document_editor(str(files["informe.docx"]))
    pump(0.5)
    t = ed.text
    for _ in range(40):
        cur = t.textCursor()
        cur.setPosition(rnd.randint(0, max(0, len(t.toPlainText()))))
        t.setTextCursor(cur)
        rnd.choice([lambda: t.insertPlainText("texto "), lambda: ed.set_heading(rnd.randint(0, 3)),
                    lambda: ed.bold.click(), lambda: ed.set_list(QTextListFormat.Style.ListDisc),
                    lambda: ed.set_list(QTextListFormat.Style.ListDecimal), lambda: t.undo(), lambda: t.redo(),
                    lambda: ed.toggle_highlight(), lambda: ed.replace_all("a", "e")])()
    cur = t.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    t.setTextCursor(cur)
    ed.insert_table()
    for ext in ("docx", "odt", "md", "html", "txt"):
        ed.save_to(str(W / f"doc_salida.{ext}"))
    from aero.office import docio

    docio.export_pdf(t.document(), str(W / "doc_salida.pdf"))
    _discard(ed)
    for name in ("notas.md", "roto.docx", "vacio.txt", "binario.txt"):
        step_name[0] = f"documento {name}"
        e2 = ctl.open_document_editor(str(files[name]))
        pump(0.2)
        _discard(e2)


@step("editor de hojas")
def sheet_editor():
    ed = ctl.open_sheet_editor(str(files["datos.xlsx"]))
    m = ed.model
    for _ in range(60):
        r, c = rnd.randint(0, 20), rnd.randint(0, 8)
        idx = m.index(r, c)
        ed.view.setCurrentIndex(idx)
        rnd.choice([lambda: m.setData(idx, str(rnd.randint(-100, 100))),
                    lambda: m.setData(idx, f"=SUMA(A1:B{rnd.randint(1, 9)})"),
                    lambda: m.setData(idx, "=1/0"), lambda: m.setData(idx, "=A1+"), lambda: m.setData(idx, "texto"),
                    lambda: ed.toggle_font("b"), lambda: ed.sort_column(rnd.random() < 0.5), ed.undo,
                    lambda: ed.filter.setText(rnd.choice(["", "1", "x"])), ed.clear_cells,
                    lambda: ed.set_number_format(rnd.choice(["General", "0.00%", "#,##0.00 €"]))])()
    ed.add_sheet()
    ed.insert_chart("Líneas", preview=False)
    for ext in ("xlsx", "csv", "ods"):
        ed.save_to(str(W / f"hoja.{ext}"))
    _discard(ed)
    for name in ("vacio.csv", "roto.xlsx"):
        step_name[0] = f"hoja {name}"
        e2 = ctl.open_sheet_editor(str(files[name]))
        pump(0.2)
        _discard(e2)


@step("editor de presentaciones")
def slides_editor():
    ed = ctl.open_slides_editor(str(files["diapos.pptx"]))
    for _ in range(25):
        rnd.choice([ed.new_slide, ed.dup_slide, ed.del_slide, ed.undo, lambda: ed.add_text("Texto"),
                    lambda: ed.add_shape(), lambda: ed._move(rnd.choice([-1, 1])),
                    lambda: ed.go(rnd.randint(0, len(ed.prs.slides) - 1))])()
        pump(0.02)
    ed.save_to(str(W / "presentacion.pptx"))
    ed.export_pdf(str(W / "presentacion.pdf"))
    _discard(ed)
    e2 = ctl.open_slides_editor(str(files["roto.pptx"])) if False else None
    _ = e2


@step("editor de vídeo")
def video_editor():
    from aero.editors.video.window import ExportDialog

    ed = ctl.open_video_editor(str(files["video"]))
    ed.import_paths([str(files["tone.mp3"]), str(files["foto.jpg"]), str(W / "no existe.mp4")])
    ed.add_to_timeline(str(files["tone.mp3"]))
    ed.add_to_timeline(str(files["foto.jpg"]))
    for _ in range(40):
        ed.seek(rnd.uniform(0, max(0.1, ed.project.duration)))
        rnd.choice([ed.split, ed.add_text, ed.undo, ed.redo, ed.delete,
                    lambda: ed.timeline.selected.update({c.id for _t, c in ed.project.all_clips()} if rnd.random() < 0.2
                                                        else set()),
                    lambda: ed.add_track(rnd.choice(["video", "audio"]))])()
        pump(0.02)
    ed.toggle_play()
    pump(1.0)
    ed.toggle_play()
    if ed.project.duration > 0:
        dlg = ExportDialog(ed)
        dlg.start(str(W / "montaje.mp4"))
        end = time.monotonic() + 60
        while not hasattr(dlg, "result_code") and time.monotonic() < end:
            pump(0.1)
        assert getattr(dlg, "result_code", 1) == 0, dlg.status.text()
    ed.project_path = str(W / "montaje.aerovid")
    ed.save_project()
    _discard(ed)
    e2 = ctl.open_video_editor(str(W / "montaje.aerovid"))
    pump(0.3)
    _discard(e2)


@step("PDF a editable")
def pdfconv():
    for name in ("doc.pdf", "roto.pdf", "vacio.pdf"):
        step_name[0] = f"pdf {name}"
        w = ctl.open_pdf_convert(str(files[name]))
        w.convert()
        end = time.monotonic() + 30
        while not w.go.isEnabled() and time.monotonic() < end:
            pump(0.1)
        pump(0.3)
        w.close()


@step("conversor común")
def converter():
    from aero.core.convert_spec import ConvertOptions, targets_for
    from aero.core.converter import ConversionManager

    cm = ConversionManager(settings)
    jobs = []
    for name in ("foto.jpg", "tone.mp3", "doc.pdf", "informe.docx", "datos.xlsx", "roto.mp4"):
        t = targets_for(str(files[name]), office=False)
        if t:
            jobs += cm.add([(str(files[name]), "")], ConvertOptions(target=t[0][0]), W / "convertidos")
    end = time.monotonic() + 120
    while cm.busy() and time.monotonic() < end:
        pump(0.1)
    for j in cm.jobs.values():
        print(f"   {j.src.name} → {j.opts.target}: {j.state} {j.message[:80]}")


@step("extraer y comprimir (acciones del menú contextual)")
def archives():
    from aero.archive import ui

    ui.AUTO_CLOSE_S = 1
    targets = [str(files[n]) for n in ("bueno.zip", "roto.zip", "roto.7z", "roto.rar")]

    def settle(t=60):
        end = time.monotonic() + t
        while time.monotonic() < end and any(isinstance(w, ui.ProgressWindow) and w.ok is None for w in ctl.editors):
            pump(0.1)
        for w in list(ctl.editors):
            if isinstance(w, ui.ProgressWindow):
                w.close()
        pump(0.2)

    for action in ("extract_here", "extract_folder", "extract_to"):
        ctl._do_action(action, targets)
        settle()
    for action in ("compress_zip", "compress_7z", "compress"):
        ctl._do_action(action, [str(files["carpeta"]), str(files["weird"])])
        settle()
    for name in ("bueno.zip", "roto.zip", "roto.7z"):
        ctl._do_action("open_archive", [str(files[name])])
        pump(0.8)
    for w in list(ctl.editors):
        if isinstance(w, ui.ArchiveManager):
            w.browser.view.selectAll() if hasattr(w.browser, "view") else None
            w.extract_folder()
            settle()
            w.test()
            w.close()
    ctl._do_action("convert", [str(files["foto.jpg"]), str(files["weird"])])
    ctl._do_action("convert", [str(files["foto.jpg"]), str(files["tone.mp3"])])
    pump(0.5)
    from aero.ui.quick_convert import QuickConvert

    for w in list(ctl.editors):
        if isinstance(w, QuickConvert):
            if w.go.isEnabled():
                w.folder.setText(str(W / "rapido"))
                w.start()
                end = time.monotonic() + 60
                while w.cm.busy() and time.monotonic() < end:
                    pump(0.1)
            w.close()
    for action in ("open", "quicklook", "edit", "browse"):
        ctl._do_action(action, [str(files["foto.jpg"])] if action != "browse" else [str(files["carpeta"])])
        pump(0.6)
    if ctl.quicklook is not None:
        ctl.quicklook.close_preview()
    for w in list(ctl.media_windows) + [e for e in ctl.editors if e.isVisible()]:
        _discard(w)


@step("reproductor")
def player():
    win = ctl.show_main()
    win.play([str(files["tone.mp3"]), str(files["video"]), str(files["roto.mp4"])], 0)
    pump(1.0)
    win.engine.next()
    pump(1.0)
    win.engine.next()
    pump(0.5)
    settings.set("visualizer_enabled", True)
    win.navigate("player")
    pump(0.5)
    win.engine.stop()


for fn in (pages, themes, open_all, quicklook_all, viewer_all, files_page, image_editor, doc_editor, sheet_editor,
           slides_editor, video_editor, pdfconv, converter, archives, player):
    fn()

print()
for p in problems:
    print("PROBLEMA", p)
print(f"RESULTADO: {len(problems)} problemas")
sys.stdout.flush()
os._exit(1 if problems else 0)
