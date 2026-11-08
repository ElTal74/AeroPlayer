# Auditoría de AERO Player — revisión profunda (2026-11-01)

Fuentes revisadas: PDF de requisitos v1.0 completo (8 páginas, incluida la imagen de referencia de la
página 1), el documento «Revisión profunda y rediseño», todo el código de `aero/`, las pruebas y el
empaquetado. Mediciones base en `docs/bench/antes.json` (herramienta `tools/bench.py`).

## Hallazgos principales

1. **Transparencia**: la ventana usaba el acrílico de DWM (`DWMWA_SYSTEMBACKDROP_TYPE`) y pintaba encima un
   fondo propio con un 58–80 % de opacidad, de modo que en la práctica parecía opaca. Además, Windows
   **desactiva ese acrílico cuando la ventana pasa a segundo plano**.
2. **Rendimiento**: 588 MB de memoria privada tras el arranque, de los que **~480 MB eran búferes de
   OpenBLAS** reservados por NumPy (uno por núcleo), aunque solo se usa la FFT. Con el visualizador
   activo, la CPU llegaba al **44–54 % de un núcleo**: cada fotograma obligaba a repintar también los
   paneles de cristal y el fondo situados debajo.
3. **Apertura de archivos**: todo archivo abría la aplicación completa; no existían ventanas dedicadas
   ni ajuste de tamaño al contenido.
4. **Windows**: no había asociaciones de archivos (solo una entrada opcional «Abrir con» en el instalador).
5. **Quick Look**: funcionaba con atajo global; el modo Espacio era opcional y estaba desactivado por
   defecto.
6. **Series**: no existían (no aparecen en el PDF v1.0, pero sí en la nueva revisión).
7. **Documentación** exigida por el PDF §18 (ARCHITECTURE, TESTING, ROADMAP, TASKS, CONTRIBUTING, LICENSES):
   faltaba.

## Investigación de la transparencia (pruebas reales con capturas)

Ventana de prueba sobre un fondo de franjas de colores, capturada con la ventana activa e inactiva
(`mss`, que también captura ventanas *layered*):

| Técnica | Qué deja ver | Activa | En segundo plano | Decisión |
|---|---|---|---|---|
| Mica (`DWMSBT_MAINWINDOW`) | Solo un tinte del fondo de pantalla, **no** las aplicaciones de detrás | — | Se vuelve opaca | Descartada |
| Acrílico DWM (`DWMSBT_TRANSIENTWINDOW`) | Con marco nativo: contenido desenfocado. Sin marco: gris plano | Sí (con marco) | **Se desactiva** | Descartada |
| `ACCENT_ENABLE_BLURBEHIND` (SetWindowCompositionAttribute) | Nada en Windows 11 26200 (negro) | No | No | Descartada |
| `ACCENT_ENABLE_ACRYLICBLURBEHIND` (SetWindowCompositionAttribute) | Aplicaciones y escritorio **desenfocados** | Sí | **Sí** | **Elegida: modo «Esmerilado»** |
| Alfa real por píxel (`WA_TranslucentBackground`, ventana *layered*) | Aplicaciones y escritorio **nítidos** | Sí | **Sí** | **Elegida: modo «Transparente»** |

El vídeo (`QVideoWidget`) no crea una ventana nativa en Qt 6.12 y decodificó 99–100 fotogramas en todas
las variantes, así que puede usarse dentro de ventanas transparentes y llevar controles superpuestos.

## Tabla de trazabilidad

Prioridad: P0 = imprescindible para la aceptación · P1 = importante · P2 = mejora.

| Requisito | Estado actual | Problema detectado | Modificación necesaria | Prioridad | Cómo se comprobará |
|---|---|---|---|---|---|
| Transparencia real de la ventana completa | Parcial | Fondo propio casi opaco; acrílico DWM desaparece al perder el foco | Ventana sin marco con alfa por píxel + acrílico por composición; fondo propio solo como tinte ajustable | P0 | Captura real con fondo de franjas, ventana activa e inactiva |
| Regular intensidad / modo opaco | Hecho | Rango insuficiente | Modos Esmerilado/Transparente/Opaco + control deslizante de 0–100 % | P0 | Capturas con varios valores |
| Controles interactivos con transparencia | No verificado | Las zonas totalmente transparentes de una ventana *layered* dejan pasar los clics | Opacidad mínima en todo el fondo; prueba de clic real | P0 | Clic real del sistema sobre zona de fondo |
| Mover / redimensionar ventana sin marco | No aplica | — | Barra superior arrastrable, bordes redimensionables, maximizar con doble clic, Snap | P0 | Prueba manual y automatizada de geometría |
| Diseño minimalista Zen + Frutiger Aero | Parcial | Barra lateral ancha, paneles anidados, colinas y fondo pintado que tapan el escritorio | Carcasa de cristal única, barra de iconos estrecha, barra de reproducción integrada que aparece solo con contenido | P0 | Capturas de cada sección |
| Rendimiento: memoria | Mal | 588 MB por OpenBLAS | Limitar OpenBLAS a 1 hilo; carga diferida de NumPy y páginas | P0 | `tools/bench.py` antes/después |
| Rendimiento: CPU visualizador | Mal | 44–54 % de un núcleo | Excluir hijos opacos del repintado del cristal; dibujo por lotes | P0 | `tools/bench.py` |
| Tiempo de arranque | Aceptable (1,1–1,25 s) | Se construyen todas las páginas al inicio | Páginas bajo demanda; modo visor sin ventana principal | P1 | `tools/bench.py` |
| Cambio de sección fluido | Aceptable (25–40 ms) | Captura completa de página para el fundido | Mantener fundido, reducir coste | P1 | `tools/bench.py` |
| Asociaciones de archivos (ProgID, Capabilities, RegisteredApplications) | No existe | — | Registro por usuario y apertura de Configuración de Windows; sin forzar predeterminados | P0 | Prueba en rama de registro aislada + lectura del estado real |
| Ajustes › Aplicaciones predeterminadas | No existe | — | Sección con tipos, estado real y botones | P0 | Captura + prueba unitaria |
| Modo A: aplicación completa | Hecho | — | Rediseño | P0 | Capturas |
| Modo B: visor minimalista imagen | No existe | Abre la app completa | Ventana dedicada con zoom, ajustar, girar, carpeta, pantalla completa, info | P0 | Lanzar con un archivo y capturar |
| Modo B: reproductor minimalista vídeo | No existe | Abre la app completa | Ventana con controles superpuestos que se ocultan, subtítulos, volumen | P0 | Lanzar con un vídeo, contar fotogramas, capturar |
| Modo B: PDF / documentos | No existe | Abre la app completa | Ventana de visor limpia | P1 | Lanzar con PDF y capturar |
| Tamaño automático según contenido y monitor | No existe | — | Cálculo por resolución, proporción, área disponible y pantalla | P0 | Pruebas unitarias del cálculo + capturas (pequeña, grande, vertical, panorámica) |
| Modo C: Quick Look con Espacio | Parcial | Espacio opcional y desactivado por defecto | Espacio activado al activar Quick Look (restringido al Explorador), cerrar con Esc/Espacio | P0 | Prueba real en el Explorador |
| Quick Look desactivable | Hecho | — | Mantener | P0 | Prueba de ajustes |
| Playlists musicales | Hecho | — | Mantener | P0 | Pruebas existentes |
| Playlists de vídeo / series | Parcial | Las listas admiten vídeos pero no hay series | Detección de series y temporadas por nombre/carpeta | P0 | Prueba unitaria del analizador + prueba de cola |
| Siguiente episodio automático | No existe | — | Cola de temporada al reproducir un episodio | P0 | Prueba de integración |
| Recordar dónde se dejó un episodio | Hecho (posiciones) | Sin vista de «Continuar viendo» | Marcar vistos y mostrar progreso | P1 | Prueba de integración |
| Visualizador | Hecho | Coste de CPU | Optimizar | P0 | Medición |
| Visores (imagen, PDF, doc, hoja, presentación) | Hecho | — | Integrar en ventana minimalista | P0 | Pruebas existentes + capturas |
| Conversor (imagen, audio, vídeo, lotes) | Hecho | — | Rediseño visual | P0 | Pruebas existentes |
| Biblioteca, historial, favoritos | Hecho | — | Rediseño visual | P0 | Pruebas existentes |
| Personalización de apariencia | Hecho | — | Añadir modos de cristal | P1 | Capturas |
| Instalador de Windows | Hecho | No registra asociaciones | Registrar capacidades al instalar y eliminarlas al desinstalar | P1 | Compilar instalador |
| Docs del PDF §18 | Faltan | — | ARCHITECTURE, TESTING, ROADMAP, TASKS, CONTRIBUTING, LICENSES | P1 | Revisión de archivos |
| Commits frecuentes y versión estable | No había git | — | Repositorio git, etiqueta `v1.0.0-base`, commits por fase | P1 | `git log` |

## Funciones que se mantienen sin cambios funcionales

Reproductor, subtítulos, visualizador (5 escenas), visores, conversor por lotes, biblioteca con búsqueda,
etiquetas, historial, favoritos, listas M3U8, vista rápida, atajos, temas, instancia única, bandeja.
