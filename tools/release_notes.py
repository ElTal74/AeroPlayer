"""Notas de una versión para GitHub: la sección de CHANGELOG.md de esa versión.

Uso: python tools/release_notes.py v1.1.0 notas.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(version)}(?![\d.]).*?$(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def main() -> int:
    version = sys.argv[1].lstrip("v")
    body = section(version) or f"AERO Player {version}"
    body += ("\n\n---\n**Instalador** (`setup.exe`): integración completa con Windows y actualizaciones con un clic.  \n"
             "**Portable** (`.zip`): sin instalar, pero no incluye el 100 % de las funciones. "
             "Comprueba las descargas con `SHA256SUMS.txt`.\n")
    Path(sys.argv[2]).write_text(body, encoding="utf-8")
    print(len(body), "caracteres")
    return 0


if __name__ == "__main__":
    sys.exit(main())
