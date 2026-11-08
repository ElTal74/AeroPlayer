"""Reconstrucción de la estructura de un PDF con texto (pypdfium2) y de páginas escaneadas (OCR).

Pasos por página:
1. Caracteres con su caja, tamaño, peso, cursiva, fuente y color (PDFium).
2. Líneas: caracteres seguidos con la misma línea base; los cambios de estilo crean tramos («runs»).
3. Tablas con bordes: segmentos horizontales y verticales de los trazados forman una rejilla; el texto
   dentro de cada celda va a esa celda.
4. Columnas: si hay un pasillo vertical vacío con texto a ambos lados, el orden de lectura es columna a
   columna (lo que cruza el pasillo, como un título, se lee en su sitio).
5. Párrafos: líneas seguidas con interlineado normal y el mismo estilo; alineación por bordes.
6. Títulos: tamaños claramente mayores que el cuerpo del documento.
7. Imágenes: se extraen a PNG con su posición.

Es una reconstrucción: cuando el PDF no guarda la información (texto escaneado, fuentes sin nombre,
tablas sin bordes), el resultado es aproximado y se avisa en `Page.warnings`.
"""

from __future__ import annotations

import ctypes
import io
import re
from statistics import median

from aero.pdfconv.model import Document, Image, Line, Page, Paragraph, Run, Table

ITALIC_FLAG = 0x40


_QT_STYLE = re.compile(r"-(\d)-(\d{3})$")   # Qt escribe «Familia-<cursiva>-<peso>»


def _font_info(raw, tp, i, cache: dict) -> tuple[str, bool, bool]:
    """(nombre, negrita, cursiva) de la fuente del objeto de texto al que pertenece el carácter."""
    obj = raw.FPDFText_GetTextObject(tp, i)
    key = ctypes.cast(obj, ctypes.c_void_p).value if obj else None
    if key in cache:
        return cache[key]
    name, flags_v, angle_v, weight = "", 0, 0, 0
    if obj:
        font = raw.FPDFTextObj_GetFont(obj)
        if font:
            buf = ctypes.create_string_buffer(256)
            if raw.FPDFFont_GetBaseFontName(font, buf, 256):
                name = buf.value.decode("utf-8", "replace")
            flags_v = raw.FPDFFont_GetFlags(font)
            angle = ctypes.c_int(0)
            raw.FPDFFont_GetItalicAngle(font, ctypes.byref(angle))
            angle_v = angle.value
            weight = raw.FPDFFont_GetWeight(font)
    if "+" in name[:8]:
        name = name.split("+", 1)[1]  # subconjunto incrustado: «ABCDEF+Arial-Bold»
    low = name.lower()
    bold = any(k in low for k in ("bold", "black", "heavy", "semibold", "demi")) or weight >= 480
    italic = bool(flags_v & ITALIC_FLAG) or angle_v != 0 or any(k in low for k in ("italic", "oblique"))
    m = _QT_STYLE.search(name)
    if m:
        italic = italic or m.group(1) == "1"
        bold = bold or int(m.group(2)) >= 600
        name = name[: m.start()]
    cache[key] = (name, bold, italic)
    return cache[key]


def _clean_font(name: str) -> str:
    base = name.split("-")[0].split(",")[0]
    for suf in ("MT", "PSMT", "PS"):
        if base.endswith(suf) and len(base) > len(suf) + 2:
            base = base[: -len(suf)]
    return base


def page_chars(page, height: float) -> list[dict]:
    import pypdfium2.raw as raw

    tp = page.get_textpage()
    n = tp.count_chars()
    out = []
    l_, r_, b_, t_ = (ctypes.c_double() for _ in range(4))
    color = [ctypes.c_uint() for _ in range(4)]
    fonts: dict = {}
    for i in range(n):
        u = raw.FPDFText_GetUnicode(tp, i)
        ch = chr(u) if u else ""
        if ch in ("\r", "\n", "\x02"):
            out.append({"ch": "\n"})
            continue
        if not raw.FPDFText_GetCharBox(tp, i, l_, r_, b_, t_):
            continue
        size = raw.FPDFText_GetFontSize(tp, i) or 0.0
        box_h = t_.value - b_.value
        if size < 2.0 or (box_h > 0 and size < box_h * 0.6):
            # Tamaño nominal escalado por la matriz de texto: se deduce de la caja (≈ 0,7 del cuerpo).
            size = max(4.0, box_h / 0.7)
        name, bold, italic = _font_info(raw, tp, i, fonts)
        loose = raw.FS_RECTF()
        if raw.FPDFText_GetLooseCharBox(tp, i, ctypes.byref(loose)):
            lx0, lx1 = loose.left, loose.right   # caja de avance: entre letras de una palabra no hay hueco
        else:
            lx0, lx1 = l_.value, r_.value
        raw.FPDFText_GetFillColor(tp, i, *(ctypes.byref(c) for c in color))
        out.append({"ch": ch, "x0": l_.value, "x1": r_.value, "lx0": lx0, "lx1": lx1, "y0": height - t_.value, "y1": height - b_.value,
                    "size": round(float(size), 1), "bold": bold, "italic": italic, "font": _clean_font(name),
                    "color": "#{:02x}{:02x}{:02x}".format(*(c.value for c in color[:3]))})
    tp.close()
    return out


def _style(c: dict) -> tuple:
    return (c["size"], c["bold"], c["italic"], c["font"], c["color"])


def chars_to_lines(chars: list[dict]) -> list[Line]:
    lines: list[Line] = []
    cur: list[dict] = []

    def flush():
        if not cur:
            return
        runs: list[Run] = []
        for c in cur:
            if runs and _style(c) == (runs[-1].size, runs[-1].bold, runs[-1].italic, runs[-1].font,
                                      runs[-1].color) or (runs and c["ch"] == " "):
                runs[-1].text += c["ch"]
            else:
                runs.append(Run(c["ch"], c["size"], c["bold"], c["italic"], c["font"], c["color"]))
        boxes = [c for c in cur if "x0" in c and c["ch"].strip()]
        if boxes and "".join(r.text for r in runs).strip():
            lines.append(Line(runs, min(c["x0"] for c in boxes), min(c["y0"] for c in boxes),
                              max(c["x1"] for c in boxes), max(c["y1"] for c in boxes)))
        cur.clear()

    for c in chars:
        if c["ch"] == "\n":
            continue  # los saltos que inventa PDFium no son fiables (p. ej. con columnas): manda la geometría
        if not c["ch"].strip():
            if cur:
                cur.append(c)  # los espacios (muchos generados por PDFium) no deciden los saltos de línea
            continue
        if cur and "y0" in c:
            prev = next((p for p in reversed(cur) if "y0" in p and p["ch"].strip()), None)
            if prev is not None:
                h = max(1.0, prev["y1"] - prev["y0"])
                same_line = abs((c["y1"]) - (prev["y1"])) < h * 0.6 and c["x0"] > prev["x0"] - h
                # Un hueco muy grande en la misma línea separa celdas de tabla o columnas, nunca palabras.
                far = c["x0"] - prev["x1"] > max(prev["size"], c["size"]) * 2.0
                if not same_line or far:
                    while cur and not cur[-1]["ch"].strip():
                        cur.pop()
                    flush()
                elif cur[-1]["ch"].strip() and c["lx0"] - prev["lx1"] > max(prev["size"], c["size"]) * 0.15:
                    sp = dict(prev)
                    sp["ch"] = " "
                    cur.append(sp)  # espacio que el PDF solo posiciona y no escribe
        cur.append(c)
    flush()
    return lines


# --------------------------------------------------------------------------- tablas con bordes
def _segments(page, height: float) -> tuple[list, list]:
    import pypdfium2.raw as raw

    hs, vs = [], []
    for obj in page.get_objects(filter=(raw.FPDF_PAGEOBJ_PATH,), max_depth=3):
        try:
            x0, b, x1, t = obj.get_bounds()
        except Exception:  # noqa: BLE001
            continue
        y0, y1 = height - t, height - b
        w, h = x1 - x0, y1 - y0
        if h <= 2.5 and w > 8:
            hs.append((x0, x1, (y0 + y1) / 2))
        elif w <= 2.5 and h > 8:
            vs.append((y0, y1, (x0 + x1) / 2))
        elif w > 8 and h > 8 and obj.type == raw.FPDF_PAGEOBJ_PATH:
            # Rectángulo con borde: sus cuatro lados cuentan como segmentos
            hs += [(x0, x1, y0), (x0, x1, y1)]
            vs += [(y0, y1, x0), (y0, y1, x1)]
    return hs, vs


def _cluster(vals: list[float], tol: float = 2.0) -> list[float]:
    out: list[float] = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def find_tables(page, height: float, lines: list[Line]) -> tuple[list[Table], list[Line]]:
    hs, vs = _segments(page, height)
    if len(hs) < 2 or len(vs) < 2:
        return [], lines
    ys = _cluster([y for _a, _b, y in hs])
    xs = _cluster([x for _a, _b, x in vs])
    if len(ys) < 2 or len(xs) < 2:
        return [], lines
    # Una sola rejilla por página (la más habitual en documentos); suficiente para la primera versión.
    rows = [["" for _ in range(len(xs) - 1)] for _ in range(len(ys) - 1)]
    used = []
    for ln in lines:
        cx, cy = (ln.x0 + ln.x1) / 2, (ln.y0 + ln.y1) / 2
        if not (xs[0] - 1 <= cx <= xs[-1] + 1 and ys[0] - 1 <= cy <= ys[-1] + 1):
            continue
        ci = max(0, min(len(xs) - 2, sum(1 for x in xs[1:-1] if cx > x)))
        ri = max(0, min(len(ys) - 2, sum(1 for y in ys[1:-1] if cy > y)))
        rows[ri][ci] = (rows[ri][ci] + " " + ln.text.strip()).strip()
        used.append(ln)
    if not used or len(rows) * len(rows[0]) < 4:
        return [], lines
    t = Table(rows, xs[0], ys[0], xs[-1], ys[-1])
    return [t], [ln for ln in lines if ln not in used]


# --------------------------------------------------------------------------- columnas y párrafos
def detect_columns(lines: list[Line], width: float) -> float | None:
    """Posición x del pasillo entre dos columnas, o None."""
    body = [ln for ln in lines if ln.x1 - ln.x0 < width * 0.48]
    if len(body) < 8:
        return None
    for frac in (0.5, 0.48, 0.52, 0.45, 0.55, 0.42, 0.58):
        gx = width * frac
        crossing = [ln for ln in lines if ln.x0 < gx - 3 and ln.x1 > gx + 3]
        left = [ln for ln in body if ln.x1 <= gx]
        right = [ln for ln in body if ln.x0 >= gx]
        if len(left) >= 4 and len(right) >= 4 and len(crossing) <= max(2, len(lines) // 10):
            return gx
    return None


def _same_style(a: Line, b: Line) -> bool:
    return abs(a.size - b.size) < 0.6 and a.runs[0].bold == b.runs[0].bold


def lines_to_paragraphs(lines: list[Line], col_x0: float, col_x1: float) -> list[Paragraph]:
    paras: list[Paragraph] = []
    if not lines:
        return paras
    widths = [ln.x1 - ln.x0 for ln in lines]
    full = max(widths)
    cur: list[Line] = [lines[0]]

    def flush():
        runs: list[Run] = []
        for i, ln in enumerate(cur):
            for r in ln.runs:
                if runs and (r.size, r.bold, r.italic, r.font, r.color) == (runs[-1].size, runs[-1].bold,
                                                                            runs[-1].italic, runs[-1].font,
                                                                            runs[-1].color):
                    runs[-1].text += r.text
                else:
                    runs.append(Run(r.text, r.size, r.bold, r.italic, r.font, r.color))
            if i < len(cur) - 1 and runs:
                t = runs[-1].text
                if t.endswith("-") and len(t) > 1 and t[-2].isalpha():
                    runs[-1].text = t[:-1]  # palabra partida al final de línea
                elif not t.endswith(" "):
                    runs[-1].text = t + " "
        p = Paragraph(runs, min(ln.x0 for ln in cur), cur[0].y0, max(ln.x1 for ln in cur), cur[-1].y1)
        p.align = _alignment(cur, col_x0, col_x1, full)
        paras.append(p)

    for prev, ln in zip(lines, lines[1:]):
        # Distancia entre líneas medida con el cuerpo de letra (no con la caja, que cambia con «q», «p»…).
        h = max(prev.size, 1.0)
        lead = (ln.y1 - prev.y1)
        short_prev = (prev.x1 - prev.x0) < full * 0.72 and prev.x1 < col_x1 - h * 3
        new = lead > h * 1.75 or lead < -h * 0.5 or not _same_style(prev, ln) or short_prev \
            or abs(ln.x0 - prev.x0) > h * 3 and abs((ln.x0 + ln.x1) - (prev.x0 + prev.x1)) > h * 2
        if new:
            flush()
            cur = [ln]
        else:
            cur.append(ln)
    flush()
    return paras


def _alignment(lines: list[Line], x0: float, x1: float, full: float) -> str:
    cw = x1 - x0
    if len(lines) == 1:
        ln = lines[0]
        left, right = ln.x0 - x0, x1 - ln.x1
        if left > cw * 0.08 and abs(left - right) < cw * 0.05:
            return "center"
        if left > cw * 0.3 and right < cw * 0.03:
            return "right"
        return "left"
    lefts = [ln.x0 for ln in lines]
    rights = [ln.x1 for ln in lines[:-1]]
    centers = [(ln.x0 + ln.x1) / 2 for ln in lines]
    if max(lefts) - min(lefts) > 6 and max(centers) - min(centers) < 4:
        return "center"
    if max(rights) - min(rights) < 2.5 and max(lefts) - min(lefts) < 2.5 and len(lines) > 2:
        return "justify"
    if max(lefts) - min(lefts) > 6 and max(rights) - min(rights) < 2.5:
        return "right"
    return "left"


# --------------------------------------------------------------------------- imágenes
def page_images(page, height: float) -> list[Image]:
    import pypdfium2.raw as raw

    out = []
    for obj in page.get_objects(filter=(raw.FPDF_PAGEOBJ_IMAGE,), max_depth=3):
        try:
            x0, b, x1, t = obj.get_bounds()
            pil = obj.get_bitmap(render=True).to_pil()
        except Exception:  # noqa: BLE001
            continue
        if (x1 - x0) < 12 or (t - b) < 12:
            continue
        buf = io.BytesIO()
        pil.convert("RGBA" if pil.mode in ("RGBA", "LA", "P") else "RGB").save(buf, "PNG", optimize=False)
        out.append(Image(buf.getvalue(), x0, height - t, x1, height - b))
    return out


# --------------------------------------------------------------------------- página completa
def merge_segments(lines: list[Line], gap: float | None) -> list[Line]:
    """Une los trozos de una misma línea (separados por huecos amplios, p. ej. «A · B · C» centrado) salvo
    que crucen el pasillo entre columnas. Las celdas de tabla ya se han retirado antes."""
    # Agrupar por línea base con tolerancia (redondear podía separar trozos de una misma línea)
    rows: list[list[Line]] = []
    for ln in sorted(lines, key=lambda ln: ln.y1):
        if rows and abs(ln.y1 - rows[-1][0].y1) < rows[-1][0].size * 0.35:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    out: list[Line] = []
    for ln in (x for row in rows for x in sorted(row, key=lambda x: x.x0)):
        prev = out[-1] if out else None
        if prev is not None and abs(ln.y1 - prev.y1) < prev.size * 0.35 and 0 <= ln.x0 - prev.x1 < prev.size * 8                 and not (gap is not None and prev.x1 <= gap + 3 <= ln.x0):
            prev.runs = prev.runs + [Run(" ", prev.runs[-1].size, prev.runs[-1].bold, prev.runs[-1].italic,
                                         prev.runs[-1].font, prev.runs[-1].color)] + ln.runs
            prev.x1, prev.y0, prev.y1 = ln.x1, min(prev.y0, ln.y0), max(prev.y1, ln.y1)
        else:
            out.append(Line(list(ln.runs), ln.x0, ln.y0, ln.x1, ln.y1))
    return out


def build_page(width: float, height: float, lines: list[Line], images: list[Image], tables: list[Table],
               ocr: bool = False) -> Page:
    page = Page(width, height, ocr=ocr)
    gap = detect_columns(lines, width)
    lines = merge_segments(lines, gap)
    if gap is not None:
        page.columns = 2
    groups: list[tuple[list[Line], float, float, int]] = []
    if gap is None:
        lines.sort(key=lambda ln: (round(ln.y0, 0), ln.x0))
        x0 = min((ln.x0 for ln in lines), default=72)
        x1 = max((ln.x1 for ln in lines), default=width - 72)
        groups.append((lines, x0, x1, 0))
    else:
        # Lo que cruza el pasillo divide la página en franjas; dentro de cada franja, columna a columna.
        spans = sorted([ln for ln in lines if ln.x0 < gap - 3 and ln.x1 > gap + 3], key=lambda ln: ln.y0)
        rest = [ln for ln in lines if ln not in spans]
        cuts = [ln.y0 for ln in spans] + [height + 1]
        prev = -1.0
        for i, cut in enumerate(cuts):
            band = [ln for ln in rest if prev <= ln.y0 < cut]
            left = sorted([ln for ln in band if ln.x1 <= gap + 3], key=lambda ln: (ln.y0, ln.x0))
            right = sorted([ln for ln in band if ln.x1 > gap + 3], key=lambda ln: (ln.y0, ln.x0))
            if left:
                groups.append((left, min(ln.x0 for ln in left), gap, 1))
            if right:
                groups.append((right, gap, max(ln.x1 for ln in right), 2))
            if i < len(spans):
                groups.append(([spans[i]], spans[i].x0, spans[i].x1, 0))
                prev = spans[i].y1
            else:
                prev = cut
    blocks = []
    for glines, x0, x1, col in groups:
        for p in lines_to_paragraphs(glines, x0, x1):
            p.column = col
            blocks.append(p)
    for im in images:
        im.column = 0 if gap is None else (1 if im.x1 <= gap + 3 else 2 if im.x0 >= gap - 3 else 0)
        blocks.append(im)
    for t in tables:
        blocks.append(t)
    if gap is None:
        blocks.sort(key=lambda b: (round(b.y0), b.x0))
    else:
        # Mantener columnas: se ordena por franja y columna, respetando el orden calculado para el texto
        order = {id(b): i for i, b in enumerate(blocks)}
        blocks.sort(key=lambda b: (_band_of(b, groups), b.column if b.column else 0, b.y0, order[id(b)]))
    page.blocks = blocks
    xs0 = [b.x0 for b in blocks] or [72]
    xs1 = [b.x1 for b in blocks] or [width - 72]
    ys0 = [b.y0 for b in blocks] or [72]
    ys1 = [b.y1 for b in blocks] or [height - 72]
    page.margins = (max(18, min(xs0)), max(18, min(ys0)), max(18, width - max(xs1)), max(18, height - max(ys1)))
    return page


def _band_of(block, groups) -> int:
    # Índice de la franja vertical a la que pertenece un bloque (las franjas las delimitan los títulos
    # que cruzan el pasillo, que tienen columna 0).
    spans = [g[0][0].y0 for g in groups if g[3] == 0]
    return sum(1 for y in spans if block.y0 >= y)


def mark_headings(doc: Document) -> None:
    sizes = [r.size for p in doc.pages for b in p.blocks if isinstance(b, Paragraph)
             for r in b.runs for _ in range(len(r.text.strip()))]  # mediana ponderada por caracteres
    if not sizes:
        return
    body = median(sizes)
    levels = sorted({round(b.runs[0].size) for p in doc.pages for b in p.blocks
                     if isinstance(b, Paragraph) and b.runs and b.runs[0].size >= body * 1.25
                     and len(b.text) < 160}, reverse=True)
    for p in doc.pages:
        for b in p.blocks:
            if isinstance(b, Paragraph) and b.runs and round(b.runs[0].size) in levels[:3] and len(b.text) < 160:
                b.heading = levels.index(round(b.runs[0].size)) + 1
            elif isinstance(b, Paragraph) and len(b.text) < 90 and all(r.bold for r in b.runs if r.text.strip()) \
                    and b.runs and b.runs[0].size >= body * 1.05:
                b.heading = min(3, len(levels) + 1)


def is_scanned(page, n_chars: int) -> bool:
    """Página escaneada: casi sin texto y una imagen que ocupa la mayor parte."""
    import pypdfium2.raw as raw

    if n_chars > 20:
        return False
    w, h = page.get_size()
    for obj in page.get_objects(filter=(raw.FPDF_PAGEOBJ_IMAGE,), max_depth=3):
        x0, b, x1, t = obj.get_bounds()
        if (x1 - x0) * (t - b) > 0.5 * w * h:
            return True
    return n_chars == 0


def convert(path: str, mode: str = "auto", lang: str = "auto", progress=None, cancelled=None) -> Document:
    """mode: auto (OCR solo en páginas escaneadas) | text (nunca OCR) | ocr (OCR en todas)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    doc = Document()
    try:
        n = len(pdf)
        for i in range(n):
            if cancelled is not None and cancelled():
                break
            page = pdf[i]
            w, h = page.get_size()
            chars = page_chars(page, h)
            n_chars = sum(1 for c in chars if c.get("ch", "").strip())
            use_ocr = mode == "ocr" or (mode == "auto" and is_scanned(page, n_chars))
            if use_ocr and mode != "text":
                from aero.pdfconv import ocr

                lines, warn = ocr.ocr_page(page, lang)
                pg = build_page(w, h, lines, [], [], ocr=True)
                pg.warnings += [f"Página {i + 1}: {m}" for m in warn]
                pg.warnings.append(f"Página {i + 1}: escaneada; texto reconocido con OCR (sin negritas ni cursivas "
                                   "y con posibles errores de reconocimiento).")
            else:
                lines = chars_to_lines(chars)
                tables, lines = find_tables(page, h, lines)
                images = page_images(page, h)
                pg = build_page(w, h, lines, images, tables)
                if tables:
                    pg.warnings.append(f"Página {i + 1}: tabla reconstruida a partir de sus bordes; revisa las "
                                       "celdas combinadas.")
                if pg.columns > 1:
                    pg.warnings.append(f"Página {i + 1}: texto a dos columnas.")
                if any(not r.font for b in pg.blocks if isinstance(b, Paragraph) for r in b.runs):
                    pg.warnings.append(f"Página {i + 1}: algunas fuentes no tienen nombre; se usa la predeterminada.")
            doc.pages.append(pg)
            page.close()
            if progress is not None:
                progress(i + 1, n)
    finally:
        pdf.close()
    mark_headings(doc)
    return doc
