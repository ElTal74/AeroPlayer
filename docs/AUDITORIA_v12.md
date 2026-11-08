# Auditoría 1.2 — refinamiento visual, errores y personalización (2026-11-01)

Fuente: documento «Refinamiento visual, corrección de errores y personalización avanzada» con ocho capturas.
Cada captura se relacionó con su componente en el código antes de modificar nada. Las pruebas citadas están
en `tests/test_v12.py`; las capturas de comprobación, en `docs/capturas/v12/`; las mediciones, en
`docs/bench/v12.json` (`tools/bench.py`).

## Tabla de trazabilidad

| Img. | Problema observado | Componente | Causa técnica encontrada | Solución | Prioridad | Prueba que lo confirma |
|---|---|---|---|---|---|---|
| 1 | Play más bajo que el resto de controles | `PlayerBar` (`player_bar.py`) | La barra medía 84 px y la columna central necesitaba 82 + márgenes: Qt daba a la fila menos altura que el Play (56 px fijo). Un widget de tamaño fijo en una celda pequeña se coloca **arriba** de la celda y se desborda hacia abajo, mientras los botones de 38 px sí quedaban centrados | Nuevo `transport_row()`: la fila mide lo que su control más alto y cada control se añade con `AlignVCenter`. Altura de barra calculada (`PlayerBar.HEIGHT = 92`). Mismo componente en Quick Look | Alta | `test_player_bar_controls_share_center_line` a 700, 1000 y 1600 px (diferencia ≤ 1 px); captura `A1_inicio` |
| 2 | Álbumes sin nombre visible | Pestaña Álbumes (`library_page.py`) | `QListWidget` en modo icono con `uniformItemSizes` y relleno de la hoja de estilos: el texto quedaba fuera de la celda | `AlbumDelegate` (`albums.py`): portada redondeada, nombre centrado (una línea, «…» si es largo) y artista en segunda línea | Alta | `test_album_delegate_elides_long_names`; captura `A2b_albumes` |
| 2 | Sin menú contextual ni edición | Biblioteca | No existía | Menú: Reproducir álbum, Añadir a la cola, Añadir a una lista, Ver información, Editar álbum, Eliminar de la biblioteca. Editor con nombre, artista, portada desde el equipo, recorte (arrastrar y zoom), restaurar original | Alta | `test_album_customisation_persists` (cerrar y reabrir la base de datos) |
| 2 | Eliminar sin distinguir | Biblioteca | — | «Quitar de la biblioteca» oculta sin tocar archivos (tabla `hidden`, el escáner los omite). «Mover archivos a la Papelera…» exige una segunda confirmación y usa la Papelera de Windows (recuperable); nunca se borra definitivamente | Alta | `test_hidden_files_are_not_rescanned` |
| 3 | Borde inferior de botones que desaparece | Hoja de estilos (`theme.py`) | Era intencionado y erróneo: `border-bottom-color: rgba(0,0,0,0.25)` simulaba sombra y en temas oscuros parecía un borde cortado. Igual en campos (`border-top-color`) | Los botones, campos, pestañas, menús, deslizadores y descripciones ya no se estilan por QSS; los dibuja `AeroStyle` (`style.py`) con **un único color de borde en todo el perímetro** | Alta | `test_qss_does_not_style_bordered_controls`, `test_button_border_is_continuous` (mide el píxel superior e inferior) |
| 4 | Bordes con dientes de sierra / líneas borrosas | Todos los controles de cristal | Qt dibuja los bordes de la hoja de estilos centrados en el límite del píxel: una línea de 1 px queda repartida entre dos píxeles a media opacidad y las curvas se ven irregulares. Bordes de foco de 1,5 px | Rectángulos alineados a medio píxel (`crisp()`), suavizado activado, mismo radio por familia (`R_BUTTON = 12`, menús 12, elementos 8), foco dibujado **hacia dentro**, menús y desplegables como ventanas con transparencia real (sin picos oscuros en las esquinas) | Alta | Capturas ampliadas de botones, menú y deslizadores (`A7_ajustes`) |
| 5 | Deslizadores de transparencia lentos | Ajustes › Apariencia | Cada movimiento llamaba a `apply_theme`: reconstruía la hoja de estilos de toda la aplicación (`setStyleSheet`), vaciaba la caché de iconos y regeneraba los fondos. **641 ms por paso** | Camino rápido `apply_levels` → `tm().set_levels` → señal `levels_changed`: solo se repinta. El fondo se guarda en dos capas y la transparencia es la opacidad con la que se pinta. Además, como mucho un cambio por fotograma y valor visible y editable (`ValueSlider`) | Alta | `test_transparency_slider_is_fast_path` (sin `changed`, sin cambiar la hoja de estilos, mediana < 60 ms); bench: **641 → 14–18 ms por paso** |
| 5 | Pocos temas y personalización limitada | `theme.py`, Ajustes | Temas fijos de 5 colores | 10 temas prediseñados (Burbuja, Frutiger Aero Classic, Frutiger Nature, Frutiger Sky, Aqua Glass, Ocean, Minimal Glass, Zen Crystal, Laguna, Aurora) con vista previa antes de aplicar. Editor: 6 colores, brillos, cristal, bordes, sombras, 7 efectos (burbujas, nubes, césped, partículas, reflejos de agua, ondas, resplandor) con cantidad y tamaño, movimiento con velocidad y dirección, distribución, imagen propia. Duplicar, editar, eliminar, importar y exportar | Alta | `test_presets_render_with_decorations`, `test_theme_export_import_roundtrip`, `test_user_theme_applies_and_animates_only_dirty_regions`; capturas `A7t_tema_*` |
| 6 | Tiempo debajo de la barra en Quick Look de audio | `MediaWindow` (`media_window.py`) | Una sola fila con controles cuya anchura mínima sumaba ~518 px dentro de una cápsula de 368 px: Qt los comprimía y el texto del tiempo se montaba sobre el progreso | Cápsula de dos filas: «transcurrido · progreso · total» (anchuras fijas calculadas para «0:00:00») y debajo el transporte centrado con los controles laterales. Por debajo de cierta anchura el volumen se reduce a su botón | Alta | `test_quicklook_audio_progress_row_aligned` a 380, 520 y 900 px; captura `C0_quicklook_audio` |
| 7 | Controles de Quick Look siempre visibles | `MediaWindow` | El ocultado dependía de `underMouse()`, que en la capa flotante (ventana sin foco) quedaba «atascado» en verdadero; además 2,2 s. Al cambiar de archivo, los controles viejos seguían visibles hasta el borrado diferido | Temporizador único reiniciado con la actividad (1,5 s); al salir el puntero de la ventana, 0,5 s; comprobación geométrica de uso (puntero sobre los controles, botón pulsado, menú abierto o deslizador arrastrándose); aparición en 160 ms y desaparición suave en 420 ms; controles viejos ocultados y soltados al momento | Alta | `test_quicklook_controls_autohide`; capturas `C0b`/`C0c` |
| 8 | Hover que agranda y corta el borde | `ActionTile` (`home_page.py`), `IconButton` | El hover escalaba la baldosa a 1,03 × dentro de su propio rectángulo: el borde se salía del widget y Qt lo recortaba. `IconButton` escalaba a 1,06 × con el anillo de foco al límite | Hover por iluminación y elevación (luz de acento desde la base, borde hacia el acento, sombra suave) animado con `HoverLight`, todo dentro de un margen interior. La pulsación aplasta hacia dentro (0,965) y rebota. Ningún hover escala por encima de 1 | Media | `test_hover_never_scales_beyond_widget`; captura `A7c_hover_baldosa` |
| 9 | Pocas visualizaciones | `visualizer.py` | 5 escenas, varias con el mismo esquema | 11 escenas con identidad propia (Aero Waves, Liquid Spectrum, Aurora, Particles, Equalizer Classic, Glass Bars, Energy Flow, Nebula, Water Rings, Fluid Motion, Anillo) sobre el espectro FFT real. Galería con vistas previas, favoritos, paleta (tema, arcoíris, color propio), intensidad, velocidad y sensibilidad, activar/desactivar, pantalla completa. Selector en Quick Look de audio | Alta | `test_visualizers_are_distinct_and_react` (todas dibujan y difieren entre sí con audio real), `test_visualizer_follows_settings_without_stopping`, `test_quicklook_audio_has_visualizer_selector` |

## Rendimiento (Fase 5)

Medido en este equipo mientras se usaba con otras aplicaciones: las cifras de CPU varían unos ±10 puntos entre
ejecuciones. Por eso los visualizadores se midieron además con el tiempo de dibujo por fotograma a 1200 × 650,
que no depende de la carga del sistema.

| Medida | Antes | Ahora |
|---|---|---|
| Paso del deslizador de transparencia | 641 ms | 14–18 ms |
| CPU en reposo (tras precalentar páginas) | 0,31 % | 0,3–0,9 % |
| CPU con tema animado (20 fps, 14 elementos móviles) | — | 4–7 % (aislado) |
| Construcción de Ajustes | — | 117 ms; bloqueo máximo al mostrarla 48 ms |
| Arranque hasta primer pintado | 0,78 s | 0,68–0,72 s |
| Memoria tras arrancar | 71 MB | 80 MB |

Dibujo por fotograma de cada visualizador (1200 × 650, audio real): Aero Waves 3,5 ms · Liquid Spectrum 2,9 ·
Aurora 1,9 · Particles 2,3 · Equalizer Classic 1,9 · Glass Bars 3,1 (antes 12,4) · Energy Flow 3,8 (antes 26) ·
Nebula 1,5 · Water Rings 2,8 · Fluid Motion 1,1 · Anillo 5,5 (antes 9,2). Todas caben de sobra en 16 ms.

Decisiones de rendimiento:

* **El fondo con movimiento es opcional** (velocidad 0 en todos los temas prediseñados). Con movimiento, solo
  14 elementos se animan de verdad; el resto queda fijo en el fondo. Cada fotograma obliga a Windows a
  recomponer la ventana transparente, así que se anima a 20 fps (6 fps si la ventana está en segundo plano),
  se detiene si no se ve, con «Menos animaciones», y mientras se ve un vídeo o el visualizador.
* **Visualizadores**: estelas a media resolución, partículas agrupadas por color y tamaño (12 llamadas de
  dibujo en lugar de cientos), forma de onda con trazo cosmético, halos con textura escalada en lugar de
  degradados por píxel, burbujas prerrenderizadas.
* **Galerías**: las miniaturas se renderizan de una en una (cola diferida) y solo se anima la vista previa
  elegida y la que está bajo el ratón. Las vistas previas usan una señal de demostración para no interferir
  con el análisis del reproductor.

## Pendiente o no verificable aquí

* Escalado de pantalla al 150–200 % y lector de pantalla: no probados en este equipo.
* El aspecto de las animaciones (rebote, iluminación, movimiento del fondo) se ha comprobado con capturas y
  mediciones, no en vídeo.
