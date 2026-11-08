# Pruebas de AERO Player 2.2 (2026-11-08)

Entorno: Windows 11 Pro 26200, Python 3.14.3, PySide6 6.12.0, FFmpeg N-123074 (GPL), sin LibreOffice.
Regla de honestidad: **A** = probado automáticamente · **R** = probado con entrada real de Windows o captura real
de pantalla · **P** = pendiente.

## Cómo ejecutar

```bash
.venv\Scripts\python -m pytest
```

```bash
.venv\Scripts\python tools\bench.py docs\bench\despues.json
```

```bash
.venv\Scripts\python tools\visual_check.py docs\capturas
```

```bash
.venv\Scripts\python tools\input_check.py
```

```bash
.venv\Scripts\python tools\stress_check.py --seed 7
```

`stress_check` recorre toda la aplicación (páginas, temas, perfiles, cada archivo en el visor y en Quick Look,
los editores con operaciones al azar, el conversor, el extractor y compresor y las acciones del menú contextual)
con archivos válidos, dañados y vacíos; los diálogos se responden solos y cualquier excepción o fallo de Qt se
anota en `%TEMP%ero_stress_problems.txt`.

`visual_check` coloca una ventana de franjas de colores detrás y captura la pantalla real (`mss`, que incluye
ventanas transparentes). `input_check` usa el ratón y el teclado del sistema: mueve el puntero un instante y abre
una ventana del Explorador que después cierra.

## Resultados

| Criterio de aceptación | Estado | Evidencia |
|---|---|---|
| 1. La ventana deja ver el fondo real | R | `docs/capturas/A1_inicio.png`, `A9_transparente.png` (franjas visibles a través) |
| 2. No es un fondo de color simulado | R | Las franjas se ven desenfocadas (Esmerilado) o nítidas (Transparente); prueba activa e inactiva en `docs/AUDITORIA.md` |
| 3. Aspecto limpio y coherente | R | Capturas de todas las secciones en `docs/capturas/` |
| 4. Navegación fluida | A | Cambio de sección 17 ms de media (`docs/bench/despues.json`) |
| 5. Rendimiento medido y corregido | A | Ver tabla siguiente |
| 6. Registro como aplicación predeterminada | A | `test_associations_register_in_isolated_branch` (rama aislada del registro); comprobación de que nunca se toca `UserChoice` |
| 7. Imagen con doble clic → visor mínimo | A + R | `test_opening_image_uses_minimal_viewer_not_main_window`; `B1`, `B2` |
| 8. Vídeo con doble clic → reproductor mínimo | A + R | `test_opening_video_resizes_to_aspect`; `B3b` (controles), `B4` (vertical) |
| 9. Tamaño de ventana según contenido y monitor | A + R | 5 pruebas de `fit_window`/`keep_aspect`; 800×500 → 800×500, 4000×3000 → 1605×1204, 1280×720 → 1280×720, 720×1280 → 677×1204 |
| 10. Quick Look con Espacio en el Explorador | R | `input_check`: Espacio real sobre `foto.jpg` → vista previa sin abrir la app completa |
| 11. Quick Look desactivable | A + R | Ajuste `quicklook_enabled`; la prueba lo desactiva al terminar |
| 12. Playlists de música y series | A | Pruebas de listas M3U8 y `test_group_series_and_next_episode_queue` |
| 13. Siguiente episodio automático | A | `test_series_autoplays_next_episode` (avanza y marca como visto) |
| 14. Funciones originales | A | Las 35 pruebas de la 1.0 siguen pasando |
| 15. Estable al cambiar de modo | A + R | `visual_check` recorre todos los modos sin errores |
| Clics con transparencia | R | Clic real del sistema sobre la zona más transparente: recibido en Esmerilado (100/90/75/60 %) y Transparente |

**Total 1.1: 54 pruebas automáticas superadas.**

### Versión 1.2

La trazabilidad completa (captura → causa → solución → prueba) está en
[docs/AUDITORIA_v12.md](docs/AUDITORIA_v12.md). Capturas en `docs/capturas/v12/` y mediciones en
`docs/bench/v12.json`.

| Criterio 1.2 | Estado | Evidencia |
|---|---|---|
| 1. Play alineado | A + R | `test_player_bar_controls_share_center_line` (700/1000/1600 px); `A1_inicio` |
| 2. Nombre bajo cada álbum | A + R | `test_album_delegate_elides_long_names`; `A2b_albumes` |
| 3. Menú contextual funcional | A | Acciones conectadas en `LibraryPage._group_menu`; menú comprobado en captura |
| 4-5. Cambiar nombre y portada; se conservan | A | `test_album_customisation_persists` (reabre la base de datos) |
| 6. Bordes inferiores completos | A + R | `test_button_border_is_continuous`, `test_qss_does_not_style_bordered_controls` |
| 7. Bordes suaves | R | Capturas ampliadas de botones, menú, deslizadores y campos |
| 8. Deslizadores fluidos | A | `test_transparency_slider_is_fast_path`; 641 → 14–18 ms por paso |
| 9. Temas prediseñados | A + R | `test_presets_render_with_decorations`; `A7t_tema_*` |
| 10. Personalización de colores y efectos | A | `test_theme_export_import_roundtrip`, `test_user_theme_applies_and_animates_only_dirty_regions` |
| 11. Tiempos de Quick Look de audio alineados | A + R | `test_quicklook_audio_progress_row_aligned` (380/520/900 px); `C0_quicklook_audio` |
| 12. Controles de Quick Look se ocultan | A + R | `test_quicklook_controls_autohide`; `C0b`/`C0c` |
| 13. Hover sin perder bordes | A + R | `test_hover_never_scales_beyond_widget`; `A7c_hover_baldosa` |
| 14. Visualizadores distintos | A | `test_visualizers_are_distinct_and_react` (11 escenas, audio real) |
| 15. Visualizadores en Quick Look | A | `test_quicklook_audio_has_visualizer_selector` |
| 16. Fluida y estable | A | 75 pruebas; tiempos de dibujo y CPU en `docs/AUDITORIA_v12.md` |

**Total 1.2: 75 pruebas automáticas superadas.**

## Versión 2.2

**269 pruebas automáticas superadas, 2 omitidas**, todas ejecutadas en el escritorio oculto «AeroDev» con
`tools/devrun.py`, con el núcleo Rust activo y sin una sola ventana en la pantalla del usuario. Son nuevas 14 en
`tests/test_v22.py` y 12 en `tests/test_v22_rust.py`; estas comparan Rust con Python y comprueban el diagnóstico
del exe.
`ruff check aero tests tools` limpio. `tools/i18n_keys.py --strict`: 1 082 claves en los 6 idiomas.
`visual_check` en el escritorio oculto: 34 capturas, `ERRORS []`.

| Criterio | Tipo | Evidencia |
|---|---|---|
| Desarrollo sin bloquear el escritorio | A + R | `test_devrun_runs_hidden_logs_and_stops`: la tarea corre en el escritorio «AeroDev», queda su registro, su estado y su código de salida, y se detiene con su árbol de procesos. La batería completa, `visual_check`, las medidas y la hoja del Explorador se ejecutaron así |
| Iconos .ico | A | `test_ico_files_have_all_sizes`: 18 categorías, 10 tamaños PNG y paquete al día |
| Iconos en los ProgIDs de AERO | A | `test_register_gives_each_progid_its_category_icon`, en una rama aislada del registro: vídeo, audio, imagen, PDF, comprimido, disco, torrent y documento |
| Iconos en tipos de otros programas | A | `test_foreign_icons_apply_and_restore_exactly`: copia, valor exacto al restaurar, cambios del usuario respetados, ProgIDs compartidos omitidos, el programa no cambia |
| Lo que ejecuta conserva su icono | A | `test_scripts_and_programs_keep_their_icon` |
| **El Explorador real muestra el icono** | A + R | `test_explorer_really_shows_the_aero_icon_and_restores`: Shell de Windows, cada paso en un proceso nuevo. `docs/capturas/v22/explorador_iconos.png`: los 18 iconos dibujados por el Explorador, en claro y oscuro |
| Registro roto reparado | A | `test_chosen_but_missing_detects_broken_choice`, `test_registration_upgrade_only_in_installed_app` |
| Fotos en el visor principal | A | `test_photo_opens_in_main_viewer_and_quicklook_stays_separate`, `test_viewer_flip_zoom_rotate`, `test_minimal_viewer_still_available` |
| Núcleo Rust idéntico a Python | A | `test_scan_dir_matches_python_exactly`, `test_folder_stats_matches_python`, `test_search_matches_python_order_and_accents`, `test_native_errors_are_the_same_classes`, `test_python_fallback_when_native_disabled` |
| Núcleo Rust más rápido | A | `test_native_is_faster_on_big_folder`; `tools/bench_native.py`: búsqueda 2,9×, estadísticas 1,65×, listado 1,5× (`docs/bench/v22_rust.json`) |
| Etiquetas de audio en Rust | A | `test_native_tags_match_mutagen` (MP3, FLAC, M4A, OGG, Opus; WMA y archivos dañados pasan a mutagen), `test_read_tags_many_parallel_with_fallback`; 30× más rápido y escaneo de la biblioteca 4× |
| Extracción más rápida y segura | A | `test_disc_extract_selected_full_and_cancel` y `tests/test_archive_ops.py` (Zip Slip y deshacer al cancelar) siguen pasando con la escritura directa; 2 000 archivos de una ISO: 2,9 → 1,25 s |
| El exe usa el núcleo nativo | A + R | `AeroPlayer.exe --diagnostico`: `frozen: true`, `nativo: true` y 18 iconos en `_internal\icons` |
| NumPy fuera del arranque | A | `test_numpy_not_loaded_at_startup`, `test_analyzer_created_on_first_use` |
| Funciones anteriores | A | El resto de la batería sigue pasando |

Hallazgos:
* En el equipo del usuario, Windows tenía elegido AERO Player para 48 tipos (`UserChoiceLatest`), pero los ProgIDs de
  AERO ya no existían, así que esos archivos no podían abrirse ni mostrar su icono. La 2.2 instalada lo repara una
  vez al arrancar, y solo con claves de AERO.
* `.img`, `.bin`, `.cue`, `.nrg` y `.mdf` no tenían un tipo conocido por el visor: abrirlos desde Windows los habría
  tratado como desconocidos.
* Con el equipo cargado, FFmpeg puede terminar sin informar de su último tiempo y la barra de exportación se quedaba
  en el 75 %. Ahora `progress=end` cuenta como el 100 %.
* `mss` no puede capturar un escritorio oculto (Windows deniega `BitBlt`), así que `visual_check` guarda lo que
  dibuja cada ventana.

## Versión 2.1

**244 pruebas automáticas superadas, 2 omitidas** (`python -m pytest`), de las cuales 20 son nuevas en `tests/test_v21.py`. `ruff check aero tests`
limpio. `tools/visual_check.py docs\capturas21`: `ERRORS []`. `tools/i18n_keys.py --strict`: todas las claves en
los 6 idiomas. `tools/i18n_screens.py --strict`: 0 textos en español, también en el diálogo de torrents y en la
ventana de descargas.

| Criterio | Tipo | Evidencia |
|---|---|---|
| Spotify retirado por completo | A | `test_spotify_removed_and_its_token_deleted` (sin módulo ni referencias en el código; se borra solo el token) |
| Mismo icono para todos los formatos de vídeo, audio e imagen | A | `test_every_media_format_shares_its_category` (18 de vídeo, 20 de audio y 22 de imagen) y `icon_for("pelicula.mkv") == icon_for("otra.webm")` |
| Resto de categorías y desconocidos | A + R | Mismo test (comprimidos, documentos, apps, accesos directos, sistema, fuentes, código, torrent, disco, sin extensión); `test_signature_only_when_extension_does_not_decide`; capturas `docs/capturas/v21/D1`–`D3` |
| Iconos vectoriales, claro/oscuro y en caché | A | `test_icons_one_per_category_cached_with_light_and_dark` (17 imágenes distintas, misma instancia desde la caché, 256 px a escala 2) |
| Carpetas con miles de archivos | A | `test_folder_with_thousands_of_files_lists_and_paints_fast`: 3000 archivos de 17 tipos, listados en < 2 s y pintados en < 1,5 s, en cuadrícula, en lista y al final del desplazamiento |
| ISO, BIN/CUE y NRG: ver y extraer | A | `test_disc_images_list_with_long_names`, `test_disc_extract_selected_full_and_cancel` (extrae lo seleccionado y todo, comprueba 3 MB byte a byte y cancela sin restos) |
| Imágenes ilegibles | A | `test_audio_cd_or_garbage_is_reported_not_invented` |
| Montar y desmontar con Windows | A + R | `test_mount_and_unmount_iso_with_windows` (ISO de IMAPI2 montada de verdad con `Mount-DiskImage`); `test_mount_failure_leaves_no_phantom_drive` |
| Torrent: abrir y leer | A + R | `test_torrent_metadata_and_safe_paths` (rutas `..`, `CON`, `C:` saneadas; archivos dañados rechazados); captura `E1_torrent_dialogo` |
| Torrent: descarga real | A | `test_torrent_downloads_only_selected_files_verified`: enjambre local con tracker HTTP y semilla; solo se escriben los archivos elegidos, verificados por SHA-1 |
| Pausar, reanudar y cancelar | A | `test_torrent_pause_resume_and_cancel` (también reanudar desde el disco, y cancelar solo borra los `.aeropart` propios) |
| Errores y recuperación | A | `test_torrent_udp_tracker_and_errors` (tracker UDP, tracker caído, sin trackers, esquema no compatible) y `test_torrent_corrupt_peer_data_is_never_written` |
| Confirmación y desactivación | A | `test_torrent_dialog_shows_content_and_requires_confirmation`, `test_torrent_disabled_never_starts_the_engine`, `test_explorer_opens_torrent_in_aero_not_windows` |
| Ventana de descargas y centro de tareas | A + R | `test_downloads_window_and_activity_center`; captura `E2_descargas` |
| La aplicación sigue funcionando | A | El resto de pruebas, de 1.0 a 2.0, siguen pasando (la de Spotify se quitó a propósito) |

Hallazgos de la prueba del ejecutable: con la interfaz en inglés, el explorador de comprimidos y discos dejaba
textos en español (filtro «Todos», orden «Nombre/Tamaño/Tipo», «1 archivo en total», «sin comprimir», avisos del
lector y «Etiqueta: …»). Venían de la 2.0. Se han traducido todos, con plurales correctos por idioma, y
`i18n_screens.py` recorre ahora también un ZIP y una ISO abiertos en el explorador para que no vuelva a pasar.
`test_quicklook_controls_autohide` falló una vez por tiempo con el equipo cargado (pasa 3 de 3 por separado): el
margen del desvanecimiento pasa de 2 a 4 s.

Hallazgo durante las pruebas: en las carpetas temporales de Python 3.13 y posteriores (permisos solo para el
usuario), Windows conecta la imagen pero el servicio de discos virtuales no puede leerla, así que no le da letra de
unidad. Antes, AERO dejaba esa unidad fantasma conectada. Ahora la desconecta y lo explica.

## Versión 2.0

**228 pruebas automáticas superadas, 2 omitidas** (`python -m pytest`) tras corregir los 5 fallos que destapó la
primera ejecución (ver abajo). `ruff check aero tests tools` limpio. `tools/visual_check.py docs\capturas\v20`:
`ERRORS []`. `tools/i18n_keys.py --strict`: 1 057/1 057 claves en en, zh-CN, ru, it, de y pt-BR.
`tools/i18n_screens.py --strict`: 0 textos en español en las pantallas recorridas de los 6 idiomas.

| Criterio | Tipo | Evidencia |
|---|---|---|
| 1. Inglés predeterminado y completo | A | `test_english_is_default_language`, `test_all_code_keys_translated_in_every_language`, `i18n_screens en` = 0 |
| 2. Idiomas sin mezclas | A | `i18n_screens` en los 6 idiomas = 0 (ventana principal con todos los apartados y Ajustes, editores de vídeo, imagen, Paint, documento, hoja, presentación, PDF editable, Spotify y lotes); red de seguridad `test_translation_safety_net_on_widgets` |
| 3. Perfiles guardan y aplican | A | `test_first_run_applies_recommended_profile` (el fallo de origen), `test_profiles_create_edit_duplicate_rename_delete_and_persist`, `test_profile_controls_thumbnails_and_proxies` |
| 4. Spotify seguro y dentro de la API | A (red simulada) | PKCE con el ejemplo de la RFC 7636, `state` rechazado, token cifrado (no aparece en claro) y borrado, renovación ante 401, `PREMIUM_REQUIRED`, usuario fuera de la lista, límite de búsqueda, panel conectado y desconectado. **P**: conexión real (necesita un Client ID y una cuenta) |
| 5. Iconos y ejecución bajo petición | A + R | `test_explorer_icons_shortcuts_and_safe_run` (iconos reales del shell, `.lnk` a carpeta y a programa, marca de Internet, 3 confirmaciones y 0 ejecuciones sin aceptar); captura de la cuadrícula y la lista con iconos de Windows |
| 6. Paint en la barra lateral | A + R | `test_paint_in_sidebar_and_as_window`; `docs/capturas/v20/A1_inicio.png` (icono de paleta en la barra) |
| 7. Mover, escalar y girar en el visor | A + R | `test_viewer_direct_manipulation_matches_export` con ratón real de Qt (clic para seleccionar, arrastre, deshacer); captura del visor con tiradores |
| 8. Transformaciones en el proyecto y la exportación | A | Misma prueba: caja roja exportada por FFmpeg a ±4 px de la del visor (escala 30 %, X 150 %, anclaje, recorte y 30°); guardar y abrir conserva los valores; `test_titles_are_transformable_in_export` |
| 9. Sin decoraciones de temporada | A + R | `test_no_seasonal_decorations`; captura de Inicio el 3 de noviembre sin adornos |
| 10. RAM y rendimiento medibles | A | Tabla siguiente; `test_closed_editors_release_memory`, `test_finished_tasks_drop_their_callbacks` |
| 11. Funciones anteriores | A | Las 211 pruebas de 1.9 siguen pasando (3 se actualizaron a propósito: Inicio sin felicitaciones, `PaintWindow.editor`, orden de capas en el marco) |

Fallos de la primera ejecución completa y su causa: la prueba de Inicio esperaba «Feliz Navidad» (cambio
pedido); `PaintWindow.size` es el método de Qt (la prueba usa ahora `w.editor.size`); el orden de capas se guardaba
solo en el marco del elemento; y dos pruebas de borradores veían el borrador de un editor que la prueba anterior
dejó abierto al fallar.

Memoria privada (abrir y cerrar 4 veces cada editor con una imagen de 3000×2000 y recorrer los apartados):

| | Antes | Después |
|---|---|---|
| Editor de imágenes, 4 aperturas | 180 → 209 → 238 → 267 MB (+29 MB cada vez) | 179 → 180 → 180 → 180 MB |
| Tras todos los editores y apartados | 295 MB | **179 MB** |

`tools/bench.py` (`docs/bench/v20_antes.json` → `docs/bench/v20.json`): CPU en reposo tras precalentar 23,8 →
**1,6 %**; reposo con tema animado 4,7 → **0,6 %**; cambio de tamaño 20,3 → 10,7 ms; abrir imagen 10,7 → 5,0 ms;
abrir PDF 35,6 → 7,0 ms; arranque 0,85 → 0,84 s. CPU en reposo con el fondo animado en Inicio (perfilador):
12,5 → 8–9 % (las tarjetas ya no se redibujan en cada fotograma).
## Versión 1.9 (auditoría)

**211 pruebas automáticas superadas, 2 omitidas** (`python -m pytest`, 7 min 26 s), sin código de salida anómalo
al terminar. `ruff check aero tests` limpio. `tools/visual_check.py docs\capturas\v19`: `ERRORS []`.

| Comprobación | Tipo | Resultado |
|---|---|---|
| Miniaturas simultáneas de 6 colores | A | Cada una coincide con su archivo (`test_browser_thumbnails_match_their_files`) |
| DOCX sin números de página | A | Se abre con `page_numbers = False` (`test_doc_editor_does_not_add_page_numbers`) |
| Cierre ordenado | A | `tests/test_v18.py` 5 ejecuciones seguidas con salida 0 (antes 1 de 2 abortaba con 0xC0000409) |
| Reposo del fondo animado | A | Inactividad simulada, batería simulada, vuelta al usar el equipo y ajuste desactivado |
| Deshacer de Paint | A | Capas sin tocar comparten memoria; pintar no altera el estado guardado |
| Borradores en segundo plano | A | Aplazado a mitad de trazo; sin escrituras dobles; descartar cancela la escritura en curso; editor de imágenes |
| Textos traducidos | A | `tools/i18n_check.py`: 618/619 en los 6 idiomas completos (el que falta es el número de versión) |

Coste por fotograma del visualizador a 1400×700 (pintado en memoria, sin componer):

| Escena | 1.8 | 1.9 |
|---|---|---|
| Barras de cristal (por defecto) | 8,25 ms | **2,48 ms** |
| Anillo | 13,83 ms | **4,78 ms** |
| Ecualizador clásico | 1,60 ms | **0,93 ms** |

`tools/bench.py` (`docs/bench/v19_antes.json` → `docs/bench/v19.json`): CPU con el visualizador 11,3 → 9,8 %;
ecualizador clásico en la app 28,9 → 15,6 %; el resto de medidas (arranque 0,79–0,80 s, memoria 91 MB tras
arrancar, cambio de sección 23 ms) sin cambios fuera del ruido. Las medidas por escena duran 2 s y varían
±5 puntos entre ejecuciones.
## Rendimiento (mismo equipo, `tools/bench.py`)

| Medida | Antes (1.0) | Después (1.1) |
|---|---|---|
| Memoria privada tras arrancar | 588 MB | **71 MB** |
| Arranque hasta la primera ventana pintada | 1,11–1,25 s | **0,78–0,92 s** |
| Construcción de la ventana principal | 306–372 ms | **160–166 ms** |
| CPU con el visualizador | 44–54 % | **14–16 %** |
| CPU reproduciendo vídeo | — | 19–25 % (incluye decodificación) |
| Cambio de sección | 25–28 ms (máx. 42) | **17 ms** (máx. 32) |
| Generación del fondo 2560×1440 | 43 ms | **3,8 ms** |
| Abrir imagen en el visor | 20–24 ms | 6–7 ms |
| Visor mínimo con foto de 4000×3000 | — | ~100–118 ms |
| CPU en reposo | ~0–1 % | ~0–1 % |

## Ejecutable compilado (`dist\AeroPlayer\AeroPlayer.exe`, arranque en frío)

| Apertura con doble clic (Modo B) | Ventana visible | Memoria privada |
|---|---|---|
| `foto.jpg` | 0,76 s | 53 MB |
| `clip.mkv` (vídeo 16:9) | 0,62 s | 208 MB (incluye decodificador y GPU) |
| `vertical.mp4` (vídeo 9:16) | 0,52 s | 195 MB |

## Pendiente

* Instalación limpia en otro Windows sin entorno de desarrollo (P).
* Escalado de Windows 150–200 % y lectores de pantalla (P).
* Conversiones con LibreOffice y NVENC (no disponibles en este equipo; se detectan en tiempo real) (P).
* Confirmación manual del usuario en Configuración de Windows tras registrar (lo exige Windows) (P).

### Versión 1.3 (fases A–F)

128 pruebas automáticas (`python -m pytest`), además de las verificaciones manuales indicadas.

| Criterio (§16) | Prueba | Tipo |
|---|---|---|
| 1 Carpeta en la biblioteca con su personalización | `test_folder_library_persists_customisation` | Automática |
| 2 Quick Look de carpetas y navegación | `test_quicklook_folder_navigation` | Automática + captura |
| 3 ZIP y RAR sin extraer | `test_archive_*`, `test_quicklook_opens_image_inside_zip_and_goes_back` | Automática (RAR creado con WinRAR) |
| 4 Protegidos o dañados | `test_archive_detects_encrypted_and_damaged`, RAR con cabecera cifrada | Automática |
| 5 Esquinas redondeadas | `test_quicklook_shade_corners_are_rounded` + capturas ampliadas | Automática + captura real |
| 6 Controles del vídeo al mover el ratón | `test_quicklook_video_area_receives_mouse` + `tools/ql_controls_check.py` (24/24 ciclos) | Automática + puntero real |
| 7 Editar imágenes y exportar copias | `test_editor_window_export_keeps_original` (hash del original) | Automática |
| 8 Guardar y reabrir proyectos | `test_project_roundtrip` (imagen), `test_project_roundtrip_and_missing_media` (vídeo) | Automática |
| 9 Documentos conservando elementos | `test_docx_roundtrip_keeps_elements` | Automática |
| 10 Hojas conservando fórmulas | `test_formulas_evaluate_and_survive_save` | Automática |
| 11 Presentaciones conservando diapositivas | `test_slide_operations_and_roundtrip` (también notas) | Automática |
| 12 PDF a editable con OCR | `test_text_pdf_reconstruction`, `test_scanned_pdf_uses_ocr`, PDF real de 8 páginas | Automática + manual |
| 13 Asociaciones de Windows | `test_compatibility_matrix_only_registers_what_opens`, `test_contextual_opening_from_windows` | Automática (rama de registro aislada) |
| 14 No bloquear la interfaz | `docs/RENDIMIENTO.md` (bloqueo máximo medido ≤ 29 ms), exportaciones y OCR en la cola de tareas | Medición |
| 15 Revisión visual | `docs/capturas/v13/` (capturas reales; las de los editores, con `grab()` porque la pantalla estaba bloqueada) | Capturas |

No verificado a mano por el usuario en esta versión.

### Versión 1.4 (extractor, compresor y menú contextual)

| Criterio | Estado | Evidencia |
|---|---|---|
| Ida y vuelta ZIP, 7Z, TAR.GZ y TAR.XZ, con y sin contraseña, nombres con acentos, emoji y japonés | A | `test_roundtrip_all_formats` (8 casos) |
| Contraseña ausente o errónea: se pide y no deja nada a medias | A | `test_password_missing_and_wrong`, `test_extract_asks_password_and_retries` |
| RAR: crear, extraer y cifrar con el WinRAR instalado | A | `test_rar_with_winrar` |
| Zip Slip, rutas absolutas, bomba de descompresión, archivo dañado, cancelación | A | `test_security_zip_slip_bomb_damaged_cancel`, `test_progress_window_cancel` |
| Menú del Explorador: claves en HKCU, filtros por extensión, separadores, actualización y baja | A | `test_context_menu_register_in_isolated_branch` |
| El Explorador muestra el submenú correcto para .zip, .7z, .rar, .tar.gz, .txt, .jpg, .mkv, .srt y carpetas | R | Enumeración real con `IContextMenu`/`IContextMenu3` del shell de Windows (registro temporal, retirado después) |
| Selección múltiple: 3 procesos lanzados a la vez → un solo ZIP con los 3 archivos | A | `test_explorer_multiselect_one_archive` (procesos reales) |
| Conversión rápida, gestor de comprimidos, «Crear» en Inicio, menú de «Archivos» | A | `test_quick_convert`, `test_archive_manager_and_add`, `test_home_create_menu`, `test_files_browser_context_menu` |
| Auditoría completa sin excepciones ni fallos | A | `stress_check` con semillas 5, 7, 11 y 23: 0 problemas |

### Versión 1.5 (instalador propio, tutorial y temas nuevos)

| Criterio | Estado | Evidencia |
|---|---|---|
| Temas Espacio Negro, Cosmos, Nebulosa, Órbita, Frutiger Metro y Metro Noche se dibujan; temas antiguos sin las claves nuevas siguen cargando | A | `test_new_themes_render_their_decorations`, `test_old_user_theme_without_new_keys_still_loads`, `test_theme_studio_lists_new_decorations` |
| Tutorial: aparece solo en el primer inicio sin archivos, recorre todas las secciones, la tarjeta cabe en la ventana, Esc lo salta, se repite desde Ajustes y el selector cambia el tema | A | `test_tutorial_runs_on_first_start_and_can_be_skipped`, `test_tutorial_not_shown_when_opening_files`, `test_tutorial_theme_picker_changes_theme` |
| Instalador: extrae, actualiza borrando solo restos propios, nunca escribe fuera de la carpeta, subcarpeta propia en carpetas ocupadas, tema inicial sin pisar otros ajustes | A | `test_install_upgrade_and_manifest`, `test_install_never_writes_outside_target`, `test_safe_target_uses_subfolder_for_busy_folders`, `test_initial_theme_is_merged_into_settings`, `test_installer_window_pages` |
| Desinstalación diferida: borra solo lo instalado y conserva archivos ajenos | A | `test_scheduled_removal_deletes_only_installed_files` (proceso real de PowerShell) |
| Instalación real con `dist\AeroPlayer-1.5.0-setup.exe` (clic en «Instalar» por UI Automation) | R | 5 s; 285 archivos, entrada en Aplicaciones, acceso del menú Inicio con destino correcto, menú contextual y «Abrir con» registrados |
| Desinstalación real con AERO Player abierto en la bandeja (`--uninstall --quiet`) | R | La aplicación se cierra sola, desaparecen carpeta, clave, acceso, menú y asociaciones; `%APPDATA%\AeroPlayer` intacto |
| Ordenar una columna con números, fechas, horas y texto (fallo encontrado por la auditoría, semilla 31) | A | `test_sheet_sort_mixed_types` |

### Versión 1.6 (revisión profunda)

| Criterio | Estado | Evidencia |
|---|---|---|
| Comprimir 200 MB + 2.000 archivos: ZIP 4 s, RAR 6 s, 7Z 54 s; primer avance visible en < 0,5 s (7Z: indicador indeterminado mientras comprime el archivo grande) | R | Ventana de progreso real con `arcbench` (scratchpad), cierre automático en 3 s |
| Extraer ZIP, 7Z y RAR de 200 MB: 3,8 / 4,5 / 4,4 s, contenido íntegro (2.001 archivos, archivo grande con su tamaño exacto) | R | Misma prueba |
| Cancelar a mitad (ZIP y RAR): sin restos en el destino, sin Rar.exe huérfano | R | Misma prueba |
| Archivos dañados: error claro y «Reintentar»; la misma operación dos veces → una sola ventana | R/A | Misma prueba; `tests/test_v14.py` |
| Cursor de bordes por ventana (nunca global, se quita al pasar a otra ventana) y redondeo de diálogos y menús | A | `test_edge_cursor_is_per_window_and_never_sticks`, `test_every_window_gets_rounded_corners` |
| Abrir un vídeo o una foto muestra «Editar» (y «Recortar» en fotos) y funcionan | A | `test_open_file_shows_contextual_actions` |
| Fondo animado: estrellas titilan, burbujas flotan; Reducido ≤ 6 elementos; Estático y minimizada sin temporizador | A | `test_background_really_moves_and_can_be_stopped` |
| Consumo en reposo (Inicio con widgets): 0,3 % de un núcleo con fondo estático, ~9 % con fondo animado | R | `cpu_idle.py` (scratchpad), 6 s de medida |
| Ajustes: 15 apartados, búsqueda sin tildes | A | `test_settings_have_sections_and_search` |
| Widgets: datos reales, reordenar arrastrando, tamaño, ocultar, quitar, campos, restaurar y persistencia; sin consultas fuera de Inicio | A | `test_home_widgets_customize_and_persist` |
| Editor de vídeo: abrir desde el visor, dos vídeos, foto encima con posición/escala/opacidad, audio independiente, mover, recortar, deshacer y exportar un MP4 que se decodifica sin errores | A | `test_video_editor_full_flow` |

### Versión 1.7 (multiherramientas)

**Total 1.7: 188 pruebas automáticas superadas, 2 omitidas** (las que necesitan LibreOffice). `ruff` sin avisos.

| Criterio | Estado | Evidencia |
|---|---|---|
| AERO Paint: pincel, formas, relleno con tolerancia, cuentagotas, capas, selección y recorte, deshacer, proyecto `.aeropaint` y exportación PNG/JPG/BMP/WEBP | A | `tests/test_v17.py` (pruebas de Paint) |
| Las 13 transiciones y los 22 efectos exportan con FFmpeg; blanco y negro realmente visible en el vídeo exportado (dispersión de canales) | A | `tests/test_v17.py` |
| Biblioteca de efectos: arrastrar, editar parámetros, quitar, copiar/pegar, guardar, reabrir y exportar; vista previa exacta en pausa | A | `tests/test_v17.py` |
| `.aeroarchive`: firma, metadatos, SHA-256, daño detectado, versión futura rechazada, recuperable como ZIP | A | `tests/test_v17.py` |
| Asociación solo de `.aeroarchive` (rama de registro aislada; `.zip` ajeno intacto; baja limpia) | A | `tests/test_v17.py` |
| Búsqueda universal y cerrar vídeo/documento volviendo a la página anterior | A | `tests/test_v17.py` |
| 8 idiomas: catálogos completos, marcadores intactos, plurales rusos, cambio en caliente, instalador en alemán | A | `tests/test_v17.py`; `tools/i18n_check.py`: 100 % de los textos recogidos en los 6 idiomas completos |
| Ajustes guardados con BOM (Bloc de notas, PowerShell) se leen sin perderse | A | `tests/test_v17.py` |
| Ejecutable compilado en alemán e inglés: barra lateral, búsqueda, tareas, saludo, fecha y widgets traducidos, también para el lector de pantalla | R | UI Automation sobre `dist\AeroPlayer\AeroPlayer.exe` («Start · Bibliothek · Einstellungen…», «Home · Library · Settings…») |
| Instalador compilado: arranca y muestra el selector de idioma | R | UI Automation sobre `dist\AeroPlayer-1.7.0-setup.exe` |
| Estabilidad: recorrido aleatorio de toda la aplicación sin fallos (semillas 43 y 47) tras liberar los reproductores al cerrar el editor de vídeo | A | `tools/stress_check.py` |
| Ventana lista ~0,84 s; ~120 MB de memoria privada; CPU en reposo 0,3 % (fondo estático), 7,3 % (tema tropical animado), 5,8 % (movimiento reducido) | R | `tools/bench.py` y medida de CPU en reposo |

Pendiente en 1.7: actualizaciones automáticas (sin canal firmado), anotaciones de PDF, lotes de renombrado y
redimensionado, perfiles del conversor, vista previa en vivo de varios vídeos, autoguardado de borradores y
traducción completa de los mensajes internos de los editores de documentos (ver ROADMAP.md).

### Versión 1.8 (conversor, lotes y recuperación)

**Total 1.8: 202 pruebas automáticas superadas, 2 omitidas** (necesitan LibreOffice). `ruff` sin avisos,
`visual_check` sin errores (`docs/capturas/v18/`), `stress_check --seed 18`: 0 problemas.

| Criterio | Estado | Evidencia |
|---|---|---|
| «Compatible con móviles / Windows»: H.264 + AAC 4:2:0, perfil y nivel, lado corto limitado (verticales incluidos), máx. 60 fps en móviles | A | `test_compat_presets_use_h264_and_cap_short_side`, `test_estimate_matches_real_encode` (el resultado real es H.264 yuv420p) |
| Tamaño estimado dentro del margen frente a conversiones reales con FFmpeg (H.264, VP9; móviles, Windows, reducido) | A + R | `test_estimate_matches_real_encode`; medida manual: 8 de 8 dentro del rango mostrado en vídeo |
| Avisos: recompresión, reducción de resolución con valores traducibles, contenedor poco compatible, «Conservar» sin aviso | A | `test_preset_notes_and_estimate`, `test_converter_page_shows_estimate` |
| Renombrado por lotes: patrón, numeración, fecha, buscar/reemplazar, mayúsculas, conflictos, intercambio de nombres, deshacer, archivo ajeno intacto | A + R | `test_batch_rename_plan_apply_and_undo`, `test_batch_rename_window`; `D1_renombrar_lote.png` |
| Redimensionado: EXIF aplicado y etiqueta de orientación quitada, metadatos conservados o quitados, sin ampliar, nunca sobrescribe, foto dañada informada, tarea en el historial | A + R | `test_batch_resize_core`, `test_batch_resize_window_registers_task`; `D2_redimensionar_fotos.png` |
| «Archivos» se actualiza solo (archivo nuevo, renombrado) y deja de vigilar al salir | A | `test_files_browser_reloads_after_changes` |
| Borradores: solo con cambios, el archivo del usuario no cambia, no se reescriben si no hay cambios, se ofrecen solo si el proceso ya no existe, recuperación ligada al original, se borran al cerrar bien, ajuste desactivable | A + R | `test_drafts_autosave_and_recover_paint`, `test_drafts_video_and_disabled_setting`, `test_recovery_dialog_lists_and_discards`; `D3_recuperar_borradores.png` |
| Textos nuevos traducidos; cobertura de `i18n_check` 100 % en los 6 idiomas completos | A | `test_new_strings_are_translated`, `tools/i18n_check.py` |

Pendiente en 1.8: borradores de los editores de documentos, hojas y presentaciones; actualizaciones automáticas
(sin canal firmado); anotaciones de PDF; vista previa en vivo de varios vídeos (ver ROADMAP.md).
