# Sistema de diseño de AERO Player

Todo lo visual sale de un pequeño número de piezas centrales. Para cambiar el aspecto de la aplicación entera
se toca aquí, no en cada ventana.

## Fichas (tokens)

| Qué | Dónde | Notas |
|---|---|---|
| Colores, fondos, materiales y decoración de cada tema | `aero/ui/theme.py` (`PRESETS`, `BASE_SPEC`) | Un tema es un diccionario: `bg1-3`, `accent`, `accent2`, `highlight`, `glow`, `glass`, `edge`, `shadow`, `orb`, decoraciones y movimiento |
| Radios de esquina | `aero/ui/corners.py` (`RADII`) | ventana 8, panel 14, tarjeta 12, control 8, menú 8, chip 6 |
| Redondeo de ventanas, diálogos y menús | `corners.install(app)` | Pide el redondeo a Windows 11 (también recorta desenfoque y vídeo) |
| Tipografía | `theme.build_qss` | Segoe UI Variable (Display para títulos); roles `h1`, `h2`, `h3`, `muted`, `caption`, `accent` |
| Iconos | `aero/ui/icons.py` | SVG propios de trazo 1,8 px en rejilla 24×24, coloreados y cacheados por tema; nunca mapas de bits |
| Movimiento | `backdrop_fx.MOTION`, `tm().reduce_motion` | Animado, reducido o estático; respeta la preferencia de Windows |

## Componentes compartidos

| Componente | Módulo |
|---|---|
| Ventana de cristal sin marco (bordes, arrastre, botones, redondeo) | `aero/ui/glasswindow.py` (`GlassWindow`) |
| Paneles y tarjetas de cristal | `aero/ui/glass.py` (`GlassPanel`) |
| Botones, interruptores, desplegables, deslizadores, barras de progreso | `aero/ui/style.py` (`AeroStyle`, dibuja todos los controles de Qt) |
| Botones de icono | `glass.IconButton` |
| Notificaciones | `glass.Toast` |
| Secciones plegables | `aero/ui/collapsible.py` |
| Acciones según el tipo de archivo | `aero/ui/file_actions.py` (`ActionBar`) |
| Progreso de operaciones largas | `aero/archive/ui.py` (`ProgressWindow`) + `aero/core/activity.py` |
| Centro de tareas | `aero/ui/task_center.py` |
| Búsqueda universal | `aero/ui/command_palette.py` |
| Tutorial y capa de foco | `aero/ui/tutorial.py` |
| Widgets de Inicio | `aero/ui/home_widgets.py` |
| Ventanas de lotes (renombrar, redimensionar) | `aero/ui/batch_tools.py` + `aero/core/batch.py` |
| Borradores automáticos y recuperación | `aero/core/drafts.py` (`Autosaver`) + `aero/ui/recovery.py` |

## Reglas

* Menos texto: iconos con etiqueta corta; la explicación va en la ayuda emergente.
* Lo avanzado, plegado (`Collapsible`); lo frecuente, a la vista.
* Ningún botón sin función. Si algo no se puede hacer con un tipo de archivo, la acción no aparece.
* El estado nunca depende solo del color: icono + texto (tareas, errores, progreso).
* Animaciones solo con propósito, suspendidas al minimizar o en segundo plano.
* Todos los textos visibles pasan por `aero.i18n.tr` (ver `LOCALIZATION.md`).

## Temas incluidos

Burbuja, Frutiger Aero Classic, Nature, Sky, Aqua Glass, Ocean, Minimal Glass, Zen Crystal, Laguna, Aurora,
Espacio Negro, Cosmos, Nebulosa, Órbita, Tropical y Atardecer tropical. Las ilustraciones (palmeras, mar, planetas,
nebulosas, estrellas) son vectoriales y se dibujan por código: no hay imágenes de baja resolución ni recursos de
terceros. Los temas Metro se retiraron en la 1.7.
