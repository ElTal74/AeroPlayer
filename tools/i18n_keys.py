"""Claves de traducción del código, extraídas sin ejecutarlo (complemento de `i18n_check.py`).

Recoge:
* los textos literales pasados a `tr()` / `ntr()` (singular y plural),
* los de los componentes que traducen solos (`label`, `IconButton`, `section`, `_check`, `Collapsible`, `act`),
* las tablas de textos visibles marcadas con un comentario `# i18n` en la línea de su nombre
  (p. ej. `PRESETS = {...}  # i18n`): sus valores de texto también se traducen al mostrarse.

Uso:
    python tools/i18n_keys.py                 # resumen por idioma
    python tools/i18n_keys.py --missing en    # lista lo que falta en ese idioma
    python tools/i18n_keys.py --strict        # código de salida 1 si falta algo en algún idioma (publicar)
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "aero" / "i18n" / "locales"
SELF_TR = {"label": 0, "IconButton": 1, "section": 0, "_check": 1, "Collapsible": 0, "act": 1}
FULL = ("en", "zh-CN", "ru", "it", "de", "pt-BR")


def _strings(node) -> list[str]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def _visible(s: str) -> bool:
    t = s.strip()
    return len(t) > 1 and any(c.isalpha() for c in t) and not re.fullmatch(r"[\w.+/#:-]+", t) or \
        (len(t) > 1 and not t.isascii())


def collect() -> dict[str, str]:
    keys: dict[str, str] = {}
    for f in sorted((ROOT / "aero").rglob("*.py")):
        rel = str(f.relative_to(ROOT))
        if "i18n" in f.parts:
            continue
        src = f.read_text(encoding="utf-8")
        tree = ast.parse(src)
        marked = {i + 1 for i, ln in enumerate(src.splitlines()) if re.search(r"#\s*i18n\b", ln)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                if name in ("tr", "ntr"):
                    for a in node.args[:1 if name == "tr" else 1]:
                        if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value:
                            keys.setdefault(a.value, rel)
                elif name in SELF_TR:
                    i = SELF_TR[name]
                    if len(node.args) > i and isinstance(node.args[i], ast.Constant) and \
                            isinstance(node.args[i].value, str) and _visible(node.args[i].value):
                        keys.setdefault(node.args[i].value, rel)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.lineno in marked:
                value = node.value
                if isinstance(value, ast.Dict):
                    texts = [s for v in value.values for s in _strings(v)]
                else:
                    texts = _strings(value)
                for s in texts:
                    if _visible(s):
                        keys.setdefault(s, rel)
        # Bucles sobre tuplas o listas de textos: `for t in ("Canciones", "Vídeos"…): tabs.addTab(tr(t))`
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
                translated = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr"
                                 and n.args and isinstance(n.args[0], ast.Name) for b in node.body for n in ast.walk(b))
                if not translated:
                    continue      # bucles de claves, atajos o nombres del registro: no son textos visibles
                for s in _strings(node.iter):
                    if _table_text(s) or (s[:1].isupper() and s.isalpha()):
                        keys.setdefault(s, rel)
        # Tablas de textos de primer nivel (y de clase): nombres de herramientas, perfiles, efectos, filtros…
        # Se muestran con tr(variable), así que sus textos visibles también tienen que estar en los catálogos.
        bodies = list(tree.body) + [n for c in tree.body if isinstance(c, ast.ClassDef) for n in c.body]
        for node in bodies:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            if not isinstance(node.value, (ast.Dict, ast.List, ast.Tuple, ast.Call)):
                continue
            for s in _strings(node.value):
                if _table_text(s):
                    keys.setdefault(s, rel)
    return keys


_SPANISH_HINT = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]|\b(de|la|el|los|las|en|con|sin|para|por|del|al|un|una|y|o)\b")


def _table_text(s: str) -> bool:
    """Texto visible en español dentro de una tabla (no claves, rutas, filtros de FFmpeg ni formatos)."""
    t = s.strip()
    if len(t) < 3 or not t[0].isupper() and not t[0] in "¿¡«" or "=" in t or "\\" in t or t.startswith(("http", "#")):
        return False
    if re.fullmatch(r"[A-Z0-9 ._:/+×%()-]+", t):
        return False      # siglas, formatos y medidas (MP4, H.264, 16:9)
    return bool(_SPANISH_HINT.search(t)) or (t.isalpha() and not t.isascii())


def main() -> int:
    keys = collect()
    strict = "--strict" in sys.argv
    missing_for = sys.argv[sys.argv.index("--missing") + 1] if "--missing" in sys.argv else ""
    bad = 0
    print(f"Claves en el código: {len(keys)}")
    for code in FULL:
        cat = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        miss = [k for k in keys if k not in cat]
        print(f"  {code}: {len(keys) - len(miss)}/{len(keys)}" + (f"  (faltan {len(miss)})" if miss else ""))
        bad += len(miss)
        if code == missing_for:
            for k in miss:
                print(f"    {keys[k]}: {k!r}")
    if strict and bad:
        print("Hay textos sin traducir: no se puede publicar esta versión.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
