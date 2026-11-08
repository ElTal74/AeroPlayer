"""Genera archivos de demostración libres de derechos en tests/media (requiere FFmpeg y requirements-dev).

Uso:  python tests/make_media.py
"""

from __future__ import annotations

import datetime
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "tests" / "media"


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def main() -> int:
    M.mkdir(parents=True, exist_ok=True)
    ff("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=8", "-f", "lavfi", "-i",
       "sine=frequency=330:duration=8", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
       str(M / "clip.mkv"))
    (M / "clip.srt").write_text("1\n00:00:00,500 --> 00:00:03,000\nHola, esto es un subtítulo\n\n"
                                "2\n00:00:03,500 --> 00:00:06,000\nSegunda línea <i>con cursiva</i>\n", encoding="utf-8")
    ff("-f", "lavfi", "-i", "color=c=0x1e7bff:s=600x600:d=1", "-frames:v", "1", str(M / "cover.png"))
    ff("-f", "lavfi", "-i", "aevalsrc=0.4*sin(2*PI*110*t)*(1+sin(2*PI*2*t))+0.2*sin(2*PI*880*t)*gt(mod(t\\,0.5)\\,0.25):d=20",
       "-i", str(M / "cover.png"), "-map", "0", "-map", "1", "-c:a", "flac", "-c:v", "png",
       "-disposition:v", "attached_pic", "-metadata", "title=Pulso Aero", "-metadata", "artist=Ensamble Cristal",
       "-metadata", "album=Burbujas", str(M / "pulso.flac"))
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-metadata", "title=Tono de prueba", str(M / "tone.mp3"))
    ff("-f", "lavfi", "-i", "testsrc=size=800x500", "-frames:v", "1", str(M / "foto.jpg"))
    (M / "roto.mp4").write_bytes(b"esto no es un video" * 100)
    (M / "notas.md").write_text("# Notas\n\n- uno\n- **dos**\n\n```py\nprint(1)\n```\n", encoding="utf-8")
    with zipfile.ZipFile(M / "pack.zip", "w") as z:
        z.write(M / "notas.md", "notas.md")
    try:
        import docx
        import openpyxl
        from pptx import Presentation
        from pptx.util import Inches
    except ImportError:
        print("Instala requirements-dev.txt para generar DOCX/XLSX/PPTX.")
        return 0
    d = docx.Document()
    d.add_heading("Informe de prueba AERO", 0)
    d.add_paragraph("Párrafo con acentos: canción, pingüino, ñandú.")
    d.add_picture(str(M / "foto.jpg"), width=docx.shared.Inches(3))
    d.save(M / "informe.docx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ventas"
    ws.append(["Mes", "Importe", "Fecha"])
    for i in range(1, 50):
        ws.append([f"Mes {i}", i * 12.5, datetime.date(2026, 1, 1) + datetime.timedelta(days=i)])
    wb.save(M / "datos.xlsx")
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Presentación AERO"
    s.placeholders[1].text = "Subtítulo de prueba"
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Con imagen"
    s2.shapes.add_picture(str(M / "foto.jpg"), Inches(1), Inches(2), width=Inches(5))
    prs.save(M / "diapos.pptx")
    from PySide6.QtGui import QGuiApplication, QPageSize, QPdfWriter, QTextDocument

    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    w = QPdfWriter(str(M / "doc.pdf"))
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    doc = QTextDocument()
    doc.setHtml("<h1>PDF de prueba</h1>" + "<p>Texto buscable cristal agua aire.</p>" * 60)
    doc.print_(w)
    print(f"Medios generados en {M}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
