"""Ajustes de imagen y color con NumPy (no destructivos: se aplican al dibujar y al exportar).

Todos los valores van de −1 a 1 (0 = sin cambio), salvo `blur` y `sharpness` (0 a 1) y `grayscale`/`sepia`
(sí o no). Se trabaja en coma flotante sobre una copia; el original nunca se toca.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

NEUTRAL = {"exposure": 0.0, "brightness": 0.0, "contrast": 0.0, "highlights": 0.0, "shadows": 0.0,
           "saturation": 0.0, "temperature": 0.0, "tint": 0.0, "sharpness": 0.0, "blur": 0.0,
           "grayscale": False, "sepia": False, "vignette": 0.0}

LABELS = {"exposure": "Exposición", "brightness": "Brillo", "contrast": "Contraste", "highlights": "Iluminaciones",
          "shadows": "Sombras", "saturation": "Saturación", "temperature": "Temperatura", "tint": "Tinte",
          "sharpness": "Nitidez", "blur": "Desenfoque", "vignette": "Viñeta"}
SLIDERS = ["exposure", "brightness", "contrast", "highlights", "shadows", "saturation", "temperature", "tint",
           "sharpness", "blur", "vignette"]
POSITIVE_ONLY = {"sharpness", "blur", "vignette"}

# Filtros prediseñados: son puntos de partida; después cada valor se puede seguir ajustando.
PRESETS: dict[str, dict] = {
    "Original": {},
    "Vívido": {"contrast": 0.18, "saturation": 0.35, "shadows": 0.1},
    "Cálido": {"temperature": 0.45, "saturation": 0.1, "highlights": -0.1},
    "Frío": {"temperature": -0.45, "tint": -0.05, "contrast": 0.08},
    "Suave": {"contrast": -0.2, "highlights": -0.2, "shadows": 0.2, "saturation": -0.1},
    "Dramático": {"contrast": 0.4, "shadows": -0.25, "saturation": -0.15, "vignette": 0.45},
    "Blanco y negro": {"grayscale": True, "contrast": 0.15},
    "Sepia": {"sepia": True, "contrast": 0.05, "vignette": 0.25},
    "Retro": {"temperature": 0.3, "contrast": -0.12, "saturation": -0.25, "vignette": 0.35, "tint": 0.08},
}


def is_neutral(a: dict) -> bool:
    return all(a.get(k, v) == v for k, v in NEUTRAL.items())


def to_array(img: QImage) -> np.ndarray:
    """Copia RGBA8888 (sin premultiplicar) como float32 0–1, forma (alto, ancho, 4)."""
    im = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h, bpl = im.width(), im.height(), im.bytesPerLine()
    arr = np.frombuffer(im.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)[:, :w * 4]
    return arr.reshape(h, w, 4).astype(np.float32) / 255.0


def from_array(a: np.ndarray) -> QImage:
    a8 = (np.clip(a, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    h, w = a8.shape[:2]
    a8 = np.ascontiguousarray(a8)
    img = QImage(a8.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    return img.copy()  # se desprende del búfer de NumPy


def box_blur(x: np.ndarray, r: int) -> np.ndarray:
    """Desenfoque de caja separable con sumas acumuladas: O(píxeles), independiente del radio."""
    if r < 1:
        return x
    out = x
    for axis in (0, 1):
        pad = [(0, 0)] * out.ndim
        pad[axis] = (r + 1, r)
        p = np.pad(out, pad, mode="edge")
        c = np.cumsum(p, axis=axis, dtype=np.float32)
        hi = np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis)
        lo = np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)
        out = (hi - lo) / (2 * r + 1)
    return out


def apply(img: QImage, a: dict, scale: float = 1.0) -> QImage:
    """Aplica los ajustes a una imagen. `scale` adapta los radios a una vista previa reducida."""
    if is_neutral(a):
        return img
    x = to_array(img)
    rgb, alpha = x[..., :3], x[..., 3:4]
    g = lambda k: float(a.get(k, 0.0) or 0.0)  # noqa: E731
    if g("exposure"):
        rgb = rgb * (2.0 ** (g("exposure") * 2.0))
    if g("brightness"):
        rgb = rgb + g("brightness") * 0.3
    if g("contrast"):
        rgb = (rgb - 0.5) * (1.0 + g("contrast")) + 0.5
    if g("shadows") or g("highlights"):
        lum = np.clip(rgb @ np.array([0.299, 0.587, 0.114], np.float32), 0, 1)[..., None]
        if g("shadows"):
            rgb = rgb + g("shadows") * 0.35 * (1.0 - lum) ** 2
        if g("highlights"):
            rgb = rgb + g("highlights") * 0.35 * lum ** 2
    if g("temperature"):
        # Balance de blancos: ganancia por canal (cálido = más rojo, menos azul), como en un revelador RAW.
        t = g("temperature")
        rgb = rgb * np.array([1.0 + 0.22 * t, 1.0 + 0.04 * t, 1.0 - 0.30 * t], np.float32)             + np.array([0.03 * t, 0.0, -0.03 * t], np.float32)
    if g("tint"):
        rgb = rgb + np.array([g("tint") * 0.05, -g("tint") * 0.10, g("tint") * 0.05], np.float32)
    if g("saturation") or a.get("grayscale") or a.get("sepia"):
        gray = (rgb @ np.array([0.299, 0.587, 0.114], np.float32))[..., None]
        if a.get("grayscale") or a.get("sepia"):
            rgb = np.repeat(gray, 3, axis=2)
            if a.get("sepia"):
                rgb = rgb * np.array([1.07, 0.88, 0.66], np.float32) + np.array([0.04, 0.02, 0.0], np.float32)
        if g("saturation"):
            rgb = gray + (rgb - gray) * (1.0 + g("saturation"))
    if g("blur"):
        r = max(1, int(round(g("blur") * 18 * scale)))
        rgb = box_blur(box_blur(rgb, r), r)
    if g("sharpness"):
        r = max(1, int(round(1.5 * scale)))
        soft = box_blur(rgb, r)
        rgb = rgb + g("sharpness") * 1.6 * (rgb - soft)
    if g("vignette"):
        h, w = rgb.shape[:2]
        yy, xx = np.ogrid[:h, :w]
        d = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
        rgb = rgb * (1.0 - g("vignette") * 0.55 * np.clip(d - 0.35, 0, 1.5)[..., None].astype(np.float32))
    return from_array(np.concatenate([np.clip(rgb, 0, 1), alpha], axis=2))
