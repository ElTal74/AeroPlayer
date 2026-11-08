"""Pruebas unitarias del núcleo: base de datos, configuración, subtítulos, formatos y conversión."""

from pathlib import Path

import numpy as np
import pytest

from aero.core import convert_spec as cs
from aero.core.db import Database, fts_query
from aero.core.formats import human_size, human_time, kind_of
from aero.core.subtitles import SubtitleTrack, parse_ass, parse_srt_vtt
from aero.player.analyzer import AudioAnalyzer
from aero.quicklook.winhook import parse_hotkey
from aero.ui.pages.playlists_page import read_m3u, write_m3u


# ----------------------------------------------------------------------------- formatos
@pytest.mark.parametrize("name,kind", [
    ("a.MP3", "audio"), ("b.mkv", "video"), ("c.JPEG", "image"), ("d.pdf", "pdf"), ("e.docx", "document"),
    ("f.xlsx", "sheet"), ("g.pptx", "slides"), ("h.py", "text"), ("i.zip", "archive"), ("j.xyz", "unknown"),
    ("sin_extension", "unknown"),
])
def test_kind_of(name, kind):
    assert kind_of(name) == kind


def test_human_helpers():
    assert human_time(3725) == "1:02:05"
    assert human_time(65) == "1:05"
    assert human_time(None) == "--:--"
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"


# ----------------------------------------------------------------------------- base de datos
def test_fts_query_is_safe():
    assert fts_query('ca"nción OR *drop') == '"ca"* "nción"* "OR"* "drop"*'
    assert fts_query("   ") == ""


def test_db_library_search_and_paging(tmp_path):
    db = Database(tmp_path / "t.db")
    rows = [{"path": f"C:/m/{i}.mp3", "root": "C:/m", "folder": "C:/m", "name": f"pista {i}", "ext": ".mp3",
             "kind": "audio", "size": i, "mtime": 1.0, "title": f"Canción {i}", "artist": "Björk" if i % 2 else "Otro",
             "album": "Ñandú", "duration": 60.0} for i in range(25)]
    db.upsert_media(rows)
    assert db.count_media("audio") == 25
    assert db.count_media("audio", search="bjork") == 12  # sin diacríticos
    page = db.query_media("audio", order="title", limit=10, offset=10)
    assert len(page) == 10
    assert len(db.all_paths("audio", order="artist", desc=True)) == 25
    assert db.albums()[0]["n"] == 25
    # actualización mantiene el índice de búsqueda sincronizado
    db.upsert_media([{**rows[0], "title": "Nuevo título"}])
    assert db.count_media(search="nuevo") == 1
    db.remove_paths(["C:/m/0.mp3"])
    assert db.count_media() == 24
    db.close()


def test_db_history_favorites_playlists_positions(tmp_path):
    db = Database(tmp_path / "t.db")
    db.add_recent("a.pdf", "pdf")
    db.add_played("b.mp3", "B", "Art")
    db.add_played("b.mp3", "B", "Art")
    assert db.recently_played()[0]["count"] == 2
    db.set_favorite("b.mp3", True)
    assert db.is_favorite("b.mp3") and db.favorites() == ["b.mp3"]
    pid = db.create_playlist("Mi lista", ["1.mp3", "2.mp3"])
    db.append_to_playlist(pid, ["3.mp3"])
    assert db.playlist_items(pid) == ["1.mp3", "2.mp3", "3.mp3"]
    db.set_playlist_items(pid, ["3.mp3", "1.mp3"])
    assert db.playlist_items(pid) == ["3.mp3", "1.mp3"]
    db.save_position("v.mkv", 123456)
    assert db.position("v.mkv") == 123456
    db.clear_history()
    assert db.recents() == [] and db.position("v.mkv") == 0
    assert db.favorites() == ["b.mp3"]  # borrar historial no borra favoritos
    db.delete_playlist(pid)
    assert db.playlists() == []
    db.close()


# ----------------------------------------------------------------------------- configuración
def test_settings_roundtrip_and_validation(tmp_path, qapp):
    from aero.core.config import Settings

    path = tmp_path / "s.json"
    path.write_text('{"theme": "cielo", "volume": 1, "max_parallel_jobs": "no", "desconocida": 1}', encoding="utf-8")
    s = Settings(path)
    assert s.get("theme") == "cielo"
    assert s.get("volume") == 1.0           # int aceptado para float
    assert s.get("max_parallel_jobs") == 2  # tipo incorrecto → valor por defecto
    s.set("theme", "aurora")
    s.save_now()
    assert Settings(path).get("theme") == "aurora"


def test_settings_corrupt_file(tmp_path, qapp):
    from aero.core.config import Settings

    path = tmp_path / "s.json"
    path.write_text("{no es json", encoding="utf-8")
    assert Settings(path).get("theme") == "burbuja"


# ----------------------------------------------------------------------------- subtítulos
SRT = "1\n00:00:01,000 --> 00:00:02,500\nHola <b>mundo</b>\n\n2\n00:00:03,000 --> 00:00:04,000\nAdiós\nlínea 2\n"
VTT = "WEBVTT\n\n00:01.000 --> 00:02.000\nUno\n\n00:00:02.500 --> 00:00:03.000 align:start\nDos\n"
ASS = ("[Script Info]\nTitle: x\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
       "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\\i1}Hola, qué tal{\\i0}\\NSegunda\n")


def test_parse_srt():
    cues = parse_srt_vtt(SRT)
    assert [(c.start, c.end) for c in cues] == [(1000, 2500), (3000, 4000)]
    assert cues[0].text == "Hola mundo"
    tr = SubtitleTrack(cues)
    assert tr.text_at(1500) == "Hola mundo"
    assert tr.text_at(2700) == ""
    assert tr.text_at(3500) == "Adiós\nlínea 2"


def test_parse_vtt_and_ass():
    assert [c.text for c in parse_srt_vtt(VTT)] == ["Uno", "Dos"]
    cues = parse_ass(ASS)
    assert cues[0].text == "Hola, qué tal\nSegunda" and cues[0].start == 1000


def test_subtitle_encoding_fallback(tmp_path):
    p = tmp_path / "s.srt"
    p.write_bytes(SRT.encode("cp1252"))
    assert SubtitleTrack.load(p).cues[1].text.startswith("Adiós")
    bad = tmp_path / "b.srt"
    bad.write_text("nada útil", encoding="utf-8")
    with pytest.raises(ValueError):
        SubtitleTrack.load(bad)


# ----------------------------------------------------------------------------- conversión (lógica pura)
def test_unique_and_safe_output(tmp_path):
    src = tmp_path / "vídeo:raro?.mkv"
    src.write_bytes(b"x")
    out = cs.output_path(src, tmp_path, "mp4")
    assert out.name == "vídeo_raro_.mp4"
    out.write_bytes(b"y")
    assert cs.output_path(src, tmp_path, "mp4").name == "vídeo_raro_ (1).mp4"
    same = tmp_path / "a.png"
    same.write_bytes(b"x")
    assert cs.output_path(same, tmp_path, "png") != same  # nunca sobrescribe el original


def test_targets_and_methods():
    assert ("png", "PNG") not in cs.targets_for("x.png", office=False)
    assert any(t[0] == "mp3" for t in cs.targets_for("x.mkv", office=False))
    assert cs.targets_for("x.doc", office=False) == []
    assert cs.method_for("x.docx", "pdf", office=True) == "office"
    assert cs.method_for("x.docx", "pdf", office=False) == "builtin"
    assert cs.method_for("x.flac", "mp3", office=False) == "ffmpeg"


INFO_H264 = {"streams": [{"codec_type": "video", "codec_name": "h264"}, {"codec_type": "audio", "codec_name": "aac"}],
             "format": {"duration": "10"}}
ENCS = frozenset({"libx264", "libx265", "libvpx-vp9", "libsvtav1", "aac", "libmp3lame", "libopus", "flac",
                  "h264_nvenc"})


def test_ffmpeg_args_remux_and_encode():
    o = cs.ConvertOptions(target="mp4", preset="conservar")
    args = cs.build_ffmpeg_args("ffmpeg", "in.mkv", "out.mp4", o, INFO_H264, ENCS)
    assert args[args.index("-c:v") + 1] == "copy" and "-n" in args and args[-1] == "out.mp4"
    o = cs.ConvertOptions(target="mp4", preset="reducido", max_height=720, hw=False)
    args = cs.build_ffmpeg_args("ffmpeg", "in.mkv", "out.mp4", o, INFO_H264, ENCS)
    assert args[args.index("-c:v") + 1] == "libx264"
    assert "scale=-2:'min(720,ih)'" in args
    o = cs.ConvertOptions(target="mp4", hw=True)
    args = cs.build_ffmpeg_args("ffmpeg", "in.mkv", "out.mp4", o, INFO_H264, ENCS, hw_check=lambda n: True)
    assert args[args.index("-c:v") + 1] == "h264_nvenc"
    o = cs.ConvertOptions(target="webm")
    args = cs.build_ffmpeg_args("ffmpeg", "in.mkv", "out.webm", o, INFO_H264, ENCS)
    assert "libvpx-vp9" in args and "libopus" in args


def test_ffmpeg_args_audio_and_errors():
    o = cs.ConvertOptions(target="mp3", preset="alta")
    args = cs.build_ffmpeg_args("ffmpeg", "in.mkv", "out.mp3", o, INFO_H264, ENCS)
    assert "-vn" in args and args[args.index("-q:a") + 1] == "0"
    no_audio = {"streams": [{"codec_type": "video", "codec_name": "h264"}]}
    with pytest.raises(ValueError):
        cs.build_ffmpeg_args("ffmpeg", "in.mkv", "out.mp3", o, no_audio, ENCS)
    assert "espacio" in cs.friendly_ffmpeg_error("av_interleaved_write_frame(): No space left on device")


# ----------------------------------------------------------------------------- otros
def test_analyzer_detects_frequency():
    a = AudioAnalyzer()
    sr = 44100
    t = np.arange(sr // 10) / sr
    tone = (0.8 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    stereo = np.repeat(tone, 2)
    for _ in range(5):
        a.feed(stereo.tobytes(), 2, sr)
        a.update()
    peak_band = int(np.argmax(a.spectrum))
    lo, hi = a._edges[peak_band], a._edges[peak_band + 1]
    freq_lo, freq_hi = lo * sr / 2048, hi * sr / 2048
    assert freq_lo - 50 <= 1000 <= freq_hi + 50
    assert a.level > 0.1


def test_parse_hotkey():
    assert parse_hotkey("Ctrl+Shift+Space") == (0x2 | 0x4, 0x20)
    assert parse_hotkey("Alt+F5") == (0x1, 0x74)
    assert parse_hotkey("Ctrl+Q") == (0x2, ord("Q"))
    assert parse_hotkey("Ctrl+Raro") is None
    assert parse_hotkey("") is None


def test_m3u_roundtrip(tmp_path):
    a = tmp_path / "a b.mp3"
    a.write_bytes(b"")
    pl = tmp_path / "l.m3u8"
    write_m3u(str(pl), [str(a)])
    assert read_m3u(str(pl)) == [str(a)]
    (tmp_path / "rel.m3u").write_text("#EXTM3U\n#EXTINF:1,x\na b.mp3\n", encoding="utf-8")
    assert Path(read_m3u(str(tmp_path / "rel.m3u"))[0]) == a
