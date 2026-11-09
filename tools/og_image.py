"""Imagen para las vistas previas al compartir la web (1200×630): website/assets/og.png.

Uso: python tools/og_image.py   (después de site_assets.py, que genera el logo y las capturas)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "website" / "assets"
W, H = 1200, 630


def font(size: int, bold: bool = False):
    names = ["segoeuib.ttf", "seguisb.ttf"] if bold else ["segoeui.ttf"]
    for n in names + ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> int:
    img = Image.new("RGB", (W, H))
    top, bottom = (24, 104, 214), (126, 214, 255)
    px = img.load()
    for y in range(H):
        t = y / (H - 1)
        c = tuple(int(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        for x in range(W):
            px[x, y] = c
    d = ImageDraw.Draw(img)
    d.ellipse((-200, 470, 1400, 1000), fill=(110, 200, 70))                 # colina
    shot = Image.open(ASSETS / "capturas" / "es" / "letra.webp").convert("RGBA")
    shot.thumbnail((700, 470))
    shadow = Image.new("RGBA", (shot.width + 40, shot.height + 40), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((20, 26, shot.width + 20, shot.height + 26), 18, fill=(0, 30, 70, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    x0, y0 = W - shot.width - 50, (H - shot.height) // 2
    img.paste(shadow, (x0 - 20, y0 - 20), shadow)
    img.paste(shot, (x0, y0), shot)
    logo = Image.open(ASSETS / "logo.png").convert("RGBA").resize((150, 150), Image.Resampling.LANCZOS)
    img.paste(logo, (60, 120), logo)
    d.text((60, 290), "AERO Player", font=font(64, True), fill="white")
    d.text((62, 372), "Windows · Linux · macOS", font=font(28), fill=(235, 248, 255))
    d.text((62, 418), "Gratis · libre · sin telemetría", font=font(28), fill=(235, 248, 255))
    out = ASSETS / "og.png"
    img.save(out, optimize=True)
    print(out, out.stat().st_size // 1024, "KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
