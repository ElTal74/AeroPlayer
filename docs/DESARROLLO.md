# Desarrollar AERO Player sin molestar a quien usa el ordenador

Desde 2.2, todo lo que abre ventanas o tarda (pruebas, compilación, capturas, ejecutables de prueba) pasa por
`tools/devrun.py`. Así puedes seguir usando Windows con normalidad mientras se trabaja en AERO Player.

## Cómo funciona

* **Escritorio aparte.** Las tareas se lanzan en un escritorio de Windows propio, «AeroDev», creado con
  `CreateDesktop`. Es el mismo mecanismo que usa Windows para la pantalla de bloqueo.
  * Las ventanas que abren las pruebas, Qt o PyInstaller existen y se dibujan, pero en un escritorio que nadie ve.
  * No aparecen encima de tus aplicaciones, no roban el foco y no capturan el ratón ni el teclado.
  * No necesita permisos de administrador ni cambia nada del sistema. El escritorio desaparece cuando ya no lo usa
    ninguna tarea.
* **Sin consolas.** Las tareas se crean con `CREATE_NO_WINDOW` y prioridad baja (`BELOW_NORMAL`), así que el equipo
  sigue respondiendo.
* **Registros y estado.**
  * Cada tarea escribe en `.devrun/<nombre>.log`.
  * Su estado (orden, PID, inicio, fin y código de salida) va a `.devrun/<nombre>.json`.
  * Un vigilante sin ventana lanza la tarea y anota cómo terminó, sin perder el código de salida aunque acabe al
    instante.
* **Detener.** `devrun.py stop <nombre>` termina la tarea y todos sus procesos hijos, sin dejar nada colgado.

## Órdenes

```bash
.venv\Scripts\python tools\devrun.py run pruebas -- .venv\Scripts\python.exe -m pytest -q
```

```bash
.venv\Scripts\python tools\devrun.py status
```

```bash
.venv\Scripts\python tools\devrun.py log pruebas 40
```

```bash
.venv\Scripts\python tools\devrun.py stop pruebas
```

```bash
.venv\Scripts\python tools\devmonitor.py --open
```

`devmonitor.py` escribe `.devrun/monitor.html`, una página local que se recarga cada 5 s con el estado y las últimas
líneas de cada tarea. Solo se abre si se lo pides con `--open`; con `--watch` se mantiene al día en segundo plano.

## Lo que necesita la pantalla de verdad

* `visual_check.py`, lanzado con devrun, guarda lo que dibuja cada ventana. Sirve para revisar la interfaz, aunque
  no muestra el fondo real a través del cristal: Windows no deja copiar la imagen de un escritorio oculto.
* La comprobación de la transparencia real se pide con `devrun.py run … --visible`.
  * Usa el **monitor secundario** si existe (aquí, `DISPLAY1`).
  * Sus ventanas se muestran sin activarse.
  * No cambia la resolución ni la disposición de las pantallas.
* `input_check.py`, que mueve el ratón real, solo se ejecuta si se pide expresamente.

## Lo que nunca se hace a escondidas

Instalar software, cambiar la configuración del sistema, tocar asociaciones de archivos o borrar datos siempre se
pregunta antes. Este sistema evita ventanas molestas, pero no se salta ninguna confirmación de seguridad.

## Medido en esta sesión

| Medida | Resultado |
|---|---|
| Batería completa en el escritorio oculto | Ninguna ventana visible; mismos resultados que en el escritorio normal |
| Capturas de `visual_check` en el escritorio oculto | 34 capturas, `ERRORS []` |
| Prueba del Explorador real (iconos) | En el escritorio oculto, con el Shell de Windows |
