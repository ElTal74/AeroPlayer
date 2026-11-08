# Sistema de iconos AERO por categoría (2.1.0)

Cada archivo recibe el icono de su **categoría**, no de su extensión: todos los vídeos comparten el icono de
vídeo, todas las imágenes el de imagen, etc. Los nombres y las extensiones siguen visibles junto al icono y en la
columna «Tipo» («Vídeo · MKV»).

## Categorías

Carpeta, vídeo, audio, imagen, documento, hoja de cálculo, presentación, PDF, archivo comprimido, aplicación,
instalador, acceso directo, sistema y configuración, fuente, código, torrent, imagen de disco y desconocido.

* La clasificación está centralizada en `aero/core/filetypes.py` (`by_extension`, `sniff`, `category_of`).
* Se clasifica por extensión, con una búsqueda en un diccionario y sin tocar el disco.
* Si la extensión no decide, se miran como mucho 64 bytes de firma: PNG, PDF, ZIP, ejecutables, fuentes,
  `CD001`, texto plano…
* Casos especiales:
  * `.ts` cuenta como vídeo (es mucho más frecuente que TypeScript);
  * `.bin` cuenta como imagen de disco;
  * las listas `.m3u` cuentan como audio.

## Diseño

* Dibujados por código en `aero/ui/file_icons.py`. Son vectoriales (QPainter en una caja de 100 unidades) y
  nítidos a cualquier tamaño y escala de pantalla.
* Estilo Frutiger Aero, como una familia:
  * cristal con degradado, banda de agua ondulada y brillo de burbuja;
  * borde suave y sombra ligera;
  * formas redondeadas y colores de naturaleza (agua, hierba, cielo, ámbar).
* Hay cuatro formas base:
  * **burbuja con emblema** para el contenido (vídeo, audio, imagen, apps, sistema, fuente, torrent);
  * **hoja con esquina doblada y etiqueta de color** para los documentos (documento, hoja, presentación, PDF, código,
    desconocido);
  * **carpeta de cristal**;
  * **caja con cremallera** para los comprimidos;
  * a ellas se suma el **disco iridiscente** para las imágenes de disco.
* Variantes clara y oscura según el tema.
* En aplicaciones y accesos directos se superpone el icono real del programa, para distinguir uno de otro. Los
  accesos directos llevan además su flecha y los scripts de Internet el aviso «!».

## En el Explorador de Windows (2.2)

* Archivos: `packaging/icons/*.ico`, 18 categorías con 10 tamaños cada una, de 16 a 256 px, en PNG.
  * Se generan con `python -m aero.ui.icon_export` a partir del mismo dibujo que se ve dentro de la aplicación.
  * En la instalación van a `_internal\icons`, una ruta estable que no depende de archivos del proyecto.
* **Tipos que abre AERO Player.** Cada ProgID tiene el `DefaultIcon` de su categoría:

  | ProgID | Icono |
  |---|---|
  | `AeroPlayer.Video` | vídeo |
  | `AeroPlayer.Audio` | audio |
  | `AeroPlayer.Image` | imagen |
  | `AeroPlayer.Pdf` | PDF |
  | `AeroPlayer.Document` | documento |
  | `AeroPlayer.Sheet` | hoja |
  | `AeroPlayer.Slides` | presentación |
  | `AeroPlayer.Archive` | comprimido |
  | `AeroPlayer.Disc` | disco |
  | `AeroPlayer.Torrent` | torrent |

  Se aplica al registrar AERO Player (Ajustes › Archivos y asociaciones) y cuando eliges AERO como programa
  predeterminado en la Configuración de Windows.
* **Tipos que abre otro programa.** Windows dibuja el icono del programa elegido, así que para verlos con el icono
  AERO hay que activar «Iconos AERO también en los tipos que abren otros programas»:
  * Escribe una capa por usuario, `HKCU\Software\Classes\<ProgID>\DefaultIcon`, que Windows antepone a la del
    programa.
  * No cambia qué programa abre el archivo ni escribe `UserChoice`, y no toca HKLM.
  * Pide confirmación, guarda el valor anterior en `HKCU\Software\AeroPlayer\IconBackup` y «Restaurar iconos
    originales» lo devuelve tal cual. Si después cambiaste un icono a mano, se respeta.
  * Se vuelve a aplicar al iniciar AERO por si cambiaste de programa predeterminado.
* **Qué conserva su icono a propósito:**
  * programas (`.exe`), accesos directos y carpetas, porque Windows muestra el icono propio de cada programa o
    destino y eso identifica qué se va a ejecutar;
  * scripts que se ejecutan con doble clic (`.bat`, `.cmd`, `.ps1`, `.vbs`, `.js`…) y archivos de sistema (`.dll`,
    `.ini`, `.reg`…);
  * ProgIDs compartidos por categorías distintas y los genéricos `Applications\programa.exe`.
* **Caché de iconos:** se avisa al Explorador (`SHChangeNotify`) y se refresca la caché del usuario
  (`ie4uinit -show`), sin reiniciar. Como todo queda en el registro, los iconos se conservan después de reiniciar
  Windows.
* **Comprobación con el Shell real:**
  * `tests/test_v22.py` crea un tipo de prueba, aplica, mide lo que dibuja el Shell en un proceso nuevo, restaura y
    lo borra todo.
  * `tools/explorer_icon_sheet.py` genera `docs/capturas/v22/explorador_iconos.png`: los 18 iconos tal como los
    dibuja el Explorador, en tema claro y oscuro.
* Los cuadros de diálogo de abrir y guardar son los de Windows, así que muestran los mismos iconos que el
  Explorador.

## Rendimiento

* Hay una caché de 256 entradas (categoría × tamaño × escala × tema). Una carpeta de miles de archivos dibuja cada
  icono una sola vez.
* Ya no se pide a Windows el icono ni el nombre de tipo de cada archivo. Solo se hace para aplicaciones y accesos
  directos, en segundo plano.
* La prueba `test_folder_with_thousands_of_files_lists_and_paints_fast` lista 3000 archivos de 17 tipos (< 2 s) y
  pinta la cuadrícula y la lista (< 1,5 s cada una).

## Dónde se usan

* El explorador de Archivos: cuadrícula, lista con detalles, carpetas y comprimidos abiertos.
* La búsqueda global (Ctrl+K).
* Los recientes e historial de Inicio.
* La cabecera del visor.
* El diálogo de torrents y la ventana de descargas.
