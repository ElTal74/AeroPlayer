"""1.8: perfiles del conversor con tamaño estimado, lotes (renombrar y redimensionar) y borradores recuperables."""

import hashlib
import os
import subprocess
import time
from pathlib import Path

import pytest


def pump(app, s=0.2):
    end = time.time() + s
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_for(app, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- conversor

def _info(w, h, fps="30/1", dur=10.0, vcodec="h264", acodec="aac"):
    return {"format": {"duration": str(dur)},
            "streams": [{"codec_type": "video", "codec_name": vcodec, "width": w, "height": h, "avg_frame_rate": fps},
                        {"codec_type": "audio", "codec_name": acodec, "channels": 2, "sample_rate": "48000"}]}


def test_compat_presets_use_h264_and_cap_short_side():
    from aero.core.convert_spec import ConvertOptions, build_ffmpeg_args

    encs = {"libx264", "libx265", "libvpx-vp9", "libsvtav1"}
    for preset in ("moviles", "windows"):
        args = build_ffmpeg_args("ffmpeg", "a.mkv", "b.mp4", ConvertOptions("mp4", preset, video_codec="auto"),
                                 _info(3840, 2160, "60/1"), encs)
        assert args[args.index("-c:v") + 1] == "libx264"
        assert "yuv420p" in args and "-profile:v" in args
        assert "aac" in args
        vf = args[args.index("-vf") + 1]
        assert ("1080" if preset == "moviles" else "2160") in vf and "gte(iw,ih)" in vf
    args = build_ffmpeg_args("ffmpeg", "a.mkv", "b.mp4", ConvertOptions("mp4", "moviles"), _info(1920, 1080), encs)
    assert args[args.index("-fpsmax") + 1] == "60"


def test_preset_notes_and_estimate():
    from aero.core.convert_spec import ConvertOptions, estimate_size, note_values, preset_notes

    vertical = _info(2160, 3840)
    notes = preset_notes(ConvertOptions("mp4", "moviles"), "v.mp4", vertical)
    assert "Se reducirá de {a}p a {b}p." in notes
    assert note_values["Se reducirá de {a}p a {b}p."] == {"a": 2160, "b": 1080}
    assert any("comprimir" in n for n in notes)
    assert any("MP4" in n for n in preset_notes(ConvertOptions("webm", "moviles"), "v.mp4", vertical))
    # Conservar con un contenedor compatible: sin aviso de pérdida y tamaño casi igual al original
    keep = ConvertOptions("mkv", "conservar")
    assert not preset_notes(keep, "v.mp4", _info(1920, 1080))
    lo, hi = estimate_size("v.mp4", keep, _info(1920, 1080), 50_000_000)
    assert 48_000_000 < lo <= hi < 51_000_000
    # Audio: MP3 a 192 kbps durante 10 s ≈ 240 kB
    lo, hi = estimate_size("a.wav", ConvertOptions("mp3", "equilibrado", audio_bitrate=192), _info(0, 0, dur=10), 0)
    assert lo <= 240_000 <= hi
    # Reducido es más pequeño que alta calidad
    small = estimate_size("v.mp4", ConvertOptions("mp4", "reducido"), _info(1920, 1080), 0)
    big = estimate_size("v.mp4", ConvertOptions("mp4", "alta"), _info(1920, 1080), 0)
    assert small[1] < big[0] * 1.5 and small[0] < big[0]
    # Sin duración o sin ffprobe no se inventa nada
    assert estimate_size("v.mp4", ConvertOptions("mp4"), None, 0) is None
    assert estimate_size("f.jpg", ConvertOptions("png"), None, 0) is None


def test_estimate_matches_real_encode(media, tmp_path):
    from aero.core import tools
    from aero.core.convert_spec import ConvertOptions, build_ffmpeg_args, estimate_size

    src = str(media / "clip.mkv")
    info = tools.probe(src)
    for preset in ("moviles", "windows", "reducido"):
        o = ConvertOptions("mp4", preset, hw=False)
        out = tmp_path / f"{preset}.mp4"
        args = [a for a in build_ffmpeg_args(tools.find_tool("ffmpeg"), src, str(out), o, info, tools.encoders())
                if a not in ("-progress", "pipe:1", "-nostats")]
        subprocess.run(args, check=True, capture_output=True)
        real = out.stat().st_size
        lo, hi = estimate_size(src, o, info, os.path.getsize(src))
        # El vídeo de prueba es sintético: se admite el doble de margen que la estimación mostrada
        assert lo / 2 <= real <= hi * 2, (preset, real, lo, hi)
        v = [s for s in tools.probe(str(out))["streams"] if s["codec_type"] == "video"][0]
        assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p"


def test_converter_page_shows_estimate(qapp, controller, media):
    from aero.ui.pages.converter_page import ConverterPage

    page = ConverterPage(controller.show_main().converter, controller.settings)
    page.add_paths([str(media / "clip.mkv"), str(media / "tono.mp3")])
    i = page.preset.findData("moviles")
    page.preset.setCurrentIndex(i)
    assert wait_for(qapp, lambda: "Tamaño estimado" in page.estimate.text(), 15), page.estimate.text()
    assert "comprimir" in page.estimate.text()
    page.deleteLater()
    pump(qapp, 0.1)


# ----------------------------------------------------------------------------- renombrado por lotes

def _files(d: Path, names):
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for n in names:
        p = d / n
        p.write_text(n, encoding="utf-8")
        out.append(p)
    return out


def test_batch_rename_plan_apply_and_undo(tmp_path):
    from aero.core import batch

    d = tmp_path / "fotos"
    srcs = _files(d, ["IMG_001.JPG", "IMG_002.JPG", "nota.txt"])
    (d / "otro.txt").write_text("ajeno", encoding="utf-8")
    opts = batch.RenameOptions(pattern="Viaje {n}", start=1, digits=3, lower_ext=True)
    plan = batch.plan_rename(srcs, opts)
    assert [it.name for it in plan] == ["Viaje 001.jpg", "Viaje 002.jpg", "Viaje 003.txt"]
    assert not any(it.problem for it in plan)
    done = batch.apply_rename(plan)
    assert sorted(p.name for p in d.iterdir()) == ["Viaje 001.jpg", "Viaje 002.jpg", "Viaje 003.txt", "otro.txt"]
    assert (d / "Viaje 003.txt").read_text(encoding="utf-8") == "nota.txt"
    assert batch.undo_rename(done) == 3
    assert sorted(p.name for p in d.iterdir()) == ["IMG_001.JPG", "IMG_002.JPG", "nota.txt", "otro.txt"]

    # Conflictos: nombre de un archivo ajeno, duplicados y caracteres no válidos → no se aplican
    plan = batch.plan_rename([d / "nota.txt"], batch.RenameOptions(pattern="otro"))
    assert plan[0].problem
    plan = batch.plan_rename(srcs[:2], batch.RenameOptions(pattern="igual"))
    assert all("mismo nombre" in it.problem for it in plan)
    plan = batch.plan_rename(srcs[:1], batch.RenameOptions(pattern="a:b"))
    assert "caracteres" in plan[0].problem
    assert batch.apply_rename(plan) == []
    assert (d / "otro.txt").read_text(encoding="utf-8") == "ajeno"

    # Intercambiar dos nombres dentro del lote funciona (renombrado en dos pasos)
    a, b = _files(tmp_path / "swap", ["a.txt", "b.txt"])
    items = [batch.RenameItem(a, "b.txt"), batch.RenameItem(b, "a.txt")]
    batch.apply_rename(items)
    assert (tmp_path / "swap" / "a.txt").read_text(encoding="utf-8") == "b.txt"

    # Buscar y reemplazar sin distinguir mayúsculas y tipo título
    plan = batch.plan_rename([d / "IMG_001.JPG"], batch.RenameOptions(find="img_", replace="foto ", case="title"))
    assert plan[0].name == "Foto 001.JPG"


def test_batch_rename_window(qapp, controller, tmp_path):
    d = tmp_path / "r"
    srcs = _files(d, ["b.txt", "a.txt", "c.txt"])
    controller.run_action("batch_rename", [str(p) for p in srcs], immediate=True)
    pump(qapp, 0.3)
    from aero.ui.batch_tools import BatchRename

    w = next(e for e in controller.editors if isinstance(e, BatchRename))
    w.pattern.setText("doc-{n}")
    w.preview()
    assert w.table.item(0, 1).text() == "doc-01.txt"
    w.apply()
    assert sorted(p.name for p in d.iterdir()) == ["doc-01.txt", "doc-02.txt", "doc-03.txt"]
    assert w.undo_btn.isVisibleTo(w)
    w.undo()
    assert sorted(p.name for p in d.iterdir()) == ["a.txt", "b.txt", "c.txt"]
    w.close()
    pump(qapp, 0.1)
    assert w not in controller.editors


# ----------------------------------------------------------------------------- redimensionado por lotes

def _photo(path: Path, w: int, h: int, orientation: int = 1):
    from PIL import Image

    im = Image.new("RGB", (w, h), (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x010F] = "Camara de prueba"
    im.save(path, "JPEG", quality=90, exif=exif.tobytes())
    return path


def test_batch_resize_core(tmp_path):
    from PIL import Image

    from aero.core import batch

    src = _photo(tmp_path / "girada.jpg", 400, 200, orientation=6)   # se ve en vertical (200×400)
    before = _sha(src)
    out = batch.resize_image(src, batch.ResizeOptions(mode="max", side=100))
    assert out == tmp_path / "Redimensionadas" / "girada.jpg"
    with Image.open(out) as im:
        assert im.size == (50, 100)
        assert im.getexif().get(0x0112, 1) == 1 and im.getexif().get(0x010F) == "Camara de prueba"
    assert _sha(src) == before
    # Nunca sobrescribe: la segunda vez se crea « (1)»
    assert batch.resize_image(src, batch.ResizeOptions(mode="max", side=100)).name == "girada (1).jpg"
    # Sin ampliar por defecto; con «ampliar» sí
    assert batch.target_size(200, 100, batch.ResizeOptions(mode="max", side=1000)) == (200, 100)
    assert batch.target_size(200, 100, batch.ResizeOptions(mode="max", side=1000, upscale=True)) == (1000, 500)
    assert batch.target_size(1000, 500, batch.ResizeOptions(mode="percent", percent=25)) == (250, 125)
    assert batch.target_size(1000, 500, batch.ResizeOptions(mode="box", width=300, height=300)) == (300, 150)
    # Sufijo junto al original, a WebP, sin metadatos
    out = batch.resize_image(src, batch.ResizeOptions(mode="percent", percent=50, fmt="webp", folder="",
                                                      strip_metadata=True))
    assert out.name == "girada_100x200.webp"
    with Image.open(out) as im:
        assert im.size == (100, 200) and not im.getexif().get(0x010F)


def test_batch_resize_window_registers_task(qapp, controller, tmp_path):
    from aero.core.activity import DONE, activities
    from aero.ui.batch_tools import open_batch_resize

    photos = [_photo(tmp_path / f"f{i}.jpg", 640, 480) for i in range(3)]
    (tmp_path / "roto.jpg").write_bytes(b"no es una foto")
    w = open_batch_resize([str(p) for p in photos] + [str(tmp_path / "roto.jpg")], controller)
    assert wait_for(qapp, lambda: "→" in (w.table.item(0, 1).text() if w.table.item(0, 1) else ""), 10)
    w.side.setValue(320)
    assert "640×480  →  320×240" in w.table.item(0, 1).text()
    w.start()
    assert wait_for(qapp, lambda: not w._queue and w.open_btn.isVisibleTo(w), 20)
    assert len(w.outputs) == 3 and len(w._errors) == 1
    assert sorted(p.name for p in (tmp_path / "Redimensionadas").iterdir()) == ["f0.jpg", "f1.jpg", "f2.jpg"]
    last = activities().history[0]
    assert last.state == DONE and last.kind == "image" and "Redimensionadas" in last.result
    w.close()


def test_files_browser_reloads_after_changes(qapp, tmp_path):
    from aero.files.browser import FolderBrowser

    d = tmp_path / "vigilada"
    _files(d, ["uno.txt"])
    b = FolderBrowser()
    b.set_root(str(d))
    assert wait_for(qapp, lambda: len(b.entries) == 1)
    (d / "dos.txt").write_text("x", encoding="utf-8")
    assert wait_for(qapp, lambda: len(b.entries) == 2, 5)
    os.rename(d / "uno.txt", d / "tres.txt")
    assert wait_for(qapp, lambda: sorted(e.name for e in b.entries) == ["dos.txt", "tres.txt"], 5)
    b.cleanup()
    assert not b.watcher.directories()
    b.deleteLater()
    pump(qapp, 0.1)


# ----------------------------------------------------------------------------- borradores

def test_drafts_autosave_and_recover_paint(qapp, controller, tmp_path):
    from PySide6.QtGui import QColor

    from aero.core import drafts
    from aero.ui import recovery

    src = tmp_path / "dibujo.png"
    from PySide6.QtGui import QImage

    img = QImage(64, 48, QImage.Format.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    img.save(str(src))
    before = _sha(src)
    w = controller.open_paint(str(src))
    pump(qapp, 0.2)
    assert not w.autosaver.tick()            # sin cambios: no hay borrador
    w.doc.layers[0].image.fill(QColor("#ff0000"))
    w.doc.dirty = True
    assert w.autosaver.tick()
    assert wait_for(qapp, lambda: not w.autosaver.writing)   # se escribe en segundo plano
    d = w.autosaver.draft
    assert d.path.exists() and d.meta_path.exists()
    assert _sha(src) == before and w.doc.path == str(src) and w.doc.dirty   # el archivo del usuario no cambia
    # Mientras el proceso vive, no se ofrece recuperar
    assert drafts.pending() == []
    # Simular un cierre inesperado: el borrador pertenece a un proceso que ya no existe
    import json

    meta = json.loads(d.meta_path.read_text(encoding="utf-8"))
    meta["pid"] = 999999
    d.meta_path.write_text(json.dumps(meta), encoding="utf-8")
    w.autosaver._timer.stop()
    w.autosaver = None
    w.doc.dirty = False
    w.close()
    pump(qapp, 0.2)
    pend = drafts.pending()
    assert [p.id for p in pend] == [d.id] and pend[0].source == str(src)
    assert recovery.recover(controller, pend[0])
    w2 = controller.editors[-1]
    assert w2.doc.path == str(src) and w2.doc.dirty
    assert w2.doc.render().pixelColor(5, 5) == QColor("#ff0000")
    drafts.discard(pend[0])
    assert drafts.pending() == []
    # Cerrar con normalidad borra el borrador del editor
    w2.autosaver.tick()
    assert wait_for(qapp, lambda: not w2.autosaver.writing)
    assert w2.autosaver.draft.path.exists()
    w2.doc.dirty = False
    w2.close()
    pump(qapp, 0.2)
    assert not w2.autosaver.draft.path.exists()
    assert drafts.all_drafts() == []


def test_drafts_video_and_disabled_setting(qapp, controller, tmp_path):
    from aero.core import drafts

    w = controller.open_video_editor()
    pump(qapp, 0.2)
    w.dirty = True
    assert w.autosaver.tick()
    assert not w.autosaver.tick()            # mismo contenido: no se reescribe
    data = w.autosaver.draft.path.read_text(encoding="utf-8")
    assert '"aero_video_project"' in data
    controller.settings.set("autosave_drafts", False)
    w.autosaver.discard()
    assert not w.autosaver.tick() and not w.autosaver.draft.path.exists()
    controller.settings.set("autosave_drafts", True)
    w.dirty = False
    w.close()
    pump(qapp, 0.2)
    assert drafts.all_drafts() == []


def test_recovery_dialog_lists_and_discards(qapp, tmp_path, monkeypatch):
    import json

    from aero.core import drafts
    from aero.ui.recovery import RecoveryDialog

    d = drafts.Draft("video", ".aerovid", "Vacaciones", "", time.time(), pid=999999)
    d.path.write_text("{}", encoding="utf-8")
    from dataclasses import asdict

    d.meta_path.write_text(json.dumps(asdict(d)), encoding="utf-8")
    assert [p.id for p in drafts.pending()] == [d.id]
    dlg = RecoveryDialog(drafts.pending())
    assert "Vacaciones" in dlg.list.item(0).text()
    assert dlg.selected()[0].id == d.id
    drafts.discard(d)
    assert drafts.pending() == []


@pytest.mark.parametrize("lang", ["en", "de"])
def test_new_strings_are_translated(lang):
    import json

    from aero import i18n

    cat = json.loads((Path(i18n.__file__).parent / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
    for s in ("Compatible con móviles", "Compatible con Windows", "Cambiar nombre en lote…", "Redimensionar fotos…",
              "Recuperar trabajo sin guardar", "Tamaño estimado: {a} – {b}", "Se reducirá de {a}p a {b}p."):
        assert s in cat, s
