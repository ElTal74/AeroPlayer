# Avisos de terceros y licencias

AERO Player se distribuye bajo **GPL-3.0-or-later** (archivo `LICENSE`). Se eligió GPL porque
`mutagen` (lectura/edición de etiquetas) es GPL-2.0-or-later y las compilaciones habituales de FFmpeg
para Windows son GPL. Todas las demás dependencias tienen licencias compatibles con GPL-3.0.

No se copia código, iconos ni marcas de otras aplicaciones: los iconos, el fondo y el icono de la
aplicación se dibujan por código en `aero/ui/icons.py` y `aero/ui/glass.py`.

## Bibliotecas incluidas en el paquete

| Componente | Versión | Licencia | Uso |
|---|---|---|---|
| Qt 6 (vía PySide6 / shiboken6) | 6.12.0 | LGPL-3.0 | Interfaz, Qt Multimedia, Qt PDF, SVG |
| Qt Multimedia — backend FFmpeg (incluido en las ruedas de PySide6) | 6.12.0 | LGPL-2.1+/LGPL-3.0 | Decodificación de audio y vídeo |
| PDFium (dentro de Qt PDF) | — | BSD-3-Clause / Apache-2.0 | Renderizado de PDF |
| NumPy | 2.5.4 | BSD-3-Clause | FFT del visualizador |
| Pillow | 13.0.0 | MIT-CMU (HPND) | Conversión de imágenes |
| pillow-heif (incluye libheif, libde265, x265) | 1.8.1 | BSD-3-Clause; libheif LGPL-3.0; x265 GPL-2.0 | HEIC/HEIF/AVIF |
| mutagen | 1.48.1 | GPL-2.0-or-later | Etiquetas y portadas |
| python-calamine (calamine, Rust) | 0.9.0 | MIT | Lectura rápida de XLSX/XLS/ODS |
| mammoth | 1.13.0 | BSD-2-Clause | Vista de DOCX |
| odfpy | 1.4.1 | Apache-2.0 / GPL-2.0 / LGPL-2.1 | Vista de ODT |
| python-pptx (+ lxml, XlsxWriter, typing_extensions) | 1.0.2 | MIT (lxml BSD-3, XlsxWriter BSD-2, PSF) | Vista aproximada de PPTX |
| striprtf | 0.0.35 | BSD-3-Clause | Vista de RTF |
| Markdown | 3.11.2 | BSD-3-Clause | Vista de Markdown |
| cobble, defusedxml | 0.1.4, 0.7.1 | BSD-2-Clause, PSF-2.0 | Dependencias de mammoth |
| pywin32 | 312 | PSF-2.0 | Integración con el Explorador (vista rápida, menú contextual) |
| py7zr (+ pyppmd, pybcj, inflate64, multivolumefile) | 1.1.4 (1.3.1, 1.0.8, 1.0.4, 0.2.3) | LGPL-2.1-or-later | Crear y extraer 7Z (AES-256, LZMA2, nombres Unicode) |
| pycdlib | 1.22.0 | LGPL-2.1-only | Leer y extraer imágenes de disco (ISO 9660, Joliet, Rock Ridge, UDF) sin montarlas. Se distribuye como archivos .py sustituibles en `_internal\pycdlib` |
| Núcleo nativo `aero_core` (Rust): PyO3 0.27, lofty 0.25 (etiquetas), rayon 1.12 (paralelismo), unicode-normalization, flate2, zlib-rs, miniz_oxide, ogg_pager, crossbeam y la biblioteca estándar de Rust 1.99 (lista completa con `cargo metadata` en native/aero_core) | ver columna | MIT / Apache-2.0; algunas también Zlib, 0BSD, Unlicense o Unicode-3.0: todas permisivas y compatibles con GPL-3.0 | Listar, clasificar y buscar archivos; leer etiquetas de audio |
| pyzipper | 0.4.0 | MIT | ZIP cifrado con AES-256 |
| pycryptodomex | 3.24.1 | BSD-2-Clause / dominio público | Cifrado AES de ZIP y 7Z |
| brotli, texttable, psutil | 1.2.1, 1.7.2, 7.2.2 | MIT, MIT, BSD-3-Clause | Dependencias de py7zr |
| Python (intérprete incluido por PyInstaller) | 3.14 | PSF-2.0 | Ejecución |

El código fuente de Qt está disponible en https://code.qt.io y el de PySide6 en
https://code.qt.io/cgit/pyside/pyside-setup.git. Las bibliotecas LGPL se distribuyen como DLL
independientes y pueden sustituirse por versiones modificadas.

## Herramientas externas (opcionales, no incluidas por defecto)

| Herramienta | Licencia | Cómo se usa |
|---|---|---|
| FFmpeg / ffprobe | GPL-3.0 (builds «gpl») o LGPL | Se ejecuta como proceso independiente para convertir audio/vídeo. Se detecta en `bin\` junto al programa, en el `PATH` o en la ruta de Ajustes. Si se incluye en el paquete (`build.ps1 -BundleFFmpeg`), debe acompañarse de su licencia y de la indicación de dónde obtener su código fuente (https://ffmpeg.org). |
| LibreOffice | MPL-2.0 | Opcional. Se detecta si está instalado y se usa en modo `--headless` para vistas de alta fidelidad y conversiones ofimáticas. No se redistribuye. |
| WinRAR (`Rar.exe`) | Licencia propietaria de RARLAB | Opcional. Solo para **crear** archivos RAR (formato propietario): si WinRAR está instalado se usa su `Rar.exe` como proceso independiente. No se redistribuye. Para extraer RAR se usa también, o el `tar.exe` de Windows. |

## Telemetría

Ninguna. AERO Player no realiza conexiones de red.
