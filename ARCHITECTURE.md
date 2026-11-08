# Arquitectura de AERO Player 1.3

## Tecnología

Python 3.11+ con **PySide6 (Qt 6, C++)**. Lo costoso se ejecuta en código nativo: decodificación y render de vídeo
por GPU (Qt Multimedia + FFmpeg), PDF (PDFium), imágenes (Qt Image I/O / Pillow), hojas de cálculo (calamine, Rust).
Python orquesta la interfaz. Ver la comparación con Tauri, libmpv, etc. en `docs/AUDITORIA.md`.

## Modos de ventana

```
                 ┌──────────────── aero/app.py (instancia única, argumentos) ────────────────┐
                 │                                                                          │
                 ▼                                                                          ▼
        AppController (aero/ui/controller.py) ── bandeja, atajo global, gancho de Espacio
          │                 │                         │
          ▼                 ▼                         ▼
   Modo A: MainWindow   Modo B: MediaWindow     Modo C: MediaWindow(quicklook=True)
   app completa          visor por archivo        vista rápida desde el Explorador
```

* **Sin argumentos** (acceso directo) → Modo A.
* **Con archivos** (doble clic en el Explorador) → Modo B: no se construye la ventana principal.
  `--full` fuerza el Modo A; una carpeta siempre abre el Modo A.
* **Segunda instancia** → envía los archivos a la primera por `QLocalServer` y se cierra.
* La aplicación termina cuando no queda ninguna ventana visible y la bandeja no está activa.

## Transparencia real

`GlassWindow` (aero/ui/glasswindow.py) es la base de todas las ventanas:

1. Ventana **sin marco** con `WA_TranslucentBackground` → alfa por píxel (*layered window*).
2. Modo *Esmerilado*: `SetWindowCompositionAttribute(ACCENT_ENABLE_ACRYLICBLURBEHIND)` → lo de detrás se
   desenfoca, también con la ventana en segundo plano. Modo *Transparente*: sin desenfoque. Modo *Opaco*.
3. `Backdrop` pinta un tinte con la opacidad elegida (nunca 0, para que los clics no atraviesen la ventana) y
   acentos Aero (luz, estela, burbujas) a media resolución.
4. `SetWindowRgn` redondea la ventana (y el desenfoque) salvo maximizada o a pantalla completa.
5. Movimiento con `startSystemMove` (Snap de Windows incluido) y bordes con `startSystemResize`.

Se descartaron Mica (no muestra las aplicaciones de detrás) y el acrílico de DWM (se apaga en segundo plano y no
funciona sin marco). Pruebas con capturas en `docs/AUDITORIA.md`.

### Rendimiento del cristal

Qt repinta los antecesores de un widget cuando la ventana es translúcida. Los widgets que pintan todo su área
(vídeo, visualizador) se registran con `mark_opaque()` y `Backdrop`/`GlassPanel` excluyen su región
(`paint_region`). Resultado: el visualizador pasó del 44–54 % al ~15 % de un núcleo.

## Visor minimalista (Modo B)

`MediaWindow` (aero/ui/media_window.py):

* Imagen / vídeo a sangre; los controles viven en una **capa superpuesta** (ventana transparente propia) porque
  el vídeo de Qt usa una superficie nativa de GPU que taparía a los widgets hermanos. Los píxeles vacíos de la
  capa dejan pasar los clics. Se ocultan tras 2,2 s sin actividad.
* Tamaño automático: `aero/core/geometry.py::fit_window` (proporción exacta, nunca amplía imágenes, no supera el
  86 % del monitor donde está el ratón). El vídeo se redimensiona con el primer fotograma y mantiene la
  proporción al estirar la ventana (`WM_SIZING` + `keep_aspect`).
* Vídeo de una serie → la cola incluye los episodios siguientes de la carpeta (`folder_episodes`).

## Módulos

| Ruta | Responsabilidad |
|---|---|
| `aero/core/` | Sin interfaz: configuración, SQLite/FTS5, escáner, etiquetas, subtítulos, conversión, series, geometría, asociaciones de Windows |
| `aero/player/` | `PlayerEngine` (cola, aleatorio, repetir, posiciones, vistos) y `AudioAnalyzer` (FFT) |
| `aero/ui/glass*.py`, `theme.py`, `icons.py`, `winfx.py` | Sistema visual y efectos de ventana |
| `aero/ui/style.py` | `AeroStyle` (QProxyStyle): dibuja botones, campos, pestañas, menús, deslizadores y descripciones con bordes nítidos y continuos. La hoja de estilos no estiliza esos controles a propósito (si lo hiciera, Qt volvería a su dibujado) |
| `aero/ui/backdrop_fx.py` | Fondo de los temas: tinte, decoración y elementos móviles (sprites con región sucia propia) |
| `aero/ui/visualizer.py`, `pages/viz_gallery.py` | 11 visualizadores y su galería |
| `aero/ui/pages/theme_studio.py`, `pages/albums.py` | Galería y editor de temas; tarjeta, editor e información de álbumes |
| `aero/ui/main_window.py`, `pages/` | Modo A; páginas creadas bajo demanda y precalentadas en reposo |
| `aero/ui/media_window.py` | Modos B y C |
| `aero/ui/viewers/` | Visores de imagen, PDF, documentos, hojas, presentaciones, ZIP |
| `aero/quicklook/` | Atajo global (`RegisterHotKey`), gancho de Espacio restringido al Explorador, lectura de la selección (COM) |
| `aero/archive/` | Lectura segura de comprimidos (ZIP/TAR con la biblioteca estándar; RAR/7Z/CAB/ISO con `tar.exe` de Windows), extracción de un solo elemento a una carpeta temporal |
| `aero/files/` | Biblioteca «Archivos»: listado, estadísticas, filtros (`__init__`), explorador compartido (`browser.py`) y página (`page.py`) |
| `aero/editors/image/` | Editor de imágenes: documento con capas e historial (`document.py`), ajustes NumPy (`adjust.py`), lienzo (`canvas.py`), ventana (`window.py`) |
| `aero/editors/video/` | Editor de vídeo: proyecto (`project.py`), exportación FFmpeg (`export.py`), miniaturas/ondas/proxies (`media.py`), línea de tiempo y ventana |
| `aero/office/` | Documentos (`docio.py`, `doc_editor.py`), hojas (`sheetio.py`, `formula.py`, `sheet_editor.py`), presentaciones (`slides_editor.py`) |
| `aero/pdfconv/` | PDF a editable: estructura (`extract.py`), OCR de Windows (`ocr.py`), DOCX/ODT/TXT/HTML (`writers.py`), ventana de comparación |
| `aero/core/tasks.py`, `quality.py`, `hardware.py`, `ui/perf.py` | Cola común de tareas con límites, perfiles de calidad, detección de hardware y optimización automática |
| `aero/core/seasons.py`, `compat.py` | Saludos y fechas por región; matriz de compatibilidad generada desde el código |

Todo lo pesado se importa al usarlo: arrancar la aplicación no carga `aero.files`, `aero.archive` ni
`aero.editors` (prueba `test_heavy_modules_not_loaded_at_startup`).

## Temas y personalización (1.2)

Un tema es un diccionario («spec») con colores, materiales (`glow`, `glass`, `edge`, `shadow`), decoración por
efecto (`on`, `amount`, `size`), movimiento, distribución e imagen de fondo. Los prediseñados están en
`theme.PRESETS`; los del usuario en el ajuste `user_themes` con clave `user:<id>`. Importar pasa por
`normalize_spec`, que descarta claves desconocidas y colores no válidos.

Dos caminos de actualización:

* `apply_theme` (cambia el tema): hoja de estilos, paleta, iconos y fondos. Raro.
* `apply_levels` (deslizadores de transparencia y paneles): solo `tm().set_levels` → `levels_changed` →
  repintar. El fondo se guarda en dos capas (tinte y decoración) y la transparencia es la opacidad con la que
  se pintan, así que nada se reconstruye.

Fondo con movimiento: solo 14 elementos se animan (el resto se hornea en la capa fija), a 20 fps (6 en segundo
plano), invalidando únicamente sus rectángulos; se detiene si la ventana no se ve, con «Menos animaciones» y
mientras se reproduce vídeo o se ve el visualizador.

## Álbumes personalizados (1.2)

La tabla `album_info` guarda nombre, artista y ruta de la portada propia (PNG de 600 px en la carpeta de datos,
`covers/`). La tabla `hidden` guarda los archivos retirados de la biblioteca; el escáner los omite. Nunca se
escriben etiquetas desde estas funciones; borrar físicamente solo es posible hacia la Papelera de Windows y
con doble confirmación.

## Asociaciones de archivos

`aero/core/associations.py` registra por usuario (HKCU) ProgIDs, `OpenWithProgids`, `Capabilities` y
`RegisteredApplications`, y abre `ms-settings:defaultapps?registeredAppUser=AERO Player`. Nunca escribe la
clave protegida `UserChoice`: Windows exige que el usuario confirme. El instalador ejecuta
`AeroPlayer.exe --register-associations` (y `--unregister-associations` al desinstalar).

## Gestión de errores

Archivos dañados → aviso y salto al siguiente; conversiones → mensaje comprensible y sin archivos parciales;
procesos externos sin shell; trabajo pesado en hilos (`run_async`, `QThreadPool`) que nunca retienen objetos Qt.

## Instalador

`aero/installer` sustituye a Inno Setup. `core.py` no usa Qt (se ejecuta en un hilo y se prueba sin
ventanas): extrae `payload.tar.xz` (generado por `packaging/make_payload.py`) en
`%LOCALAPPDATA%\Programs\AeroPlayer`, escribe `uninstall.json` con la lista de archivos, crea los accesos
directos con el AppUserModelID de la aplicación, registra la entrada de «Aplicaciones» en HKCU y llama a
`AeroPlayer.exe --register-associations` / `--register-context-menu`. Si el programa está abierto se le pide
salir por el socket local (`{"quit": true}`); una instalación anterior de Inno Setup se desinstala en silencio
antes. `ui.py` es la ventana de cristal (bienvenida, personalizar con elección de tema, progreso con consejos,
final) y la de desinstalación. El desinstalador es el propio `AeroPlayer.exe --uninstall`: quita la
integración con Windows y deja a un script de PowerShell, que espera a que el proceso termine, el borrado de
los archivos listados en `uninstall.json` (nunca otros). `packaging/setup.spec` une la interfaz (solo
QtCore/Gui/Widgets/Svg/Network) y el paquete en un único ejecutable.

## Esquinas, cursores y estilo compartido (1.6)

* `aero/ui/corners.py`: radios de toda la interfaz (`RADII`) y política que redondea cada ventana de primer
  nivel al mostrarse (DWM de Windows 11: recorta también desenfoque, sombras y vídeo nativo).
* `GlassWindow`: el redimensionado por bordes pone el cursor en la propia ventana (no un cursor global de la
  aplicación), así no se queda activo al cruzar a otra ventana.
* `aero/ui/file_actions.py`: acciones por tipo de archivo (Editar, Recortar, Convertir, Propiedades, Extraer…)
  compartidas por el visor rápido y el reproductor.
* `aero/ui/collapsible.py`: secciones plegables para opciones avanzadas (editores).

## Compresión (1.6)

`aero/archive/ops.py` escribe el avance en un `Stats` (bytes, archivos, fase, proceso externo) que la ventana
lee 8 veces por segundo; cada operación corre en su hilo (no en la cola de tareas pesadas). Los motores externos
(WinRAR, tar.exe) extraen a una carpeta temporal cuyo tamaño se mide para tener progreso real, y se terminan al
cancelar. Lo que una extracción escribe directamente en el destino se registra y se deshace si se cancela o falla.

## Inicio con widgets (1.6)

`aero/core/sysinfo.py` (sin Qt) reúne los datos: API de Windows por ctypes (CPU, memoria, discos, batería),
registro (modelo de CPU, placa, Windows, VRAM), contadores PDH (uso y memoria de la GPU) y WMI una sola vez
(nombres de GPU, ratón y teclado). `aero/ui/home_widgets.py` (servicio + tarjetas + tablero) solo consulta
mientras Inicio está a la vista: cada 2 s activa, cada 5 s en segundo plano, nunca minimizada. Temperaturas solo
si `MSAcpi_ThermalZoneTemperature` responde; si no, «No disponible».

## Fondo animado (1.6)

`backdrop_fx.MOTION` (Ajustes › Animaciones y fondos): «on», «reduced» (velocidad ×0,4 y como mucho 6
elementos) o «static». Si Windows tiene desactivadas las animaciones, «on» pasa a «reduced». Los temas sin
velocidad propia usan 0,4. Las estrellas titilan (cambian de brillo sin moverse).
