"""Conversiones internas que no necesitan FFmpeg ni LibreOffice (imágenes, PDF, documentos sencillos).

Todas las funciones se ejecutan en hilos de trabajo; `cancelled()` permite abortar entre pasos.
"""

from __future__ import annotations

import csv
import html
import io
from pathlib import Path
from typing import Callable

from aero.core.convert_spec import ConvertOptions, safe_name, unique_path

try:
    from PIL import Image, ImageOps, ImageSequence, features
except ImportError:  # pragma: no cover
    Image = None

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - opcional
    pillow_heif = None

Progress = Callable[[float], None]
Cancelled = Callable[[], bool]

DOC_CSS = """
body { font-family: 'Segoe UI', sans-serif; font-size: 11pt; line-height: 1.5; color: #111; max-width: 46em; margin: 2em auto; }
img { max-width: 100%; } table { border-collapse: collapse; } td, th { border: 1px solid #bbb; padding: 4px 8px; }
pre, code { font-family: 'Cascadia Mono', Consolas, monospace; }
"""


STYLE_MAP = """
p[style-name='Title'] => h1.title:fresh
p[style-name='Subtitle'] => h2.subtitle:fresh
p[style-name='Heading 1'] => h1:fresh
p[style-name='Heading 2'] => h2:fresh
p[style-name='Heading 3'] => h3:fresh
"""


class ConversionCancelled(Exception):
    pass


def pillow_has_avif() -> bool:
    try:
        return Image is not None and bool(features.check("avif"))
    except Exception:
        return False


# ----------------------------------------------------------------------------- imágenes

def _open_image(src: Path):
    if src.suffix.lower() in (".svg", ".svgz"):
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer

        r = QSvgRenderer(str(src))
        if not r.isValid():
            raise ValueError("SVG no válido.")
        size = r.defaultSize()
        scale = max(1.0, 1024 / max(size.width(), size.height(), 1))
        img = QImage(int(size.width() * scale), int(size.height() * scale), QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        r.render(p)
        p.end()
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        return Image.open(io.BytesIO(bytes(buf.data())))
    return Image.open(src)


def _flatten(im, bg: str):
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, bg)
        base.paste(im, mask=im.getchannel("A"))
        return base
    return im.convert("RGB")


def convert_image(src: Path, dst: Path, opts: ConvertOptions, progress: Progress, cancelled: Cancelled) -> list[Path]:
    if Image is None:
        raise RuntimeError("Pillow no está instalado.")
    t = opts.target
    q = max(1, min(100, opts.quality))
    with _open_image(src) as im:
        n_frames = getattr(im, "n_frames", 1)
        animated = n_frames > 1 and t in ("gif", "webp", "png")
        kwargs: dict = {}
        if not opts.strip_metadata and im.info.get("icc_profile") and t in ("jpg", "png", "webp", "tiff", "avif"):
            kwargs["icc_profile"] = im.info["icc_profile"]
        if animated:
            frames, durations = [], []
            for i, fr in enumerate(ImageSequence.Iterator(im)):
                if cancelled():
                    raise ConversionCancelled()
                f = fr.convert("RGBA")
                if opts.max_side:
                    f.thumbnail((opts.max_side, opts.max_side), Image.Resampling.LANCZOS)
                frames.append(f)
                durations.append(fr.info.get("duration", 100))
                progress(0.8 * (i + 1) / n_frames)
            extra = {"quality": q, "method": 4} if t == "webp" else {}
            frames[0].save(dst, save_all=True, append_images=frames[1:], duration=durations, loop=0, **extra)
            return [dst]
        im.load()
        work = ImageOps.exif_transpose(im)
        if opts.max_side:
            work.thumbnail((opts.max_side, opts.max_side), Image.Resampling.LANCZOS)
        progress(0.5)
        if t in ("jpg", "bmp", "pdf"):
            work = _flatten(work, opts.bg_color)
        elif work.mode in ("CMYK", "YCbCr", "I;16", "I", "F"):
            work = work.convert("RGB")
        elif work.mode == "P" and t not in ("gif", "png"):
            work = work.convert("RGBA")
        exif = im.info.get("exif") if not opts.strip_metadata else None
        if t == "jpg":
            kwargs.update(quality=q, optimize=True, progressive=True, subsampling=0 if q >= 90 else 2)
            if exif:
                kwargs["exif"] = exif
            work.save(dst, "JPEG", **kwargs)
        elif t == "png":
            work.save(dst, "PNG", optimize=True, **kwargs)
        elif t == "webp":
            if exif:
                kwargs["exif"] = exif
            work.save(dst, "WEBP", quality=q, method=4, lossless=q >= 100, **kwargs)
        elif t == "avif":
            work.save(dst, "AVIF", quality=q, **kwargs)
        elif t == "tiff":
            work.save(dst, "TIFF", compression="tiff_lzw", **kwargs)
        elif t == "gif":
            work.save(dst, "GIF", optimize=True)
        elif t == "bmp":
            work.save(dst, "BMP")
        elif t == "ico":
            sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= max(work.size)] or [(16, 16)]
            work.save(dst, "ICO", sizes=sizes)
        elif t == "pdf":
            work.save(dst, "PDF", resolution=150.0)
        else:
            raise ValueError(f"Formato de imagen no compatible: {t}")
    progress(1.0)
    return [dst]


# ----------------------------------------------------------------------------- PDF

def pdf_to_images(src: Path, dst: Path, opts: ConvertOptions, progress: Progress, cancelled: Cancelled) -> list[Path]:
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument

    doc = QPdfDocument()
    if doc.load(str(src)) != QPdfDocument.Error.None_:
        raise ValueError("No se pudo abrir el PDF (¿dañado o protegido con contraseña?).")
    folder = unique_path(dst.with_suffix(""))
    folder.mkdir(parents=True)
    dpi = int(opts.extra.get("dpi", 150))
    outs = []
    n = doc.pageCount()
    for i in range(n):
        if cancelled():
            raise ConversionCancelled()
        pts = doc.pagePointSize(i)
        size = QSize(max(1, int(pts.width() * dpi / 72)), max(1, int(pts.height() * dpi / 72)))
        img = doc.render(i, size)
        if opts.target == "jpg":
            from PySide6.QtGui import QImage, QPainter
            flat = QImage(img.size(), QImage.Format.Format_RGB32)
            flat.fill(0xFFFFFFFF)
            p = QPainter(flat)
            p.drawImage(0, 0, img)
            p.end()
            img = flat
        out = folder / f"{safe_name(src.stem)}_p{i + 1:03d}.{opts.target}"
        if not img.save(str(out), None, opts.quality if opts.target == "jpg" else -1):
            raise OSError("No se pudo escribir la imagen de salida.")
        outs.append(out)
        progress((i + 1) / n)
    doc.close()
    return outs


def pdf_to_text(src: Path, dst: Path, opts, progress: Progress, cancelled: Cancelled) -> list[Path]:
    # pypdfium2 une bien las letras de una misma línea aunque el PDF las coloque una a una (pasa con PDF
    # generados en Linux); QtPdf queda de reserva.
    try:
        import pypdfium2 as pdfium
    except ImportError:
        pdfium = None
    if pdfium is not None:
        try:
            pdf = pdfium.PdfDocument(str(src))
        except pdfium.PdfiumError as e:
            raise ValueError("No se pudo abrir el PDF.") from e
        try:
            parts = []
            n = len(pdf)
            for i in range(n):
                if cancelled():
                    raise ConversionCancelled()
                page = pdf[i]
                tp = page.get_textpage()
                parts.append(tp.get_text_range().replace("\r\n", "\n"))
                tp.close()
                page.close()
                progress((i + 1) / n)
        finally:
            pdf.close()
        dst.write_text("\n\n\f".join(parts), encoding="utf-8")
        return [dst]
    from PySide6.QtPdf import QPdfDocument

    doc = QPdfDocument()
    if doc.load(str(src)) != QPdfDocument.Error.None_:
        raise ValueError("No se pudo abrir el PDF.")
    parts = []
    n = doc.pageCount()
    for i in range(n):
        if cancelled():
            raise ConversionCancelled()
        parts.append(doc.getAllText(i).text())
        progress((i + 1) / n)
    dst.write_text("\n\n\f".join(parts), encoding="utf-8")
    return [dst]


# ----------------------------------------------------------------------------- documentos

def document_to_html(src: Path) -> str:
    """HTML legible para vista previa o conversión (DOCX, ODT, RTF, MD, TXT, HTML)."""
    ext = src.suffix.lower()
    if ext == ".docx":
        import mammoth

        with open(src, "rb") as fh:
            body = mammoth.convert_to_html(fh, style_map=STYLE_MAP).value
    elif ext == ".odt":
        body = odt_to_html(src)
    elif ext in (".md", ".markdown"):
        import markdown

        body = markdown.markdown(read_text_file(src), extensions=["tables", "fenced_code", "sane_lists", "toc"])
    elif ext in (".html", ".htm"):
        return read_text_file(src)
    elif ext == ".rtf":
        from striprtf.striprtf import rtf_to_text

        body = "<pre style='white-space:pre-wrap;font-family:Segoe UI'>" + html.escape(
            rtf_to_text(read_text_file(src), errors="ignore")) + "</pre>"
    else:
        body = "<pre>" + html.escape(read_text_file(src)) + "</pre>"
    return f"<html><head><meta charset='utf-8'><style>{DOC_CSS}</style></head><body>{body}</body></html>"


def odt_to_html(src: Path) -> str:
    from odf import teletype
    from odf.opendocument import load
    from odf.table import TableCell, TableRow
    from odf.text import P

    doc = load(str(src))
    body = doc.text
    if not body.childNodes:
        # Algunos ODT (p. ej. los que escribe Qt) dejan vacío el acceso directo de odfpy: se busca el cuerpo
        from odf.office import Text

        found = doc.body.getElementsByType(Text)
        body = found[0] if found else body
    out = []
    for el in body.childNodes:
        q = el.qname[1] if hasattr(el, "qname") else ""
        if q == "h":
            level = el.getAttribute("outlinelevel") or 2
            out.append(f"<h{level}>{html.escape(teletype.extractText(el))}</h{level}>")
        elif q == "p":
            out.append(f"<p>{html.escape(teletype.extractText(el))}</p>")
        elif q == "list":
            items = [f"<li>{html.escape(teletype.extractText(i))}</li>" for i in el.getElementsByType(P)]
            out.append("<ul>" + "".join(items) + "</ul>")
        elif q == "table":
            rows = []
            for r in el.getElementsByType(TableRow):
                cells = "".join(f"<td>{html.escape(teletype.extractText(c))}</td>" for c in r.getElementsByType(TableCell))
                rows.append(f"<tr>{cells}</tr>")
            out.append("<table>" + "".join(rows) + "</table>")
        else:
            txt = teletype.extractText(el)
            if txt.strip():
                out.append(f"<p>{html.escape(txt)}</p>")
    return "\n".join(out)


def read_text_file(path: Path, limit: int | None = None) -> str:
    with open(path, "rb") as fh:
        raw = fh.read(limit) if limit else fh.read()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        if limit:
            # Puede haberse cortado un carácter multibyte al final.
            try:
                return raw[:-3].decode("utf-8-sig") if len(raw) > 3 else raw.decode("cp1252", "replace")
            except UnicodeDecodeError:
                pass
        return raw.decode("cp1252", "replace")


def document_to_text(src: Path) -> str:
    ext = src.suffix.lower()
    if ext == ".docx":
        import mammoth

        with open(src, "rb") as fh:
            return mammoth.extract_raw_text(fh).value
    if ext == ".odt":
        from odf import teletype
        from odf.opendocument import load

        return teletype.extractText(load(str(src)).text)
    if ext == ".rtf":
        from striprtf.striprtf import rtf_to_text

        return rtf_to_text(read_text_file(src), errors="ignore")
    if ext in (".pptx", ".ppsx"):
        return slides_text(src)
    return read_text_file(src)


def slides_text(src: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(src))
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        lines = [f"— Diapositiva {i} —"]
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                lines.append(shape.text_frame.text)
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def html_to_pdf(html_text: str, dst: Path) -> None:
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument

    writer = QPdfWriter(str(dst))
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                     QMarginsF(18, 18, 18, 18), QPageLayout.Unit.Millimeter))
    writer.setResolution(1200)       # con 120 las letras se colocaban a saltos y el texto se copiaba troceado
    doc = QTextDocument()
    # Métricas de diseño y sin «hinting»: con las de pantalla (FreeType en Linux) las palabras salían troceadas
    # en el PDF y al copiar el texto aparecían letras sueltas.
    doc.setUseDesignMetrics(True)
    font = doc.defaultFont()
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    doc.setDefaultFont(font)
    doc.setHtml(html_text)
    doc.print_(writer)


def convert_document_builtin(src: Path, dst: Path, opts: ConvertOptions, progress: Progress,
                             cancelled: Cancelled) -> list[Path]:
    t = opts.target
    progress(0.1)
    if t == "html":
        dst.write_text(document_to_html(src), encoding="utf-8")
    elif t == "txt":
        dst.write_text(document_to_text(src), encoding="utf-8")
    elif t == "pdf":
        html_to_pdf(document_to_html(src), dst)
    else:
        raise ValueError(f"Conversión no disponible sin LibreOffice: {src.suffix} → {t}")
    progress(1.0)
    return [dst]


def sheet_to_csv(src: Path, dst: Path, opts, progress: Progress, cancelled: Cancelled) -> list[Path]:
    if src.suffix.lower() in (".csv", ".tsv"):
        raise ValueError("El archivo ya es CSV.")
    from python_calamine import CalamineWorkbook

    wb = CalamineWorkbook.from_path(str(src))
    names = wb.sheet_names
    outs = []
    for i, name in enumerate(names):
        if cancelled():
            raise ConversionCancelled()
        rows = wb.get_sheet_by_name(name).to_python(skip_empty_area=False)
        out = dst if len(names) == 1 else unique_path(dst.with_name(f"{dst.stem}_{safe_name(name)}.csv"))
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:
            csv.writer(fh).writerows(rows)
        outs.append(out)
        progress((i + 1) / len(names))
    return outs


def pdf_to_editable(src: Path, dst: Path, opts: ConvertOptions, progress: Progress, cancelled: Cancelled) -> list[Path]:
    """Reconstrucción del documento (aero.pdfconv): OCR automático en páginas escaneadas."""
    from aero.pdfconv import extract, writers

    mode = (opts.extra or {}).get("pdf_mode", "auto")
    lang = (opts.extra or {}).get("ocr_lang", "auto")
    doc = extract.convert(str(src), mode, lang, progress=lambda i, n: progress(0.95 * i / max(1, n)),
                          cancelled=cancelled)
    if cancelled():
        raise RuntimeError("Cancelado")
    writers.WRITERS[opts.target](doc, str(dst))
    progress(1.0)
    return [dst]


def run_builtin(src: Path, dst: Path, opts: ConvertOptions, progress: Progress, cancelled: Cancelled) -> list[Path]:
    from aero.core.formats import kind_of

    kind = kind_of(src)
    if kind == "image":
        return convert_image(src, dst, opts, progress, cancelled)
    if kind == "pdf":
        if opts.target in ("png", "jpg"):
            return pdf_to_images(src, dst, opts, progress, cancelled)
        if opts.target in ("txt", "docx", "odt"):
            return pdf_to_editable(src, dst, opts, progress, cancelled)
    if kind == "sheet" and opts.target == "csv":
        return sheet_to_csv(src, dst, opts, progress, cancelled)
    if kind in ("document", "text", "slides"):
        return convert_document_builtin(src, dst, opts, progress, cancelled)
    raise ValueError("Conversión no compatible.")
