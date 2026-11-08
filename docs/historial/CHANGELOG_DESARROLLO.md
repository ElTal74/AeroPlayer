# Historial de desarrollo (antes de la 1.0 pública)

Registro interno de las versiones de desarrollo (numeradas 1.0–2.2). La numeración pública empieza de nuevo en
**1.0.0** con todo lo que se describe aquí; ver `CHANGELOG.md`.

## 2.2.0 — 2026-11-08 · Iconos AERO en el Explorador, fotos en la ventana principal y desarrollo sin molestar

- **Iconos AERO en el Explorador de Windows** (`docs/ICONOS.md`).
  - Hay 18 iconos `.ico` (de 16 a 256 px) dibujados con el mismo código que dentro de la aplicación, e incluidos en
    la instalación.
  - Cada tipo que abre AERO lleva el icono de su categoría: vídeo, audio, imagen, PDF, documento, hoja,
    presentación, comprimido, **imagen de disco** y **torrent**. Las dos últimas tienen ahora su propio ProgID, y
    antes todos llevaban el icono del programa.
  - Opción para usar también los iconos AERO en los tipos que abre otro programa.
    - Nunca cambia qué programa abre el archivo ni escribe `UserChoice`.
    - Se activa solo con confirmación y guarda una copia de lo anterior.
    - «Restaurar iconos originales» lo deja exactamente como estaba.
    - Programas, scripts, accesos directos y archivos de sistema conservan su icono.
  - Se ha comprobado con el Shell real de Windows (antes, después y restaurado), y la caché de iconos se refresca
    sin reiniciar.
  - Categoría nueva **Instalador** (MSI, MSIX, APPX) con su icono, y detalles de césped en los iconos grandes.
- **Fotos en la ventana principal**: una foto abierta desde Windows va a la sección Visor, que ocupa toda la ventana
  y tiene anterior/siguiente, zoom con la rueda, arrastre, ajustar, 1:1, girar, **voltear en horizontal y en
  vertical**, tamaño y resolución, y editar. La vista rápida (Espacio) no cambia. El visor mínimo sigue disponible
  en Ajustes.
- **Desarrollo sin molestar** (`docs/DESARROLLO.md`): `tools/devrun.py` ejecuta pruebas, compilaciones y capturas en
  un escritorio de Windows aparte, sin consola, con prioridad baja, con registros y con opción de detener.
  `tools/devmonitor.py` muestra el estado en una página local.
- **Rust, fase R1**: el núcleo de archivos es nativo (`native/aero_core`, PyO3). Hace el listado y la clasificación,
  el tamaño de las carpetas y la búsqueda global sin el GIL, con resultados idénticos a la versión Python, que queda
  de respaldo.
  - Medido: búsqueda 2,9× más rápida, estadísticas 1,65× y listado 1,5×. La interfaz no se congela mientras tanto.
- **Rust, etiquetas de audio** (`lofty`, en paralelo en todos los núcleos): 30× más rápido; escanear la biblioteca,
  4× (2 000 canciones nuevas: 1,2 → 0,3 s). Además lee las etiquetas de WAV y AIFF que antes se perdían. WMA y
  vídeos siguen con mutagen.
- **Extraer ISO y ZIP con muchos archivos, 2,3× más rápido** (sin Rust: se quitaron llamadas repetidas al sistema).
  - Auditoría y fases siguientes en `docs/RUST.md`.
- **Rendimiento**: NumPy ya no se carga al abrir; el analizador de espectro se crea al primer uso. Importar la ventana
  principal baja de 614 a 420 ms.

## 2.1.0 — 2026-11-04 · Iconos AERO, imágenes de disco y BitTorrent; Spotify retirado

- **Spotify retirado por completo** (decisión y motivos en `docs/SPOTIFY.md`).
  - Sus límites hacen imposible una integración completa para cualquier usuario: modo de desarrollo con 5 usuarios
    y Premium del propietario, acceso ampliado solo para empresas grandes, y reproducción solo en la app oficial.
  - Se han quitado la pestaña, los botones, los menús, el código y las pruebas.
  - Al iniciar se borra solo su token cifrado.
- **Iconos AERO por categoría** (`docs/ICONOS.md`).
  - Hay 17 categorías: vídeo, audio, imagen, documento, hoja, presentación, PDF, comprimido, aplicación, acceso
    directo, sistema, fuente, código, torrent, disco, carpeta y desconocido.
  - Son dibujos vectoriales propios de cristal, agua y burbuja, en variante clara y oscura, con caché.
  - Se usan en el explorador (cuadrícula y lista), la búsqueda, los recientes, el visor y los torrents.
  - Todos los formatos de una categoría comparten icono.
  - La clasificación está centralizada, por extensión y, si hace falta, por firma.
  - El resumen de cada carpeta cuenta por categoría y aparece traducido.
- **Imágenes de disco** (`docs/DISCOS.md`): ISO, IMG, BIN/CUE, NRG, MDF y UDF.
  - Se exploran en Archivos como una carpeta.
  - Se pueden extraer lo seleccionado o todo, con progreso, cancelación sin restos y comprobación byte a byte.
  - «Montar en Windows» y «Desmontar» para ISO, IMG, VHD y VHDX, con las herramientas nativas y solo a petición.
  - Si Windows no da letra de unidad, la imagen se desconecta y se explica el motivo.
- **BitTorrent** (`docs/TORRENTS.md`), con un motor propio en Python puro.
  - Abrir un `.torrent` muestra su contenido: nombre, tamaño, árbol de archivos con casillas, trackers, avisos si hay
    programas o no hay trackers, y espacio libre.
  - Solo se descarga al pulsar «Descargar». Hay trackers HTTP y UDP, verificación SHA-1 de cada pieza y selección de
    archivos.
  - Los archivos incompletos llevan la extensión `.aeropart` y nunca se sobrescribe nada.
  - Se puede pausar, reanudar (también tras cerrar AERO) y cancelar.
  - La ventana «Descargas BitTorrent» y el centro de tareas muestran el progreso, la velocidad, el tamaño y el estado.
  - Se puede desactivar por completo en Ajustes.
  - No tiene DHT ni magnet, no abre ningún puerto y nunca ejecuta lo descargado.
- Explorador de comprimidos y discos traducido por completo:
  - el filtro, el orden, el resumen y los avisos del lector seguían en español con la interfaz en otro idioma;
  - los plurales salen bien en cada idioma;
  - el detector de pantallas comprueba ahora un ZIP y una ISO abiertos.
- Dependencia nueva: `pycdlib` 1.22.0 (LGPL-2.1). Se distribuye como archivos `.py` sustituibles.

## 2.0.1 — 2026-11-03 · Spotify conecta

- **Spotify**: el inicio de sesión fallaba con «redirect_uri: Not matching configuration» y AERO se quedaba
  esperando. Causa: AERO volvía a un puerto distinto en cada intento (p. ej. `127.0.0.1:61084`), que Spotify
  rechaza aunque su documentación diga que lo admite. Ahora usa siempre `http://127.0.0.1/callback` (y
  `http://127.0.0.1:8888/callback` si el puerto 80 está ocupado). La pantalla de conexión muestra las dos para
  copiarlas y la de espera explica qué hacer si Spotify muestra ese error.
- Barra «Sonando en Spotify» en Música › Spotify: portada, canción, artista y dispositivo, con anterior,
  reproducir/pausar y siguiente (Spotify Connect, Premium). Se actualiza cada 5 s solo mientras se ve el panel.
- Exportar títulos desde un guion o una prueba sin ventana abortaba el proceso (Qt necesita una aplicación para las
  fuentes); el relleno de audio de la exportación termina ahora a la duración exacta (pad=whole_dur).
- Pestañas de Biblioteca «Series», «Artistas» y «Carpetas», y la lista «Favoritos», traducidas (la comprobación
  de idiomas ahora también recoge los textos de bucles que se traducen).
## 2.0.0 — 2026-11-03 · Idiomas completos, perfiles que funcionan, Spotify, explorador, Paint y edición de vídeo directa

- **Idiomas**
  - El **inglés es el idioma predeterminado** (cuando no se ha elegido otro) y la referencia de todos los catálogos.
  - Unos 1 100 textos de la interfaz pasan por el traductor, también los compuestos con datos («PDF exportado ·
    12 páginas»), los de las tablas (herramientas, efectos, perfiles, formatos) y los nombres por defecto.
  - Red de seguridad: los textos fijos que llegan por variables se traducen al mostrarse cada ventana o diálogo.
  - Comprobaciones nuevas, que también se ejecutan al compilar y la detienen si falla algo:
    - `tools/i18n_keys.py --strict`: todas las claves del código, en los 6 idiomas completos.
    - `tools/i18n_screens.py --strict`: recorre las pantallas reales en cada idioma y no deja ni un texto en español.
- **Perfiles de rendimiento**
  - **Causa del fallo**: en el primer arranque el perfil recomendado se guardaba, pero no se aplicaba hasta el
    siguiente inicio.
  - **Perfiles disponibles**: Ahorro de recursos, Equilibrado, Alto rendimiento (nuevo), Máxima calidad y
    Personalizado, más los propios: crear, duplicar, renombrar, eliminar y elegir.
  - Se muestra el perfil activo, y editar un perfil propio no toca los demás.
  - Ajustes nuevos con efecto real:
    - miniaturas guardadas en memoria;
    - tareas a la vez para las miniaturas;
    - editor de vídeo con proxies.
- **Spotify** en Música, con la API oficial (ver `docs/SPOTIFY.md`).
  - Conexión segura con PKCE; el token se guarda cifrado con DPAPI.
  - Listas, canciones y álbumes guardados, artistas y búsqueda.
  - «Abrir en Spotify» con cualquier cuenta y reproducción en dispositivos Spotify con Premium.
  - Errores claros y desconexión que lo borra todo. Se respetan los límites del modo de desarrollo de Spotify.
- **Archivos**
  - Iconos reales de Windows (también de programas y accesos directos), con distintivos de acceso directo y de
    programa descargado de Internet.
  - Accesos directos `.lnk` y `.url` resueltos: un acceso a carpeta entra en ella y uno a documento lo abre.
  - Programas y scripts solo se ejecutan tras confirmar, con aviso si Windows los marcó como descargados de
    Internet; también «Ejecutar como administrador» (UAC).
  - Menú con «Abrir con la aplicación de Windows» y «Abrir con…». Tipos legibles en el idioma de AERO.
- **AERO Paint en la barra lateral**, como apartado propio (el mismo editor que la ventana independiente, que se
  sigue abriendo desde la edición de imágenes).
- **Editor de vídeo: manipulación directa en el visor**
  - Seleccionar con un clic.
  - Arrastrar para mover, con guías e imán al centro y a los bordes.
  - Esquinas para escalar con proporción (Mayús: libre) y lados para estirar en X o en Y.
  - Alt para recortar, tirador para girar (Mayús: pasos de 15°), punto de anclaje y flechas para mover de píxel
    en píxel.
  - Inspector con valores exactos (posición, escala, escala X/Y, giro, anclaje, opacidad, recorte) y
    «restablecer» por propiedad. Todo se puede deshacer.
  - Pistas bloqueables desde el candado de su cabecera.
  - Geometría única para el visor y la exportación (lo que se ve es lo que se exporta; antes el recorte no se veía
    en el visor). Los títulos se exportan como imagen y también se mueven, escalan y giran.
- **Sin decoraciones de temporada**: fuera los adornos y felicitaciones por fechas. Se conserva el saludo según
  la hora, así como los temas y fondos.
- **Memoria y rendimiento**
  - Fuga corregida: cada tarea en segundo plano terminada podía retener lo que capturaba. Por ejemplo, el editor
    de imágenes cerrado con su imagen (+29 MB cada vez).
  - Tras abrir y cerrar todos los editores y recorrer los apartados: 179 MB en lugar de 295 MB.
  - Las tarjetas y baldosas de Inicio se dibujan desde una imagen guardada: el fondo animado ya no las redibuja
    enteras en cada fotograma (CPU en reposo con fondo animado: de 12,5 a 8–9 %).
## 1.9.0 — 2026-11-03 · Auditoría: errores, rendimiento, energía e idiomas

- **Errores corregidos**
  - Miniaturas de «Archivos»: con varias cargando a la vez, algunas podían mostrar la imagen de otro archivo (la
    tarea leía la ruta cuando ya había cambiado).
  - Editor de documentos: abrir y guardar un DOCX sin números de página se los añadía siempre. Ahora se
    conserva lo que tenía. El aviso de elementos no compatibles ya no depende del texto en español.
  - AERO Paint: cambiar el nombre de una capa no marcaba el dibujo como modificado (se podía cerrar sin aviso).
  - Cierre: el programa podía terminar con un error interno (0xC0000409) si quedaban tareas en segundo plano;
    ahora espera a que terminen. Era también la causa de los fallos intermitentes al compilar.
- **Rendimiento**
  - Visualizador: «Barras de cristal» (la escena por defecto) pinta cada fotograma 3,3 veces más rápido
    (8,3 → 2,5 ms), «Anillo» 2,9 veces (13,8 → 4,8 ms) y «Ecualizador clásico» 1,7 veces (rectángulos por el
    camino rápido de Qt y polígonos convexos en lugar de trazados).
  - AERO Paint: deshacer ya no duplica las capas que no cambian (comparten memoria hasta que se pintan): con
    varias capas usa mucha menos memoria y cada trazo empieza antes.
  - Borradores de AERO Paint y del editor de imágenes: se escriben en segundo plano (la edición no se congela
    cada minuto con imágenes grandes), no se reescriben si no hubo cambios y no se guardan a mitad de un trazo.
  - Visor de imágenes (formatos vía Pillow como HEIC o AVIF): sin PNG intermedio, decodificación directa.
  - Ajustes: el tamaño de datos y caché se calcula en segundo plano (antes recorría la caché en el hilo de la
    interfaz).
- **Ahorro de energía (nuevo)**: el fondo animado se detiene tras 3 minutos sin usar el equipo y cuando funciona
  con batería, y vuelve al momento al mover el ratón. El visualizador sigue funcionando. Desactivable en
  Ajustes › Movimiento.
- **Idiomas**: 533 textos más de la interfaz pasan por el traductor (Ajustes, editores de imagen, vídeo y
  AERO Paint, documentos, hojas, presentaciones, PDF a editable, biblioteca, listas, reproductor, temas,
  comprimidos…) con 295 traducciones nuevas en los 6 idiomas completos.
## 1.8.0 — 2026-11-03 · Conversor más claro, lotes y recuperación del trabajo

- **Conversor**: perfiles nuevos **Compatible con móviles** (H.264 + AAC, lado corto hasta 1080p, máximo
  60 fps) y **Compatible con Windows** (H.264 + AAC hasta 4K), que se reproducen sin instalar nada. Los vídeos
  verticales se limitan por su lado corto. Antes de convertir se muestra el **tamaño estimado** (con ffprobe en
  segundo plano, también en «Convertir…» del clic derecho) y avisos claros: recompresión con posible pérdida de
  calidad, reducción de resolución, límite de fotogramas, contenedor poco compatible o audio con pérdida pasado
  a FLAC/WAV. Los nombres de los perfiles ya se traducen.
- **Cambiar nombre en lote** (clic derecho en «Archivos»): patrón con `{nombre}`, `{n}`, `{fecha}` y
  `{carpeta}`, buscar y reemplazar, mayúsculas, numeración y extensión en minúsculas, con vista previa en vivo.
  Detecta nombres vacíos, caracteres no válidos, nombres reservados, duplicados y archivos ajenos con el mismo
  nombre (nunca se sobrescriben). Se aplica en dos pasos (permite intercambiar nombres), se revierte solo si
  algo falla y se puede **deshacer**.
- **Redimensionar fotos** por lotes: lado mayor, porcentaje o caja; sin ampliar salvo que se pida; mismo
  formato, JPG, PNG o WebP con calidad; orientación EXIF aplicada; metadatos conservados o quitados. Crea copias
  en «Redimensionadas» o junto al original con el tamaño en el nombre; nunca sobrescribe. Avance, cancelar y
  registro en el centro de tareas.
- **Borradores automáticos**: AERO Paint, el editor de vídeo y el editor de imágenes guardan cada minuto una
  copia del trabajo sin guardar (el archivo del usuario no se toca). Si AERO Player se cierra de golpe, al
  volver a abrirlo se ofrece **recuperar** cada trabajo, ligado a su archivo original. Desactivable en
  Ajustes › General.
- «Archivos» se actualiza solo cuando cambia la carpeta abierta (renombrados, copias nuevas, otros programas),
  sin perder la selección ni el desplazamiento.
- Accesibilidad: los nombres que lee el Narrador (barra lateral, botones, baldosas, controles de reproducción)
  siguen el idioma elegido. El menú del clic derecho de «Archivos» se traduce.

## 1.7.0 — 2026-11-03 · Multiherramientas: AERO Paint, efectos de vídeo, tareas, búsqueda e idiomas

- **8 idiomas**: español de España, español de Latinoamérica e internacional (solo las 33 diferencias reales:
  video, computadora, mouse, Configuración…), inglés, chino simplificado, ruso (plurales de tres formas),
  italiano, alemán y portugués de Brasil. Se elige en el instalador y en Ajustes › General › Idioma, sin
  reinstalar; números y fechas siguen el idioma. Sistema central `aero/i18n` y comprobador de cobertura
  `tools/i18n_check.py` (100 % de los textos recogidos en las pantallas comunes).
- **AERO Paint**: lápiz, pincel (redondo, cuadrado, rotulador, aerógrafo), borrador, línea, rectángulo,
  elipse, triángulo, estrella, relleno con tolerancia, cuentagotas, texto, selección rectangular y libre,
  recortar, redimensionar imagen o lienzo, capas (crear, borrar, ordenar, ocultar, opacidad, renombrar),
  colores 1 y 2 con paleta, recientes y personalizados, cuadrícula, zoom y desplazamiento, fondo blanco,
  transparente o de color, proyecto `.aeropaint` y exportación PNG/JPG/BMP/WEBP. Desde «Crear», desde las
  acciones de una foto («Dibujar») y arrastrando imágenes.
- **Editor de vídeo — biblioteca de transiciones y efectos**: 13 transiciones (disolución, fundidos de
  entrada, a negro y a blanco, deslizamientos en cuatro direcciones, zoom, barrido, cortina, desenfoque y giro)
  con animación de muestra real, y 22 efectos en 10 categorías (desenfoques, nitidez, viñeta, grano, look
  cinematográfico, blanco y negro, sepia, saturación, contraste, exposición, temperatura, tinte, resplandor,
  aberración cromática, pixelado, negativo, contornos, retro, zoom, espejo, estela) con miniaturas reales.
  Se arrastran a la línea de tiempo; las transiciones se ven, se seleccionan, se alargan arrastrando su borde
  y se limitan a la mitad de los clips. Efectos activables, con parámetros, orden, quitar, restablecer,
  copiar y pegar. Se guardan en el proyecto y se exportan con los mismos filtros de FFmpeg; la vista previa
  en pausa muestra el fotograma exacto con efectos.
- **Centro de tareas**: comprimir, extraer, convertir y exportar en un mismo lugar, con avance real,
  tiempo, cancelar, resultado y errores; historial guardado (200 últimas).
- **Formato propio `.aeroarchive`**: firma, versión, metadatos, SHA-256 del contenido y un ZIP estándar
  dentro (recuperable con cualquier herramienta ZIP). Icono propio en el Explorador; solo se asocia su propia
  extensión (ZIP, RAR y 7Z no se tocan).
- **Búsqueda universal (Ctrl+K)**: herramientas, ajustes, biblioteca, recientes, tareas y archivos de tus
  carpetas (en segundo plano, solo donde tú has elegido), con filtros.
- **Cerrar** solo el vídeo o el documento abierto dentro de la aplicación y volver a donde estabas.
- **Inicio**: widgets nuevos de archivos recientes y de tareas.
- **Temas**: fuera los Metro; nuevos **Tropical** y **Atardecer tropical** (mar, arena y palmeras vectoriales).
- **Desinstalador**: opción (desmarcada) de borrar también los ajustes; nunca los archivos del usuario.
- Documentación: `DESIGN_SYSTEM.md`, `LOCALIZATION.md`, ROADMAP y TASKS actualizados.

## 1.6.0 — 2026-11-02 · Revisión profunda: compresión, editores, ajustes, Inicio y fondos

- **Compresión y extracción reparadas.** Causas encontradas: las operaciones esperaban en la cola de tareas
  pesadas (detrás de conversiones o escaneos: «Preparando…» sin fin), el progreso solo avanzaba al terminar
  cada archivo, la cancelación de WinRAR esperaba a su siguiente línea de salida, la ventana posponía su
  cierre mientras el ratón estuviera encima y el 7Z usaba el ajuste más lento de LZMA. Ahora cada operación
  tiene su hilo, el progreso es real en bytes (también para WinRAR y tar.exe, midiendo lo escrito) con
  porcentaje, archivos, tamaño, velocidad y tiempo restante (o un indicador indeterminado si no se puede saber),
  cancelar detiene el proceso al momento y deshace lo extraído, la misma operación no se lanza dos veces, los
  errores ofrecen «Reintentar» y la ventana se cierra sola con cuenta atrás. 7Z sin contraseña se extrae con el
  tar.exe de Windows (2,5 veces más rápido) y «Normal» comprime el doble de rápido.
- **Esquinas uniformes**: `aero/ui/corners.py` centraliza los radios y pide a Windows 11 el redondeo de todas
  las ventanas, diálogos, menús, desplegables y capas sobre vídeo.
- **Cursor**: el cursor de redimensionar ya no se queda puesto (antes era un cursor global de la aplicación);
  en la línea de tiempo del editor de vídeo el borde de los clips cortos ya no ocupa todo el clip.
- **Acciones visibles al abrir un archivo**: Editar, Recortar, Convertir, Propiedades (etiquetas), Extraer o
  Carpeta según el tipo, sin pasar por el menú del clic derecho; «Editar» también en la barra del reproductor.
- **Editor de fotos rediseñado**: diez herramientas con icono y nombre corto (Selección, Recortar, Tamaño,
  Ajustes, Filtros, Texto, Dibujo, Píxeles, Capas, Exportar), opciones avanzadas plegadas y filtros con
  miniaturas de la propia foto.
- **Editor de vídeo**: propiedades agrupadas según el tipo de clip; posición, giro libre y opacidad (también en
  la exportación); vista previa por capas (fotos encima del vídeo); las fotos se colocan solas en la pista de
  encima y los audios en una pista libre; menús de pista (subir, bajar, ocultar, silenciar, eliminar) y de
  clip (dividir, capa superior o inferior, eliminar); herramientas con nombre.
- **Ajustes** con navegación lateral en 15 apartados, iconos y buscador (también sin tildes); nuevos ajustes de
  compresión (formato, nivel, cierre automático) y de almacenamiento.
- **Inicio con widgets** del equipo: procesador, gráfica, memoria, discos, pantalla, sistema, placa base,
  ratón, teclado y batería, con datos reales de Windows; se pueden añadir, quitar, ocultar, cambiar de tamaño,
  elegir qué muestran y reordenar arrastrando; la distribución se guarda. Las temperaturas solo aparecen si
  Windows las expone; si no, «No disponible».
- **Fondos animados de verdad** (burbujas, nubes, partículas y estrellas que titilan) con modos Animado,
  Reducido y Estático; respeta «Mostrar animaciones» de Windows y se detiene al minimizar.
- **Textos**: el instalador, el tutorial y el README ya no etiquetan el estilo visual de la aplicación.
- **Corregido**: ordenar en el editor de hojas una columna con números y fechas (versión 1.5.0).

## 1.5.0 — 2026-11-02 · Instalador propio, tutorial y temas nuevos

- **Instalador propio** con el aspecto de AERO Player (ventana de cristal, burbujas en movimiento y el tema
  que elijas) en lugar del asistente genérico de Inno Setup. Instalación en un clic o personalizada
  (carpeta, menú Inicio, escritorio, menú del clic derecho, «Abrir con» y tema inicial), progreso con
  consejos, por usuario y sin administrador. Actualiza encima de la versión instalada (también de las
  1.4 y anteriores hechas con Inno Setup), cierra AERO Player si estaba abierto y solo borra los archivos
  que instaló: nunca otros archivos de la carpeta ni los datos del usuario.
- **Desinstalador** con la misma estética (Configuración › Aplicaciones o `AeroPlayer.exe --uninstall`;
  `--quiet` sin ventanas): quita el programa, accesos directos, menú contextual, asociaciones e inicio
  automático; conserva ajustes, bibliotecas y archivos.
- **Tutorial de bienvenida** la primera vez que se abre (se puede saltar con «Saltar tutorial» o Esc):
  resalta cada zona de la ventana, recorre Inicio, Biblioteca, Reproductor, Archivos, el menú del clic
  derecho, el Conversor y Ajustes, y permite elegir tema en el momento. Se repite desde Ajustes › Inicio.
- **Temas nuevos**: Espacio Negro, Cosmos, Nebulosa y Órbita (estrellas con destellos, nebulosas y
  planetas con anillos) y Frutiger Metro / Frutiger Metro Noche (mosaicos de colores planos con el brillo
  de Aero). Estrellas, nebulosa, planeta y mosaicos Metro también están en el Estudio de temas.

## 1.4.0 — 2026-11-02 · Extractor, compresor y menú contextual

- **Extractor y compresor** al estilo WinRAR: extraer ZIP, 7Z, RAR, TAR, GZ, XZ, CAB e ISO; crear ZIP y 7Z
  (AES-256; en 7Z también se cifran los nombres), TAR.GZ, TAR.XZ y RAR (con el WinRAR instalado). Contraseñas
  (se piden al extraer si hacen falta), extracción parcial, modos renombrar / sobrescribir / omitir,
  nombres Unicode (emoji, CJK), protección Zip Slip, enlaces y bombas, comprobación de espacio libre,
  cancelación y escritura atómica. Ventana de progreso que se cierra sola al terminar bien.
- **Gestor de comprimidos**: ver el contenido, extraer todo o la selección, comprobar y añadir archivos
  (ZIP y 7Z, también arrastrando).
- **Menú «AERO Player» en el clic derecho del Explorador** (solo para el usuario, sin administrador):
  extraer aquí, en carpeta, en…, abrir comprimido, comprimir en ZIP / 7Z / …, convertir, editar y vista
  rápida, filtrado por tipo de archivo. Las selecciones múltiples se agrupan en una sola acción. Casilla
  en el instalador y en Ajustes; se actualiza solo si cambia la ruta del programa y se quita al desinstalar.
- **Conversión rápida**: elegir formato y calidad y convertir sin abrir la aplicación.
- **Crear** en Inicio: documento, hoja, presentación y proyecto de vídeo nuevos, editar imagen, PDF a
  editable, comprimir y abrir comprimidos (antes los editores solo se abrían con un archivo).
- **Archivos**: menú contextual en los elementos (abrir, vista rápida, mostrar en el Explorador, editar,
  extraer, comprimir, convertir; dentro de un comprimido, extraer la selección).
- **Estabilidad**: auditoría automática (`tools/stress_check.py`) que recorre toda la aplicación con
  archivos válidos, dañados y vacíos; corregidos un PPTX dañado que impedía abrir el editor, un fallo al
  extraer de un comprimido dañado en el navegador y filas obsoletas tras un error.

## 1.3.0 — 2026-11-02 · Archivos, editores y ofimática

### Fase C · Ofimática y PDF
- **Editor de documentos** (DOCX, ODT, RTF, TXT, Markdown, HTML): formato, títulos, listas, tablas,
  imágenes, encabezado, pie y números de página, buscar y sustituir, exportar a PDF. Avisa de lo que no
  conserva y propone guardar una copia.
- **Editor de hojas** (XLSX, XLSM, XLS, XLSB, ODS, CSV): fórmulas guardadas tal cual y recalculadas con un
  evaluador propio (funciones en español e inglés), formato, filas y columnas, ordenar, filtrar, varias hojas,
  gráficos de barras y líneas.
- **Editor de presentaciones** (PPTX; ODP y PPT con LibreOffice): diapositivas, textos, imágenes, formas,
  fondos, mover y redimensionar, presentar y exportar a PDF.
- **PDF a documento editable** con OCR de Windows y comparación lado a lado; también desde el conversor.

### Fase D · Editor de vídeo
- Línea de tiempo con pistas de vídeo y audio, recortes, divisiones, velocidad, volumen, fundidos,
  transiciones, color, textos e imágenes, proxies, vista previa exacta y exportación en segundo plano.

### Fase E · Integración
- Asociaciones para PDF, documentos, hojas, presentaciones, comprimidos y proyectos; matriz de
  compatibilidad generada desde el código; cada archivo abierto desde Windows va a su experiencia.

### Fase B · Editor de imágenes

- **Editor de imágenes** en su propia ventana: botón «Editar» (o tecla E) en el visor y en Quick Look.
  - Composición: recortar con proporciones (libre, original, 1:1, 4:3, 3:2, 16:9, 9:16, 4:5), girar,
    voltear, enderezar (recorte automático sin esquinas vacías), cambiar tamaño y resolución, márgenes.
  - Color y filtros: exposición, brillo, contraste, iluminaciones, sombras, saturación, temperatura, tinte,
    nitidez, desenfoque, viñeta, blanco y negro, sepia y 9 filtros prediseñados ajustables. **No destructivo**:
    son parámetros que se aplican al exportar; la vista previa se calcula reducida y en segundo plano.
  - Píxeles: pixelar, mosaico y desenfoque de una zona o de toda la imagen, y efecto de baja resolución.
  - Dibujo: pincel, resaltador, línea, flecha, rectángulo y elipse (con relleno opcional), color, grosor y
    opacidad. Texto con tamaño, color y negrita. Lo dibujado va a una capa propia.
  - Capas: importar imágenes encima, mover, escalar, girar, opacidad, ordenar, duplicar, ocultar y eliminar.
  - Deshacer y rehacer (40 pasos, Ctrl+Z / Ctrl+Y) con instantáneas que solo ocupan memoria en la capa que
    cambia.
  - Guardar: copia (por defecto), proyecto editable `.aeroimg` (capas y ajustes) o, con doble confirmación,
    sobrescribir el original. Exportar a PNG, JPG, WebP, BMP o TIFF con calidad, tamaño y peso estimado,
    en segundo plano por la cola de tareas pesadas.

## Fase A · Organización

- **Quick Look de vídeo: los controles vuelven siempre al mover el ratón.** El área del vídeo tenía alfa 0
  en la ventana translúcida y Windows entregaba el ratón a la ventana de detrás. Ahora es opaca: el ratón,
  el doble clic (pantalla completa) y los clics llegan a AERO Player. También en el reproductor principal.
  Verificado con el puntero real en 4 tamaños y a pantalla completa, 3 pasadas (`tools/ql_controls_check.py`).
- **Esquinas redondeadas en Quick Look**: el degradado de la barra superior ya no deja un pico oscuro fuera
  de la esquina (`docs/capturas/v13/esquina_antes.png` / `esquina_despues.png`).
- **Quick Look de carpetas**: nombre, número de archivos y subcarpetas, tamaño total (en segundo plano, con
  límite), fecha, tipos presentes, cuadrícula o lista con miniaturas; entrar en subcarpetas, subir y volver.
- **Comprimidos sin extraer** (ZIP, CBZ, TAR, TAR.GZ/BZ2/XZ, RAR, CBR, 7Z, CAB, ISO): árbol, tamaños e
  información; abrir un elemento extrae solo ese a una carpeta temporal propia que se borra al cerrar.
  Protecciones: Zip Slip, bombas de compresión, límite de tamaño, contenido cifrado y archivos dañados.
  RAR/7Z usan el `tar.exe` que incluye Windows (nada que instalar).
- **Nueva sección «Archivos»**: carpetas personales como tarjetas, con nombre visual, descripción, portada
  recortable, color, favoritas, orden por arrastre o menú y ordenación del contenido recordada. Dentro:
  cuadrícula o lista, buscar, filtrar por tipo, ordenar, selección múltiple, Espacio para vista rápida.
  Las carpetas son referencias: AERO Player nunca mueve, copia ni borra nada.
- **Inicio rediseñado**: saludo grande y ligero según la hora; fechas especiales por región (Navidad, Año
  Nuevo, Reyes, Halloween, Día de Muertos, Acción de Gracias) y bienvenida a cada estación la primera
  semana, con hemisferio sur. Detalle de temporada estático y discreto. Cinco accesos compactos y los cinco
  últimos archivos; el historial completo, solo con «Ver todo». Todo desactivable en Ajustes › Inicio.
- **Rendimiento y calidad visual** (Ajustes): perfiles Ultra ligero, Equilibrado, Alta calidad y
  Personalizado, perfiles propios guardados y cada efecto ajustable o desactivable (burbujas, nubes,
  partículas, decoración, reflejos, sombras, velocidad, fotogramas, elementos en movimiento, desenfoque de
  Windows, transiciones, color de portada, detalle del visualizador, miniaturas y tareas simultáneas). Ningún
  perfil quita funciones. En el primer arranque se elige el perfil recomendado para el equipo (RAM, núcleos,
  gráfica y pantalla detectados sin procesos externos).
- **Optimización automática** (opcional): baja los efectos si el sistema pasa del 85 % de carga y los
  recupera poco a poco; solo mide mientras algo se anima.
- **Cola común de tareas**: miniaturas, recuentos y conversiones comparten límites según el perfil; lo
  visible va primero; con vídeo en reproducción el trabajo en segundo plano baja a una tarea.

## 1.2.0 — 2026-11-01 · Refinamiento visual y personalización

- **Bordes de calidad**: botones, campos, pestañas, menús, deslizadores y descripciones se dibujan con un
  estilo propio: borde de 1 px nítido y continuo en todo el perímetro (antes el inferior se oscurecía y las
  líneas quedaban repartidas entre dos píxeles), radios coherentes y foco dibujado hacia dentro. Menús con
  esquinas realmente transparentes.
- **Play alineado** con el resto de controles en cualquier tamaño (la barra se quedaba corta y el Play se
  desbordaba hacia abajo).
- **Hover sin recortes**: las baldosas y botones se iluminan y elevan en lugar de crecer.
- **Álbumes**: nombre y artista bajo la portada; menú contextual (reproducir, cola, lista, información,
  editar, eliminar); editor con nombre, artista y portada propia recortable; los cambios se guardan en AERO
  Player sin tocar los archivos. «Quitar de la biblioteca» no borra nada; mover a la Papelera pide doble
  confirmación.
- **Temas**: galería de 10 temas con vista previa (Frutiger Aero Classic, Nature, Sky, Aqua Glass, Ocean,
  Minimal Glass, Zen Crystal…) y editor de temas propios: colores, brillos, cristal, bordes, sombras,
  burbujas, nubes, césped, partículas, reflejos, ondas, movimiento, distribución e imagen de fondo.
  Duplicar, importar y exportar.
- **Deslizadores fluidos**: transparencia y paneles responden al momento (641 ms → ~15 ms por paso), con el
  valor visible y editable con el teclado.
- **Quick Look**: audio con progreso y tiempos alineados en su propia fila y selector de visualizador;
  imágenes y vídeos ocultan los controles tras 1,5 s quietos (antes en 0,5 s si el puntero sale) y nunca
  mientras se usan.
- **Visualizadores**: 11 estilos distintos que reaccionan al audio real, con galería, favoritos, colores,
  intensidad, velocidad, sensibilidad y opción de pantalla completa. Todos dibujan en menos de 6 ms por
  fotograma.

## 1.1.0 — estilo burbuja

- Esquinas de ventana limpias: el redondeo de Windows 11 recorta también el desenfoque (antes asomaba un
  rectángulo oscuro en las cuatro esquinas).
- Botón de reproducción como burbuja transparente con borde iridiscente, icono centrado y animación «pop».
- Animación elástica («squishy») al pulsar en todos los botones de icono y en las baldosas de Inicio;
  selección de la barra lateral como burbuja que se desliza con rebote; avisos con entrada elástica.
- Tiradores de los deslizadores como burbujas completas (antes se recortaban arriba y abajo).
- Tema «Burbuja» por defecto (perla, menta y rosa iridiscente) y tema «Personalizado» con colores propios.

## 1.1.0 — 2026-11-01 · Revisión profunda

- **Transparencia real**: ventanas sin marco con alfa por píxel y acrílico por composición; se ve el escritorio
  y las aplicaciones de detrás, también con la ventana en segundo plano. Modos Esmerilado / Transparente / Opaco.
- **Rediseño minimalista** (Zen Browser + Frutiger Aero): carcasa de cristal única, barra de iconos estrecha,
  barra superior con búsqueda y botones propios, reproductor integrado que solo aparece con contenido.
- **Modos de apertura**: aplicación completa, visor minimalista por archivo (imagen, vídeo, audio, PDF y
  documentos) y Quick Look. Abrir un archivo ya no construye la ventana principal.
- **Ventana a medida**: se adapta a la resolución y proporción del contenido y al monitor; mantiene la proporción
  del vídeo al redimensionar.
- **Aplicación predeterminada**: registro por usuario en «Abrir con» y en Aplicaciones predeterminadas de Windows
  (sección nueva en Ajustes y opción del instalador).
- **Series**: temporadas y episodios, siguiente episodio automático, vistos y «Continuar viendo».
- **Quick Look**: Espacio en el Explorador activado al activar la función; acepta teclados en pantalla.
- **Rendimiento**: memoria 588 → 71 MB, visualizador 44–54 % → 15 % de CPU, arranque 1,25 → 0,8 s, cambio de
  sección 17 ms.

## 1.0.0 — revisión visual

- Transparencia real: cristal acrílico de Windows 11 detrás de toda la ventana y de la vista rápida, con
  control de «Transparencia» en Ajustes (los temas claros la limitan para mantener la legibilidad).
- Estética Frutiger Aero reforzada: nuevo tema por defecto «Pradera» (cielo, sol con rayos, colinas
  brillantes, burbujas con reflejos), botones y pestañas de gel, paneles con casquete brillante y borde de luz.
- Menos texto: baldosas de Inicio solo con icono y título, acciones con iconos y descripciones en tooltips.

## 1.0.0 — 2026-11-01

Primera versión.

- Reproductor de audio y vídeo (Qt Multimedia + FFmpeg) con cola, aleatorio, repetir, velocidad, pistas de
  audio, subtítulos incrustados y externos (SRT/VTT/ASS) con desfase, pantalla completa con controles
  que se ocultan solos y recuerdo de posición y volumen.
- Visualizador que analiza el audio real (FFT): columnas de luz, ondas con estela, partículas, aurora y anillo;
  modo de bajo consumo.
- Fondo ambiental que toma el color de la portada.
- Visor universal: imágenes (con zoom, giro y navegación por carpeta), PDF con búsqueda, DOCX/ODT/RTF/MD/TXT,
  hojas de cálculo, presentaciones (modo presentación F5) y ZIP.
- Conversor por lotes: imágenes, audio, vídeo y documentos; perfiles, opciones avanzadas, aceleración por
  hardware verificada, pausa/reanudar, cancelar, reintentar, sin sobrescrituras.
- Biblioteca indexada en SQLite + búsqueda instantánea sin acentos (FTS5), álbumes con portadas, artistas,
  carpetas, edición de etiquetas, escaneo incremental pausable con exclusiones.
- Listas de reproducción (M3U8), favoritos e historial.
- Vista rápida desde el Explorador con atajo global o barra espaciadora (opcional y restringida).
- Cuatro temas (Abismo, Cielo, Laguna, Aurora), intensidad del cristal, modo de alta opacidad,
  reducir animaciones, atajos configurables.
- Instancia única, bandeja del sistema, inicio con Windows opcional, sin telemetría.
