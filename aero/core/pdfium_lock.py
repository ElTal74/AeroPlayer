"""PDFium (pypdfium2) no admite usarse desde dos hilos a la vez: un único cerrojo para toda la aplicación.

Se vio en macOS: el conversor de PDF a editable y otra tarea con PDF a la vez → cierre en FPDF_LoadPage.
Las tareas en segundo plano esperan su turno (`with LOCK:`); el hilo de la interfaz solo espera un momento
(`try_lock`) para no quedarse congelado mientras dura una conversión larga.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

LOCK = threading.RLock()


@contextmanager
def try_lock(timeout: float = 0.3):
    """Como `with LOCK`, pero si PDFium está ocupado más de `timeout` segundos entrega False y no bloquea."""
    got = LOCK.acquire(timeout=timeout)
    try:
        yield got
    finally:
        if got:
            LOCK.release()
