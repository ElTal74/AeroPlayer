"""Editor de vídeo (fase D): edición no lineal, proyecto, medios ausentes y exportación real con FFmpeg."""

import json
import shutil
import subprocess
import time

import pytest


def _probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, encoding="utf-8", errors="replace")
    return json.loads(r.stdout)


@pytest.fixture()
def clips(media, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg no está disponible")
    v = tmp_path / "toma.mkv"
    shutil.copy(media / "clip.mkv", v)
    a = tmp_path / "musica.mp3"
    shutil.copy(media / "tono.mp3", a)
    img = tmp_path / "logo.png"
    shutil.copy(media / "img.png", img)
    return v, a, img


def _project(clips):
    from aero.editors.video.project import Clip, Project, clip_from_media, media_info

    v, a, img = clips
    p = Project(640, 360, 25.0)
    v1 = next(t for t in p.tracks if t.name == "V1")
    v2 = next(t for t in p.tracks if t.name == "V2")
    a1 = next(t for t in p.tracks if t.kind == "audio")
    c1 = p.add_clip(v1, clip_from_media(str(v), media_info(str(v))))
    assert abs(c1.duration - 2.0) < 0.15
    c2 = p.add_clip(v1, clip_from_media(str(v), media_info(str(v))))
    c2.speed = 2.0
    c2.transition, c2.transition_d = "dissolve", 0.3
    c2.brightness, c2.saturation = 0.05, 1.3
    im = p.add_clip(v1, clip_from_media(str(img), media_info(str(img))))
    im.out_s = 1.0
    im.fade_out = 0.3
    txt = p.add_clip(v2, Clip(kind="text", text="Título: «AERO» 100%", out_s=1.5, fade_in=0.3), at=0.2)
    mus = p.add_clip(a1, clip_from_media(str(a), media_info(str(a))), at=0.5)
    mus.volume, mus.fade_in = 0.5, 0.2
    return p, c1, c2, im, txt, mus


def test_editing_operations(clips):
    p, c1, c2, im, _txt, _mus = _project(clips)
    total = p.duration
    assert abs(total - (2.0 + 1.0 + 1.0)) < 0.2, "2 s + 2 s a velocidad doble + 1 s de imagen"
    second = p.split(c1.id, 0.8)
    assert second is not None and abs(c1.duration - 0.8) < 1e-6 and abs(second.in_s - 0.8) < 1e-6
    p.trim(second.id, "out", 1.5)
    assert abs(second.end - 1.5) < 1e-6
    p.trim(c1.id, "in", 0.3)
    assert abs(c1.in_s - 0.3) < 1e-6 and abs(c1.start - 0.3) < 1e-6
    p.move(im.id, 10.0)
    assert im.start == 10.0
    p.delete([im.id])
    assert p.find(im.id) == (None, None)
    before = p.duration
    p.ripple_delete_range(0.5, 1.0)
    assert abs(p.duration - (before - 0.5)) < 0.05, "eliminar un fragmento junta lo que queda"
    assert p.top_clip_at(0.4) is not None


def test_project_roundtrip_and_missing_media(clips, tmp_path):
    from aero.editors.video.project import Project

    p, c1, *_ = _project(clips)
    path = tmp_path / "montaje.aerovid"
    p.export["codec"] = "hevc"
    p.save(str(path))
    back = Project.load(str(path))
    assert [len(t.clips) for t in back.tracks] == [len(t.clips) for t in p.tracks]
    b1 = back.find(c1.id)[1]
    assert (b1.in_s, b1.out_s, b1.start) == (c1.in_s, c1.out_s, c1.start)
    assert back.export["codec"] == "hevc" and back.missing_media() == []
    clips[1].unlink()  # la música desaparece
    assert back.missing_media() == [str(clips[1])]


def test_export_real_file(clips, tmp_path):
    from aero.editors.video.export import build_command, parse_progress

    p, *_ = _project(clips)
    out = tmp_path / "final.mp4"
    args, total, temps = build_command(p, str(out), "mp4", "h264", 28, 128)
    t0 = time.monotonic()
    r = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    assert parse_progress(r.stdout, total) == pytest.approx(1.0, abs=0.05)
    info = _probe(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (int(v["width"]), int(v["height"])) == (640, 360) and v["codec_name"] == "h264"
    assert a["codec_name"] == "aac"
    assert abs(float(info["format"]["duration"]) - total) < 0.25
    for t in temps:
        __import__("os").remove(t)
    assert time.monotonic() - t0 < 60


def test_preview_segment_and_other_formats(clips, tmp_path):
    from aero.editors.video.export import build_command

    p, *_ = _project(clips)
    out = tmp_path / "previa.mp4"
    args, total, _t = build_command(p, str(out), start=1.0, end=3.0, scale_to=320, fast=True)
    r = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    info = _probe(out)
    assert abs(float(info["format"]["duration"]) - 2.0) < 0.25
    assert max(int(s.get("width", 0)) for s in info["streams"]) == 320
    webm = tmp_path / "final.webm"
    args, _total, _t = build_command(p, str(webm), "webm", "vp9", 33, 96, end=1.0)
    r = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    names = {s["codec_name"] for s in _probe(webm)["streams"]}
    assert names == {"vp9", "opus"}


def _wait(qapp, cond, t=30):
    end = time.monotonic() + t
    while time.monotonic() < end and not cond():
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


def test_editor_window_workflow(qapp, clips, tmp_path, controller):
    from aero.editors.video.project import Project
    from aero.editors.video.window import ExportDialog

    v, a, _img = clips
    ed = controller.open_video_editor(str(v))
    assert len(list(ed.project.all_clips())) == 1, "abrir un vídeo lo coloca en la línea de tiempo"
    assert _wait(qapp, lambda: str(v) in ed.timeline.thumbs and str(v) in ed.timeline.waves), \
        "miniatura y forma de onda en segundo plano"
    ed.import_paths([str(a)])
    ed.add_to_timeline(str(a))
    assert any(t.kind == "audio" and t.clips for t in ed.project.tracks)
    ed.seek(1.0)
    ed.timeline.selected.clear()
    ed.split()
    vids = [c for t in ed.project.tracks if t.kind == "video" for c in t.clips]
    assert len(vids) == 2
    ed.add_text()
    ed.f_text.setPlainText("Hola")
    assert ed.selected_clip().text == "Hola"
    ed.undo()
    ed.redo()
    ed.toggle_play()
    _wait(qapp, lambda: ed.timeline.playhead > 1.3, 5)
    ed.toggle_play()
    assert ed.timeline.playhead > 1.0, "la reproducción avanza el cabezal"
    proj = tmp_path / "montaje.aerovid"
    ed.project_path = str(proj)
    ed.save_project()
    assert Project.load(str(proj)).duration == ed.project.duration
    dlg = ExportDialog(ed)
    dlg.start(str(tmp_path / "salida.mp4"))
    assert _wait(qapp, lambda: hasattr(dlg, "result_code"), 120), dlg.status.text()
    assert dlg.result_code == 0, dlg.status.text()
    info = _probe(tmp_path / "salida.mp4")
    assert abs(float(info["format"]["duration"]) - ed.project.duration) < 0.3
    # Cancelar una exportación borra el archivo a medio hacer
    dlg2 = ExportDialog(ed)
    dlg2.start(str(tmp_path / "cancelada.mp4"))
    dlg2.stop()
    assert _wait(qapp, lambda: hasattr(dlg2, "result_code"), 30)
    assert not (tmp_path / "cancelada.mp4").exists()
    from aero.core.tasks import tasks

    assert tasks().held == 0, "la plaza pesada se libera"
    ed.dirty = False
    ed.close()
