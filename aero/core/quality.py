"""Perfiles de rendimiento y calidad visual.

Los perfiles solo cambian **cómo** se dibuja y cuánto se trabaja en segundo plano; nunca qué funciones hay.
Cada valor actúa sobre un mecanismo real:

* `bubbles`, `clouds`, `particles`, `decor`, `reflections`: multiplican la cantidad de cada decoración del
  tema (0 = apagada) → `backdrop_fx`.
* `motion`, `fps`, `max_moving`, `anim_speed`: fondo animado (fotogramas por segundo, elementos que se mueven
  de verdad y velocidad) → `Backdrop`.
* `viz`: detalle del visualizador («low»: 30 fps y estelas a menor resolución; «high»: estelas más finas).
* `blur`: desenfoque acrílico de Windows (lo calcula la GPU del sistema); sin él, cristal transparente nítido.
* `shadows`: intensidad de sombras de paneles y baldosas.
* `transitions`: transiciones y animaciones de la interfaz.
* `ambient`: tinte del cristal con los colores de la portada.
* `thumbs`: lado en píxeles de las miniaturas que se leen del disco.
* `background`: cuántas tareas en segundo plano pueden ir a la vez (miniaturas, recuentos…).
* `heavy`: cuántas tareas pesadas a la vez (conversiones, exportaciones, OCR).
* `thumb_cache`: cuántas miniaturas se guardan en memoria en «Archivos» (más = volver a una carpeta es
  instantáneo; menos = menos RAM).
* `proxies`: el editor de vídeo empieza editando con copias ligeras de 360p (la exportación usa los originales).

Perfiles predefinidos: Ahorro de recursos, Equilibrado, Alto rendimiento (fluidez y trabajo en paralelo con
efectos moderados), Máxima calidad (todo el detalle) y Personalizado; además, los que guarde el usuario.
"""

from __future__ import annotations

PROFILE_NAMES = {"ultra": "Ahorro de recursos", "balanced": "Equilibrado", "performance": "Alto rendimiento",
                 "high": "Máxima calidad", "custom": "Personalizado"}

PROFILES: dict[str, dict] = {
    "ultra": {"bubbles": 0.35, "clouds": 0.3, "particles": 0.0, "decor": 0.6, "reflections": 0.4,
              "motion": False, "fps": 10, "max_moving": 6, "anim_speed": 1.0, "viz": "low", "blur": False,
              "shadows": 0.4, "transitions": False, "ambient": False, "thumbs": 96, "background": 1, "heavy": 1,
              "thumb_cache": 120, "proxies": True},
    "balanced": {"bubbles": 1.0, "clouds": 1.0, "particles": 0.7, "decor": 1.0, "reflections": 1.0,
                 "motion": True, "fps": 20, "max_moving": 14, "anim_speed": 1.0, "viz": "normal", "blur": True,
                 "shadows": 1.0, "transitions": True, "ambient": True, "thumbs": 152, "background": 2, "heavy": 1,
                 "thumb_cache": 400, "proxies": False},
    "performance": {"bubbles": 0.8, "clouds": 0.8, "particles": 0.5, "decor": 1.0, "reflections": 0.8,
                    "motion": True, "fps": 30, "max_moving": 12, "anim_speed": 1.0, "viz": "normal", "blur": True,
                    "shadows": 0.8, "transitions": True, "ambient": True, "thumbs": 152, "background": 4,
                    "heavy": 2, "thumb_cache": 800, "proxies": False},
    "high": {"bubbles": 1.0, "clouds": 1.0, "particles": 1.0, "decor": 1.0, "reflections": 1.0,
             "motion": True, "fps": 30, "max_moving": 24, "anim_speed": 1.0, "viz": "high", "blur": True,
             "shadows": 1.0, "transitions": True, "ambient": True, "thumbs": 256, "background": 3, "heavy": 2,
             "thumb_cache": 600, "proxies": False},
}
DEFAULT = "balanced"

# Límites de cada valor (para el editor y para validar perfiles importados o antiguos).
RANGES = {
    "bubbles": (0.0, 1.5), "clouds": (0.0, 1.5), "particles": (0.0, 1.5), "decor": (0.0, 1.0),
    "reflections": (0.0, 1.0), "fps": (6, 30), "max_moving": (0, 30), "anim_speed": (0.25, 2.0),
    "shadows": (0.0, 1.0), "thumbs": (64, 320), "background": (1, 4), "heavy": (1, 4),
    "thumb_cache": (50, 2000),
}


def profile_label(key: str) -> str:
    """Nombre visible del perfil (los del usuario se guardan como «user:<nombre>»)."""
    if key.startswith("user:"):
        return key[5:]
    return PROFILE_NAMES.get(key, PROFILE_NAMES[DEFAULT])
VIZ_LEVELS = ("low", "normal", "high")

# Pasos de la optimización automática: se aplican encima del perfil y se deshacen al recuperarse.
AUTO_STEPS = [
    {},
    {"fps_cap": 12, "max_moving_cap": 8, "viz_cap": "normal", "particles_cap": 0.5},
    {"fps_cap": 8, "max_moving_cap": 4, "viz_cap": "low", "particles_cap": 0.0, "motion_off": False},
]


def normalize(values: dict | None, base: str = DEFAULT) -> dict:
    """Completa y acota un perfil (los valores ausentes salen del perfil base)."""
    out = dict(PROFILES.get(base, PROFILES[DEFAULT]))
    for k, v in (values or {}).items():
        if k not in out:
            continue
        ref = out[k]
        try:
            if isinstance(ref, bool):
                out[k] = bool(v)
            elif isinstance(ref, int):
                lo, hi = RANGES[k]
                out[k] = int(min(hi, max(lo, int(v))))
            elif isinstance(ref, float):
                lo, hi = RANGES[k]
                out[k] = float(min(hi, max(lo, float(v))))
            elif k == "viz":
                out[k] = v if v in VIZ_LEVELS else ref
        except (TypeError, ValueError):
            pass
    return out


def resolve(settings) -> dict:
    """Valores efectivos según el perfil elegido en Ajustes."""
    key = settings.get("quality_profile") or DEFAULT
    if key == "custom":
        return normalize(settings.get("quality_custom"))
    if key.startswith("user:"):
        user = settings.get("quality_user") or {}
        if key[5:] not in user:   # perfil borrado o renombrado fuera de la app: se vuelve al predeterminado
            return normalize({})
        return normalize(user.get(key[5:]))
    return normalize({}, key if key in PROFILES else DEFAULT)


def apply_auto(q: dict, step: int) -> dict:
    """Rebaja el perfil `q` según el paso de la optimización automática (0 = sin cambios)."""
    if step <= 0:
        return q
    s = AUTO_STEPS[min(step, len(AUTO_STEPS) - 1)]
    out = dict(q)
    out["fps"] = min(out["fps"], s["fps_cap"])
    out["max_moving"] = min(out["max_moving"], s["max_moving_cap"])
    out["particles"] = min(out["particles"], s["particles_cap"])
    if VIZ_LEVELS.index(out["viz"]) > VIZ_LEVELS.index(s["viz_cap"]):
        out["viz"] = s["viz_cap"]
    return out
