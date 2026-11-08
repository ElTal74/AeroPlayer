"""Pruebas de integración con procesos y motores reales: FFmpeg, Pillow, QtPdf, calamine, escáner y reproducción."""

import time

import pytest

from aero.core import tools
from aero.core.convert_spec import ConvertOptions
from aero.core.metadata import read_editable, read_tags, write_tags


def wait_until(qapp, cond, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


class FakeSettings:
    def __init__(self, **kw):
        self.d = {"keep_structure": False, "max_parallel_jobs": 2, "use_hw_encoding": False, **kw}

    def get(self, k):
        return self.d.get(k)


def run_jobs(qapp, items, opts, out_dir, timeout=120):
    from aero.core.converter import FINISHED, ConversionManager

    m = ConversionManager(FakeSettings())
    ids = m.add([(str(p), "") for p in items], opts, out_dir)
    assert wait_until(qapp, lambda: all(m.jobs[i].state in FINISHED for i in ids), timeout)
    return [m.jobs[i] for i in ids], m


def test_tags_read_and_write(media, tmp_path):
    src = tmp_path / "t.mp3"
    src.write_bytes((media / "tono.mp3").read_bytes())
    tags = read_tags(src)
    assert tags["title"] == "Tono" and tags["album"] == "Álbum Ñ" and 1.5 < tags["duration"] < 2.5
    write_tags(src, {"title": "Nuevo", "artist": "Yo", "tracknumber": "3"})
    assert read_editable(src)["title"] == "Nuevo"
    assert read_tags(src)["track"] == 3
    assert read_tags(media / "dañado.mp4") == {}  # archivo corrupto: sin excepción


def test_convert_audio_video_image(qapp, media, tmp_path):
    if not tools.find_tool("ffmpeg"):
        pytest.skip("sin FFmpeg")
    out = tmp_path / "salida con espacios & acentos ñ"
    jobs, _ = run_jobs(qapp, [media / "clip.mkv"], ConvertOptions(target="mp4", preset="conservar"), out)
    assert jobs[0].state == "Completado", jobs[0].message
    info = tools.probe(str(jobs[0].outputs[0]))
    assert info["streams"][0]["codec_name"] == "h264"

    jobs, _ = run_jobs(qapp, [media / "clip.mkv"], ConvertOptions(target="mp3", preset="reducido"), out)
    assert jobs[0].state == "Completado", jobs[0].message
    assert jobs[0].outputs[0].suffix == ".mp3"

    jobs, _ = run_jobs(qapp, [media / "clip.mkv"], ConvertOptions(target="webm", max_height=120, hw=False), out)
    assert jobs[0].state == "Completado", jobs[0].message
    v = [s for s in tools.probe(str(jobs[0].outputs[0]))["streams"] if s["codec_type"] == "video"][0]
    assert v["codec_name"] == "vp9" and v["height"] == 120

    jobs, _ = run_jobs(qapp, [media / "img.png"] * 2, ConvertOptions(target="jpg", quality=80), out)
    names = sorted(j.outputs[0].name for j in jobs)
    assert names == ["img (1).jpg", "img.jpg"]  # sin sobrescribir


def test_convert_errors_are_friendly(qapp, media, tmp_path):
    jobs, _ = run_jobs(qapp, [media / "dañado.mp4"], ConvertOptions(target="mp3"), tmp_path)
    assert jobs[0].state == "Error"
    assert jobs[0].message and not list(tmp_path.glob("*.mp3"))  # no deja archivos parciales


def test_cancel_and_retry(qapp, media, tmp_path):
    from aero.core.converter import ConversionManager

    m = ConversionManager(FakeSettings())
    (jid,) = m.add([(str(media / "clip.mkv"), "")], ConvertOptions(target="mkv", preset="alta", hw=False), tmp_path)
    m.cancel(jid)
    assert wait_until(qapp, lambda: m.jobs[jid].state == "Cancelado", 30)
    m.retry(jid)
    assert wait_until(qapp, lambda: m.jobs[jid].state == "Completado", 120), m.jobs[jid].message


def test_builtin_documents(qapp, tmp_path):
    from aero.core.builtin_convert import html_to_pdf, pdf_to_images, pdf_to_text

    pdf = tmp_path / "d.pdf"
    html_to_pdf("<h1>Hola</h1><p>cristal</p>" * 40, pdf)
    assert pdf.stat().st_size > 1000
    txt = tmp_path / "d.txt"
    pdf_to_text(pdf, txt, None, lambda f: None, lambda: False)
    assert "cristal" in txt.read_text(encoding="utf-8")
    outs = pdf_to_images(pdf, tmp_path / "d.png", ConvertOptions(target="png", extra={"dpi": 40}),
                         lambda f: None, lambda: False)
    assert len(outs) >= 1 and all(o.exists() for o in outs)


def test_sheet_viewer_loader(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from aero.ui.viewers.doc_viewers import load_sheets

    wb = openpyxl.Workbook()
    wb.active.append(["a", 1.5])
    wb.create_sheet("Dos").append(["x"])
    p = tmp_path / "w.xlsx"
    wb.save(p)
    sheets = load_sheets(str(p))
    assert [s[0] for s in sheets] == ["Sheet", "Dos"] and sheets[0][1][0] == ["a", 1.5]
    csv = tmp_path / "c.csv"
    csv.write_text("x;y\n1;2\n", encoding="utf-8")
    assert load_sheets(str(csv))[0][1] == [["x", "y"], ["1", "2"]]


def test_scanner_incremental(qapp, media, tmp_path):
    from aero.core.db import Database
    from aero.core.scanner import LibraryScanner

    lib = tmp_path / "lib"
    (lib / "sub").mkdir(parents=True)
    (lib / "excluida").mkdir()
    (lib / "sub" / "a.mp3").write_bytes((media / "tono.mp3").read_bytes())
    (lib / "excluida" / "b.mp3").write_bytes((media / "tono.mp3").read_bytes())
    (lib / "c.mkv").write_bytes((media / "clip.mkv").read_bytes())
    dbp = tmp_path / "lib.db"

    def scan():
        s = LibraryScanner([str(lib)], [str(lib / "excluida")], dbp)
        result = []
        s.finished_scan.connect(lambda c, r: result.append((c, r)))
        s.start()
        assert wait_until(qapp, lambda: bool(result), 30)
        s.wait()
        return result[0]

    assert scan() == (2, 0)
    assert scan() == (0, 0)  # incremental: nada cambia
    (lib / "c.mkv").unlink()
    assert scan() == (0, 1)
    db = Database(dbp)
    assert db.count_media("audio") == 1 and db.media_by_path(str(lib / "sub" / "a.mp3"))["title"] == "Tono"
    assert (lib / "sub" / "a.mp3").exists()  # nunca se tocan los archivos
    db.close()


def test_player_plays_and_analyses(qapp, media):
    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.player.engine import PlayerEngine

    eng = PlayerEngine(Settings(), Database())
    eng.audio.setVolume(0.0)
    eng.set_analysis(True)
    eng.play_files([str(media / "tono.mp3"), str(media / "dañado.mp4")])
    assert wait_until(qapp, lambda: eng.player.position() > 500, 20)
    assert eng.current.title == "Tono"
    assert wait_until(qapp, lambda: (eng.analyzer.update(), eng.analyzer.level > 0.05)[1], 10)
    errors = []
    eng.error.connect(errors.append)
    eng.next()
    assert wait_until(qapp, lambda: bool(errors), 15)  # archivo dañado: error controlado, sin bloqueo
    eng.stop()
