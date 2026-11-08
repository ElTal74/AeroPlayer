"""Modelo intermedio de un documento reconstruido desde PDF (independiente del formato de salida)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Run:
    text: str
    size: float = 11.0          # puntos
    bold: bool = False
    italic: bool = False
    font: str = ""
    color: str = "#000000"


@dataclass
class Line:
    runs: list[Run]
    x0: float
    y0: float                   # arriba (coordenadas de página, origen arriba a la izquierda, puntos)
    x1: float
    y1: float

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    @property
    def size(self) -> float:
        sizes = [r.size for r in self.runs if r.text.strip()]
        return max(set(sizes), key=sizes.count) if sizes else 11.0


@dataclass
class Paragraph:
    runs: list[Run]
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    align: str = "left"         # left | center | right | justify
    heading: int = 0            # 0 = cuerpo; 1–3 = nivel de título
    column: int = 0

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class Image:
    png: bytes
    x0: float
    y0: float
    x1: float
    y1: float
    column: int = 0


@dataclass
class Table:
    rows: list[list[str]]
    x0: float
    y0: float
    x1: float
    y1: float
    column: int = 0


@dataclass
class Page:
    width: float
    height: float
    blocks: list = field(default_factory=list)   # Paragraph | Image | Table, en orden de lectura
    columns: int = 1
    ocr: bool = False
    margins: tuple[float, float, float, float] = (72, 72, 72, 72)   # izquierda, arriba, derecha, abajo
    warnings: list[str] = field(default_factory=list)


@dataclass
class Document:
    pages: list[Page] = field(default_factory=list)
    title: str = ""

    @property
    def warnings(self) -> list[str]:
        return [w for p in self.pages for w in p.warnings]
