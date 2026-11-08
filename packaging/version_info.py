"""Genera el recurso de versión de Windows de los ejecutables a partir de `aero.__version__` (una sola fuente)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('0C0A04B0', [
      StringStruct('CompanyName', 'Proyecto AERO Player'),
      StringStruct('FileDescription', '{desc}'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', '{internal}'),
      StringStruct('LegalCopyright', 'GPL-3.0-or-later'),
      StringStruct('OriginalFilename', '{filename}'),
      StringStruct('ProductName', 'AERO Player'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [0x0C0A, 1200])])
  ]
)
"""


def app_version() -> str:
    text = (ROOT / "aero" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def write(path: Path, desc: str, internal: str, filename: str) -> Path:
    ver = app_version()
    nums = [int(x) for x in re.findall(r"\d+", ver)[:3]] + [0]
    tup = tuple((nums + [0, 0, 0])[:4])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(tup=tup, desc=desc, ver=ver, internal=internal, filename=filename),
                    encoding="utf-8")
    return path
