"""Extractor y compresor: ZIP, 7Z, TAR y RAR; contraseñas, nombres en cualquier idioma, seguridad."""

import os
import zipfile
from pathlib import Path

import pytest

NAMES = ["normal.txt", "acentos ñandú.txt", "emoji 😀.txt", "日本語.txt", "sub/dentro de carpeta.txt"]


def _tree(base: Path) -> Path:
    root = base / "Mis cosas"
    for n in NAMES:
        p = root / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"contenido de {n}\n" * 50, encoding="utf-8")
    (root / "vacía").mkdir()
    return root


def _same(a: Path, b: Path):
    for n in NAMES:
        assert (b / n).read_text(encoding="utf-8") == (a / n).read_text(encoding="utf-8"), n


@pytest.mark.parametrize("fmt", ["zip", "7z", "tar.gz", "tar.xz"])
@pytest.mark.parametrize("password", [None, "clave secreta ñ"])
def test_roundtrip_all_formats(tmp_path, fmt, password):
    from aero.archive import ops

    if password and fmt.startswith("tar"):
        pytest.skip("TAR no admite contraseña")
    src = _tree(tmp_path)
    out = tmp_path / f"copia.{fmt}"
    seen = []
    res = ops.compress([str(src)], str(out), fmt, 7, password, progress=lambda i, n, name: seen.append((i, n)))
    assert out.exists() and res.files == len(NAMES)
    assert seen and seen[-1][0] == seen[-1][1], "el progreso llega al final"
    assert not list(tmp_path.glob(".*part")), "no quedan temporales"
    dest = tmp_path / "salida"
    r = ops.extract(str(out), str(dest), password=password)
    _same(src, dest / "Mis cosas")
    assert (dest / "Mis cosas" / "vacía").is_dir()
    assert r.files == len(NAMES) and not r.unsafe
    ok, msg = ops.test_archive(str(out), password)
    assert ok, msg


@pytest.mark.parametrize("fmt", ["zip", "7z"])
def test_password_missing_and_wrong(tmp_path, fmt):
    from aero.archive import PasswordRequired, ops

    src = _tree(tmp_path)
    out = tmp_path / f"c.{fmt}"
    ops.compress([str(src)], str(out), fmt, 5, "buena")
    with pytest.raises(PasswordRequired):
        ops.extract(str(out), str(tmp_path / "a"))
    with pytest.raises(PasswordRequired):
        ops.extract(str(out), str(tmp_path / "b"), password="mala")
    assert not any((tmp_path / "b").rglob("*.txt")), "nada a medias con la contraseña errónea"


def test_overwrite_modes_and_partial(tmp_path):
    from aero.archive import ops

    src = _tree(tmp_path)
    out = tmp_path / "c.zip"
    ops.compress([str(src / "normal.txt"), str(src / "sub")], str(out), "zip")
    dest = tmp_path / "d"
    ops.extract(str(out), str(dest))
    (dest / "normal.txt").write_text("mío", encoding="utf-8")
    r = ops.extract(str(out), str(dest), mode="skip")
    assert (dest / "normal.txt").read_text(encoding="utf-8") == "mío" and "normal.txt" in r.skipped
    ops.extract(str(out), str(dest), mode="rename")
    assert (dest / "normal (2).txt").exists() and (dest / "normal.txt").read_text(encoding="utf-8") == "mío"
    ops.extract(str(out), str(dest), mode="overwrite")
    assert (dest / "normal.txt").read_text(encoding="utf-8").startswith("contenido")
    only = tmp_path / "solo"
    ops.extract(str(out), str(only), members=["sub"])
    assert (only / "sub" / "dentro de carpeta.txt").exists() and not (only / "normal.txt").exists()


def test_extract_here_and_into_folder(tmp_path):
    from aero.archive import ops

    src = _tree(tmp_path)
    out = tmp_path / "fotos.tar.gz"
    ops.compress([str(src / "normal.txt")], str(out), "tar.gz")
    r = ops.extract_to_folder(str(out))
    assert Path(r.dest) == tmp_path / "fotos" and (tmp_path / "fotos" / "normal.txt").exists()
    r2 = ops.extract_to_folder(str(out))
    assert Path(r2.dest) == tmp_path / "fotos (2)", "no mezcla con una carpeta existente"
    here = tmp_path / "aqui"
    here.mkdir()
    z = here / "x.zip"
    ops.compress([str(src / "normal.txt")], str(z), "zip")
    ops.extract_here(str(z))
    assert (here / "normal.txt").exists()


def test_security_zip_slip_bomb_damaged_cancel(tmp_path):
    from aero.archive import ArchiveError, ops

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../../fuera.txt", "x")
        z.writestr("C:/Windows/mal.txt", "x")
        z.writestr("bien.txt", "x")
    r = ops.extract(str(evil), str(tmp_path / "d"))
    assert r.files == 1 and len(r.unsafe) == 2
    assert not (tmp_path / "fuera.txt").exists() and not list((tmp_path / "d").rglob("mal.txt"))
    bomb = tmp_path / "bomba.zip"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ceros.bin", b"\0" * (300 * 1024 * 1024))
    with pytest.raises(ArchiveError, match="bomba"):
        ops.extract(str(bomb), str(tmp_path / "e"))
    broken = tmp_path / "roto.7z"
    broken.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\0" * 40)
    with pytest.raises(ArchiveError):
        ops.extract(str(broken), str(tmp_path / "f"))
    src = _tree(tmp_path)
    out = tmp_path / "grande.zip"
    with pytest.raises(ops.Cancelled):
        ops.compress([str(src)], str(out), "zip", cancelled=lambda: True)
    assert not out.exists() and not list(tmp_path.glob(".grande.zip*"))


def test_rar_with_winrar(tmp_path):
    from aero.archive import PasswordRequired, ops

    if not (ops.winrar() or "").lower().endswith("rar.exe"):
        pytest.skip("WinRAR no instalado")
    src = _tree(tmp_path)
    out = tmp_path / "c.rar"
    ops.compress([str(src)], str(out), "rar", 5)
    dest = tmp_path / "d"
    ops.extract(str(out), str(dest))
    _same(src, dest / "Mis cosas")
    enc = tmp_path / "enc.rar"
    ops.compress([str(src)], str(enc), "rar", 5, "clave")
    with pytest.raises(PasswordRequired):
        ops.extract(str(enc), str(tmp_path / "x"))
    ops.extract(str(enc), str(tmp_path / "y"), password="clave")
    _same(src, tmp_path / "y" / "Mis cosas")


def test_formats_offered():
    from aero.archive import ops

    fmts = ops.available_write_formats()
    assert {"zip", "7z", "tar.gz", "tar.xz"} <= set(fmts)
    assert ("rar" in fmts) == bool((ops.winrar() or "").lower().endswith("rar.exe")), \
        "RAR solo se ofrece si WinRAR está instalado"
    assert os.path.basename(str(ops.default_archive_name([__file__], "zip"))).endswith(".zip")
