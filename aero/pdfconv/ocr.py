"""OCR con el reconocedor integrado en Windows (Windows.Media.Ocr) a través de `winrt`.

No se distribuyen modelos: los idiomas disponibles son los paquetes de idioma con OCR instalados en Windows
(Configuración › Hora e idioma). Se ejecuta en un hilo de trabajo y solo cuando se pide.
El reconocedor no informa de negritas, cursivas ni fuentes: se avisa de ello en el resultado.
"""

from __future__ import annotations

import asyncio

from aero.pdfconv.model import Line, Run

DPI = 300


def available_languages() -> list[tuple[str, str]]:
    """[(etiqueta, nombre)] de los idiomas de OCR instalados en Windows."""
    try:
        from winrt.windows.media.ocr import OcrEngine

        return [(lang.language_tag, lang.display_name) for lang in OcrEngine.available_recognizer_languages]
    except Exception:  # noqa: BLE001
        return []


def _engine(lang: str):
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine

    if lang and lang != "auto":
        language = Language(lang)
        if OcrEngine.is_language_supported(language):
            return OcrEngine.try_create_from_language(language)
    return OcrEngine.try_create_from_user_profile_languages()


def recognize(gray_bytes: bytes, width: int, height: int, lang: str = "auto"):
    """Reconoce una imagen en escala de grises. Devuelve [(texto_línea, [(palabra, x, y, w, h), …])]."""
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.storage.streams import DataWriter

    engine = _engine(lang)
    if engine is None:
        raise RuntimeError("No hay ningún idioma de OCR instalado en Windows. Añádelo en Configuración › Hora e "
                           "idioma › Idioma y región.")
    writer = DataWriter()
    writer.write_bytes(gray_bytes)
    bmp = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.GRAY8, width, height)

    async def run():
        return await engine.recognize_async(bmp)

    result = asyncio.run(run())
    out = []
    for line in result.lines:
        words = [(w.text, w.bounding_rect.x, w.bounding_rect.y, w.bounding_rect.width, w.bounding_rect.height)
                 for w in line.words]
        out.append((line.text, words))
    return out


def ocr_image(pil, lang: str = "auto", dpi: float = DPI) -> list[Line]:
    """OCR de una imagen PIL; coordenadas devueltas en puntos (1/72 de pulgada)."""
    from winrt.windows.media.ocr import OcrEngine

    gray = pil.convert("L")
    limit = int(OcrEngine.max_image_dimension or 10000)
    k = 1.0
    if max(gray.size) > limit:
        k = limit / max(gray.size)
        gray = gray.resize((int(gray.width * k), int(gray.height * k)))
    res = recognize(gray.tobytes(), gray.width, gray.height, lang)
    f = 72.0 / (dpi * k)
    lines: list[Line] = []
    for text, words in res:
        if not words:
            continue
        x0 = min(w[1] for w in words) * f
        y0 = min(w[2] for w in words) * f
        x1 = max(w[1] + w[3] for w in words) * f
        y1 = max(w[2] + w[4] for w in words) * f
        hs = sorted(w[4] for w in words)
        size = round(hs[len(hs) // 2] * f * 1.35 * 2) / 2   # caja de palabra ≈ 0,74 del cuerpo de letra (medido)
        lines.append(Line([Run(text, max(6.0, size))], x0, y0, x1, y1))
    return lines


def ocr_page(page, lang: str = "auto") -> tuple[list[Line], list[str]]:
    pil = page.render(scale=DPI / 72.0, grayscale=True).to_pil()
    lines = ocr_image(pil, lang)
    warn = [] if lines else ["no se reconoció texto en la imagen."]
    return lines, warn
