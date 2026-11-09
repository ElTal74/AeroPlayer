"""Mantiene el equipo despierto mientras dura una tarea larga de desarrollo (sin tocar la configuración de energía).

Usa SetThreadExecutionState: mientras este proceso vive, Windows no suspende el equipo (la pantalla puede
apagarse). Al terminar el proceso, todo vuelve a ser como antes.

Uso: python tools/devrun.py run despierto -- .venv/Scripts/python.exe tools/keep_awake.py [horas]
"""

import ctypes
import sys
import time

ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_AWAYMODE_REQUIRED = 0x80000000, 0x00000001, 0x00000040
hours = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)
print(f"Equipo despierto durante {hours:g} h como máximo", flush=True)
end = time.time() + hours * 3600
while time.time() < end:
    time.sleep(60)
ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
