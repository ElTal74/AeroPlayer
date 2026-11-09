# AERO Player

Reproductor multimedia, visor universal, editor de imágenes, vídeo y documentos, y conversor de archivos para
Windows, con temas y fondos personalizables. Software libre (GPL-3.0-or-later), sin telemetría.

**© 2026 David Seva Gonzalvez.** Web oficial y descargas: https://eltal74.github.io/AeroPlayer/ ·
código: https://github.com/ElTal74/AeroPlayer

## Qué hace

- **Reproductor**: música y vídeo (MP3, FLAC, AAC, OGG, Opus, WAV, MKV, MP4, MOV, AVI, WebM…), cola,
  aleatorio, repetir, velocidad, pistas de audio, subtítulos incrustados y externos con desfase, pantalla
  completa, recuerda posición y volumen.
- **Visualizadores** que analizan el sonido real (FFT): 11 estilos (Aero Waves, Liquid Spectrum, Aurora,
  Particles, Equalizer Classic, Glass Bars, Energy Flow, Nebula, Water Rings, Fluid Motion y Anillo) con
  galería, favoritos, colores, intensidad, velocidad y sensibilidad. También en la vista rápida de audio.
- **Visor**: imágenes (incl. HEIC/AVIF), PDF con búsqueda, DOCX/ODT/RTF/Markdown/TXT/código, Excel/ODS/CSV,
  PowerPoint (con modo presentación), carpetas y comprimidos (ZIP, RAR, 7Z, TAR, CAB, ISO) sin extraer.
- **Archivos**: biblioteca de carpetas personales como tarjetas (nombre, descripción, portada, color, favoritas,
  orden) que nunca mueve ni copia nada; explorador con cuadrícula o lista, filtros, búsqueda y vista rápida.
- **Iconos AERO**: cada archivo lleva el icono de su categoría (vídeo, audio, imagen, documento, PDF, comprimido,
  aplicación, torrent, imagen de disco…), dibujado en cristal y agua, en tema claro u oscuro (`docs/ICONOS.md`).
- **Imágenes de disco**: ISO, IMG, BIN/CUE, NRG y MDF se exploran y extraen sin montarlas; las ISO, IMG, VHD y VHDX
  se montan con Windows si lo pides (`docs/DISCOS.md`).
- **BitTorrent**: abre un `.torrent`, mira su contenido, elige archivos y carpeta y descarga con progreso, pausa,
  reanudación y cancelación. Nada empieza ni se ejecuta solo y se puede desactivar del todo (`docs/TORRENTS.md`).
- **Editor de imágenes**: recortar, girar, enderezar, tamaño, márgenes; color y filtros no destructivos;
  pixelar, mosaico y desenfoque por zonas; dibujo, flechas, formas y texto; capas; deshacer; exportar.
- **Editor de vídeo**: línea de tiempo con pistas, recortar, dividir, mover, velocidad, volumen, fundidos,
  transiciones, color, textos e imágenes; proxies; exportación MP4/MKV/WebM/MOV con FFmpeg en segundo plano.
- **Ofimática**: editor de documentos (DOCX, ODT, RTF, TXT, Markdown) con exportación a PDF; hojas de cálculo
  (XLSX, XLS, ODS, CSV) que conservan las fórmulas; presentaciones (PPTX).
- **PDF a documento editable**: reconstrucción de párrafos, estilos, tablas, imágenes y columnas; OCR de
  Windows en páginas escaneadas; comparación lado a lado con el original. Se avisa cuando es aproximado.
- **Rendimiento y calidad visual**: perfiles Ultra ligero, Equilibrado y Alta calidad (más perfiles propios),
  cada efecto ajustable, perfil recomendado según el equipo y optimización automática opcional.
- **Extractor y compresor (como WinRAR)**: extrae ZIP, 7Z, RAR, TAR, GZ, XZ, CAB e ISO (con contraseña,
  extracción parcial y qué hacer con los archivos existentes) y crea ZIP y 7Z con cifrado AES-256, TAR.GZ y
  TAR.XZ, y RAR si WinRAR está instalado. Nombres en cualquier idioma, protección contra rutas peligrosas y
  «bombas», cancelable y sin dejar archivos a medias. Gestor para ver el contenido, comprobar y añadir.
- **Menú contextual del Explorador**: clic derecho › **AERO Player** › Extraer aquí, Extraer en una carpeta
  con su nombre, Extraer en…, Comprimir en ZIP / 7Z, Comprimir…, Convertir…, Editar y Vista rápida. Solo
  aparece lo que tiene sentido para cada archivo; con varios seleccionados, se comprimen o convierten juntos.
  En Windows 11 está en «Mostrar más opciones» (o Mayús+F10). Se activa o quita en Ajustes.
- **Crear** desde Inicio: documento, hoja, presentación o proyecto de vídeo nuevos, editar una imagen,
  PDF a editable, comprimir y abrir comprimidos.
- **Conversor por lotes**: imágenes, audio, vídeo (H.264/H.265/VP9/AV1, GIF, extraer audio, copia sin
  recomprimir) y documentos, con perfiles, progreso, tiempo restante, pausa, cancelación y reintento.
  Nunca sobrescribe ni modifica los originales.
- **Biblioteca** con búsqueda instantánea (también sin acentos), álbumes con portada, artistas y carpetas;
  álbumes editables (nombre, artista y portada recortable, sin tocar los archivos); edición de etiquetas;
  escaneo incremental que se puede pausar.
- **Listas y favoritos** (importar/exportar M3U8) e **historial** (se puede desactivar y borrar).
- **Vista rápida** desde el Explorador de Windows (atajo global, y opcionalmente barra espaciadora).
- **Cristal real**: el escritorio y las aplicaciones de detrás se ven a través de la ventana, desenfocados
  (Esmerilado) o nítidos (Transparente), también en segundo plano; transparencia ajustable o modo Opaco.
- **Temas**: galería de 10 temas con vista previa y editor de temas propios (colores, materiales, burbujas,
  nubes, césped, partículas, reflejos, ondas, movimiento e imagen de fondo; importar y exportar). Reducir
  animaciones; atajos configurables; teclado.

- **Tres modos**: aplicación completa; visor minimalista al abrir un archivo desde el Explorador (la ventana se
  adapta al tamaño de la imagen o del vídeo); y Quick Look con Espacio.
- **Aplicación predeterminada**: Ajustes › Aplicaciones predeterminadas registra AERO Player y abre la
  Configuración de Windows para que lo elijas.
- **Series**: temporadas, siguiente episodio automático y «Continuar viendo».

Consulta [docs/FORMATOS.md](docs/FORMATOS.md) para los formatos probados, [ARCHITECTURE.md](ARCHITECTURE.md)
para el diseño técnico y [TESTING.md](TESTING.md) para las pruebas y mediciones.

## Instalar y ejecutar (para usuarios)

Descarga `AeroPlayer-1.1.0-setup.exe` (instalador propio, no requiere administrador) o
`AeroPlayer-1.1.0-portable.zip` (descomprimir y ejecutar `AeroPlayer.exe`) desde Releases.

> **La versión portable no incluye el 100 % de las funciones del programa.** Es ideal para un USB o un ordenador
> donde no puedes instalar nada, pero la integración con Windows y las actualizaciones con un clic son del
> instalador.

| Lo que puedes hacer | Instalador | Portable |
| --- | :---: | :---: |
| Reproducir, ver, editar, convertir y comprimir | ✔ | ✔ |
| Accesos directos en Inicio y en el escritorio | ✔ | ✘ |
| «Abrir con» y aplicación predeterminada | ✔ | Desde Ajustes (se pierde si mueves la carpeta) |
| Iconos AERO en el Explorador | ✔ | Desde Ajustes |
| Menú del clic derecho del Explorador | ✔ | Desde Ajustes |
| Actualizaciones | Con un clic | Aviso y descarga manual |
| Desinstalar desde Configuración de Windows | ✔ | Borrar la carpeta |
| Funciona sin instalar (USB, PC del trabajo) | ✘ | ✔ |
| Tus ajustes y biblioteca | Se guardan en tu usuario | Se guardan en tu usuario |

El instalador tiene el mismo aspecto que la aplicación: pulsa **Instalar** o **Personalizar…** para elegir
carpeta, accesos directos, el menú del clic derecho, «Abrir con» y el tema con el que empezar. Si ya tenías
AERO Player, lo actualiza conservando tus datos. La primera vez que abras la aplicación verás un tutorial
breve (puedes saltarlo y repetirlo desde Ajustes › Inicio). Para desinstalar: Configuración de Windows ›
Aplicaciones › AERO Player.

**FFmpeg** es necesario solo para *convertir* audio y vídeo (la reproducción funciona sin él). Si no viene
incluido, instálalo con:

```bash
winget install Gyan.FFmpeg
```

**LibreOffice** es opcional: mejora la vista de DOC/PPT/ODP y permite convertir entre formatos de Office.

## Ejecutar desde el código fuente

Requisitos: Windows 10/11 y Python 3.11 o superior.

```bash
python -m venv .venv
```

```bash
.venv\Scripts\pip install -r requirements-dev.txt
```

```bash
.venv\Scripts\python -m aero
```

También puedes pasar archivos: `python -m aero cancion.flac documento.pdf`, o iniciar en la bandeja con
`--background`.

## Pruebas

```bash
.venv\Scripts\python -m pytest
```

Las pruebas de integración generan sus propios medios con FFmpeg (libres de derechos) y usan una carpeta de
datos temporal, así que nunca tocan tu configuración. Para generar archivos de demostración en
`tests/media`: `python tests/make_media.py`.

## Compilar el ejecutable y el instalador

```bash
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Genera `dist\AeroPlayer\` (portable), `dist\AeroPlayer-<versión>-portable.zip`,
`dist\AeroPlayer-<versión>-setup.exe` (instalador propio: `packaging/make_payload.py` comprime el programa y
`packaging/setup.spec` lo une a la interfaz de `aero/installer`) y `dist\SHA256SUMS.txt`. No necesita
Inno Setup.
Con `-BundleFFmpeg C:\ruta\ffmpeg\bin` se incluye FFmpeg en el paquete (respeta su licencia).

## Arquitectura

| Módulo | Responsabilidad |
|---|---|
| `aero/core` | Lógica sin interfaz: configuración, base de datos SQLite/FTS5, escáner, etiquetas, subtítulos, especificación y cola de conversión, herramientas externas |
| `aero/player` | Motor de reproducción (QMediaPlayer) y análisis de audio (NumPy FFT) |
| `aero/ui` | Sistema visual (temas como datos, cristal, estilo propio de controles `style.py`, fondo decorativo `backdrop_fx.py`, iconos), ventana principal, páginas, visores y visualizadores |
| `aero/quicklook` | Atajo global, gancho opcional de Espacio en el Explorador y ventana de vista rápida |
| `aero/installer` | Instalador y desinstalador propios (lógica en `core.py`, ventana de cristal en `ui.py`) |
| `packaging` | PyInstaller (programa e instalador), paquete comprimido, versión e icono |

Decisiones principales:

- **PySide6 (Qt 6, C++)** en lugar de Tauri/Electron: el trabajo pesado (decodificación, render de vídeo
  por GPU, PDF, imágenes) ocurre en código nativo; Python solo orquesta. Arranque en ~1,3 s (medido con el .exe compilado) y bajo consumo
  frente a un navegador embebido, y reproducción de MKV/AVI/subtítulos que WebView2 no ofrece.
- **Qt Multimedia con backend FFmpeg** en lugar de libmpv: viene incluido en PySide6 (LGPL), no requiere
  DLL externas y entrega muestras de audio en tiempo real para el visualizador.
- **calamine (Rust)** para hojas de cálculo: decenas de veces más rápido que openpyxl.
- **Procesos externos sin shell**: FFmpeg y LibreOffice se lanzan con listas de argumentos (nunca se
  construyen comandos con nombres de archivo), sin ventana y cancelables.
- **Vista rápida segura**: `RegisterHotKey` no lee el teclado. El modo Espacio (opcional) solo consume la
  tecla si la ventana activa es el Explorador, el foco está en la lista de archivos, no se está escribiendo y
  no hay modificadores; en cualquier otro caso la pulsación pasa intacta.

## Privacidad

Sin telemetría: AERO Player no envía datos de uso a nadie. Solo se conecta a internet para buscar versiones nuevas
(desactivable) y para las descargas BitTorrent que inicies tú. Datos en `%APPDATA%\AeroPlayer` (preferencias, biblioteca, listas) y
caché en `%LOCALAPPDATA%\AeroPlayer\cache`. Ajustes › Privacidad permite borrar historial, caché o todo.
Desinstalar no borra tus archivos multimedia.

* **Actualizaciones:** una vez al día como mucho, AERO Player pregunta a GitHub si hay una versión nueva. No
  envía datos tuyos y se puede desactivar en Ajustes › Acerca de. Nada se instala sin que pulses «Actualizar».

## Limitaciones conocidas

- La vista de PPTX sin LibreOffice es aproximada (texto, imágenes, tablas, rellenos; sin gráficos ni
  animaciones). DOC, PPT y ODP requieren LibreOffice.
- La pausa de conversiones está disponible para FFmpeg (suspende el proceso); las conversiones de imagen y
  documento son rápidas y solo admiten cancelación.
- El tamaño de los subtítulos externos depende del renderizador de Qt; el desfase sí es ajustable.
- La vista rápida obtiene la selección del Explorador mediante COM; en el escritorio puede no estar
  disponible en algunas configuraciones.
- No hay actualizaciones automáticas.
- Editor de documentos: no conserva notas al pie, comentarios, control de cambios, campos ni cuadros de texto
  (avisa antes de guardar y propone una copia).
- Hojas: openpyxl no conserva los gráficos e imágenes que ya tuviera un XLSX (avisa); XLS y ODS se abren
  como valores. El evaluador de fórmulas cubre las funciones habituales (lista en `aero/office/formula.py`).
- PDF a editable: tablas sin bordes, fórmulas y maquetaciones complejas salen aproximadas; el OCR solo
  reconoce los idiomas instalados en Windows y no detecta negritas ni cursivas.
- Editor de vídeo: la vista previa normal muestra el clip superior, una pista de audio y los textos; el color
  y las transiciones se ven con «Vista previa exacta» o al exportar.
- RAR/7Z con nombres en alfabetos que no son el del sistema no se pueden abrir por dentro (límite de tar.exe).

## Licencia

Copyright © 2026 David Seva Gonzalvez.

* El código es **software libre** bajo la **GPL-3.0-or-later** (`LICENSE`): puedes usarlo, estudiarlo,
  modificarlo y compartirlo. Las versiones que distribuyas tienen que mantener la autoría, publicar su código y
  usar la misma licencia.
* El nombre **«AERO Player»** y su logotipo **no** se conceden con la licencia: una versión modificada debe
  llevar otro nombre.
* Los detalles están en [NOTICE.md](NOTICE.md), y las licencias de terceros en `THIRD_PARTY_NOTICES.md`.
