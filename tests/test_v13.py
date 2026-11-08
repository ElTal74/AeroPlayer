"""Pruebas de la 1.3: Quick Look (ratón sobre el vídeo, esquinas), biblioteca de archivos y comprimidos."""

import time


def wait_until(qapp, cond, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def _alpha_at_center(widget):
    img = widget.grab().toImage()
    c = img.rect().center()
    return img.pixelColor(c.x(), c.y()).alpha()


# ----------------------------------------------------------------------------- §4 controles del vídeo
def test_quicklook_video_area_receives_mouse(qapp, media, controller):
    """Causa raíz del fallo: bajo el vídeo quedaba alfa 0 y Windows enviaba el ratón a la ventana de detrás.
    La verificación con el puntero real está en tools/ql_controls_check.py."""
    controller.show_quicklook(str(media / "clip.mkv"))
    ql = controller.quicklook
    assert wait_until(qapp, lambda: ql.aspect > 0, 20)
    assert _alpha_at_center(ql) == 255, "el área del vídeo debe ser opaca para recibir el ratón"
    ql.close_preview()


def test_main_player_video_area_receives_mouse(qapp, controller):
    win = controller.show_main()
    video = win.page("player").video
    assert video.autoFillBackground()
    assert video.palette().color(video.backgroundRole()).alpha() == 255


def test_quicklook_shade_corners_are_rounded(qapp, media, controller):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter

    controller.show_quicklook(str(media / "img.png"))
    ql = controller.quicklook
    qapp.processEvents()
    shade = ql.shade
    img = QImage(shade.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    shade.render(p, QPoint(0, 0))
    p.end()
    assert img.pixelColor(0, 0).alpha() == 0, "la esquina superior izquierda no debe pintarse"
    assert img.pixelColor(img.width() - 1, 0).alpha() == 0
    assert img.pixelColor(img.width() // 2, 0).alpha() > 0
    ql.close_preview()


# ----------------------------------------------------------------------------- §2 comprimidos
def _zip(path, files):
    import zipfile

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return str(path)


def test_archive_lists_tree_without_extracting(tmp_path, media):
    from aero import archive

    data = (media / "img.png").read_bytes()
    p = _zip(tmp_path / "a.zip", {"fotos/img.png": data, "fotos/viaje/b.txt": "hola", "léeme.txt": "x"})
    before = set(tmp_path.rglob("*"))
    info = archive.read_archive(p)
    assert set(tmp_path.rglob("*")) == before, "listar no debe escribir nada"
    assert {e.name for e in info.children("")} == {"fotos", "léeme.txt"}
    assert {e.name for e in info.children("fotos")} == {"fotos/img.png", "fotos/viaje"}
    assert info.total_size == len(data) + 5


def test_archive_extracts_one_entry_to_private_temp(tmp_path, media):
    from aero import archive

    data = (media / "img.png").read_bytes()
    info = archive.read_archive(_zip(tmp_path / "a.zip", {"x/img.png": data, "otro.bin": b"0" * 1000}))
    ws = archive.Workspace(tmp_path / "ws")
    e = next(e for e in info.entries if e.base == "img.png")
    out = archive.extract_entry(info, e, ws)
    assert out.read_bytes() == data and ws.dir in out.parents
    assert [p.name for p in ws.dir.rglob("*") if p.is_file()] == ["img.png"], "solo se extrae lo pedido"
    ws.cleanup()
    assert not ws.dir.exists()


def test_archive_blocks_zip_slip(tmp_path):
    from aero import archive

    info = archive.read_archive(_zip(tmp_path / "evil.zip", {"../../fuera.txt": "x", "C:/Windows/y.txt": "y"}))
    assert all(e.unsafe for e in info.entries) and info.warnings
    ws = archive.Workspace(tmp_path / "ws")
    for e in info.entries:
        try:
            archive.extract_entry(info, e, ws)
            raise AssertionError("no debió extraerse")
        except archive.UnsafeEntry:
            pass
    assert not (tmp_path / "fuera.txt").exists() and not list(ws.dir.rglob("*.txt"))


def test_archive_blocks_compression_bomb(tmp_path):
    from aero import archive

    info = archive.read_archive(_zip(tmp_path / "bomba.zip", {"cero.bin": b"\0" * (64 * 1024 * 1024)}))
    e = info.entries[0]
    assert e.size / e.packed > archive.MAX_RATIO
    try:
        archive.extract_entry(info, e, archive.Workspace(tmp_path / "ws"))
        raise AssertionError("no debió extraerse")
    except archive.ArchiveError as err:
        assert "bomba" in str(err)


def test_archive_detects_encrypted_and_damaged(tmp_path):
    import struct

    from aero import archive

    p = tmp_path / "cifrado.zip"
    _zip(p, {"secreto.txt": "x"})
    raw = bytearray(p.read_bytes())
    # Marcar el bit de cifrado en la cabecera local y en el directorio central
    for sig in (b"PK\x03\x04", b"PK\x01\x02"):
        i = raw.find(sig)
        off = i + (6 if sig == b"PK\x03\x04" else 8)
        flags = struct.unpack_from("<H", raw, off)[0] | 1
        struct.pack_into("<H", raw, off, flags)
    p.write_bytes(bytes(raw))
    info = archive.read_archive(str(p))
    assert info.encrypted and info.entries[0].encrypted
    try:
        archive.extract_entry(info, info.entries[0], archive.Workspace(tmp_path / "ws"))
        raise AssertionError
    except archive.PasswordRequired:
        pass
    bad = tmp_path / "roto.zip"
    bad.write_bytes(b"PK\x03\x04" + b"\x00" * 50)
    try:
        archive.read_archive(str(bad))
        raise AssertionError
    except archive.ArchiveError as err:
        assert "dañado" in str(err) or "compatible" in str(err)


def test_archive_tar_and_7z(tmp_path):
    import os
    import shutil
    import subprocess
    import tarfile

    import pytest

    from aero import archive

    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "c.txt").write_text("contenido")
    with tarfile.open(tmp_path / "t.tar.gz", "w:gz") as t:
        t.add(src / "sub", arcname="sub")
    info = archive.read_archive(str(tmp_path / "t.tar.gz"))
    e = next(e for e in info.entries if e.base == "c.txt")
    ws = archive.Workspace(tmp_path / "ws")
    assert archive.extract_entry(info, e, ws).read_text() == "contenido"
    exe = archive._bsdtar()
    if exe is None or os.name != "nt":
        pytest.skip("sin bsdtar")
    subprocess.run([exe, "--format", "7zip", "-cf", str(tmp_path / "t.7z"), "sub"], cwd=src, check=True)
    info = archive.read_archive(str(tmp_path / "t.7z"))
    assert info.fmt == "7Z"
    e = next(e for e in info.entries if e.base == "c.txt")
    assert archive.extract_entry(info, e, ws).read_text() == "contenido"
    rar = shutil.which("rar") or r"C:\Program Files\WinRAR\Rar.exe"
    if os.path.exists(rar):
        subprocess.run([rar, "a", "-idq", str(tmp_path / "t.rar"), "sub"], cwd=src, check=True)
        info = archive.read_archive(str(tmp_path / "t.rar"))
        e = next(e for e in info.entries if e.base == "c.txt")
        assert archive.extract_entry(info, e, ws).read_text() == "contenido"
        subprocess.run([rar, "a", "-idq", "-hpclave", str(tmp_path / "c.rar"), "sub"], cwd=src, check=True)
        assert archive.read_archive(str(tmp_path / "c.rar")).encrypted


# ----------------------------------------------------------------------------- §2 Quick Look de carpetas
def _tree(tmp_path, media):
    import shutil

    root = tmp_path / "Proyecto"
    (root / "Fotos" / "Viaje").mkdir(parents=True)
    shutil.copy(media / "img.png", root / "Fotos" / "playa.png")
    (root / "notas.txt").write_text("hola")
    (root / "Fotos" / "Viaje" / "x.txt").write_text("x")
    _zip(root / "paquete.zip", {"dentro/img.png": (media / "img.png").read_bytes(), "leeme.txt": "zip"})
    return root


def test_quicklook_folder_navigation(qapp, media, controller, tmp_path):
    root = _tree(tmp_path, media)
    controller.show_quicklook(str(root))
    ql = controller.quicklook
    b = ql._views["browse"]
    assert ql.kind == "folder" and ql.stack.currentWidget() is b
    assert wait_until(qapp, lambda: b.model.rowCount() == 3)
    names = [e.name for e in b.model.rows]
    assert names[0] == "Fotos", "las carpetas van primero"
    assert "1 carpeta ·" in b.meta.text() and "2 archivos" in b.meta.text()
    assert wait_until(qapp, lambda: "en total" in b.meta.text()), "el tamaño total se calcula en segundo plano"
    b._activate(b.model.index(0))                     # entrar en Fotos
    assert wait_until(qapp, lambda: {e.name for e in b.model.rows} == {"Viaje", "playa.png"})
    assert b.btn_up.isEnabled()
    b.go_up()
    assert wait_until(qapp, lambda: b.model.rowCount() == 3)
    assert not b.btn_up.isEnabled(), "no se sube por encima de la carpeta abierta"
    ql.close_preview()


def test_quicklook_opens_image_inside_zip_and_goes_back(qapp, media, controller, tmp_path):
    root = _tree(tmp_path, media)
    controller.show_quicklook(str(root / "paquete.zip"))
    ql = controller.quicklook
    b = ql._views["browse"]
    assert ql.kind == "archive"
    assert wait_until(qapp, lambda: b.model.rowCount() == 2)
    b._activate(b.model.index(0))                     # carpeta «dentro»
    assert wait_until(qapp, lambda: [e.name for e in b.model.rows] == ["img.png"])
    b._activate(b.model.index(0))                     # abrir la imagen: se extrae solo ella
    assert wait_until(qapp, lambda: ql.kind == "image")
    extracted = ql.path
    assert b.workspace is not None and str(b.workspace.dir) in extracted
    assert ql.btn_back.isVisibleTo(ql)
    ql.go_back()
    assert wait_until(qapp, lambda: ql.kind == "archive" and [e.name for e in b.model.rows] == ["img.png"])
    ql.close_preview()
    import os

    assert not os.path.exists(extracted), "lo extraído para previsualizar se borra al cerrar"
    assert list(root.parent.rglob("img.png")) == [], "nada se extrae junto al archivo original"


def test_folder_browser_filters_sorts_and_searches(qapp, tmp_path):
    from aero.files.browser import FolderBrowser

    for n, size in (("b.mp3", 3), ("a.jpg", 1), ("c.pdf", 2)):
        (tmp_path / n).write_bytes(b"x" * size)
    (tmp_path / "zeta").mkdir()
    b = FolderBrowser()
    b.set_root(str(tmp_path))
    assert wait_until(qapp, lambda: b.model.rowCount() == 4)
    assert [e.name for e in b.model.rows] == ["zeta", "a.jpg", "b.mp3", "c.pdf"]
    b.sort.setCurrentIndex(b.sort.findData("size"))
    b.btn_order.setChecked(True)
    assert [e.name for e in b.model.rows] == ["zeta", "b.mp3", "c.pdf", "a.jpg"]
    b.filter.setCurrentIndex(b.filter.findData("image"))
    assert [e.name for e in b.model.rows] == ["zeta", "a.jpg"], "las carpetas siguen visibles para navegar"
    b.filter.setCurrentIndex(0)
    b.search.setText("pd")
    assert [e.name for e in b.model.rows] == ["c.pdf"]
    b.search.clear()
    b.set_grid(False)
    b.view.selectAll()
    assert len(b.selected_entries()) == 4
    b.cleanup()


# ----------------------------------------------------------------------------- §1 biblioteca de carpetas
def _snapshot(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*"))


def test_folder_library_persists_customisation(qapp, media, tmp_path):
    from PySide6.QtGui import QImage

    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.files.page import FilesPage

    a, b, c = (_tree(tmp_path / n, media) for n in ("A", "B", "C"))
    before = [_snapshot(x) for x in (a, b, c)]
    db = Database()
    page = FilesPage(db, Settings())
    for x in (a, b, c):
        assert page.add_folder(str(x))
    assert not page.add_folder(str(a)), "no se duplica"
    assert page.model.rowCount() == 3
    page._set(str(a), title="Trabajo", description="Facturas y contratos", color="#e0a32e", favorite=1, sort="date")
    img = QImage(300, 200, QImage.Format.Format_RGB32)
    img.fill(0x3366AA)
    page._set(str(b), cover=page._save_cover_image(str(b), img))
    page._move(str(c), 0)                                  # C al principio
    db.conn.close()

    db2 = Database()                                       # «cerrar y volver a abrir»
    page2 = FilesPage(db2, Settings())
    rows = db2.library_folders()
    assert [r["path"] for r in rows] == [str(c), str(a), str(b)]
    ra = rows[1]
    assert (ra["title"], ra["description"], ra["color"], ra["favorite"], ra["sort"]) == \
        ("Trabajo", "Facturas y contratos", "#e0a32e", 1, "date")
    assert rows[2]["cover"] and page2.cover_pixmap(rows[2]) is not None
    page2.seg_fav.click()
    assert page2.model.rowCount() == 1 and page2.model.item(0).text() == "Trabajo"
    page2.seg_all.click()
    page2.search.setText("factur")
    assert page2.model.rowCount() == 1
    page2.search.clear()
    page2.open_folder(str(a))
    assert page2.browser.sort.currentData() == "date", "la ordenación del contenido se recuerda"
    assert wait_until(qapp, lambda: page2.browser.model.rowCount() == 3)
    page2.show_library()
    page2.remove(str(a), confirm=False)
    assert [r["path"] for r in db2.library_folders()] == [str(c), str(b)]
    assert a.exists() and [_snapshot(x) for x in (a, b, c)] == before, "la biblioteca nunca toca los archivos"
    db2.conn.close()


def test_folder_library_reorder_by_drag_model(qapp, tmp_path):
    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.files.page import FOLDER_ROLE, FilesPage

    dirs = []
    for n in "XYZ":
        (tmp_path / n).mkdir()
        dirs.append(str(tmp_path / n))
    page = FilesPage(Database(), Settings())
    for d in dirs:
        page.add_folder(d)
    # Simula el resultado de un arrastre: la fila Z pasa delante
    page.model.insertRow(0, page.model.takeRow(2))
    page._save_order()
    assert [page.model.item(i).data(FOLDER_ROLE)["path"] for i in range(3)] == [dirs[2], dirs[0], dirs[1]]


def test_files_page_in_navigation(qapp, controller):
    win = controller.show_main()
    win.navigate("files")
    assert win.current_page() == "files"
    from aero.files.page import FilesPage

    assert isinstance(win.page("files"), FilesPage)


def test_heavy_modules_not_loaded_at_startup():
    """Arranque ligero: los módulos de archivos y comprimidos solo se cargan al usarlos."""
    import subprocess
    import sys

    code = ("import sys, aero, aero.app; "
            "print(any(m.startswith(('aero.files', 'aero.archive', 'aero.editors')) for m in sys.modules))")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "False", r.stdout + r.stderr


# ----------------------------------------------------------------------------- §5 Inicio
def test_greetings_by_time_season_and_region():
    import datetime as dt

    from aero.core.seasons import greeting

    def g(y, m, d, h, region, specials=True):
        return greeting(dt.datetime(y, m, d, h), region, specials)

    assert g(2026, 3, 3, 9, "ES").title == "Buenos días"
    assert g(2026, 3, 3, 15, "ES").title == "Buenas tardes"
    assert g(2026, 3, 3, 23, "ES").title == "Buenas noches"
    assert g(2026, 12, 25, 10, "ES").title == "Feliz Navidad"
    assert g(2026, 1, 1, 10, "US").title == "Feliz Año Nuevo"
    assert g(2026, 1, 6, 10, "ES").title == "Feliz Día de Reyes"
    assert g(2026, 1, 6, 10, "US").title == "Buenos días", "Reyes no se felicita en EE. UU."
    assert g(2026, 10, 31, 20, "ES").title == "Feliz Halloween"
    assert g(2026, 10, 31, 20, "MX").title == "Buenas tardes"
    assert g(2026, 11, 1, 20, "MX").title == "Feliz Día de Muertos"
    assert g(2026, 11, 1, 20, "ES").title == "Buenas tardes", "Día de Muertos solo en México"
    assert g(2026, 11, 26, 10, "US").title == "Feliz Día de Acción de Gracias"
    assert g(2026, 12, 25, 10, "none").title == "Buenos días"
    assert g(2026, 12, 25, 10, "ES", specials=False).title == "Buenos días", "se pueden desactivar"
    assert "Bienvenida la primavera" in g(2026, 3, 22, 10, "ES").subtitle
    assert "primavera" not in g(2026, 4, 22, 10, "ES").subtitle, "solo la primera semana"
    assert g(2026, 7, 10, 10, "ES").season == "summer"
    assert g(2026, 7, 10, 10, "SUR").season == "winter", "hemisferio sur"
    assert "Bienvenido el invierno" in g(2026, 6, 23, 10, "SUR").subtitle
    assert g(2026, 11, 1, 22, "ES").subtitle.startswith("Domingo, 1 de noviembre")


def test_home_page_is_minimal_and_follows_settings(qapp, controller):
    import datetime as dt

    win = controller.show_main()
    home = win.page("home")
    s = controller.settings
    s.set("holiday_region", "ES")
    # 2.0: identidad visual permanente, sin felicitaciones ni adornos por fechas (solo el saludo según la hora)
    home.refresh(dt.datetime(2026, 12, 25, 18))
    assert home.greet.text() == "Buenas tardes" and not hasattr(home, "art")
    assert len(home.tiles) == 6 and not home.history.isVisibleTo(home), "historial completo solo bajo demanda"
    home.more.setChecked(True)
    assert home.history.isVisibleTo(home)


def test_browser_clears_rows_when_archive_fails(qapp, tmp_path, media):
    from aero.files.browser import FolderBrowser

    good = tmp_path / "bueno.zip"
    _zip(good, {"a.txt": "x"})
    bad = tmp_path / "roto.zip"
    bad.write_bytes(b"PK\x03\x04" + b"basura" * 20)  # cabecera sin directorio central: dañado de verdad
    b = FolderBrowser()
    b.set_root(str(good))
    assert wait_until(qapp, lambda: b.model.rowCount() == 1)
    b.set_root(str(bad))
    assert b.model.rowCount() == 0, "no quedan filas del comprimido anterior"
    assert wait_until(qapp, lambda: b.state.currentIndex() == 2)
    b._activate(b.model.index(0))  # no debe fallar aunque no haya filas
    b.cleanup()
