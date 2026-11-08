"""Punto de entrada del instalador (packaging/setup.spec)."""

import sys

from aero.installer.ui import main_install

if __name__ == "__main__":
    sys.exit(main_install())
