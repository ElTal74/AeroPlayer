"""Internacionalización centralizada de AERO Player.

* El texto de origen es el español de España: `tr("Ajustes")`. Los catálogos `locales/<código>.json` asocian
  cada texto de origen con su traducción; lo que falta se muestra en español (y `tools/i18n_check.py` lo
  detecta y cuenta).
* «es-419» (español de Latinoamérica e internacional) solo guarda lo que cambia respecto a España (vídeo →
  video, ordenador → computadora, móvil → celular, Ajustes → Configuración…): nunca duplica textos idénticos.
* Plurales: `ntr("{n} archivo", "{n} archivos", n)` — cada catálogo puede dar sus formas en una lista
  (ruso usa tres: uno, pocos, muchos).
* Números y fechas siguen la configuración regional del idioma (`QLocale`).

Para añadir un idioma: copiar `locales/en.json`, traducir los valores y añadirlo a `LANGUAGES`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LANGUAGES: dict[str, str] = {
    "es-ES": "Español (España)",
    "es-419": "Español (Latinoamérica e internacional)",
    "en": "English",
    "zh-CN": "简体中文",
    "ru": "Русский",
    "it": "Italiano",
    "de": "Deutsch",
    "pt-BR": "Português (Brasil)",
}
SOURCE = "es-ES"
# Idioma predeterminado de la aplicación cuando el usuario no ha elegido otro. El inglés es la referencia: todas
# las claves del código se comprueban en todos los catálogos antes de publicar (tools/i18n_keys.py --strict).
DEFAULT_LANGUAGE = "en"
# Idioma predeterminado de la aplicación cuando el usuario no ha elegido otro (el inglés es la referencia: todos
# los catálogos se comprueban contra él antes de publicar con tools/i18n_keys.py --strict). = "en"
FALLBACK = {"es-419": "es-ES"}           # qué catálogo completa a cada uno
QT_LOCALE = {"es-ES": "es_ES", "es-419": "es_419", "en": "en_US", "zh-CN": "zh_CN", "ru": "ru_RU", "it": "it_IT",
             "de": "de_DE", "pt-BR": "pt_BR"}

_current = SOURCE


@lru_cache(maxsize=None)
def catalog(code: str) -> dict:
    if code == SOURCE:
        return {}
    path = Path(__file__).with_name("locales") / f"{code}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("@")}


def system_language() -> str:
    """Idioma de Windows, si es uno de los disponibles (si no, inglés)."""
    from PySide6.QtCore import QLocale

    name = QLocale.system().name()          # p. ej. «es_MX», «pt_BR», «zh_CN»
    lang = name.split("_")[0]
    if lang == "es":
        return "es-ES" if name.endswith("_ES") else "es-419"
    if lang == "pt":
        return "pt-BR"
    if lang == "zh":
        return "zh-CN"
    return lang if lang in LANGUAGES else "en"


def set_language(code: str) -> str:
    global _current
    _current = code if code in LANGUAGES else SOURCE
    try:
        from PySide6.QtCore import QLocale

        QLocale.setDefault(QLocale(QT_LOCALE[_current]))
    except ImportError:
        pass
    return _current


def language() -> str:
    return _current


SEEN: set[str] | None = set() if __import__("os").environ.get("AERO_I18N_COLLECT") else None


def tr(text: str, **kw) -> str:
    """Texto traducido al idioma actual (con `{marcadores}` opcionales)."""
    if SEEN is not None and text:
        SEEN.add(text)  # herramienta de cobertura (tools/i18n_check.py)
    out = _lookup(text)
    if isinstance(out, list):
        out = out[0]
    return out.format(**kw) if kw else out


def _lookup(text: str):
    code = _current
    while code and code != SOURCE:
        cat = catalog(code)
        if text in cat:
            return cat[text]
        code = FALLBACK.get(code, SOURCE if code != SOURCE else "")
    return text


def plural_index(code: str, n: int) -> int:
    n = abs(int(n))
    if code == "ru":  # uno / pocos / muchos
        if n % 10 == 1 and n % 100 != 11:
            return 0
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return 1
        return 2
    if code == "zh-CN":
        return 0
    return 0 if n == 1 else 1


def ntr(singular: str, plural: str, n: int, **kw) -> str:
    """Plural correcto para cada idioma. La clave del catálogo es el singular en español."""
    forms = _lookup(singular)
    if isinstance(forms, list):
        i = min(plural_index(_current, n), len(forms) - 1)
        text = forms[i]
    elif forms != singular:
        text = forms                         # idioma sin plural distinto (p. ej. chino)
    else:
        text = singular if n == 1 else plural
    return text.format(n=n, **kw)


def number(value: float, decimals: int = 0) -> str:
    from PySide6.QtCore import QLocale

    return QLocale().toString(float(value), "f", decimals)
