"""Matriz de compatibilidad: qué abre AERO Player, con qué módulo, qué puede hacer y si se ofrece como
aplicación predeterminada. Se genera a partir del código (formatos, asociaciones y editores), no a mano:
`python tools/gen_compat.py` escribe `docs/COMPATIBILIDAD.md`.
"""

from __future__ import annotations

from dataclasses import dataclass

from aero.core import associations
from aero.core.formats import ARCHIVE, AUDIO, DOCUMENT, IMAGE, NEEDS_OFFICE, PDF, TEXT, VIDEO


@dataclass
class Row:
    ext: str
    kind: str
    module: str
    capability: str
    status: str
    default_app: bool


def _assoc() -> dict[str, str]:
    return {e: c.label for c in associations.CATEGORIES for e in c.exts}


def matrix() -> list[Row]:
    reg = _assoc()
    rows: list[Row] = []

    def add(exts, kind, module, cap, status="Completo"):
        for e in sorted(exts):
            rows.append(Row(e, kind, module, cap, status, e in reg))

    add(AUDIO, "Audio", "Reproductor · Quick Look", "Reproducir, cola, visualizador, etiquetas, convertir")
    add(VIDEO, "Vídeo", "Visor minimalista · Quick Look · Editor de vídeo",
        "Reproducir, subtítulos, pistas, editar y exportar, convertir")
    add(IMAGE - {".psd", ".dds", ".icns", ".tga", ".ppm", ".pgm", ".pbm"}, "Imagen",
        "Visor · Quick Look · Editor de imágenes", "Ver, editar (capas, color, dibujo), exportar, convertir")
    add({".psd", ".dds", ".icns", ".tga", ".ppm", ".pgm", ".pbm"}, "Imagen", "Visor · Editor de imágenes",
        "Ver (capa combinada), editar como imagen plana", "Parcial")
    add(PDF, "PDF", "Visor PDF · PDF a editable", "Ver, buscar, convertir a DOCX/ODT/TXT con OCR")
    add({".docx", ".odt", ".md", ".markdown"}, "Documento", "Editor de documentos",
        "Editar y guardar (formato, listas, tablas, imágenes), exportar a PDF")
    add({".rtf"}, "Documento", "Editor de documentos", "Abrir el texto; guardar como DOCX/ODT", "Parcial")
    add({".html", ".htm", ".epub"} & DOCUMENT, "Documento", "Visor", "Ver", "Solo lectura")
    add({".txt"}, "Texto", "Visor · Editor de documentos", "Ver y editar")
    add(TEXT - {".txt"}, "Texto", "Visor de texto", "Ver con resaltado básico", "Solo lectura")
    add({".xlsx", ".xlsm"}, "Hoja de cálculo", "Editor de hojas", "Editar conservando fórmulas y formato, gráficos")
    add({".xls", ".xlsb", ".ods"}, "Hoja de cálculo", "Editor de hojas", "Abrir valores; guardar como XLSX/ODS",
        "Parcial")
    add({".csv", ".tsv"}, "Hoja de cálculo", "Editor de hojas", "Editar y guardar")
    add({".pptx", ".ppsx"}, "Presentación", "Editor de presentaciones",
        "Editar diapositivas, texto, imágenes, formas; presentar; PDF")
    add({".odp"}, "Presentación", "Editor de presentaciones", "Editar convirtiendo con LibreOffice",
        "Requiere LibreOffice")
    add(NEEDS_OFFICE, "Office antiguo", "Visor (vía LibreOffice)", "Ver", "Requiere LibreOffice")
    add({".zip", ".cbz", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".tbz2", ".txz"}, "Comprimido",
        "Quick Look · Explorador", "Explorar y previsualizar sin extraer")
    add(ARCHIVE - {".zip", ".cbz", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".tbz2", ".txz"}, "Comprimido",
        "Quick Look · Explorador", "Explorar y previsualizar sin extraer (tar.exe de Windows)")
    add({".iso", ".img", ".bin", ".cue", ".nrg", ".mdf"}, "Imagen de disco", "Explorador · Extraer · Montar",
        "Explorar y extraer sin montar; montar ISO/IMG con Windows")
    add({".torrent"}, "Torrent", "Descargas BitTorrent", "Ver contenido, elegir archivos y descargar")
    add({".aerovid"}, "Proyecto", "Editor de vídeo", "Abrir y guardar proyectos")
    add({".aeroimg"}, "Proyecto", "Editor de imágenes", "Abrir y guardar proyectos")
    seen, out = set(), []
    for r in rows:
        if r.ext not in seen:
            seen.add(r.ext)
            out.append(r)
    return out


def markdown() -> str:
    lines = ["# Matriz de compatibilidad", "",
             "Generada con `python tools/gen_compat.py` a partir del código. «Predeterminado» indica que AERO "
             "Player se registra como aplicación capaz de abrir esa extensión (Abrir con y Aplicaciones "
             "predeterminadas). Elegirla como predeterminada lo decide siempre el usuario en Windows.", "",
             "| Extensión | Tipo | Módulo | Capacidad | Estado | Predeterminado |", "|---|---|---|---|---|---|"]
    for r in matrix():
        lines.append(f"| `{r.ext}` | {r.kind} | {r.module} | {r.capability} | {r.status} | "
                     f"{'Sí' if r.default_app else '—'} |")
    return "\n".join(lines) + "\n"
