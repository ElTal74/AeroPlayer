# AERO Player y Rust: auditoría y propuesta de migración (2.2)

## 1. Auditoría de la arquitectura actual

| Capa | Lenguaje | Tamaño | Qué hace |
|---|---|---|---|
| `aero/ui` | Python + Qt (PySide6) | 15 900 líneas | Ventanas, páginas, cristal, visualizadores, iconos, tutorial |
| `aero/editors` | Python + Qt | 7 300 | Editor de imágenes, de vídeo (DaVinci-like) y Paint |
| `aero/core` | Python | 5 100 | Ajustes, biblioteca (SQLite), tareas, conversión, perfiles, asociaciones |
| `aero/office` | Python | 3 000 | Documentos, hojas y presentaciones |
| `aero/archive` | Python | 2 600 | Comprimidos e imágenes de disco |
| `aero/files` | Python | 1 700 | Explorador de archivos |
| `aero/torrent` | Python | 1 500 | Motor BitTorrent propio |
| Resto (pdfconv, installer, player, quicklook, i18n) | Python | 3 400 | — |

* **No hay JavaScript ni TypeScript** en AERO Player. Tampoco hay Rust todavía.
* El trabajo pesado **ya es código nativo**, hoy escrito en C, C++ o Rust:

| Dependencia | Lenguaje | Para qué |
|---|---|---|
| Qt 6 (PySide6) | C++ | Interfaz, multimedia, PDF, SVG |
| FFmpeg | C | Decodificar y convertir audio y vídeo |
| Pillow, pillow-heif | C | Imágenes |
| NumPy | C | Espectro de los visualizadores |
| pdfium | C++ | PDF |
| python-calamine | **Rust** | Leer hojas de cálculo |
| pyppmd, pybcj, pycryptodomex | C | Compresión y cifrado de 7Z/ZIP |

* Lo que es Python es el **pegamento**: la lógica de la interfaz, el orden de las operaciones, los formatos simples
  y algunos bucles (listar carpetas, el motor torrent, el lector de imágenes de disco, la biblioteca).

### Lo que cuesta Python hoy (medido en este equipo, `tools/bench.py`, `docs/bench/v21.json`)

| Medida | Valor | De dónde viene |
|---|---|---|
| Arranque hasta la primera ventana | 0,84 s | Importar Python + Qt (~0,4 s) y construir la ventana |
| Memoria tras arrancar | 95 MB | Intérprete + Qt + módulos importados |
| CPU en reposo (20 s después de abrir) | 0,0 % | — |
| Listar 3000 archivos de 17 tipos | < 2 s, la mayoría al leer el disco | `os.scandir` (en C) + crear objetos Python |
| Cambiar de sección | 25 ms | Qt |

Medido en las mismas condiciones (escritorio oculto, 2 pasadas por versión, `docs/bench/v22_antes.json` frente a
`docs/bench/v22.json`):

| Medida | 2.1 | 2.2 |
|---|---|---|
| Importar la aplicación | 324–336 ms | **187–190 ms** |
| Arranque total | 1 027–1 050 ms | **894–956 ms** |
| Memoria tras arrancar | 94–95 MB | 94 MB |

En 2.2 ya se ha aplicado la primera optimización medida: NumPy se carga solo cuando hace falta el
visualizador. Importar la ventana principal baja de 614 ms a 420 ms (`-X importtime`).

## 2. Opciones

### A. Núcleo en Rust, con la interfaz Qt actual (recomendada)

* Se crea un módulo nativo `aero_core` en Rust (PyO3 + maturin, una `.pyd` como la de python-calamine).
* Python pasa a orquestar la interfaz y Rust hace el trabajo intensivo.
* Se migra módulo a módulo, cada uno con sus pruebas y su medición antes y después. Si un módulo no mejora, no se
  cambia.

| Fase | Módulo | Bibliotecas Rust maduras | Ganancia esperada |
|---|---|---|---|
| R1 | Listar carpetas, clasificar por categoría y firma, estadísticas, búsqueda global | `std::fs`, `jwalk`/`ignore`, `rayon` | Carpetas enormes y búsqueda en todo el disco, en paralelo |
| R2 | Miniaturas y caché de imágenes, redimensionado por lotes | `image`, `fast_image_resize`, `zune-jpeg` | Miniaturas 3–10× más rápidas y con menos memoria |
| R3 | Motor BitTorrent e imágenes de disco | `tokio`, `sha1`, `cdfs`/`iso9660` | Más velocidad con muchos pares; SHA-1 nativo |
| R4 | Comprimidos | `zip`, `sevenz-rust`, `tar`, `flate2` | Sustituir partes de py7zr (LGPL) |
| R5 | Biblioteca y metadatos | `lofty`, `rusqlite` | Escaneo de bibliotecas grandes |
| R6 | Herramientas de Windows (asociaciones, Shell, iconos) | `windows-rs` (oficial de Microsoft) | Menos `ctypes`, más seguro |

* Riesgo bajo: la interfaz no cambia y cada fase se puede deshacer.
* Coste: hace falta compilar Rust al construir el paquete, y hay dos lenguajes que mantener.

### B. Reescribir también la interfaz en Rust

| Opción | Estado | Encaje con AERO |
|---|---|---|
| **Slint** | Maduro; licencia GPL-3 o propia | Bueno: declarativo, GPU, efectos. Habría que rehacer cristal, temas y visualizadores |
| **cxx-qt** (KDAB) | Maduro | Mantiene Qt/QML desde Rust; la interfaz habría que reescribirla en QML |
| **egui / iced** | Maduros | Estética de herramienta, difíciles de llevar al estilo Aero de cristal |
| Tauri | Maduro | Usa una vista web (HTML/JS): justo lo que no quieres |

Lo que no tiene equivalente maduro en Rust y obligaría a mantener C/C++ por debajo:

* La reproducción de vídeo con aceleración y subtítulos, que hoy da Qt Multimedia con FFmpeg. En Rust sería `libmpv`
  o `ffmpeg-next`, que siguen siendo C.
* Los editores de documentos DOCX, XLSX y PPTX con edición y diseño.
* La conversión de PDF a editable.

Reescribir 48 000 líneas de interfaz probada llevaría muchos meses. Durante ese tiempo habría funciones perdidas,
justo lo que pides evitar. Tampoco hay garantía de más velocidad en la interfaz, porque Qt ya es C++ y la mayor parte
del tiempo de pintado ocurre ahí.

## 3. Propuesta

1. **Ahora:** fase R1, el núcleo de archivos en Rust.
   * Es lo que más se nota con miles de archivos y en la búsqueda, y donde Python tiene el bucle más caliente.
   * Llevará pruebas de equivalencia: mismo resultado que la versión Python con 3000 y con 100 000 archivos.
   * La versión Python se queda como respaldo si el módulo nativo no está disponible.
2. **Después:** R2–R6, una por versión, con `tools/bench.py` antes y después.
3. **Interfaz:** un prototipo de una sección (por ejemplo Inicio) en Slint y en cxx-qt, midiendo el arranque, la
   memoria y la fluidez frente a la actual. Solo si gana claramente se plantea migrar más.
4. Python se mantiene solo donde no haya alternativa Rust madura o donde no aporte rendimiento.

## 4. Fase R1 hecha (2.2): núcleo de archivos en Rust

Rust 1.99.1 (MSVC) y las Microsoft C++ Build Tools 2022 están instalados, con tu permiso, en segundo plano con
`winget`.

* **Crate `native/aero_core`.** Usa PyO3 0.27 con ABI estable (`abi3-py311`), así que una sola `.pyd` vale para
  Python 3.11 y posteriores. Se compila con `python tools/build_native.py`, sin herramientas extra, y
  `packaging/build.ps1` lo hace automáticamente.
* **Funciones:**
  * `scan_dir`: lista una carpeta, quita ocultos y de sistema, clasifica por extensión y, si hace falta, por firma;
  * `folder_stats`: tamaño de una carpeta, con límites de elementos y de tiempo;
  * `search`: busca por nombre sin distinguir tildes ni mayúsculas, en el mismo orden que `os.walk`, y se puede
    detener;
  * `fold_text`: normaliza el texto (minúsculas y sin tildes) igual que la búsqueda de Python.
* **Una sola fuente de verdad.** Python pasa a Rust las tablas de `aero/core/filetypes.py` (extensiones y firmas),
  así que las dos versiones no pueden discrepar.
* **Sin bloquear la interfaz.** Rust trabaja con el GIL liberado: mientras recorre el disco, otros hilos de Python
  siguen funcionando.
* **Respaldo.** Si la `.pyd` no está, o con `AERO_NO_NATIVE=1`, se usa la versión Python (`aero/core/native.py`).
* **Equivalencia probada** (`tests/test_v22_rust.py`):
  * mismo resultado que Python con ocultos, de sistema, archivos sin extensión, firmas (PNG, texto, ISO, RIFF,
    ftyp), Unicode y emojis, vacíos y subcarpetas;
  * mismas excepciones (`FileNotFoundError`, `NotADirectoryError`);
  * mismo orden de búsqueda y misma normalización de tildes; la búsqueda se puede detener.

### Medido (`tools/bench_native.py`, árbol de 50 000 archivos en 500 carpetas; `docs/bench/v22_rust.json`)

| Operación | Python | Rust | Mejora |
|---|---|---|---|
| Listar y clasificar 5 100 archivos | 64 ms | 42 ms | 1,5× |
| Tamaño de una carpeta con 50 000 archivos | 164 ms | 99 ms | 1,65× |
| Buscar en 50 000 nombres | 396 ms | 135 ms | **2,9×** |
| Otro hilo de Python trabajando a la vez | — | 67 % del tiempo | El GIL queda libre |

Al listar, Rust solo tarda 3–4 ms en recorrer 5 000 entradas; el resto es crear los objetos de Python. Por eso
`FileEntry` usa ahora `slots`. La mejora no es de 10×, porque `os.scandir` de Python ya está escrito en C. Donde más
se nota es en la búsqueda y en las carpetas enormes, y en que la interfaz no se congela mientras tanto.

## 5. Más módulos en Rust y mejoras medidas (2.2)

Antes de mover nada se midió dónde se pierde tiempo de verdad, siempre en las mismas condiciones:

| Candidato | Medido antes | Decisión | Resultado |
|---|---|---|---|
| **Etiquetas de audio** (mutagen, Python puro) | 4,3 ms por canción | **Rust** (`lofty` + `rayon`, en paralelo y sin GIL) | **30× más rápido** (600 canciones: 211 → 7 ms); **escanear la biblioteca 4×** (2 000 canciones nuevas: 1,2 → 0,3 s; lo que queda es SQLite) |
| Extraer ISO y ZIP con muchos archivos | 2,9 s para 2 000 archivos | **Python** (no hacía falta Rust): `resolve()` una vez por carpeta, y escritura directa de los archivos nuevos | **2,3×** (2,9 → 1,25 s; el mínimo del disco es 0,8 s) |
| Miniaturas de fotos | 12,5 ms por foto de 12 MP con Qt, que ya libera el GIL (el otro hilo, al 98 %) | **No**: Qt ya es C++ con libjpeg-turbo | — |
| Extraer 7Z | 175 MB/s; py7zr ya usa liblzma en C | **No**: lo limita el propio LZMA | — |
| Listar ISO | 46 ms con 2 000 archivos | No hace falta | — |
| SHA-1 del torrent | `hashlib` en C, sin GIL | No hace falta | — |

* **Etiquetas.** Mismos campos que con mutagen: título, artista, álbum, artista del álbum, género, año, pista,
  duración (al milisegundo), frecuencia y canales.
  * Rust lee además etiquetas que mutagen ignoraba: RIFF INFO de WAV, AIFF y la frecuencia de Opus.
  * Lo que lofty no entiende (WMA, vídeos MKV/AVI, archivos dañados) se lee con mutagen, como antes.
  * Lo comprueban `test_native_tags_match_mutagen` y `test_read_tags_many_parallel_with_fallback`.
* **Con el disco en frío**, el tiempo del escaneo lo marca la lectura del disco en las dos versiones.

## 6. Siguientes fases

Medidas y descartadas por ahora: miniaturas (Qt ya es más rápido), 7Z (limitado por LZMA) y SHA-1 (ya en C). Quedan
candidatas: la integración con Windows (`windows-rs`, por seguridad más que por velocidad) y, solo si un prototipo
lo justifica midiendo, partes de la interfaz.

## 7. Instalación de las herramientas (hecha con tu permiso)

Para compilar Rust en Windows hacen falta dos instalaciones:

| Software | Tamaño aproximado | Licencia | Cómo |
|---|---|---|---|
| Rust (rustup, cargo y rustc estables) | ~1,5 GB | MIT / Apache-2.0 | `winget install Rustlang.Rustup` (solo para tu usuario) |
| Microsoft C++ Build Tools (enlazador MSVC y Windows SDK) | ~5–7 GB | Licencia gratuita de Microsoft | `winget install Microsoft.VisualStudio.2022.BuildTools` con la carga «Desarrollo para el escritorio con C++». Pide confirmación de administrador |

Instalado el 8 de noviembre de 2026 con tu permiso: Rust 1.99.1 (`stable-x86_64-pc-windows-msvc`) y Build Tools
2022 (`C:\Program Files (x86)\Microsoft Visual Studio2\BuildTools`). Para quitarlos: Configuración ›
Aplicaciones, o `rustup self uninstall`.
