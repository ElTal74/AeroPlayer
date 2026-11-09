"""Punto de entrada del instalador (packaging/setup.spec).

`--update`: actualización automática desde AERO Player (sin asistente; conserva las opciones y los datos).
"""

import sys

from aero.installer.ui import main_install, main_update

if __name__ == "__main__":
    sys.exit(main_update() if "--update" in sys.argv[1:] else main_install())
