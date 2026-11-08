"""Operaciones por lotes desde «Archivos»: renombrado masivo y redimensionado de fotos (sin Qt).

Reglas: nunca se sobrescribe un archivo que no forma parte del lote, el renombrado se puede deshacer y el
redimensionado crea copias (los originales no se tocan).
"""

from __future__ import annotations

import datetime as dt
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
CASES = {"keep": "Sin cambios", "lower": "minúsculas", "upper": "MAYÚSCULAS", "title": "Tipo Título"}
TOKEN_EN = {"{nombre}": "{name}", "{fecha}": "{date}", "{carpeta}": "{folder}"}
TOKENS = {"{nombre}": "Nombre original", "{n}": "Número", "{fecha}": "Fecha de modificación",
          "{carpeta}": "Carpeta"}


# ----------------------------------------------------------------------------- renombrado

@dataclass
class RenameOptions:
    pattern: str = "{nombre}"
    find: str = ""
    replace: str = ""
    match_case: bool = False
    case: str = "keep"
    start: int = 1
    digits: int = 2
    lower_ext: bool = False


@dataclass
class RenameItem:
    src: Path
    name: str          # nombre nuevo (con extensión)
    problem: str = ""  # vacío si se puede renombrar

    @property
    def changed(self) -> bool:
        return self.name != self.src.name


def _apply_case(text: str, case: str) -> str:
    if case == "lower":
        return text.lower()
    if case == "upper":
        return text.upper()
    if case == "title":
        return " ".join(w[:1].upper() + w[1:].lower() for w in text.split(" "))
    return text


def new_name(src: Path, index: int, opts: RenameOptions) -> str:
    stem, ext = src.stem, src.suffix
    try:
        date = dt.date.fromtimestamp(src.stat().st_mtime).isoformat()
    except OSError:
        date = ""
    number = str(opts.start + index).zfill(max(1, opts.digits))
    out = opts.pattern or "{nombre}"
    for canon, value in (("{nombre}", stem), ("{n}", number), ("{fecha}", date), ("{carpeta}", src.parent.name)):
        # Cada ficha también vale en inglés ({name}, {date}, {folder}): la interfaz las muestra según el idioma
        out = out.replace(canon, value).replace(TOKEN_EN.get(canon, canon), value)
    if opts.find:
        flags = 0 if opts.match_case else re.IGNORECASE
        out = re.sub(re.escape(opts.find), lambda _m: opts.replace, out, flags=flags)
    out = _apply_case(out, opts.case).strip().rstrip(".")
    return out + (ext.lower() if opts.lower_ext else ext)


def _problem(name: str) -> str:
    stem = Path(name).stem
    if not stem.strip():
        return "El nombre queda vacío"
    if INVALID.search(name):
        return "Contiene caracteres no permitidos (< > : \" / \\ | ? *)"
    if stem.upper() in RESERVED:
        return "Nombre reservado por Windows"
    if len(name) > 240:
        return "Nombre demasiado largo"
    return ""


def plan_rename(paths: list[str | Path], opts: RenameOptions) -> list[RenameItem]:
    """Calcula los nombres nuevos y marca los problemas (duplicados, archivos ajenos con ese nombre…)."""
    srcs = [Path(p) for p in paths]
    items = [RenameItem(p, new_name(p, i, opts)) for i, p in enumerate(srcs)]
    own = {str(p).lower() for p in srcs}
    seen: dict[str, int] = {}
    for it in items:
        it.problem = _problem(it.name)
        key = str(it.src.with_name(it.name)).lower()
        seen[key] = seen.get(key, 0) + 1
    for it in items:
        if it.problem:
            continue
        target = it.src.with_name(it.name)
        key = str(target).lower()
        if seen[key] > 1:
            it.problem = "Varios archivos tendrían el mismo nombre"
        elif it.changed and key not in own and target.exists():
            it.problem = "Ya existe otro archivo con ese nombre"
    return items


def apply_rename(items: list[RenameItem]) -> list[tuple[Path, Path]]:
    """Renombra en dos pasos (permite intercambiar nombres dentro del lote). Si algo falla, deshace lo hecho.

    Devuelve los pares (antes, después) para poder deshacer.
    """
    todo = [it for it in items if it.changed and not it.problem]
    temps: list[tuple[Path, Path, Path]] = []
    done: list[tuple[Path, Path]] = []
    tag = uuid.uuid4().hex[:8]
    try:
        for i, it in enumerate(todo):
            tmp = it.src.with_name(f".aero-renombrando-{tag}-{i}{it.src.suffix}")
            os.rename(it.src, tmp)
            temps.append((it.src, tmp, it.src.with_name(it.name)))
        for src, tmp, dst in temps:
            if dst.exists():
                raise FileExistsError(f"Ya existe {dst.name}")
            os.rename(tmp, dst)
            done.append((src, dst))
    except OSError:
        # Volver al estado inicial: primero lo ya renombrado, después lo que quedó con nombre temporal.
        for src, dst in reversed(done):
            try:
                os.rename(dst, src)
            except OSError:
                pass
        finished = {s for s, _ in done}
        for src, tmp, _dst in temps:
            if src not in finished and tmp.exists():
                try:
                    os.rename(tmp, src)
                except OSError:
                    pass
        raise
    return done


def undo_rename(done: list[tuple[Path, Path]]) -> int:
    """Devuelve los nombres originales. Cuenta los archivos restaurados."""
    items = [RenameItem(dst, src.name) for src, dst in done if dst.exists()]
    for it in items:
        target = it.src.with_name(it.name)
        if target.exists() and str(target).lower() not in {str(d).lower() for _s, d in done}:
            it.problem = "Ya existe otro archivo con ese nombre"
    return len(apply_rename(items))


# ----------------------------------------------------------------------------- redimensionado

MODES = {"max": "Lado mayor máximo", "percent": "Porcentaje", "box": "Ajustar dentro de"}
FORMATS = {"keep": "Mismo formato", "jpg": "JPG", "png": "PNG", "webp": "WebP"}


@dataclass
class ResizeOptions:
    mode: str = "max"
    side: int = 1920        # «max»
    percent: int = 50       # «percent»
    width: int = 1280       # «box»
    height: int = 1280
    upscale: bool = False
    fmt: str = "keep"
    quality: int = 88
    strip_metadata: bool = False
    folder: str = "Redimensionadas"   # subcarpeta junto al original; vacío = misma carpeta con sufijo


def target_size(w: int, h: int, opts: ResizeOptions) -> tuple[int, int]:
    if opts.mode == "percent":
        f = max(1, opts.percent) / 100
    elif opts.mode == "box":
        f = min(max(1, opts.width) / w, max(1, opts.height) / h)
    else:
        f = max(1, opts.side) / max(w, h)
    if not opts.upscale:
        f = min(f, 1.0)
    return max(1, round(w * f)), max(1, round(h * f))


def output_for(src: Path, size: tuple[int, int], opts: ResizeOptions) -> Path:
    from aero.core.convert_spec import unique_path

    ext = src.suffix.lower() if opts.fmt == "keep" else "." + opts.fmt
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in SAVE_AS:
        ext = ".jpg"   # HEIC, AVIF, ICO…: la copia se guarda en un formato que abre cualquier programa
    if opts.folder:
        return unique_path(src.parent / opts.folder / (src.stem + ext))
    return unique_path(src.with_name(f"{src.stem}_{size[0]}x{size[1]}{ext}"))


SAVE_AS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".bmp": "BMP", ".tif": "TIFF",
           ".tiff": "TIFF", ".gif": "GIF"}


def resize_image(src: str | Path, opts: ResizeOptions) -> Path:
    """Crea una copia redimensionada (orientación EXIF aplicada) y devuelve su ruta. El original no cambia."""
    from PIL import Image, ImageOps

    from aero.core import builtin_convert  # noqa: F401 - registra HEIC/HEIF si está disponible

    src = Path(src)
    with Image.open(src) as im:
        im.load()
        icc = im.info.get("icc_profile")
        exif = im.info.get("exif")
        work = ImageOps.exif_transpose(im)
        size = target_size(work.width, work.height, opts)
        if size != work.size:
            if work.mode == "P":
                work = work.convert("RGBA")
            work = work.resize(size, Image.Resampling.LANCZOS)
        dst = output_for(src, size, opts)
        kind = SAVE_AS[dst.suffix.lower()]
        kw: dict = {}
        if icc and not opts.strip_metadata and kind in ("JPEG", "PNG", "WEBP", "TIFF"):
            kw["icc_profile"] = icc
        if exif and not opts.strip_metadata and kind in ("JPEG", "WEBP"):
            # La orientación ya se aplicó a los píxeles: se quita la etiqueta para que no se gire dos veces.
            ex = Image.Exif()
            ex.load(exif)
            ex.pop(0x0112, None)
            kw["exif"] = ex.tobytes()
        if kind == "JPEG":
            if work.mode not in ("RGB", "L"):
                from aero.core.builtin_convert import _flatten

                work = _flatten(work, "#ffffff")
            kw.update(quality=max(1, min(100, opts.quality)), optimize=True, progressive=True)
        elif kind == "WEBP":
            kw.update(quality=max(1, min(100, opts.quality)), method=4)
        elif kind == "PNG":
            kw.update(optimize=True)
        elif kind == "BMP" and work.mode not in ("RGB", "L", "1"):
            work = work.convert("RGB")
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".{dst.stem}.aero-tmp{dst.suffix}")
        try:
            work.save(tmp, kind, **kw)
            os.rename(tmp, dst)   # falla si apareció otro archivo con ese nombre: nunca se sobrescribe
        finally:
            if tmp.exists():
                tmp.unlink()
    return dst
