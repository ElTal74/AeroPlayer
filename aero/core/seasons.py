"""Saludo según la hora, estación y fechas especiales por región (fecha local del equipo).

Solo se felicitan las fechas de la región elegida (o detectada del sistema): nada de festividades ajenas.
La región «none» deja solo «Buenos días / Buenas tardes / Buenas noches».
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

REGIONS = {
    "auto": "Automática (según Windows)",
    "ES": "España",
    "MX": "México",
    "US": "Estados Unidos",
    "SUR": "Hemisferio sur (Argentina, Chile, Uruguay…)",
    "LATAM": "Otros países de Latinoamérica",
    "none": "Sin fechas especiales",
}
# Territorios (código ISO) → región
_TERRITORY = {"ES": "ES", "MX": "MX", "US": "US", "AR": "SUR", "CL": "SUR", "UY": "SUR", "PY": "SUR", "AU": "SUR",
              "NZ": "SUR", "ZA": "SUR", "CO": "LATAM", "PE": "LATAM", "VE": "LATAM", "EC": "LATAM", "BO": "LATAM",
              "CR": "LATAM", "GT": "LATAM", "DO": "LATAM", "PA": "LATAM", "HN": "LATAM", "SV": "LATAM", "NI": "LATAM",
              "CU": "LATAM", "PR": "US"}
SOUTH = {"SUR"}


@dataclass
class Greeting:
    title: str            # «Buenas noches» o la felicitación del día
    subtitle: str         # fecha y, si procede, la estación
    season: str           # spring | summer | autumn | winter
    occasion: str         # christmas | newyear | halloween | dead | kings | thanksgiving | "" (decoración)


def detect_region() -> str:
    try:
        from PySide6.QtCore import QLocale

        code = QLocale.territoryToCode(QLocale.system().territory())
    except Exception:  # noqa: BLE001
        code = ""
    return _TERRITORY.get(code, "none" if not code else "generic")


def time_greeting(hour: int) -> str:
    return "Buenos días" if 6 <= hour < 13 else "Buenas tardes" if 13 <= hour < 21 else "Buenas noches"


def season_of(day: dt.date, region: str) -> str:
    md = (day.month, day.day)
    north = "spring" if (3, 20) <= md < (6, 21) else "summer" if (6, 21) <= md < (9, 22) else \
        "autumn" if (9, 22) <= md < (12, 21) else "winter"
    if region in SOUTH:
        return {"spring": "autumn", "summer": "winter", "autumn": "spring", "winter": "summer"}[north]
    return north


_SEASON_START = {"spring": (3, 20), "summer": (6, 21), "autumn": (9, 22), "winter": (12, 21)}
_SEASON_WELCOME = {"spring": "Bienvenida la primavera", "summer": "Feliz verano", "autumn": "Bienvenido el otoño",
                   "winter": "Bienvenido el invierno"}


def _thanksgiving(year: int) -> dt.date:
    d = dt.date(year, 11, 1)
    first_thu = d + dt.timedelta(days=(3 - d.weekday()) % 7)
    return first_thu + dt.timedelta(weeks=3)


def occasion(day: dt.date, region: str) -> tuple[str, str]:
    """(clave, felicitación) de la fecha especial de hoy en esa región, o ("", "")."""
    if region in ("none", ""):
        return "", ""
    m, d = day.month, day.day
    if (m, d) in ((12, 31),) or (m == 1 and d <= 2):
        return "newyear", "Feliz Año Nuevo"
    if m == 12 and 24 <= d <= 26 and region != "generic":
        return "christmas", "Feliz Navidad"
    if (m, d) == (1, 6) and region in ("ES", "MX", "LATAM", "SUR"):
        return "kings", "Feliz Día de Reyes"
    if (m, d) == (10, 31) and region in ("ES", "US"):
        return "halloween", "Feliz Halloween"
    if m == 11 and d in (1, 2) and region == "MX":
        return "dead", "Feliz Día de Muertos"
    if region == "US" and day == _thanksgiving(day.year):
        return "thanksgiving", "Feliz Día de Acción de Gracias"
    return "", ""


def _long_date(day: dt.date) -> str:
    """«Lunes, 2 de noviembre» en el idioma de la interfaz (formato regional de Qt)."""
    from aero.i18n import language

    if language().startswith("es"):
        months = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
                  "noviembre", "diciembre")
        days = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
        return f"{days[day.weekday()].capitalize()}, {day.day} de {months[day.month - 1]}"
    from PySide6.QtCore import QDate, QLocale

    text = QLocale().toString(QDate(day.year, day.month, day.day), QLocale.FormatType.LongFormat)
    return text[:1].upper() + text[1:]


def greeting(now: dt.datetime, region: str = "auto", specials: bool = True) -> Greeting:
    if region == "auto":
        region = detect_region()
    day = now.date()
    season = season_of(day, region if region in SOUTH else "")
    occ_key, occ_text = occasion(day, region) if specials else ("", "")
    from aero.i18n import tr

    title = tr(occ_text or time_greeting(now.hour))
    sub = _long_date(day)
    if specials and region not in ("none", ""):
        # La primera semana de cada estación se da la bienvenida; el resto del tiempo, solo la fecha.
        sm, sd = _SEASON_START[season_of(day, "")]
        start = dt.date(day.year, sm, sd)
        if 0 <= (day - start).days < 7:
            sub += " · " + tr(_SEASON_WELCOME[season])
    if occ_text:
        sub = tr(time_greeting(now.hour)) + " · " + sub
    return Greeting(title, sub, season, occ_key)
