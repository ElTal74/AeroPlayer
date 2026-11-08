"""Acceso al núcleo nativo en Rust (`aero_core`, ver native/aero_core y docs/RUST.md).

Si el módulo compilado no está (alguien ejecuta desde el código sin Rust) o se desactiva con
`AERO_NO_NATIVE=1`, todo sigue funcionando con la versión Python de siempre: mismas funciones, mismos
resultados (las pruebas de `tests/test_v22_rust.py` comparan las dos).
"""

from __future__ import annotations

import os

_mod = None
_tried = False


def core():
    """El módulo nativo ya configurado, o None si no se puede usar."""
    global _mod, _tried
    if _tried:
        return _mod
    _tried = True
    if os.environ.get("AERO_NO_NATIVE"):
        return None
    try:
        from aero import aero_core as m
    except ImportError:
        return None
    from aero.core import filetypes

    # Una sola fuente de verdad: las tablas de clasificación son las de filetypes.py
    m.configure(dict(filetypes._BY_EXT), [(off, bytes(sig), cat) for off, sig, cat in filetypes._MAGIC])
    _mod = m
    return m


def available() -> bool:
    return core() is not None


def reset() -> None:
    """Para las pruebas: vuelve a decidir si se usa el módulo nativo (p. ej. tras cambiar AERO_NO_NATIVE)."""
    global _mod, _tried
    _mod, _tried = None, False
