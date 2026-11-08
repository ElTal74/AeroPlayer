# BitTorrent en AERO Player (2.1.0)

## Motor

AERO Player usa un **motor propio en Python puro** (`aero/torrent/`), sin dependencias externas.

Se buscó primero un motor mantenido:

* `libtorrent` (rasterbar, BSD-3) no publica ruedas para Python 3.14 en Windows, y compilarlo exige Boost y OpenSSL.
* Las alternativas en Python puro (`torrentool`, `torf`, `bencode.py`…) solo leen o crean `.torrent`: no descargan.
* Integrar `aria2c` o un cliente externo obligaría a distribuir y lanzar otro programa con su propia red.

Un motor propio, pequeño y comprobado de punta a punta, es lo más seguro y controlable para este alcance.

## Qué hace

| Función | Detalle |
|---|---|
| Leer `.torrent` | Bencode completo; v1 e híbridos; nombre, tamaño, árbol de archivos, piezas, trackers, comentario, programa y fecha de creación, privado. Los v2 puros se rechazan con un mensaje claro. |
| Rutas seguras | Se quitan `..`, unidades, rutas absolutas, caracteres no válidos y nombres reservados de Windows (`CON`, `NUL`…). Un torrent no puede escribir fuera de su carpeta. |
| Trackers | HTTP/HTTPS (BEP 3, lista compacta BEP 23) y UDP (BEP 15); reanuncio periódico; aviso de fin. |
| Pares | Protocolo BEP 3: saludo, campo de bits, `have`, interés, choke/unchoke, bloques de 16 KiB con 12 peticiones en vuelo por par, hasta 40 pares. Piezas más raras primero y modo final. |
| Integridad | Cada pieza se comprueba con **SHA-1** antes de escribirse. Una pieza dañada se descarta y se vuelve a pedir. |
| Selección | Solo se escriben los archivos marcados (las piezas compartidas con otros archivos se descargan pero solo se guarda la parte elegida). |
| Incompletos | Mientras no están completos se llaman `nombre.aeropart`; al verificarse todas sus piezas se renombran. Si ya existe un archivo con ese nombre se crea `nombre (2)`: **nunca se sobrescribe nada**. |
| Pausar / reanudar | Pausar cierra las conexiones; reanudar vuelve a comprobar lo que hay en el disco. Volver a abrir el `.torrent` con la misma carpeta (también tras cerrar AERO) continúa donde se quedó. |
| Cancelar | Pide confirmación y borra **solo** los `.aeropart` de esa descarga; lo ya completado se queda. |
| Progreso | Estado, porcentaje, bytes, velocidad (últimos 5 s), tiempo restante, pares conectados y conocidos; también en el centro de tareas. |
| Errores | Tracker inaccesible, sin pares, sin trackers, disco lleno (se comprueba antes de empezar), carpeta no disponible: se muestran en la descarga, no la bloquean ni cierran la aplicación. |

Todo corre en un bucle `asyncio` en su propio hilo; la interfaz solo lee instantáneas cada 0,5 s. La red nunca
bloquea la ventana.

## Seguridad y privacidad

* **Nada se descarga solo.** Abrir un `.torrent` (desde Archivos, el Explorador de Windows o arrastrándolo) muestra
  su contenido; la descarga empieza únicamente al pulsar «Descargar» tras elegir archivos y carpeta.
* **Nada se ejecuta.** AERO Player no abre ni ejecuta nada de lo descargado; al terminar solo ofrece abrir la
  carpeta. Si el torrent contiene programas o scripts se avisa antes de empezar.
* **Se puede desactivar del todo**: Ajustes › Descargas BitTorrent › «Permitir descargas BitTorrent». Desactivado,
  el motor no existe (ni hilo ni conexiones) y las descargas en curso se detienen.
* **Sin conexiones ocultas ni en segundo plano**: el motor solo se crea al empezar una descarga y se detiene al
  cerrar AERO Player. No hay DHT, PEX, LSD ni UPnP, y **no se abre ningún puerto** (no aparece el aviso del
  cortafuegos). Solo se conecta a los trackers del propio torrent y a los pares que estos devuelven.
* El diálogo recuerda que la dirección IP es visible para los demás participantes y que solo debe descargarse
  contenido que se tenga derecho a obtener.

## Limitaciones conocidas

* **Sin enlaces magnet ni DHT**: un torrent sin trackers (o con trackers caídos) no encontrará pares. Se avisa.
* **Sin conexiones entrantes**: solo conectamos nosotros a los pares. Con pocas semillas que tampoco acepten
  conexiones, la descarga puede ser lenta o no avanzar.
* Por cortesía se envían bloques ya verificados a los pares a los que estamos conectados, pero AERO Player no
  sigue compartiendo al terminar (no actúa como semilla).
* Las descargas no se guardan entre sesiones: tras cerrar AERO, se continúa volviendo a abrir el `.torrent` con la
  misma carpeta (se verifica lo que ya hay y solo se descarga lo que falta).
* Torrents solo v2 (BEP 52) no se descargan.

## Pruebas

`tests/test_v21.py` monta un enjambre local en `127.0.0.1` (tracker HTTP, tracker UDP y semilla) y comprueba:
descarga real verificada por SHA-1, selección de archivos, pausar y reanudar, reanudar desde el disco, cancelar
(sin restos), datos corruptos que nunca llegan al disco, tracker caído, torrent sin trackers, desactivación desde
Ajustes y que abrir no descarga.
