"""Cálculo del tamaño de ventana según el contenido (imágenes y vídeos) y el monitor disponible."""

from __future__ import annotations


def fit_window(content_w: float, content_h: float, avail_w: float, avail_h: float, *, max_frac: float = 0.86,
               min_w: float = 420, min_h: float = 300, upscale: bool = False) -> tuple[int, int, float]:
    """Devuelve (ancho, alto, escala del contenido).

    * Nunca supera `max_frac` del área disponible del monitor.
    * Mantiene la proporción del contenido (sin deformar).
    * Sin `upscale`, un contenido pequeño se muestra a su tamaño real (la ventana crece hasta el mínimo y el
      contenido queda centrado); con `upscale` (vídeo), se amplía lo justo para alcanzar el tamaño mínimo.
    """
    if content_w <= 0 or content_h <= 0:
        return int(min(avail_w * 0.6, 960)), int(min(avail_h * 0.6, 640)), 1.0
    max_w, max_h = avail_w * max_frac, avail_h * max_frac
    # Nunca se amplía por encima del tamaño real salvo para alcanzar el mínimo (vídeos diminutos).
    scale = min(max_w / content_w, max_h / content_h, 1.0)
    w, h = content_w * scale, content_h * scale
    if upscale and (w < min_w or h < min_h):
        grow = min(max(min_w / w, min_h / h), max_w / w, max_h / h)
        scale *= grow
        w, h = content_w * scale, content_h * scale
        return int(round(w)), int(round(h)), scale
    return int(round(max(w, min(min_w, max_w)))), int(round(max(h, min(min_h, max_h)))), scale


def keep_aspect(rect: tuple[int, int, int, int], edge: int, aspect: float) -> tuple[int, int, int, int]:
    """Ajusta un rectángulo (izq, arr, der, abj) durante WM_SIZING para mantener la proporción."""
    left, top, right, bottom = rect
    w, h = right - left, bottom - top
    if aspect <= 0:
        return rect
    # WMSZ: 1 izq, 2 der, 3 arr, 4 arr-izq, 5 arr-der, 6 abj, 7 abj-izq, 8 abj-der
    if edge in (1, 2, 4, 5, 7, 8):
        nh = round(w / aspect)
        if edge in (4, 5):
            top = bottom - nh
        else:
            bottom = top + nh
    else:
        nw = round(h * aspect)
        right = left + nw
    return left, top, right, bottom
