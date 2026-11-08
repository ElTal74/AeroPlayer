# Rendimiento y calidad visual (requisito 18) — mediciones 2026-11-02

Herramienta: `python tools/bench_profiles.py docs/bench/perfiles_v13.json`. Cada perfil se mide en un
proceso nuevo, dos veces seguidas (dos pasadas). Datos en bruto de la última pasada: `docs/bench/perfiles_v13.json`.

**Qué es real y qué es simulado**

* «Este equipo»: Ryzen 7 5800X3D (16 hilos), 32 GB, Radeon RX 9060 XT, pantalla 2560×1440. Medido de
  verdad, pero **con el usuario usando el equipo a la vez**: la CPU varía varios puntos entre pasadas.
* «Limitado (simulado)»: el mismo equipo con el proceso dentro de un objeto de trabajo de Windows de
  **2 núcleos y 1,5 GB** como máximo. No reduce la velocidad de cada núcleo, no simula una gráfica integrada
  ni un disco lento. **No se ha probado en un equipo modesto real**, así que no se declara compatibilidad
  con ninguno concreto.

## Resultados (rango de las dos pasadas)

| Medida | Ultra ligero | Equilibrado | Alta calidad | Ultra (lim.) | Equilibrado (lim.) | Alta (lim.) |
|---|---|---|---|---|---|---|
| Arranque hasta la ventana (ms) | 673–692 | 676–706 | 667–681 | 764–772 | 775–792 | 775–776 |
| Memoria en reposo (MB) | 105 | 105 | 105 | 105 | 105 | 105 |
| CPU en reposo (%) | 0,2–4,1¹ | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 |
| CPU con tema animado (%) | 0,0–1,6² | 1,8–6,5 | 4,9–10,9 | 0,0 | 7,0–9,1 | 12,0–17,2 |
| CPU música + visualizador (%) | 7,8–10,3 | 10,9–12,8 | 10,6–15,6 | 5,6 | 9,1–9,4 | 10,0–11,6 |
| CPU vídeo 320×240 (%) | 4,2–6,8 | 6,3–11,5 | 6,8–8,3 | 7,3–8,9 | 4,2–6,8 | 4,7–12,5 |
| Abrir imagen 4000×3000 en Quick Look (ms) | 96–98 | 97–99 | 95–97 | 112–113 | 112–114 | 112 |
| Bloqueo máx. al abrir carpeta de 5 000 archivos (ms) | 35 | 33–35 | 33–36 | 37–48 | 40–60³ | 62³ |
| Bloqueo máx. en reposo (ms) | 6–7 | 6–7 | 6 | 6 | 6–7 | 6–7 |
| Memoria tras el recorrido (MB) | 246–250 | 249–251 | 250–254 | 224–229 | 230–233 | 230–234 |

¹ Un valor aislado de 4,1 % en una pasada (las demás, ≤ 0,2 %): atribuido a actividad del equipo durante la
medición; se vigilará en próximas mediciones.
² En Ultra ligero el fondo no se anima; el resto es el repintado normal de la ventana.
³ La primera cifra es anterior a la colocación por tandas de la cuadrícula (`setLayoutMode(Batched)`), que
lo bajó a 43 ms en la comprobación aislada. En Alta calidad con 2 núcleos simulados una pasada llegó a
62 ms. **Corregido después**: el perfilado mostró que el bloqueo venía del recuento de tamaño en segundo
plano, que acaparaba el intérprete de Python (GIL) con `pathlib` en cada archivo. `kind_of` pasó a una
búsqueda directa en un diccionario (0,3 µs por archivo) y el recuento dejó de clasificar tipos que no se
usaban. Tres pasadas nuevas del peor caso (Alta calidad, 2 núcleos simulados): **17, 23 y 29 ms**.

## Presupuestos y estado

| Presupuesto | Estado |
|---|---|
| Reposo < 1 % de CPU en cualquier perfil | Se cumple salvo un valor aislado (ver ¹) |
| Reposo < 120 MB | Se cumple (105 MB) |
| Arranque < 1 s | Se cumple (0,67–0,79 s) |
| Abrir imagen en Quick Look < 300 ms | Se cumple (≈ 0,1 s) |
| Ningún bloqueo de la interfaz > 50 ms | Se cumple (peor caso medido tras la corrección: 29 ms; ver ³) |

## Qué cambia cada perfil (mecanismos reales)

| | Ultra ligero | Equilibrado | Alta calidad |
|---|---|---|---|
| Fondo animado | No | Sí, 20 fps, 14 elementos | Sí, 30 fps, 24 elementos |
| Burbujas / nubes / partículas | 35 % / 30 % / 0 % | 100 % / 100 % / 70 % | 100 % |
| Desenfoque de Windows | No (cristal nítido) | Sí | Sí |
| Transiciones | No | Sí | Sí |
| Color de portada en el cristal | No | Sí | Sí |
| Visualizador | Sencillo (30 fps, estelas a menor resolución) | Normal | Detallado |
| Miniaturas | 96 px | 152 px | 256 px |
| Tareas en segundo plano / pesadas a la vez | 1 / 1 | 2 / 1 | 3 / 2 |

Las funciones son las mismas en todos (`test_profiles_never_remove_features`).
