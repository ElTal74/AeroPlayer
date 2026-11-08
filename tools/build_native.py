"""Compila el núcleo nativo en Rust (native/aero_core) y lo deja como `aero/aero_core.pyd`.

Uso: python tools/build_native.py [--debug]
Necesita Rust (rustup, toolchain «stable-x86_64-pc-windows-msvc») y las Microsoft C++ Build Tools.
Sin ellos, AERO Player funciona igual con la versión Python (aero/core/native.py).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "native" / "aero_core"


def cargo() -> str | None:
    found = shutil.which("cargo")
    if found:
        return found
    home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")) / "bin" / "cargo.exe"
    return str(home) if home.exists() else None


def build(debug: bool = False) -> Path:
    exe = cargo()
    if not exe:
        raise SystemExit("No se encuentra cargo: instala Rust (rustup) para compilar el núcleo nativo.")
    cmd = [exe, "build", "--manifest-path", str(CRATE / "Cargo.toml")] + ([] if debug else ["--release"])
    env = dict(os.environ, PYO3_PYTHON=sys.executable)
    r = subprocess.run(cmd, cwd=CRATE, env=env)
    if r.returncode:
        raise SystemExit(r.returncode)
    dll = CRATE / "target" / ("debug" if debug else "release") / "aero_core.dll"
    out = ROOT / "aero" / "aero_core.pyd"
    shutil.copy2(dll, out)
    print(f"Núcleo nativo listo: {out} ({out.stat().st_size // 1024} KB)")
    return out


if __name__ == "__main__":
    build("--debug" in sys.argv)
