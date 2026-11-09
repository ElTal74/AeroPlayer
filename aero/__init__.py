"""AERO Player — reproductor multimedia, visor universal y conversor."""

import os as _os

# NumPy solo se usa para la FFT del visualizador (no necesita BLAS). Sin este límite, OpenBLAS reserva
# búferes para cada núcleo de la CPU: ~500 MB de memoria privada en un equipo de 16 hilos.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    _os.environ.setdefault(_var, "1")

__version__ = "1.3.0"
APP_NAME = "AERO Player"
APP_ID = "AeroPlayer"
AUTHOR = "David Seva Gonzalvez"
COPYRIGHT = f"© 2026 {AUTHOR}"
UPDATE_REPO = "ElTal74/AeroPlayer"     # GitHub: de aquí salen las versiones y las actualizaciones
