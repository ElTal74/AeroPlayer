# Idiomas de AERO Player

## Idiomas

| Código | Idioma | Notas |
|---|---|---|
| es-ES | Español (España) | Idioma de origen: los textos se escriben así en el código |
| es-419 | Español (Latinoamérica e internacional) | Solo guarda lo que cambia: video, computadora, mouse, Configuración, Presiona, Tarjeta madre… El resto se hereda de es-ES (no se duplican textos idénticos) |
| en | English (EE. UU.) | |
| zh-CN | 简体中文 | Chino simplificado |
| ru | Русский | Plural de tres formas (`ntr`) |
| it | Italiano | |
| de | Deutsch | Textos más largos: los botones usan etiquetas compactas |
| pt-BR | Português (Brasil) | Variante inicial; la arquitectura admite pt-PT añadiendo `locales/pt-PT.json` con `FALLBACK = {"pt-PT": "pt-BR"}` |

## Cómo funciona

* `aero/i18n/__init__.py`: `tr("texto en español", **marcadores)` y `ntr(singular, plural, n)`.
* Catálogos: `aero/i18n/locales/<código>.json` (texto de origen → traducción). Lo que falta se muestra en español.
* Los componentes comunes traducen solos: `label()`, ayudas de `IconButton`, apartados y casillas de Ajustes,
  acciones de archivo, tutorial, instalador, centro de tareas, búsqueda, AERO Paint, biblioteca de efectos,
  lotes (renombrar y redimensionar), recuperación de borradores, perfiles y avisos del conversor y los nombres
  accesibles que lee el Narrador.
* Números y fechas siguen el idioma (`QLocale.setDefault`).
* El idioma se elige en el instalador (se guarda en `settings.json`) y se cambia en Ajustes › General › Idioma
  sin reinstalar: la ventana principal se reconstruye al momento.
* Primer arranque sin idioma guardado: **inglés** (DEFAULT_LANGUAGE). El instalador y Ajustes › General ›
  Idioma permiten elegir cualquier otro.

## Comprobar la cobertura

```bash
.venv\Scripts\python tools\i18n_keys.py --strict
.venv\Scripts\python tools\i18n_screens.py --strict
```

* `i18n_keys.py` extrae sin ejecutar nada todas las claves del código: textos de `tr()`/`ntr()`, de los
  componentes que traducen solos y de las tablas de textos (herramientas, efectos, perfiles…). Comprueba que
  estén en los 6 idiomas completos; con `--missing en` lista lo que falta.
* `i18n_screens.py` abre la ventana principal con todos sus apartados, los editores, los lotes, el diálogo de torrents y la ventana de descargas en cada
  idioma y busca textos que sigan en español.
* Las dos se ejecutan en `packaging\build.ps1`: si falta una traducción, **no se genera el paquete**.
* Red de seguridad (`aero/i18n/widgets.py`): al mostrarse cada ventana o diálogo, los textos fijos que son claves
  del catálogo se traducen aunque hayan llegado por una variable.
## Añadir un idioma

1. Copiar `locales/en.json` a `locales/<código>.json` y traducir los valores (conservar `{marcadores}`).
2. Añadir el código a `LANGUAGES` y a `QT_LOCALE`.
3. Ejecutar `tools/i18n_check.py` y las pruebas (`tests/test_v17.py::test_languages_*`).

## Límite conocido

Desde la 1.9 casi todos los textos fijos de la interfaz (botones, casillas, menús, títulos, ayudas, diálogos) pasan
por `tr()`. Siguen en español parte de los mensajes compuestos con datos (p. ej. «Listo: 12 archivos en …») y
algunos errores internos que se muestran tal cual. La cobertura medida está en TESTING.md.