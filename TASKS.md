# Tareas

Estado: A = automatizada (pytest), R = comprobada a mano con el programa real, — = pendiente.

## Hechas en 2.2
| Tarea | Criterio de aceptación | Estado |
|---|---|---|
| Desarrollo sin interferir | Pruebas, compilación y capturas en el escritorio «AeroDev»: sin ventanas visibles, sin foco, registros, estado y detener | A + R |
| Iconos AERO en el Explorador | 18 .ico; ProgIDs de AERO con su icono; opción para tipos ajenos con copia y restauración exacta; Shell real | A + R |
| Fotos en la ventana principal | Desde Windows van al Visor; voltear; Quick Look aparte; visor mínimo opcional | A |
| Registro roto | Si el usuario eligió AERO y faltan sus claves, el programa instalado lo repara una vez | A |
| Rust | Auditoría y propuesta por fases | Documento; instalación pendiente de permiso |

## Hechas en 2.1
| Tarea | Criterio de aceptación | Estado |
|---|---|---|
| Decisión sobre Spotify | Retirado por completo: sin código, pestaña ni pruebas; token borrado al iniciar; decisión documentada | A |
| Iconos AERO por categoría | 17 categorías; todos los vídeos/audios/imágenes con su icono; claro/oscuro; caché; 3000 archivos rápidos | A + R |
| Imágenes de disco | ISO, BIN/CUE, NRG: listar, extraer con progreso y cancelar sin restos; montar y desmontar con Windows | A + R |
| BitTorrent | Metadatos, selección, descarga real verificada, pausa, reanudar, cancelar, errores, desactivable, nada automático | A + R |

## Hechas en 2.0
| Tarea | Criterio de aceptación | Estado |
|---|---|---|
| Inglés por defecto y traducción completa | 1 057 claves en 6 idiomas; 0 textos en español en las pantallas; la compilación se detiene si falta algo | A |
| Perfiles de rendimiento | Se aplican al elegirlos y en el primer arranque; crear, duplicar, renombrar, eliminar; persisten | A |
| Spotify | Retirado en 2.1 (ver `docs/SPOTIFY.md`) | — |
| Archivos con iconos y programas | Iconos reales, accesos directos, nada se ejecuta sin confirmar, aviso de Internet | A + R |
| Paint en la barra lateral | Apartado propio con el mismo editor | A + R |
| Manipulación directa en el visor | Mover, escalar, estirar, recortar, girar, anclaje, guías, deshacer, pistas bloqueadas | A + R |
| Exportación fiel al visor | Diferencia ≤ 4 px con FFmpeg real; títulos transformables | A |
| Sin decoraciones de temporada | Inicio sin adornos ni felicitaciones por fecha | A + R |
| Memoria | Editores cerrados liberan su memoria; tareas terminadas sueltan sus retrollamadas | A |
| Descarga BitTorrent desde Internet | Probada con un enjambre local (tracker HTTP/UDP y semilla); un enjambre público depende de la red | P |
## Hechas en 1.9 (auditoría)
| Tarea | Criterio de aceptación | Estado |
|---|---|---|
| Miniaturas correctas | Varias a la vez: cada miniatura es la de su archivo | A |
| DOCX sin números añadidos | Abrir y guardar conserva la ausencia de números de página | A |
| Cierre sin error interno | Sin tareas en hilos al terminar; pruebas repetidas sin código de salida anómalo | A |
| Visualizador más rápido | Barras 8,3 → 2,5 ms, anillo 13,8 → 4,8 ms por fotograma (1400×700) | A |
| Deshacer de Paint sin copias | Las capas sin tocar comparten memoria; pintar no altera la copia | A |
| Borradores en segundo plano | Sin escrituras a mitad de trazo ni repetidas; descartar cancela la escritura en curso | A |
| Ahorro de energía | Fondo quieto sin actividad o con batería; vuelve al usar el equipo; desactivable | A |
| 533 textos más traducidos | Catálogos completos en 6 idiomas; traducir dos veces no altera | A |
## Hechas en 1.8
| Tarea | Criterio de aceptación | Estado |
|---|---|---|
| Perfiles «Compatible con móviles / Windows» | H.264 + AAC 4:2:0, lado corto limitado, el vídeo resultante se decodifica | A |
| Tamaño estimado y avisos | Dentro del margen frente a conversiones reales; avisos de recompresión, resolución y contenedor | A |
| Renombrado por lotes | Vista previa, conflictos detectados, intercambio de nombres, deshacer, sin tocar archivos ajenos | A |
| Redimensionado por lotes | EXIF aplicado, metadatos, sin ampliar, sin sobrescribir, tarea registrada, foto dañada informada | A |
| Borradores y recuperación | Se guardan solo con cambios, no tocan el original, se ofrecen tras un cierre inesperado y se borran al cerrar bien | A |
| «Archivos» se actualiza solo | Archivos nuevos y renombrados aparecen sin recargar a mano | A |
| Nombres accesibles traducidos | UI Automation del ejecutable en alemán e inglés | R |

## Hechas en 1.7
| Tarea | Criterio de aceptación | Estado |
|---|---|---|
| Quitar temas Metro, añadir Tropical | Sin «metro» en los temas; los nuevos se dibujan | A |
| AERO Paint | Pincel, formas, relleno, cuentagotas, capas, selección, recorte, deshacer, proyecto y 4 formatos | A |
| Biblioteca de efectos y transiciones | Arrastrar, editar, quitar, copiar, guardar, reabrir y exportar con el efecto visible | A |
| Todas las transiciones y efectos exportan | FFmpeg acepta las 13 × 22 combinaciones | A |
| Vista previa con efectos | Fotograma exacto en pausa; vídeo en vivo al reproducir | A |
| Centro de tareas e historial | Compresión, extracción, conversión y exportación registradas; cancelar | A/R |
| `.aeroarchive` | Firma, metadatos, SHA-256, daños detectados, versión futura rechazada, recuperable como ZIP | A |
| Asociación del formato propio | Solo `.aeroarchive`; `.zip` ajeno intacto; baja limpia | A |
| Búsqueda universal | Herramientas, ajustes (sin tildes), biblioteca, recientes, tareas, archivos en segundo plano | A |
| Cerrar vídeo o documento | Vuelve a la página anterior sin cerrar la aplicación | A |
| 8 idiomas | Catálogos completos, marcadores intactos, cambio en caliente, instalador traducido | A/R |
| Desinstalar con opción de borrar ajustes | Desmarcada por defecto; nunca archivos del usuario | R |

## Pendientes
- [ ] Ver ROADMAP.md (1.9)
- [ ] Prueba de instalación en un Windows limpio y con escalado 150–200 % y Narrador
