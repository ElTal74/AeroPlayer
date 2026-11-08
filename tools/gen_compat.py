"""Genera docs/COMPATIBILIDAD.md a partir del código (aero.core.compat)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aero.core.compat import markdown  # noqa: E402

(ROOT / "docs" / "COMPATIBILIDAD.md").write_text(markdown(), encoding="utf-8")
print("docs/COMPATIBILIDAD.md actualizado")
