# Matriz de formatos

Leyenda: **P** = probado automáticamente con archivos reales generados · **M** = probado en el recorrido de la
interfaz (capturas) · **S** = soportado por el motor pero no probado específicamente.

No se promete que se abra «cualquier» archivo: los archivos dañados o no compatibles muestran un aviso
comprensible y la reproducción salta al siguiente elemento.

## Reproducción (Qt Multimedia, backend FFmpeg, decodificación por hardware D3D11 cuando está disponible)

| Formato | Estado | Notas |
|---|---|---|
| MP3 | P, M | Etiquetas, portada, posición |
| FLAC (24 bits) | P, M | Portada incrustada, visualizador |
| WAV, AAC/M4A, OGG, Opus | S | Mismo motor FFmpeg |
| MKV (H.264 + AAC) | P, M | 71 fotogramas decodificados en 2,3 s en la prueba |
| MP4, MOV, AVI, WebM, WMV | S | Contenedores y códecs que incluya el FFmpeg de Qt |
| Subtítulos incrustados | S | Menú «Subtítulos y pistas» |
| Subtítulos externos SRT, VTT, ASS/SSA | P, M | Carga automática si tienen el mismo nombre; desfase ajustable |
| Archivo dañado | P, M | Aviso + salto al siguiente, sin bloqueos |

## Visor

| Formato | Estado | Motor |
|---|---|---|
| JPG, PNG, GIF (animado), WebP, BMP, TIFF, ICO, SVG | P/M (JPG, PNG) · S resto | Qt Image I/O |
| HEIC, AVIF, PSD | S | Pillow + pillow-heif |
| PDF (búsqueda, zoom, páginas, contraseña) | P, M | Qt PDF (PDFium) |
| DOCX | M | mammoth (vista de lectura; imágenes incluidas) |
| ODT, RTF, Markdown, HTML, TXT y código | M (MD) · S resto | odfpy, striprtf, Markdown |
| XLSX, XLS, XLSB, ODS | P (XLSX), M | calamine (hasta 300 000 filas por hoja) |
| CSV / TSV | P | Detección automática de separador |
| PPTX | M | Render aproximado propio; **alta fidelidad con LibreOffice** |
| DOC, PPT, ODP | Requiere LibreOffice | Conversión a PDF en caché |
| ZIP / CBZ | M | Listado del contenido |

## Conversión

| Origen → destino | Estado | Herramienta |
|---|---|---|
| MKV → MP4 sin recomprimir («Conservar») | P, M | FFmpeg (copia de pistas) |
| Vídeo → WebM VP9 con escalado | P | FFmpeg |
| Vídeo → MP3 (extraer audio) | P | FFmpeg |
| MP3 → M4A (AAC) | M | FFmpeg |
| Vídeo → H.264/H.265/AV1, GIF animado | S | FFmpeg (NVENC/QSV/AMF si funcionan; se prueban en tiempo real) |
| PNG → JPG (sin sobrescribir: «img (1).jpg») | P | Pillow |
| JPG → PNG | M | Pillow |
| PDF → imágenes PNG/JPG, PDF → TXT | P, M | Qt PDF |
| XLSX → CSV (una hoja por archivo) | M | calamine |
| DOCX/MD/TXT → PDF básico, HTML, TXT | P (HTML→PDF) | Qt (sin LibreOffice) |
| DOCX ↔ ODT ↔ PDF, XLSX ↔ ODS, PPTX ↔ ODP | Requiere LibreOffice | `soffice --headless` |
| Archivo dañado | P | Error comprensible, sin archivos parciales |
| Cancelar y reintentar | P | |
