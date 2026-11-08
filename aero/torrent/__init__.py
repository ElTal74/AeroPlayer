"""BitTorrent en AERO Player: lectura de .torrent y motor propio de descarga.

Nada se descarga solo: la interfaz muestra primero el contenido y el usuario elige archivos, destino y pulsa
«Descargar». Los archivos descargados nunca se abren ni se ejecutan automáticamente.
"""

from __future__ import annotations

import threading

from aero.torrent.metainfo import Torrent, TorrentError, load, parse  # noqa: F401

_engine = None
_lock = threading.Lock()


def get_engine():
    """Motor compartido (se crea la primera vez que hace falta: hasta entonces no hay hilo ni conexiones)."""
    global _engine
    with _lock:
        if _engine is None:
            from aero.torrent.engine import Engine

            _engine = Engine()
        return _engine


def running():
    return _engine is not None


def shutdown(timeout: float = 5.0) -> None:
    global _engine
    with _lock:
        e, _engine = _engine, None
    if e is not None:
        e.stop(timeout)
