"""2.1: Spotify retirado, iconos AERO por categoría, imágenes de disco (leer, extraer, montar) y BitTorrent."""

import io
import os
import socket
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


def wait_for(app, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if app is not None:
            app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


# ----------------------------------------------------------------------------- Spotify retirado

def test_spotify_removed_and_its_token_deleted(qapp, controller):
    import importlib.util

    from aero.core.paths import data_dir
    from aero.ui.controller import AppController

    assert importlib.util.find_spec("aero.spotify") is None
    for name in ("spotify.bin", "spotify.part"):
        (data_dir() / name).write_bytes(b"x")
    (data_dir() / "otra_cosa.json").write_text("{}")
    AppController._remove_old_feature_data()
    assert not (data_dir() / "spotify.bin").exists() and not (data_dir() / "spotify.part").exists()
    assert (data_dir() / "otra_cosa.json").exists()          # solo se borra lo de Spotify
    root = Path(__file__).resolve().parents[1] / "aero"
    assert not any("spotify" in p.read_text(encoding="utf-8").lower() for p in root.rglob("*.py")
                   if p.name != "controller.py")


# ----------------------------------------------------------------------------- categorías e iconos

def test_every_media_format_shares_its_category():
    from aero.core import filetypes as ft
    from aero.core import formats

    for exts, cat in ((formats.VIDEO, "video"), (formats.AUDIO, "audio"), (formats.IMAGE, "image")):
        assert {ft.by_extension("x" + e) for e in exts} == {cat}
    cases = {"a.zip": "archive", "a.7z": "archive", "a.tar.gz": "archive", "a.docx": "document", "a.txt": "document",
             "a.xlsx": "sheet", "a.pptx": "slides", "a.pdf": "pdf", "a.exe": "app", "a.msi": "installer",
             "a.lnk": "shortcut", "a.url": "shortcut", "a.ttf": "font", "a.py": "code", "a.ini": "system",
             "a.dll": "system", "a.torrent": "torrent", "a.iso": "disc", "a.bin": "disc", "a.cue": "disc",
             "a.nrg": "disc", "a.ts": "video", "a.m3u": "audio", "a.qwerty": "unknown", "sin_extension": "unknown",
             "A.MP4": "video", "carpeta.mp4/": "unknown"}
    for name, cat in cases.items():
        assert ft.by_extension(name) == cat, name
    assert ft.by_extension("Lo que sea", is_dir=True) == "folder"


def test_signature_only_when_extension_does_not_decide(tmp_path):
    from aero.core import filetypes as ft

    (tmp_path / "foto").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 40)
    (tmp_path / "LEEME").write_text("Hola, esto es texto plano.\n", encoding="utf-8")
    (tmp_path / "raro").write_bytes(bytes(range(256)))
    iso = tmp_path / "disco"
    iso.write_bytes(b"\0" * 0x8001 + b"CD001" + b"\0" * 100)
    (tmp_path / "falso.mp4").write_bytes(b"%PDF-1.4")
    assert ft.category_of(str(tmp_path / "foto"), look=True) == "image"
    assert ft.category_of(str(tmp_path / "LEEME"), look=True) == "document"
    assert ft.category_of(str(tmp_path / "raro"), look=True) == "unknown"
    assert ft.category_of(str(iso), look=True) == "disc"
    assert ft.category_of(str(tmp_path / "falso.mp4"), look=True) == "video"     # manda la extensión
    assert ft.category_of(str(tmp_path / "foto")) == "unknown"                    # sin `look` no se lee


def test_icons_one_per_category_cached_with_light_and_dark(qapp):
    from PySide6.QtGui import QImage

    from aero.core.filetypes import CATEGORIES
    from aero.ui import file_icons

    file_icons.clear_cache()
    imgs = {}
    for cat in CATEGORIES:
        pm = file_icons.pixmap(cat, 48)
        assert not pm.isNull() and pm.width() == 48
        img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        assert img.pixelColor(24, 24).alpha() > 0 or cat in ("disc",)     # el disco tiene el agujero en medio
        imgs[cat] = bytes(img.constBits())
    assert len(set(imgs.values())) == len(CATEGORIES)          # cada categoría se distingue
    assert file_icons.pixmap("video", 48) is file_icons.pixmap("video", 48)   # caché
    light = file_icons.pixmap("video", 48, dark=False).toImage()
    assert bytes(light.convertToFormat(QImage.Format.Format_ARGB32).constBits()) != imgs["video"]
    big = file_icons.pixmap("archive", 256, dpr=2.0)
    assert big.width() == 512 and abs(big.devicePixelRatio() - 2.0) < 1e-6   # vectorial: cualquier tamaño
    a = file_icons.icon_for("pelicula.mkv", 32).pixmap(32).toImage()
    b = file_icons.icon_for("otra.webm", 32).pixmap(32).toImage()
    assert a == b                                              # mismo icono para todos los vídeos


def test_folder_with_thousands_of_files_lists_and_paints_fast(qapp, tmp_path):
    from aero import files
    from aero.files.browser import FolderBrowser

    exts = [".mp4", ".mkv", ".mp3", ".flac", ".jpg", ".png", ".docx", ".pdf", ".zip", ".iso", ".torrent", ".exe",
            ".py", ".ttf", ".ini", ".xyz", ""]
    for i in range(3000):
        (tmp_path / f"archivo {i:04d}{exts[i % len(exts)]}").write_bytes(b"" if i % 3 else b"x")
    t0 = time.perf_counter()
    entries = files.list_dir(str(tmp_path))
    listed = time.perf_counter() - t0
    assert len(entries) == 3000 and listed < 2.0, listed
    assert {e.category for e in entries} >= {"video", "audio", "image", "document", "pdf", "archive", "disc",
                                              "torrent", "app", "code", "font", "system", "unknown"}
    b = FolderBrowser()
    b.resize(1000, 700)
    b.show()
    b.set_root(str(tmp_path))
    assert wait_for(qapp, lambda: len(b.model.rows) == 3000, 15)
    for grid in (True, False):           # cuadrícula y lista con columnas (tipo, tamaño, fecha)
        b.set_grid(grid)
        qapp.processEvents()
        t0 = time.perf_counter()
        b.grab()
        assert time.perf_counter() - t0 < 1.5
    b.view.verticalScrollBar().setValue(b.view.verticalScrollBar().maximum())
    t0 = time.perf_counter()
    b.grab()
    assert time.perf_counter() - t0 < 1.5
    b.close()


# ----------------------------------------------------------------------------- imágenes de disco

@pytest.fixture()
def discs(tmp_path):
    pycdlib = pytest.importorskip("pycdlib")
    iso_path = tmp_path / "prueba.iso"
    iso = pycdlib.PyCdlib()
    iso.new(joliet=3, vol_ident="AERO_TEST")
    big = os.urandom(3 * 1024 * 1024)
    for name, data in (("LEEME.TXT", b"hola"), ("GRANDE.BIN", big)):
        iso.add_fp(io.BytesIO(data), len(data), f"/{name};1", joliet_path=f"/{name.title()}")
    iso.add_directory("/CARPETA", joliet_path="/Carpeta con nombre largo ñ")
    iso.add_fp(io.BytesIO(b"dentro"), 6, "/CARPETA/A.TXT;1", joliet_path="/Carpeta con nombre largo ñ/Archivo.txt")
    iso.write(str(iso_path))
    iso.close()
    raw = iso_path.read_bytes()
    bin_path = tmp_path / "juego.bin"
    with open(bin_path, "wb") as f:
        for i in range(0, len(raw), 2048):
            f.write(b"\x00" + b"\xff" * 10 + b"\x00" + b"\x00\x02\x00\x01" + raw[i:i + 2048] + b"\x00" * 288)
    cue = tmp_path / "juego.cue"
    cue.write_text('FILE "juego.bin" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n')
    nrg = tmp_path / "nero.nrg"
    nrg.write_bytes(b"\x00" * 307200 + raw)
    return {"iso": iso_path, "cue": cue, "bin": bin_path, "nrg": nrg, "big": big}


def test_disc_images_list_with_long_names(discs):
    from aero import archive

    want = {"Leeme.Txt", "Grande.Bin", "Carpeta con nombre largo ñ"}
    for key in ("iso", "cue", "bin", "nrg"):
        info = archive.read_archive(str(discs[key]))
        top = {e.name.split("/")[0] for e in info.entries}
        assert want <= top, (key, top)
        assert any("AERO_TEST" in w for w in info.warnings)


def test_disc_extract_selected_full_and_cancel(discs, tmp_path):
    from aero.archive import ops

    out = tmp_path / "salida"
    ops.extract(str(discs["cue"]), str(out), members=["Carpeta con nombre largo ñ"])
    assert sorted(os.listdir(out)) == ["Carpeta con nombre largo ñ"]
    assert (out / "Carpeta con nombre largo ñ" / "Archivo.txt").read_bytes() == b"dentro"
    progress = []
    ops.extract(str(discs["iso"]), str(out), mode="rename", progress=lambda *a: progress.append(a))
    big = [n for n in os.listdir(out) if n.lower() == "grande.bin"]
    assert big and (out / big[0]).read_bytes() == discs["big"] and progress
    calls = [0]

    def cancel():
        calls[0] += 1
        return calls[0] > 3

    out2 = tmp_path / "cancelada"
    with pytest.raises(ops.Cancelled):
        ops.extract(str(discs["nrg"]), str(out2), cancelled=cancel)
    assert not out2.exists() or not any(p.is_file() for p in out2.rglob("*"))     # sin restos a medias


def test_audio_cd_or_garbage_is_reported_not_invented(tmp_path):
    from aero import archive

    (tmp_path / "audio.bin").write_bytes(b"\0" * 2352 * 40)
    (tmp_path / "audio.cue").write_text('FILE "audio.bin" BINARY\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n')
    (tmp_path / "basura.iso").write_bytes(os.urandom(100_000))
    for name in ("audio.cue", "basura.iso"):
        with pytest.raises(archive.ArchiveError):
            archive.read_archive(str(tmp_path / name))


IMAPI = r'''
$d = $args[0]
$fs = New-Object -ComObject IMAPI2FS.MsftFileSystemImage; $fs.FileSystemsToCreate = 3; $fs.VolumeName = "AEROTEST"
$fs.Root.AddTree("$d\src", $false); $res = $fs.CreateResultImage(); $stream = $res.ImageStream
$code = @"
using System; using System.IO; using System.Runtime.InteropServices; using System.Runtime.InteropServices.ComTypes;
public static class IsoW { public static void Save(object s, string path) { var st = (IStream)s;
 using (var f = File.Create(path)) { byte[] b = new byte[65536]; IntPtr p = Marshal.AllocHGlobal(4);
 try { while (true) { st.Read(b, b.Length, p); int n = Marshal.ReadInt32(p); if (n <= 0) break; f.Write(b, 0, n); } }
 finally { Marshal.FreeHGlobal(p); } } } }
"@
Add-Type -TypeDefinition $code; [IsoW]::Save($stream, "$d\windows.iso")
'''


@pytest.mark.skipif(os.name != "nt", reason="montaje nativo de Windows")
def test_mount_and_unmount_iso_with_windows(tmp_path):
    import shutil
    import uuid

    from aero import archive
    from aero.archive import disc

    # Las carpetas temporales de pytest solo dan permiso al usuario (Python 3.13+) y el servicio de discos virtuales
    # de Windows no puede leer una imagen ahí: se usa una carpeta normal, como las del usuario.
    plain = Path(os.environ.get("TEMP", str(tmp_path))) / f"aero_mount_{uuid.uuid4().hex[:8]}"
    os.makedirs(plain)
    try:
        _mount_case(plain, archive, disc)
    finally:
        shutil.rmtree(plain, ignore_errors=True)


def _mount_case(tmp_path, archive, disc):

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "hola.txt").write_text("hola")
    script = tmp_path / "crear.ps1"
    script.write_text(IMAPI, encoding="utf-8-sig")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                        str(tmp_path)], capture_output=True, text=True, timeout=120)
    iso = tmp_path / "windows.iso"
    if not iso.exists():
        pytest.skip(f"IMAPI2 no disponible: {r.stderr[:200]}")
    assert [e.name for e in archive.read_archive(str(iso)).entries] == ["hola.txt"]   # sin montar
    assert disc.can_mount(str(iso)) and not disc.can_mount(str(tmp_path / "x.nrg"))
    drive = disc.mount(str(iso))
    try:
        assert os.listdir(drive + "\\") == ["hola.txt"]
        assert disc.mounted_drive(str(iso)) == drive
    finally:
        disc.unmount(str(iso))
    assert disc.mounted_drive(str(iso)) == ""
    return iso


def test_mount_failure_leaves_no_phantom_drive(tmp_path):
    """En una carpeta que el servicio de discos de Windows no puede leer, se informa y no queda nada conectado."""
    from aero.archive import disc

    if os.name != "nt":
        pytest.skip("Windows")
    bad = tmp_path / "rota.iso"
    bad.write_bytes(os.urandom(4096 * 4))
    with pytest.raises(disc.DiscError):
        disc.mount(str(bad))
    r = disc._ps(f"(Get-DiskImage -ImagePath {disc._q(str(bad))} -ErrorAction SilentlyContinue).Attached")
    assert r.stdout.strip() in ("", "False")


# ----------------------------------------------------------------------------- BitTorrent: metadatos

def test_torrent_metadata_and_safe_paths():
    from aero.torrent import metainfo

    data = metainfo.make([("a/uno.bin", b"1" * 50_000), ("dos.txt", b"2" * 10)], "Pack", 16384,
                         "http://tracker.invalid/announce")
    t = metainfo.parse(data)
    assert t.name == "Pack" and [f.path for f in t.files] == ["a/uno.bin", "dos.txt"] and t.total == 50_010
    assert len(t.pieces) == 4 and t.trackers == ["http://tracker.invalid/announce"] and len(t.info_hash) == 20
    assert metainfo.parse(data).info_hash == t.info_hash
    assert list(t.pieces_of(t.files[1])) == [3]
    evil = metainfo.encode({"info": {"name": "../../Windows", "piece length": 16384, "pieces": b"\0" * 20,
                                     "files": [{"length": 5, "path": ["..", "..", "CON", "a:b.txt"]},
                                               {"length": 5, "path": ["C:", "x.exe"]}]}})
    t = metainfo.parse(evil)
    for f in t.files:
        assert ".." not in f.path.split("/") and ":" not in f.path
    assert t.files[0].path == "_CON/a_b.txt" and "/" not in t.name and "\\" not in t.name
    for bad in (b"", b"no es bencode", b"d4:infoi1ee", metainfo.encode({"info": {"name": "x", "piece length": 16384,
                                                                                "pieces": b"\0" * 7, "length": 3}})):
        with pytest.raises(metainfo.TorrentError):
            metainfo.parse(bad)


# ----------------------------------------------------------------------------- BitTorrent: descarga real local

class _Tracker:
    """Tracker HTTP mínimo en 127.0.0.1 que anuncia las semillas indicadas."""

    def __init__(self):
        from aero.torrent import metainfo

        self.peers: list[tuple[str, int]] = []
        self.hits = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits += 1
                body = metainfo.encode({"interval": 60, "peers": b"".join(
                    socket.inet_aton(h) + struct.pack(">H", p) for h, p in outer.peers)})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/announce"

    def close(self):
        self.srv.shutdown()


class _UdpTracker:
    def __init__(self, peers):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("127.0.0.1", 0))
        self.url = f"udp://127.0.0.1:{self.s.getsockname()[1]}/announce"
        self.peers = peers
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                data, addr = self.s.recvfrom(2048)
            except OSError:
                return
            action, tx = struct.unpack(">II", data[8:16])
            if action == 0:
                self.s.sendto(struct.pack(">IIQ", 0, tx, 1234), addr)
            elif action == 1:
                body = b"".join(socket.inet_aton(h) + struct.pack(">H", p) for h, p in self.peers)
                self.s.sendto(struct.pack(">IIIII", 1, tx, 60, 0, 1) + body, addr)

    def close(self):
        self.s.close()


@pytest.fixture()
def swarm(tmp_path):
    from aero.torrent import engine as eng
    from aero.torrent import metainfo

    files = [("a/uno.bin", os.urandom(300_000)), ("dos.txt", b"hola mundo " * 5000), ("tres.bin", os.urandom(90_000))]
    src = tmp_path / "semilla"
    for n, d in files:
        p = src / "Pack" / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(d)
    tracker = _Tracker()
    t = metainfo.parse(metainfo.make(files, "Pack", 32768, tracker.url))
    seed = eng.Seeder(t, str(src))
    tracker.peers.append(("127.0.0.1", seed.port))
    e = eng.Engine()
    yield {"t": t, "files": files, "engine": e, "seed": seed, "tracker": tracker, "dest": tmp_path / "descargas"}
    e.stop()
    seed.stop()
    tracker.close()


def _wait(d, states=("done", "error"), timeout=30):
    end = time.time() + timeout
    while time.time() < end and d.state not in states:
        time.sleep(0.05)
    return d.state


def test_torrent_downloads_only_selected_files_verified(swarm):
    d = swarm["engine"].add(swarm["t"], str(swarm["dest"]), {0, 2})
    assert _wait(d) == "done", d.message
    out = swarm["dest"] / "Pack"
    assert (out / "a" / "uno.bin").read_bytes() == swarm["files"][0][1]
    assert (out / "tres.bin").read_bytes() == swarm["files"][2][1]
    assert not (out / "dos.txt").exists() and not list(out.rglob("*.aeropart"))
    s = d.snapshot()
    assert s.progress == 1.0 and s.done == s.total == 390_000 and s.files_done == 2
    assert swarm["tracker"].hits >= 1


def test_torrent_pause_resume_and_cancel(swarm):
    from aero.torrent import engine as eng

    e, t = swarm["engine"], swarm["t"]
    # Pausar a medias: el motor deja de pedir bloques y al reanudar comprueba lo que ya hay.
    slow = eng.BLOCK
    d = e.add(t, str(swarm["dest"]))
    end = time.time() + 20
    while time.time() < end and not d.have:
        time.sleep(0.005)
    d.pause()
    assert _wait(d, ("paused", "done")) in ("paused", "done")
    had = len(d.have)
    d.start()
    assert _wait(d) == "done" and len(d.have) >= had and slow == eng.BLOCK
    # Reabrir la misma carpeta (como tras cerrar AERO): todo se verifica desde el disco, sin descargar.
    again = e.add(t, str(swarm["dest"]))
    assert _wait(again) == "done" and not (swarm["dest"] / "Pack" / "tres (2).bin").exists()
    # Cancelar: se borran solo los .aeropart que creó; lo de otras descargas se queda.
    keep = swarm["dest"] / "Pack" / "a" / "uno.bin"
    other = swarm["dest"].parent / "otra"
    c = e.add(t, str(other))
    c.cancel()
    assert _wait(c, ("cancelled",)) == "cancelled"
    time.sleep(0.3)
    assert not list(other.rglob("*.aeropart")) and keep.exists()


def test_torrent_udp_tracker_and_errors(swarm, tmp_path):
    from aero.torrent import engine as eng
    from aero.torrent import metainfo

    udp = _UdpTracker([("127.0.0.1", swarm["seed"].port)])
    try:
        peers, interval = eng.announce(udp.url, swarm["t"].info_hash, 1, 0, 0, "started")
        assert peers == [("127.0.0.1", swarm["seed"].port)] and interval == 60
        t2 = metainfo.parse(metainfo.make(swarm["files"], "Pack", 32768, udp.url))
        d = swarm["engine"].add(t2, str(tmp_path / "udp"))
        assert _wait(d) == "done"
    finally:
        udp.close()
    with pytest.raises(eng.EngineError):
        eng.announce("wss://x/announce", b"\0" * 20, 0, 0, 0)
    # Tracker que no responde: la descarga informa, no se bloquea ni se cae.
    dead = metainfo.parse(metainfo.make([("x.bin", b"x" * 1000)], "x.bin", 16384, "http://127.0.0.1:9/announce"))
    d = swarm["engine"].add(dead, str(tmp_path / "muerta"))
    assert wait_for(None, lambda: "tracker" in d.message, 20) and d.state == "connecting"
    d.cancel()
    # Sin trackers: se dice que sin DHT no hay pares.
    lonely = metainfo.parse(metainfo.make([("y.bin", b"y" * 1000)], "y.bin", 16384))
    d = swarm["engine"].add(lonely, str(tmp_path / "sola"))
    assert wait_for(None, lambda: "DHT" in d.message, 5)
    d.cancel()


def test_torrent_corrupt_peer_data_is_never_written(swarm, tmp_path):
    from aero.torrent import engine as eng

    bad = tmp_path / "mala"
    for n, data in swarm["files"]:
        p = bad / "Pack" / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(bytes(len(data)))            # mismo tamaño, contenido incorrecto
    seed = eng.Seeder(swarm["t"], str(bad))
    try:
        d = swarm["engine"].add(swarm["t"], str(tmp_path / "dest"))
        d.extra_peers.append(("127.0.0.1", seed.port))
        swarm["tracker"].peers[:] = [("127.0.0.1", seed.port)]
        time.sleep(3)
        assert not d.have or all(swarm["t"].pieces[p] for p in d.have)
        # Ninguna pieza mala llegó al disco: lo que haya se comprueba con SHA-1 y no coincide con la semilla mala.
        out = tmp_path / "dest" / "Pack"
        assert not (out / "tres.bin").exists() and not (out / "a" / "uno.bin").exists()
        d.cancel()
    finally:
        seed.stop()


# ----------------------------------------------------------------------------- BitTorrent: interfaz

def test_torrent_dialog_shows_content_and_requires_confirmation(qapp, tmp_path):
    from aero.torrent import metainfo, ui

    data = metainfo.make([("Carpeta/video.mkv", b"v" * 40_000), ("Carpeta/setup.exe", b"e" * 100),
                          ("leeme.txt", b"t" * 10)], "Pack", 16384)
    t = metainfo.parse(data)
    dlg = ui.TorrentDialog(t)
    dlg.dest.setText(str(tmp_path))
    dlg.show()
    qapp.processEvents()
    assert dlg.selected() == {0, 1, 2} and dlg.ok.isEnabled()
    assert "DHT" in dlg.warn.text() and "No se ejecutarán" in dlg.warn.text()     # sin trackers y con un .exe
    dlg._set_all(False)
    assert dlg.selected() == set() and not dlg.ok.isEnabled()
    dlg._leaves[0][0].setCheckState(0, dlg._leaves[0][0].checkState(0).Checked)
    wait_for(qapp, lambda: dlg.ok.isEnabled(), 2)
    assert dlg.selected() == {0} and "1 de 3" in dlg.count.text()
    dlg.dest.setText("relativa")
    qapp.processEvents()
    wait_for(qapp, lambda: not dlg.ok.isEnabled(), 2)
    assert not dlg.ok.isEnabled()
    dlg.close()


def test_torrent_disabled_never_starts_the_engine(qapp, controller, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from aero import torrent
    from aero.torrent import metainfo, ui

    torrent.shutdown()
    controller.settings.set("torrent_enabled", False)
    path = tmp_path / "x.torrent"
    path.write_bytes(metainfo.make([("x.bin", b"x" * 100)], "x.bin", 16384, "http://127.0.0.1:9/a"))
    seen = {}

    def fake_exec(self):
        seen["ok"] = self.ok.isEnabled()
        seen["problem"] = self.problem.text()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ui.TorrentDialog, "exec", fake_exec)
    controller.open_files([str(path)])
    assert seen["ok"] is False and "desactivado" in seen["problem"] and not torrent.running()
    controller.settings.set("torrent_enabled", True)
    accept = {}
    monkeypatch.setattr(ui.TorrentDialog, "exec", lambda self: (accept.setdefault("shown", True),
                                                                QDialog.DialogCode.Rejected)[1])
    controller.open_files([str(path)])
    assert accept and not torrent.running()          # mostrar no descarga: hace falta pulsar «Descargar»
    (tmp_path / "roto.torrent").write_bytes(b"basura")
    warned = []
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *a, **k: warned.append(a))
    ui.open_torrent(str(tmp_path / "roto.torrent"))
    assert warned


def test_explorer_opens_torrent_in_aero_not_windows(qapp, tmp_path, monkeypatch):
    from aero.files.browser import FolderBrowser
    from aero.torrent import ui

    path = tmp_path / "a.torrent"
    path.write_bytes(b"d4:infod4:name1:xee")
    called = []
    monkeypatch.setattr(ui, "open_torrent", lambda p, parent=None: called.append(p))
    b = FolderBrowser()
    b.open_entry(str(path))
    assert called == [str(path)]
    b.close()


def test_downloads_window_and_activity_center(qapp, swarm, monkeypatch):
    from aero import torrent
    from aero.core.activity import activities
    from aero.torrent import ui

    monkeypatch.setattr(torrent, "get_engine", lambda: swarm["engine"])
    m = ui.TorrentManager()
    d = m.add(swarm["t"], str(swarm["dest"]), {0, 1, 2})
    assert m.add(swarm["t"], str(swarm["dest"]), {0}) is d          # la misma descarga no se duplica
    w = ui.DownloadsWindow(m)
    w.show()
    assert wait_for(qapp, lambda: d.state == "done", 30)
    m._tick()
    w.refresh()
    row = w._rows[id(d)]
    assert "Completado" in row.text(1) and w.tree.itemWidget(row, 2).value() == 1000
    assert any(a.kind == "torrent" and a.state == "done" for a in activities().history)
    w.tree.setCurrentItem(row)
    assert w.b_remove.isEnabled() and not w.b_pause.isEnabled()
    m.remove(d)
    assert not m.items and not w._rows
    w.close()


def test_app_survives_torrent_shutdown(qapp):
    from aero import torrent

    torrent.shutdown()
    e = torrent.get_engine()
    assert torrent.running() and e.thread.is_alive()
    torrent.shutdown()
    assert not torrent.running() and not e.thread.is_alive()
    assert Path(__file__).exists()
