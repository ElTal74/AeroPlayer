# Propuesta técnica 1.3+ — biblioteca de archivos, Quick Look universal, editores y ofimática (2026-11-01)

Fuente: documento «Expansión del visor, biblioteca, edición multimedia y ofimática» (secciones 1–18 y
«Objetivo final») con cinco capturas. Este documento es la **primera tarea** que pide la sección 17:
auditoría del estado actual, arquitectura, tecnologías y licencias, hoja de ruta y criterios de prueba.

Leyenda de estado: **Existe** (funciona hoy) · **Parcial** · **No existe**.
Leyenda de verificación (sección 16): *implementado* · *probado automáticamente* (pytest) ·
*verificado con capturas reales* · *verificado a mano por el usuario*.

---

## 1. Las cinco capturas

| # | Qué muestra | Componente actual | Lectura |
|---|---|---|---|
| 1 | Biblioteca con pestañas Canciones, Vídeos, Series, Álbumes, Artistas, Carpetas | `library_page.py` | La biblioteca solo indexa medios. «Carpetas» agrupa canciones por carpeta; no hay biblioteca de documentos ni carpetas personalizables. |
| 2 | Quick Look sobre una carpeta: «No se pudo abrir el archivo · No tienes permiso» | `media_window.py` → `_open_document` | Quick Look trata la carpeta como un archivo, falla al leerla y muestra un error engañoso (no es un problema de permisos). Se ve también la esquina superior izquierda oscura y puntiaguda. |
| 3 | Detalle de una esquina de Quick Look | `_Shade` en `media_window.py` | Pico oscuro en la esquina: ver §3. |
| 4 | Inicio: cuatro baldosas grandes, «Continuar viendo» y dos listas largas | `home_page.py` | Demasiado texto y elementos compitiendo; listas de 20 entradas con nombres de archivo completos. |
| 5 | Visor de imagen en la aplicación completa | `viewers/image_viewer.py` | Solo visualización: zoom, girar, anterior/siguiente. No existe edición. |

## 2. Causas encontradas en los errores de Quick Look (ya corregidos en esta fase)

**Controles del vídeo que no reaparecen (sección 4).** Reproducido con movimientos reales del puntero:
tras ocultarse, el puntero sobre el vídeo no generaba **ningún** evento en AERO Player y
`WindowFromPoint` devolvía **la ventana de detrás** (en la prueba, un navegador). Causa: la ventana es
translúcida (capa de Windows con alfa por píxel) y, para no repintar el cristal en cada fotograma, el
fondo no se pintaba bajo el vídeo (`mark_opaque`). El fotograma lo compone la GPU encima, pero para Windows
esos píxeles tenían **alfa 0**, y en una ventana translúcida el alfa 0 deja pasar el ratón. Mientras los
controles se veían, el ratón sobre ellos sí llegaba; al ocultarse, ya no llegaba nada. Consecuencias
adicionales del mismo defecto: el doble clic sobre el vídeo no ponía pantalla completa y un clic sobre el
vídeo activaba la aplicación de detrás. Afectaba también al reproductor de la ventana principal.

Solución de raíz: `opaque_video()` (`glass.py`) — el cristal sigue sin pintarse bajo el vídeo (sin coste
por fotograma), pero el propio widget de vídeo rellena su área con negro **opaco**, así que Windows le
entrega el ratón. Medido: los repintados por segundo y la CPU durante la reproducción no cambian.

**Esquinas puntiagudas (sección 3).** Windows 11 redondea la ventana principal (DWM, 8 px), pero los
controles flotantes viven en otra ventana superpuesta (necesaria porque el vídeo es una superficie de GPU) y
esa ventana no se redondea. El degradado oscuro de la barra superior se pintaba en un rectángulo y dejaba
un pico oscuro fuera de la esquina redondeada. Solución: el degradado se recorta con el mismo radio que la
ventana (recto solo a pantalla completa o maximizada). Comprobado con capturas reales ampliadas.

## 3. Auditoría: qué existe hoy

| Área | Estado | Dónde |
|---|---|---|
| Reproductor de audio/vídeo, cola, listas, series | Existe | `player/engine.py`, `pages/player_page.py`, `core/series.py` |
| Biblioteca de medios (canciones, vídeos, álbumes editables, artistas, carpetas) | Existe | `core/scanner.py`, `core/db.py`, `pages/library_page.py`, `pages/albums.py` |
| Quick Look (Espacio en el Explorador) para imagen, audio, vídeo, PDF y documentos | Existe | `quicklook/`, `media_window.py` |
| Quick Look de carpetas y comprimidos | No existe | — |
| Visores PDF, DOCX, ODT, RTF, TXT, MD, XLSX/XLS/ODS/CSV, PPTX | Existe (solo lectura; PPTX aproximado) | `viewers/` |
| Conversor (FFmpeg externo + conversor propio de imágenes) con cola | Existe | `core/converter.py`, `core/builtin_convert.py`, `pages/converter_page.py` |
| Asociaciones de Windows (sin `UserChoice`) para audio, vídeo, imagen, PDF y documentos | Existe | `core/associations.py` |
| Temas, editor de temas, visualizadores, reducir animaciones | Existe | `theme.py`, `theme_studio.py`, `visualizer.py` |
| Perfiles de calidad visual, detección de hardware, optimización automática | No existe (solo «Menos animaciones») | — |
| Cola común de tareas con límites de concurrencia | Parcial (cada módulo usa `run_async` / su propia cola) | `async_util.py`, `converter.py` |
| Editores (imagen, vídeo, documentos, hojas, presentaciones), OCR, PDF→DOCX | No existe | — |

### Limitaciones de la arquitectura actual
1. **Carga perezosa ya presente pero sin reglas**: los visores se importan al abrir el archivo, pero no hay un
   registro de módulos; añadir cinco editores así acabaría con `if kind == ...` repartidos por la interfaz.
2. **Sin cola común**: un escaneo, miniaturas y una conversión pueden competir sin límite.
3. **`kind_of()` solo conoce medios y documentos**: carpetas y comprimidos no tienen tipo.
4. **La base de datos** no tiene tablas para carpetas de usuario ni para proyectos.
5. **La ventana de controles flotantes** es una ventana aparte: todo lo que se pinte en ella debe respetar
   el redondeo a mano (resuelto en §2).

## 4. Arquitectura propuesta

Cada módulo es un paquete que **no se importa** hasta que se usa. Un registro único decide qué módulo abre
cada tipo de archivo, tanto desde la interfaz como desde Windows.

```
aero/
  core/            configuración, BD, formatos, escáner, asociaciones (existente)
  core/tasks.py    cola común de tareas: prioridades, clases de recurso, cancelación   [1.3]
  core/hardware.py RAM, núcleos, GPU, resolución → perfil recomendado                 [1.3]
  modules.py       registro: tipo → módulo (visor, editor, Quick Look); importación diferida [1.3]
  files/           biblioteca de carpetas: modelo, listado, miniaturas, orden y filtros [1.3]
  archive/         lectura segura de ZIP/TAR (stdlib) y RAR/7Z/CAB/ISO (bsdtar de Windows) [1.3]
  player/          motor multimedia (existente)
  quicklook/       atajo y selección del Explorador (existente)
  ui/viewers/      visores (existente)
  editors/image/   editor de imágenes                                                   [1.4]
  office/          documentos, hojas, presentaciones                                    [1.5–1.6]
  pdfconv/         PDF → documento editable, OCR                                         [1.5–1.6]
  editors/video/   editor de vídeo no lineal                                             [1.7]
```

Reglas que se mantienen: nada pesado en el hilo de la interfaz, las tareas en hilos no capturan objetos Qt,
NumPy solo tras `aero/__init__.py`, los procesos externos (FFmpeg, bsdtar, OCR) se lanzan al pedirlos y se
cierran al acabar.

## 5. Tecnologías y licencias evaluadas

AERO Player es **GPL-3.0-or-later**. Se evalúa impacto en RAM, arranque, tamaño y compatibilidad.

| Necesidad | Opción elegida | Licencia | Impacto | Alternativas descartadas y por qué |
|---|---|---|---|---|
| ZIP, TAR, TAR.GZ/BZ2/XZ | `zipfile`, `tarfile` de Python | PSF | 0 MB; en proceso; control fino de tamaños y ratios | — |
| RAR, 7Z, CAB, ISO | `tar.exe` (bsdtar/libarchive) **incluido en Windows 11** | BSD-2 (parte del sistema, no se redistribuye) | 0 MB; proceso aparte solo al abrir | `py7zr` (LGPL, 7 dependencias); `unrar` (licencia no libre); empaquetar libarchive (DLL y dependencias). Si el sistema no tiene `tar.exe` con RAR, se muestra un aviso y no se finge soporte |
| Editor de imágenes | Qt (`QPainter`, `QImage`) + Pillow + NumPy (ya incluidos) | LGPL / HPND / BSD | 0 MB nuevos | OpenCV (≈90 MB), Skia |
| Editor de vídeo: vista previa | Qt Multimedia (ya incluido) con proxies | LGPL | — | MLT (LGPL, pesado), libmpv (GPL, DLL de 30 MB) |
| Editor de vídeo: exportación, proxies, ondas | FFmpeg externo (ya usado) con `filter_complex` | GPL/LGPL (externo) | proceso aparte | — |
| Documentos | `QTextDocument` (edición) + `python-docx` (DOCX, ya instalado en el entorno) + escritor ODF de Qt | LGPL / MIT | +0,3 MB | LibreOffice embebido (≈350 MB) |
| Hojas de cálculo | `openpyxl` (conserva fórmulas y estilos) + `python-calamine` (lectura rápida, ya incluido) | MIT | +4 MB | `pycel` (GPL, recálculo), `formulas` (EUPL) — se valorarán para recalcular |
| Presentaciones | `python-pptx` (ya incluido) | MIT | — | — |
| DOCX/XLSX/PPTX → PDF fiel | LibreOffice **si está instalado** (`--headless`), ya contemplado | MPL-2.0 (externo, no se redistribuye) | 0 MB | Sin LibreOffice: DOCX→PDF aproximado con Qt, avisando |
| PDF con texto → DOCX | `pypdfium2` (caracteres con posición, tamaño, peso, fuente e imágenes) + análisis de maquetación propio + `python-docx` | Apache-2.0 / BSD-3 | +4 MB | PyMuPDF/pdf2docx (**AGPL-3.0**: obligaciones adicionales) |
| OCR | **OCR de Windows** (`Windows.Media.Ocr`, incluido en el sistema) vía `winrt` | MIT (enlace), motor del sistema | +1 MB; sin modelos que distribuir | Tesseract (Apache-2.0, ≈60 MB + idiomas) como opción si el usuario lo instala; los idiomas de Windows OCR dependen de los paquetes de idioma instalados |
| Detección de hardware | `GlobalMemoryStatusEx`, `EnumDisplayDevices` (ctypes), `os.cpu_count` | — | 0 MB | `psutil` (BSD, innecesario) |

Ninguna dependencia nueva es necesaria para la fase A. Las fases B–D añaden `openpyxl`, `pypdfium2` y
`winrt-Windows.Media.Ocr`; se pedirá conformidad antes de instalarlas (en el entorno virtual del proyecto,
nunca de forma global) y se registrarán en `LICENSES.md`.

## 6. Hoja de ruta

Se mantiene el orden propuesto con dos cambios justificados:

* **La infraestructura de rendimiento (cola de tareas, perfiles de calidad, registro de módulos) se adelanta
  a la fase A.** Todo lo demás se apoya en ella; añadirla al final obligaría a rehacer cada editor.
* **La integración con el conversor se hace en cada fase** (cada editor exporta con el conversor común), no
  solo en la fase E.

| Versión | Fase | Contenido | Primera versión funcional | Después |
|---|---|---|---|---|
| **1.3** | A · Organización | Correcciones de Quick Look; biblioteca «Archivos»; Quick Look de carpetas y comprimidos; Inicio rediseñado con saludo y detalles de temporada; cola de tareas; «Rendimiento y calidad visual» con perfiles | Todo lo de la columna anterior | Pausar y reanudar tareas; caché de miniaturas con límite configurable |
| **1.4** | B · Imagen | Editor: recorte, tamaño, girar, voltear, enderezar, márgenes; pixelar y desenfocar (todo o selección); dibujo, formas, flechas, texto, resaltado; capas de imagen; ajustes de color y filtros; deshacer; guardar copia y exportar con el conversor | Todo lo anterior, sin herramientas vacías | Pinceles avanzados, máscaras, curvas |
| **1.5** | C1 · Documentos y PDF | Editor de documentos (TXT, MD, RTF, DOCX, ODT) con formato, listas, tablas, imágenes, buscar y sustituir, PDF; PDF con texto → DOCX/ODT/TXT con comparación lado a lado | DOCX conserva texto, formato, tablas e imágenes; avisa de lo que no conserva | Encabezados y pies complejos, campos |
| **1.6** | C2 · Hojas, presentaciones, OCR | Hojas (XLSX/ODS/CSV, XLS solo lectura→XLSX): celdas, formato, fórmulas conservadas, ordenar, filtrar, varias hojas, gráficos básicos; presentaciones (PPTX); OCR de PDF escaneados | Conservar fórmulas y diapositivas | Recalcular fórmulas avanzadas, ODP, PPT vía LibreOffice |
| **1.7** | D · Vídeo | Proyecto, línea de tiempo con pistas, recortar, dividir, mover, fundidos, transiciones básicas, texto, imágenes, volumen, color, velocidad; proxies; exportación con FFmpeg en segundo plano con progreso y cancelación | Cortar y unir clips con audio y exportar de forma fiable | Más transiciones, corrección de color avanzada |
| **1.8** | E · Integración | Matriz de compatibilidad completa, asociaciones para comprimidos y ofimática, apertura contextual de cada tipo en su experiencia | — | — |
| **1.9** | F · Calidad final | Pruebas de bajo consumo con límites de recursos, seguridad, licencias, instalador, documentación | — | — |

No se afirmará que AERO Player sustituye a Photoshop, Premiere, DaVinci Resolve u Office: cada versión
declara exactamente lo que hace.

## 7. Trazabilidad de requisitos

| Requisito | Estado actual | Módulo | Cambios necesarios | Prioridad | Dependencias | Prueba de aceptación |
|---|---|---|---|---|---|---|
| §1 Sección «Archivos» en la navegación | No existe | `files/`, `sidebar.py` | Página nueva, tablas `folders` en BD | Alta (1.3) | — | Añadir carpeta, cerrar, reabrir: nombre, portada, color, favorito y orden se conservan |
| §1 Tarjetas de carpeta personalizables y menú contextual | No existe | `files/` | Delegado de tarjetas, editor (reutiliza el de álbumes) | Alta (1.3) | — | Cada opción del menú tiene efecto comprobable; nada mueve ni copia archivos |
| §1 Contenido: cuadrícula/lista, ordenar, filtrar, buscar, varios seleccionados, vista previa | No existe | `files/` | Modelo virtualizado, miniaturas bajo demanda | Alta (1.3) | Cola de tareas | Carpeta con 5 000 archivos se abre sin bloquear (> 50 ms) la interfaz |
| §2 Quick Look de carpetas | No existe (error engañoso) | `media_window.py`, `files/` | Vista de carpeta con recuento, tamaño en segundo plano, navegación | Alta (1.3) | — | Entrar y volver en subcarpetas; recuento correcto |
| §2 ZIP/RAR/7Z sin extraer | No existe | `archive/` | Listado, árbol, información, vista previa de un elemento | Alta (1.3) | `tar.exe` del sistema para RAR/7Z | Listar sin escribir nada en disco; previsualizar una imagen interna |
| §2 Seguridad de comprimidos | — | `archive/` | Rutas normalizadas (Zip Slip), límites de tamaño y ratio, temporales propios borrados al cerrar, contraseña detectada, nunca ejecutar | Alta (1.3) | — | ZIP con `../`, bomba de compresión, cifrado y dañado: aviso claro, nada escrito fuera |
| §3 Esquinas redondeadas | Defectuoso | `media_window.py` | Recorte del degradado de la capa | Alta | — | Captura ampliada de las cuatro esquinas sin picos ✔ |
| §4 Controles de vídeo que reaparecen | Defectuoso | `glass.py`, `media_window.py`, `player_page.py` | Fondo opaco bajo el vídeo | Crítica | — | Puntero real: ocultar y reaparecer en 4 tamaños y pantalla completa, repetido |
| §5 Inicio minimalista, saludo y temporadas | Parcial | `home_page.py`, `core/seasons.py` | Rediseño, calendario por región, opción para desactivar | Alta (1.3) | — | Fechas simuladas: saludo y festividad correctos por región; desactivable |
| §6 Editor de imágenes | No existe | `editors/image/` | Ver hoja de ruta 1.4 | Alta (1.4) | Conversor | Editar, deshacer, exportar copia; original intacto (hash) |
| §7 Editor de vídeo | No existe | `editors/video/` | Ver 1.7 | Media | FFmpeg | Guardar y reabrir proyecto; exportar en segundo plano y cancelar |
| §8 Ofimática | Solo lectura | `office/` | Ver 1.5–1.6 | Alta | `openpyxl` | Abrir, editar, guardar y reabrir conservando fórmulas y diapositivas |
| §9 PDF → editable y OCR | No existe | `pdfconv/` | Ver 1.5–1.6 | Alta | `pypdfium2`, OCR de Windows | Comparación lado a lado; avisos de reconstrucción aproximada |
| §10 Conversor universal | Parcial (medios e imágenes) | `core/converter.py` | Perfiles, historial, documentos | Media | LibreOffice opcional | Lote con cancelación e historial |
| §11 Predeterminados | Parcial | `core/associations.py` | Matriz de compatibilidad, registrar solo lo que se abre de verdad | Media (1.8) | Cada módulo | Abrir cada extensión registrada en su experiencia, sin la ventana principal |
| §12 Acabado profesional | Continuo | Todos | Revisión por módulo con capturas | Alta | — | Capturas por módulo |
| §13 Arquitectura modular | Parcial | `modules.py` | Registro y carga diferida | Alta (1.3) | — | Importar `aero` no carga editores (prueba de `sys.modules`) |
| §18 Perfiles de calidad y optimización automática | Parcial | `core/hardware.py`, Ajustes | Sección «Rendimiento y calidad visual» | Alta (1.3) | — | Mismas funciones en todos los perfiles; CPU en reposo medida por perfil |
| §18.10 Cola de tareas | Parcial | `core/tasks.py` | Prioridad interactiva, límite por clase | Alta (1.3) | `hardware.py` | Con perfil de 4 GB nunca hay dos tareas pesadas a la vez |
| §18.12 Mediciones | Parcial | `tools/bench.py` | Mediciones por perfil y entorno limitado (objeto de trabajo de Windows) | Alta | — | Informe con lo medido y lo simulado claramente separados |

## 8. Pruebas de bajo consumo (§18.12)

No hay un equipo físico de 4 GB disponible. Se medirá en este equipo y además con **límites simulados**:
un objeto de trabajo de Windows (`JobObject`) que limita la memoria y la afinidad a 2 núcleos, y la
aplicación con el perfil «Ultra ligero». Los informes separarán siempre «medido en este equipo» de
«simulado con límites». No se declarará compatibilidad con un equipo que no se haya probado.

Presupuestos iniciales (a confirmar con mediciones): reposo < 1 % de CPU y < 120 MB en cualquier perfil;
arranque < 1 s; abrir Quick Look de imagen < 300 ms; ninguna tarea bloquea el hilo de la interfaz más de
50 ms.

## 9. Decisiones que necesitan tu conformidad

1. Instalar en el entorno virtual del proyecto (no global) `openpyxl`, `pypdfium2` y `winrt-Windows.Media.Ocr`
   cuando lleguen las fases C (1.5–1.6). La fase A no necesita nada nuevo.
2. RAR y 7Z dependen del `tar.exe` que trae Windows 11. Si prefieres no depender del sistema, la alternativa
   es incluir `libarchive` (BSD) en el instalador (+≈6 MB).

## 10. Estado de la fase A (actualizado 2026-11-01)

| Requisito | Estado | Verificación |
|---|---|---|
| §4 Controles de vídeo en Quick Look | Hecho | Prueba automática de la causa (`test_quicklook_video_area_receives_mouse`, falla con el código anterior) y puntero real: 24/24 ciclos en 4 tamaños y pantalla completa |
| §3 Esquinas redondeadas | Hecho | `test_quicklook_shade_corners_are_rounded` y capturas ampliadas antes/después |
| §2 Quick Look de carpetas | Hecho | `test_quicklook_folder_navigation`; capturas `ql_carpeta*.png` |
| §2 Comprimidos y seguridad | Hecho | 6 pruebas (árbol sin escribir en disco, extracción de un solo elemento, Zip Slip, bomba, cifrado, dañado, TAR, 7Z, RAR y RAR cifrado); captura `ql_zip*.png` |
| §1 Biblioteca «Archivos» | Hecho | `test_folder_library_persists_customisation` (cerrar y reabrir la base de datos; los archivos no cambian), reordenación; capturas `archivos_*.png` |
| §5 Inicio y saludos | Hecho | `test_greetings_by_time_season_and_region` (fechas simuladas por región), `test_home_page_is_minimal_and_follows_settings`; capturas `inicio_*.png` |
| §13 Carga diferida | Hecho para lo nuevo | `test_heavy_modules_not_loaded_at_startup` |
| §18 Perfiles de calidad, cola común de tareas, detección de hardware, optimización automática | Hecho | 8 pruebas en `tests/test_perf13.py`; mediciones por perfil y en simulación de 2 núcleos/1,5 GB en `docs/RENDIMIENTO.md`; captura `ajustes_rendimiento.png`; bloqueo máximo al abrir 5 000 archivos ≤ 29 ms |

Límites conocidos: con RAR/7Z, los nombres con caracteres fuera de la página de códigos de Windows
(p. ej. japonés en un sistema en español) se listan con «?» y no se pueden abrir (limitación de la salida
de `tar.exe`); se avisa en pantalla. Los ZIP cifrados se listan pero no se abren (no se piden contraseñas
en esta versión). No verificado a mano por el usuario.

## 11. Estado de la fase B — editor de imágenes (2026-11-02)

| Requisito (§6) | Estado | Verificación |
|---|---|---|
| Recortar, proporciones, girar, voltear, enderezar, tamaño, resolución, márgenes | Hecho | `test_crop_resize_rotate_flip_and_undo`, `test_straighten_margins_pixelate_and_low_res`; captura `editor_composicion.png` |
| Pixelar (todo o zona, tamaño ajustable), desenfoque, baja resolución, mosaico | Hecho | Prueba de bloques de un solo color y zona intacta fuera; captura `editor_pixeles.png` |
| Dibujo, líneas, flechas, círculos, rectángulos, texto, resaltar, color, grosor, opacidad | Hecho | Capturas `editor_dibujo.png`, `editor_capas.png` |
| Capas: importar, mover, tamaño, rotar, transparencia, ordenar, duplicar, ocultar, eliminar | Hecho | `test_layers_and_drawing` |
| Brillo, contraste, saturación, temperatura, tinte, exposición, sombras, iluminaciones, nitidez, desenfoque, B/N, filtros | Hecho, no destructivo | `test_adjustments_are_non_destructive` (los píxeles del fondo no cambian); captura `editor_color.png` |
| Deshacer y rehacer | Hecho (40 pasos) | Pruebas de historial |
| Guardar, guardar como, exportar; original conservado | Hecho | `test_editor_window_export_keeps_original` (hash SHA-256 del original igual tras exportar) |
| Proyecto editable | Hecho (`.aeroimg`) | `test_project_roundtrip` |
| Carga diferida | Hecho | El paquete `aero.editors` no se importa al arrancar |

Límites conocidos de esta primera versión: el texto y las formas se rasterizan al colocarlos (se pueden
deshacer, mover con su capa u ocultar, pero no reescribir el texto); las capas giradas se pixelan sobre el
rectángulo que las envuelve; con ajustes de color activos y zoom por encima de la vista previa, la
pantalla muestra la vista previa reducida (la exportación usa siempre la resolución completa). No
verificado a mano por el usuario. No hay dependencias nuevas (Qt, NumPy y Pillow ya estaban incluidos).

## 12. Estado de las fases C, D, E y F (2026-11-02)

| Fase | Contenido | Estado | Verificación |
|---|---|---|---|
| C1 | Editor de documentos | Hecho | `tests/test_office_docs.py` (5 pruebas) |
| C1 | PDF a editable (texto) | Hecho | `tests/test_pdfconv.py`, PDF real |
| C2 | Hojas de cálculo | Hecho | `tests/test_office_sheets.py` (3 pruebas) |
| C2 | Presentaciones | Hecho | `tests/test_office_slides.py` (2 pruebas) |
| C2 | OCR | Hecho (OCR de Windows) | `test_scanned_pdf_uses_ocr` |
| D | Editor de vídeo | Hecho | `tests/test_video_editor.py` (5 pruebas, exportación real con FFmpeg) |
| E | Asociaciones, matriz, apertura contextual | Hecho | `test_compatibility_matrix_only_registers_what_opens`, `test_contextual_opening_from_windows` |
| F | Versión 1.3.0, documentación, licencias, instalador | Hecho | Ver TESTING.md y LICENSES.md |

Pendiente para versiones siguientes (no simulado en esta): pedir contraseña de ZIP cifrados, texto editable
después de colocarlo en el editor de imágenes, tablas sin bordes en PDF, recálculo de funciones avanzadas
de Excel, transiciones de cortinilla en vídeo, vista previa de vídeo con mezcla de varias pistas en tiempo real.
