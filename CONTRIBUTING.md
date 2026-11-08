# Guía para contribuir a AERO Player

* Idioma del producto, comentarios y documentación: español.
* Entorno: `.venv` (Python 3.14, PySide6 6.12). Ejecutar: `.venv\Scripts\python -m aero [archivos]`.
* Antes de dar algo por terminado: `ruff check aero tests tools`, `python -m pytest` y, para cambios visuales,
  `python tools\visual_check.py <carpeta>`. Las dos últimas, siempre a través de `tools\devrun.py` (ver abajo).
* Rendimiento: comparar con `python tools\bench.py` y `docs/bench/despues.json`.

## Trabajar sin molestar a quien usa el ordenador (obligatorio)
* Pruebas, compilaciones, capturas y cualquier orden que abra ventanas se lanzan con
  `.venv\Scripts\python tools\devrun.py run <nombre> -- <orden…>` y se esperan con `devrun.py wait <nombre>`.
  * Van a un escritorio de Windows aparte («AeroDev»): sus ventanas no aparecen, no roban el foco ni el ratón.
  * Se ejecutan sin consola y con prioridad baja.
  * Los registros van a `.devrun/<nombre>.log`, el estado se ve con `devrun.py status` y una tarea se para con
    `devrun.py stop <nombre>`.
  * `tools/devmonitor.py` genera `.devrun/monitor.html` para que el usuario vea el progreso cuando quiera.
* Nunca capturar la pantalla entera del usuario. `visual_check.py` en el escritorio oculto guarda lo que dibuja
  cada ventana; la transparencia real solo con `--visible`, que usa el segundo monitor.
* Para probar el ejecutable compilado: `AERO_INSTANCE` y `AERO_DATA_DIR` propios (si no, los archivos van a la
  instancia que el usuario tenga abierta) y `PrintWindow` solo de esa ventana.
* No ocultar nada que necesite permiso: instalar software, cambiar el sistema o borrar datos se pregunta antes.

## Reglas que no hay que romper
* No importar NumPy antes de `aero/__init__.py` (limita OpenBLAS a 1 hilo; si no, +480 MB).
* Widgets que pintan todo su área (vídeo, visualizador) → `mark_opaque()`; si no, el cristal se repinta en
  cada fotograma.
* Nunca llamar a `QProcess.deleteLater()` dentro de su señal `finished` (doble liberación con PySide).
* Las tareas en hilos no deben capturar objetos Qt (`self`) en sus cierres.
* El vídeo usa una superficie nativa: los controles sobre vídeo van en la capa `MediaWindow.overlay`.
* El fondo de ventana nunca debe pintarse con alfa 0: los clics atravesarían la ventana.
* Asociaciones: nunca escribir `UserChoice`; Windows exige confirmación del usuario.
* Pruebas: usar la plataforma Qt nativa en Windows (`offscreen` no tiene fuentes).
