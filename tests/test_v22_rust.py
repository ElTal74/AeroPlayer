"""Fase R1 de Rust: el núcleo nativo (aero_core) da exactamente lo mismo que la versión Python, y es más rápido."""

import os
import subprocess
import threading
import time

import pytest

from aero.core import native

nc = native.core()
needs = pytest.mark.skipif(nc is None, reason="núcleo nativo no compilado (tools/build_native.py)")


def _tree(root):
    """Carpeta con casos difíciles: ocultos, de sistema, sin extensión, firmas, Unicode, vacíos y subcarpetas."""
    (root / "sub" / "más hondo").mkdir(parents=True)
    for i in range(300):
        (root / f"archivo {i:03d}.{['mp4', 'flac', 'jpg', 'docx', 'zip', 'iso', 'torrent', 'xyz'][i % 8]}").write_bytes(
            b"x" * (i % 7))
    (root / "foto_sin_ext").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 40)
    (root / "LEEME").write_text("Hola, texto plano.\n", encoding="utf-8")
    (root / "binario").write_bytes(bytes(range(256)))
    (root / "disco").write_bytes(b"\0" * 0x8001 + b"CD001" + b"\0" * 50)
    (root / "riff_wav").write_bytes(b"RIFF\0\0\0\0WAVEfmt " + b"\0" * 40)
    (root / "mp4_ftyp").write_bytes(b"\0\0\0\x18ftypisom" + b"\0" * 40)
    (root / "vacío").write_bytes(b"")
    (root / "Canción ñandú 🎵.mp3").write_bytes(b"ID3")
    (root / ".config_punto").write_text("x")
    (root / "$basura").write_text("x")
    (root / "desktop.ini").write_text("x")
    oculto = root / "oculto.txt"
    oculto.write_text("x")
    if os.name == "nt":
        subprocess.run(["attrib", "+h", str(oculto)], check=True, capture_output=True)
    (root / "sub" / "dentro.pdf").write_bytes(b"%PDF")
    (root / "sub" / "más hondo" / "Árbol de Navidad.png").write_bytes(b"x" * 10)
    return root


def _key(e):
    return (e.name, e.is_dir, e.size, round(e.mtime, 3), e.kind, e.category, e.path)


@needs
def test_scan_dir_matches_python_exactly(tmp_path):
    from aero import files

    root = _tree(tmp_path)
    rust = sorted(_key(e) for e in files.list_dir(str(root)))
    py = sorted(_key(e) for e in files.list_dir_py(str(root)))
    assert rust == py
    names = {k[0] for k in rust}
    assert "oculto.txt" not in names and "$basura" not in names and "desktop.ini" not in names
    cats = {k[0]: k[5] for k in rust}
    assert cats["foto_sin_ext"] == "image" and cats["LEEME"] == "document" and cats["disco"] == "disc"
    assert cats["riff_wav"] == "audio" and cats["mp4_ftyp"] == "video" and cats["binario"] == "unknown"
    assert cats["sub"] == "folder" and cats["Canción ñandú 🎵.mp3"] == "audio"


@needs
def test_scan_dir_errors_like_python(tmp_path):
    with pytest.raises(FileNotFoundError):
        nc.scan_dir(str(tmp_path / "no existe"))


@needs
def test_folder_stats_matches_python(tmp_path):
    from aero import files

    root = _tree(tmp_path)
    a, b = files.folder_stats(str(root)), files.folder_stats_py(str(root))
    assert (a.files, a.dirs, a.size, a.complete) == (b.files, b.dirs, b.size, b.complete)
    assert a.complete and a.dirs == 1 and a.size > 0
    small = files.folder_stats(str(root), max_items=10)
    assert not small.complete


@needs
def test_search_matches_python_order_and_accents(tmp_path):
    from aero.ui.command_palette import fold, search_files, search_files_py

    root = _tree(tmp_path)
    stop = threading.Event()
    for q in ("arbol", "ÁRBOL navidad", "archivo 01", "cancion", "zzz no hay", "sub"):
        assert search_files([str(root)], q, stop) == search_files_py([str(root)], q, stop), q
    assert search_files([str(root)], "archivo", stop, limit=7) == search_files_py([str(root)], "archivo", stop, 7)
    for s in ("Árbol", "ÑANDÚ", "Canción 🎵", "Straße", "École"):
        assert nc.fold_text(s) == fold(s), s


@needs
def test_search_stops_when_asked(tmp_path):
    root = _tree(tmp_path)
    stop = threading.Event()
    stop.set()
    t0 = time.perf_counter()
    nc.search([str(root)] * 50, "archivo", stop, 100_000)
    assert time.perf_counter() - t0 < 1.0


def test_python_fallback_when_native_disabled(tmp_path, monkeypatch):
    from aero import files

    monkeypatch.setenv("AERO_NO_NATIVE", "1")
    native.reset()
    try:
        assert native.core() is None
        root = _tree(tmp_path)
        assert len(files.list_dir(str(root))) == len(files.list_dir_py(str(root)))
    finally:
        monkeypatch.delenv("AERO_NO_NATIVE")
        native.reset()


@needs
def test_native_is_faster_on_big_folder(tmp_path):
    from aero import files

    exts = [".mp4", ".mkv", ".mp3", ".jpg", ".docx", ".pdf", ".zip", ".iso", ".py", ""]
    for i in range(5000):
        (tmp_path / f"f{i:05d}{exts[i % len(exts)]}").write_bytes(b"x" if i % 3 else b"")

    def best(fn):
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            fn(str(tmp_path))
            times.append(time.perf_counter() - t0)
        return min(times)

    rust, py = best(files.list_dir), best(files.list_dir_py)
    print(f"\nlistar 5000 archivos: Rust {rust * 1000:.1f} ms · Python {py * 1000:.1f} ms")
    assert rust < py


@needs
def test_native_errors_are_the_same_classes(tmp_path):
    f = tmp_path / "archivo.txt"
    f.write_text("x")
    for target, exc in ((tmp_path / "no existe", FileNotFoundError), (f, NotADirectoryError)):
        with pytest.raises(exc):
            os.scandir(str(target)).close()
        with pytest.raises(exc):
            nc.scan_dir(str(target))


def test_diagnostico_reports_native_and_icons(tmp_path):
    import json
    import sys

    out = tmp_path / "diag.json"
    r = subprocess.run([sys.executable, "-m", "aero", "--diagnostico", str(out)], capture_output=True, text=True,
                       timeout=60, cwd=str(os.path.dirname(os.path.dirname(__file__))))
    assert r.returncode == 0, r.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["version"] and d["nativo"] == (nc is not None) and len(d["iconos_ico"]) == 18


# ----------------------------------------------------------------------------- etiquetas de audio (lofty)

META = ["-metadata", "title=Canción ñandú", "-metadata", "artist=Artista Á", "-metadata", "album=Álbum",
        "-metadata", "album_artist=Varios", "-metadata", "genre=Pop", "-metadata", "date=2019-05-01",
        "-metadata", "track=3/12"]
SINE = ["-f", "lavfi", "-i", "sine=frequency=440:duration=3.2"]


@pytest.fixture(scope="module")
def tagged(tmp_path_factory):
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg no está disponible")
    d = tmp_path_factory.mktemp("tags")
    cases = {"a.mp3": META + ["-c:a", "libmp3lame", "-b:a", "192k"], "a.flac": META + ["-c:a", "flac"],
             "a.m4a": META + ["-c:a", "aac"], "a.ogg": META + ["-c:a", "libvorbis"],
             "a.opus": META + ["-c:a", "libopus"], "a.wma": META + ["-c:a", "wmav2"],
             "sin_tags.mp3": ["-c:a", "libmp3lame", "-map_metadata", "-1"]}
    for name, args in cases.items():
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *SINE, *args, str(d / name)], check=True)
    (d / "roto.mp3").write_bytes(b"\xff\xfb" + b"basura" * 100)
    return d


@needs
def test_native_tags_match_mutagen(tagged):
    from aero.core.metadata import read_tags_py

    for f in sorted(tagged.iterdir()):
        py, rs = read_tags_py(f), nc.read_tags(str(f))
        if f.name in ("a.wma", "roto.mp3"):
            assert rs is None, f.name            # lofty no lo entiende: se usa mutagen
            continue
        assert rs is not None, f.name
        for k in ("title", "artist", "album", "album_artist", "genre", "year", "track"):
            assert rs.get(k) == py.get(k), (f.name, k, rs.get(k), py.get(k))
        assert abs(rs["duration"] - py["duration"]) < 0.01, f.name
        assert rs["channels"] == py["channels"]
        if "sample_rate" in py:
            assert rs["sample_rate"] == py["sample_rate"]
        assert abs(rs["bitrate"] - py["bitrate"]) <= max(1500, py["bitrate"] * 0.02), f.name
    assert nc.read_tags(str(tagged / "a.flac"))["title"] == "Canción ñandú"
    assert "title" not in nc.read_tags(str(tagged / "sin_tags.mp3"))


@needs
def test_read_tags_many_parallel_with_fallback(tagged):
    from aero.core.metadata import read_tags, read_tags_many, read_tags_py

    files = [str(p) for p in sorted(tagged.iterdir())] * 20
    many = read_tags_many(files)
    assert len(many) == len(files)
    wma = files.index(str(tagged / "a.wma"))
    assert many[wma] == read_tags_py(files[wma])           # el formato que lofty no lee viene de mutagen
    assert read_tags(str(tagged / "roto.mp3")) == read_tags_py(tagged / "roto.mp3")
    assert many[files.index(str(tagged / "a.mp3"))]["artist"] == "Artista Á"
