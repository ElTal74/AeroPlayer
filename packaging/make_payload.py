"""Empaqueta dist\\AeroPlayer para el instalador propio: payload.tar.xz + manifest.json en build\\payload.

Uso:  python packaging\\make_payload.py [carpeta_origen] [carpeta_destino]
"""

from __future__ import annotations

import json
import lzma
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from aero import __version__

    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "AeroPlayer"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "build" / "payload"
    if not (src / "AeroPlayer.exe").is_file():
        print(f"No se encuentra {src / 'AeroPlayer.exe'}: ejecuta antes PyInstaller.")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in src.rglob("*") if p.is_file())
    manifest = {"version": __version__,
                "files": [{"path": p.relative_to(src).as_posix(), "size": p.stat().st_size} for p in files]}
    archive = out / "payload.tar.xz"
    tmp = archive.with_suffix(".tmp")
    # El ejecutable primero: si algo fallara a medias, al menos se sabe qué versión había.
    files.sort(key=lambda p: (p.name != "AeroPlayer.exe", p.relative_to(src).as_posix()))
    with tarfile.open(tmp, "w:xz", preset=8 | lzma.PRESET_EXTREME if "--max" in sys.argv else 7) as tar:
        for p in files:
            tar.add(p, arcname=p.relative_to(src).as_posix(), recursive=False)
    tmp.replace(archive)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    total = sum(f["size"] for f in manifest["files"])
    print(f"{len(files)} archivos, {total / 2**20:.0f} MB -> {archive.stat().st_size / 2**20:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
