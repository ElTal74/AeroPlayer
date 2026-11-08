"""Sistema visual Frutiger Aero: temas como datos (colores, materiales y decoración) y hoja de estilos.

Un tema es un diccionario («spec») que puede venir de la galería de prediseñados o de un tema creado por el
usuario. `theme_from_spec` lo convierte en un `Theme` inmutable que leen todos los componentes.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from PySide6.QtGui import QColor


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    dark: bool
    bg: tuple[tuple[float, str], ...]        # tinte del cristal de la ventana
    orbs: tuple[tuple[str, float, float, float], ...]  # luces: color, x, y, radio (relativos)
    text: str
    text2: str
    accent: str
    accent2: str
    glass: str        # tinte de los paneles
    solid: str        # color opaco para el modo opaco y los menús
    border: str
    viz: tuple[str, ...]
    spec: dict = field(default_factory=dict, compare=False, hash=False)   # materiales y decoración


# ---------------------------------------------------------------------------------------------- decoración
# Cada efecto se puede activar por separado. «amount» es cantidad o densidad (0-1), «size» la escala.
DECO_KEYS = ("bubbles", "clouds", "grass", "particles", "reflections", "waves", "sun", "stars", "nebula", "planet",
             "tropical")
DECO_LABELS = {"bubbles": "Burbujas", "clouds": "Nubes", "grass": "Césped", "particles": "Partículas de luz",
               "reflections": "Reflejos de agua", "waves": "Ondas", "sun": "Resplandor", "stars": "Estrellas",
               "nebula": "Nebulosa", "planet": "Planeta", "tropical": "Playa y palmeras"}
LAYOUTS = {"random": "Repartidos", "bottom": "Abajo", "top": "Arriba", "edges": "En los bordes"}
DIRECTIONS = {"up": "Hacia arriba", "down": "Hacia abajo", "left": "Hacia la izquierda", "right": "Hacia la derecha"}

BASE_SPEC: dict = {
    "name": "Tema",
    "light": False,
    "bg1": "#2c2542", "bg2": "#1f3b47", "bg3": "#3d2a47",
    "accent": "#8fe3ff", "accent2": "#ff9ad5",
    "highlight": "#ffffff",       # tono de reflejos y brillos
    "glow": 0.6,                  # intensidad de brillos (0-1)
    "glass": 0.5,                 # opacidad del cristal de los paneles (0-1)
    "edge": 0.6,                  # intensidad de los bordes de los paneles (0-1)
    "shadow": 0.4,                # intensidad de las sombras (0-1)
    "orb": 1.0,                   # intensidad de las luces de color de las esquinas (0-1)
    "image": "",                  # imagen de fondo propia (ruta) o vacío
    "image_opacity": 0.55,
    "layout": "random",
    "motion": {"speed": 0.0, "dir": "up"},
    "deco": {
        "bubbles": {"on": True, "amount": 0.45, "size": 1.0},
        "clouds": {"on": False, "amount": 0.5, "size": 1.0},
        "grass": {"on": False, "amount": 0.6, "size": 1.0},
        "particles": {"on": False, "amount": 0.4, "size": 1.0},
        "reflections": {"on": False, "amount": 0.5, "size": 1.0},
        "waves": {"on": True, "amount": 0.35, "size": 1.0},
        "sun": {"on": True, "amount": 0.6, "size": 1.0},
        "stars": {"on": False, "amount": 0.5, "size": 1.0},
        "nebula": {"on": False, "amount": 0.5, "size": 1.0},
        "planet": {"on": False, "amount": 0.5, "size": 1.0},
        "tropical": {"on": False, "amount": 0.6, "size": 1.0},
    },
}


def _spec(**kw) -> dict:
    s = copy.deepcopy(BASE_SPEC)
    deco = kw.pop("deco", {})
    s.update(kw)
    for k, v in deco.items():
        s["deco"][k].update(v)
    return s


PRESETS: dict[str, dict] = {
    "burbuja": _spec(name="Burbuja", bg1="#2c2542", bg2="#1f3b47", bg3="#3d2a47", accent="#8fe3ff",
                     accent2="#ff9ad5", glow=0.65, deco={"bubbles": {"amount": 0.5}}),
    "aero": _spec(name="Frutiger Aero Classic", bg1="#0a2c58", bg2="#0b4f80", bg3="#0b7f8f", accent="#4fd2ff",
                  accent2="#3ff0c8", glow=0.75,
                  deco={"bubbles": {"amount": 0.4}, "reflections": {"on": True, "amount": 0.45},
                        "waves": {"amount": 0.5}}),
    "nature": _spec(name="Frutiger Nature", bg1="#0f3d2a", bg2="#1d6b3a", bg3="#5aa83a", accent="#9cff7a",
                    accent2="#ffe36b", highlight="#f4ffd8", glow=0.7, layout="bottom",
                    deco={"grass": {"on": True, "amount": 0.7}, "bubbles": {"amount": 0.25},
                          "particles": {"on": True, "amount": 0.3}, "waves": {"on": False},
                          "clouds": {"on": True, "amount": 0.3}}),
    "cielo": _spec(name="Frutiger Sky", light=True, bg1="#9fd8ff", bg2="#d9f2ff", bg3="#bfeaff", accent="#0a84d6",
                   accent2="#00a88f", glow=0.8,
                   deco={"clouds": {"on": True, "amount": 0.65}, "bubbles": {"amount": 0.2},
                         "waves": {"on": False}}),
    "aqua": _spec(name="Aqua Glass", bg1="#06425a", bg2="#0c7a9c", bg3="#37c6e0", accent="#7ff0ff",
                  accent2="#b3fff1", glow=0.8,
                  deco={"bubbles": {"amount": 0.8, "size": 1.15}, "reflections": {"on": True, "amount": 0.55}}),
    "abismo": _spec(name="Ocean", bg1="#020a1c", bg2="#06203f", bg3="#08394f", accent="#3fd4ff", accent2="#38f2c9",
                    glow=0.5, layout="bottom",
                    deco={"waves": {"amount": 0.8}, "reflections": {"on": True, "amount": 0.6},
                          "bubbles": {"amount": 0.35}}),
    "minimal": _spec(name="Minimal Glass", bg1="#1b1e24", bg2="#22262d", bg3="#1d2128", accent="#cfd8e3",
                     accent2="#9fb4c8", glow=0.3, edge=0.45, shadow=0.25,
                     deco={"bubbles": {"on": False}, "waves": {"on": False}, "sun": {"amount": 0.3}}),
    "zen": _spec(name="Zen Crystal", bg1="#1a1f2b", bg2="#232a3a", bg3="#2a2438", accent="#a8c7ff",
                 accent2="#d6b8ff", glow=0.45, edge=0.5,
                 deco={"bubbles": {"amount": 0.12, "size": 1.4}, "waves": {"amount": 0.15},
                       "sun": {"amount": 0.45}}),
    "laguna": _spec(name="Laguna", bg1="#022a30", bg2="#055a62", bg3="#0b9a96", accent="#4ff5e0", accent2="#7dd8ff",
                    deco={"reflections": {"on": True, "amount": 0.4}}),
    "aurora": _spec(name="Aurora", bg1="#170c3a", bg2="#24175e", bg3="#0f4f84", accent="#b98cff", accent2="#4fd8ff",
                    deco={"particles": {"on": True, "amount": 0.35}}),
    # Espacio: estrellas, nebulosas y planetas (sin burbujas ni ondas, que son de agua)
    "espacio_negro": _spec(name="Espacio Negro", bg1="#000000", bg2="#02030a", bg3="#05040e", accent="#d8e6ff",
                           accent2="#9aa8ff", highlight="#e8f0ff", glow=0.35, edge=0.45, shadow=0.6, orb=0.12,
                           deco={"bubbles": {"on": False}, "waves": {"on": False}, "sun": {"on": False},
                                 "stars": {"on": True, "amount": 0.75}}),
    "cosmos": _spec(name="Cosmos", bg1="#05031a", bg2="#120a3a", bg3="#03243f", accent="#7fc8ff", accent2="#c58cff",
                    highlight="#e6ecff", glow=0.55, orb=0.55,
                    deco={"bubbles": {"on": False}, "waves": {"on": False}, "sun": {"on": False},
                          "stars": {"on": True, "amount": 0.6}, "nebula": {"on": True, "amount": 0.45},
                          "planet": {"on": True, "amount": 0.5}, "particles": {"on": True, "amount": 0.15}}),
    "nebulosa": _spec(name="Nebulosa", bg1="#0b0318", bg2="#2a0838", bg3="#0a1a3d", accent="#ff8ad8",
                      accent2="#8fb8ff", highlight="#ffe6f6", glow=0.6,
                      deco={"bubbles": {"on": False}, "waves": {"on": False}, "sun": {"on": False},
                            "stars": {"on": True, "amount": 0.5}, "nebula": {"on": True, "amount": 0.85,
                                                                           "size": 1.2}}),
    "orbita": _spec(name="Órbita", bg1="#01040d", bg2="#041a33", bg3="#0a0f24", accent="#5fd0ff", accent2="#ffcf7a",
                    highlight="#dff4ff", glow=0.6, layout="edges", orb=0.35,
                    deco={"bubbles": {"on": False}, "waves": {"on": False}, "sun": {"amount": 0.35},
                          "stars": {"on": True, "amount": 0.55}, "planet": {"on": True, "amount": 0.9, "size": 1.3},
                          "nebula": {"on": True, "amount": 0.2}}),
    # Tropical: mar turquesa, arena y palmeras vectoriales; burbujas suaves que suben del agua
    "tropical": _spec(name="Tropical", light=True, bg1="#7fd6ef", bg2="#c8f1ff", bg3="#9fe3e0", accent="#0aa6b8",
                      accent2="#ff8a5c", highlight="#fffaf0", glow=0.7, glass=0.6, edge=0.45, shadow=0.3, orb=0.35,
                      deco={"bubbles": {"amount": 0.22, "size": 0.9}, "waves": {"on": False},
                            "sun": {"amount": 0.55}, "clouds": {"on": True, "amount": 0.25},
                            "tropical": {"on": True, "amount": 0.7}}),
    "tropical_atardecer": _spec(name="Atardecer tropical", bg1="#2b1a4a", bg2="#a3456b", bg3="#f08a4b",
                                accent="#ffb36b", accent2="#5fd3c6", highlight="#fff1d6", glow=0.65, orb=0.4,
                                deco={"bubbles": {"amount": 0.12}, "waves": {"on": False}, "sun": {"amount": 0.7},
                                      "tropical": {"on": True, "amount": 0.55},
                                      "particles": {"on": True, "amount": 0.12}}),
}

# Compatibilidad: claves antiguas que sigan en archivos de ajustes.
THEMES = PRESETS
DEFAULT_CUSTOM = {"bg1": "#2c2542", "bg2": "#1f3b47", "accent": "#8fe3ff", "accent2": "#ff9ad5", "light": False}


def normalize_spec(spec: dict | None) -> dict:
    """Completa un spec con los valores por defecto (sirve también para temas importados incompletos)."""
    out = copy.deepcopy(BASE_SPEC)
    if not isinstance(spec, dict):
        return out
    for k, v in spec.items():
        if k == "deco" and isinstance(v, dict):
            for dk, dv in v.items():
                if dk in out["deco"] and isinstance(dv, dict):
                    out["deco"][dk].update({kk: vv for kk, vv in dv.items() if kk in out["deco"][dk]})
        elif k == "motion" and isinstance(v, dict):
            out["motion"].update({kk: vv for kk, vv in v.items() if kk in out["motion"]})
        elif k in out:
            if isinstance(out[k], (int, float)) and not isinstance(out[k], bool) and isinstance(v, (int, float)):
                out[k] = float(v)
            elif type(v) is type(out[k]):
                out[k] = v
    for c in ("bg1", "bg2", "bg3", "accent", "accent2", "highlight"):
        if not QColor(out[c]).isValid():
            out[c] = BASE_SPEC[c]
    return out


def _mix(a: str, b: str, t: float = 0.5) -> str:
    ca, cb = QColor(a).toRgb(), QColor(b).toRgb()
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t), int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def theme_from_spec(key: str, spec: dict) -> Theme:
    s = normalize_spec(spec)
    light = bool(s["light"])
    solid = "#f3faff" if light else QColor(_mix(s["bg1"], "#000000", 0.35)).name()
    return Theme(
        key, s["name"], not light,
        ((0.0, s["bg1"]), (0.5, s["bg2"]), (1.0, s["bg3"])),
        ((s["accent"], 0.12, 0.08, 0.5), (s["accent2"], 0.9, 0.9, 0.5)),
        "#06263f" if light else "#fbf8ff", "#3d5873" if light else "#d6cce8", s["accent"], s["accent2"],
        "#ffffff", solid, "#ffffff",
        (s["accent"], s["accent2"], _mix(s["accent"], "#9affc9"), _mix(s["accent2"], "#b9a2ff"), "#ffe39a"),
        s,
    )


def get_theme(key: str) -> Theme:
    k = key if key in PRESETS else "burbuja"
    return theme_from_spec(k, PRESETS[k])


def custom_theme(c: dict | None) -> Theme:
    """Tema personalizado antiguo (solo colores): se traduce a spec."""
    c = {**DEFAULT_CUSTOM, **(c or {})}
    spec = _spec(name="Personalizado", light=bool(c.get("light")), bg1=c["bg1"], bg2=_mix(c["bg1"], c["bg2"]),
                 bg3=c["bg2"], accent=c["accent"], accent2=c["accent2"])
    return theme_from_spec("custom", spec)


def rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{max(0, min(255, int(alpha * 255)))})"


@dataclass
class GlassStyle:
    """Parámetros de pintado de los paneles derivados de los ajustes y del tema."""
    fill: float          # opacidad del tinte
    solid: bool          # modo alta opacidad (sin cristal)
    border: float
    highlight: float
    glow: float = 0.6
    edge: float = 0.6
    shadow: float = 0.4


def glass_style(theme: Theme, intensity: float, high_opacity: bool) -> GlassStyle:
    s = theme.spec or BASE_SPEC
    glow, edge, shadow = float(s.get("glow", 0.6)), float(s.get("edge", 0.6)), float(s.get("shadow", 0.4))
    if high_opacity:
        return GlassStyle(0.96, True, 0.25, 0.0, glow, edge, shadow)
    intensity = max(0.0, min(1.0, intensity)) * (0.5 + float(s.get("glass", 0.5)))
    border = 0.6 + 0.8 * edge
    if theme.dark:
        return GlassStyle(0.04 + 0.10 * intensity, False, (0.14 + 0.16 * intensity) * border,
                          (0.30 + 0.30 * intensity) * (0.5 + glow), glow, edge, shadow)
    return GlassStyle(0.22 + 0.30 * intensity, False, (0.40 + 0.35 * intensity) * border,
                      (0.55 + 0.4 * intensity) * (0.5 + glow), glow, edge, shadow)


def _assets(t: Theme) -> dict[str, str]:
    """Genera SVG con los colores del tema (interruptores) y devuelve sus rutas."""
    from aero.core.paths import cache_dir

    folder = cache_dir() / "theme"
    folder.mkdir(parents=True, exist_ok=True)
    off_knob = "#ffffff" if t.dark else "#7c93a8"
    files = {
        "switch_off": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 20"><rect x="0.5" y="0.5" width="35" '
                      f'height="19" rx="9.5" fill="{t.text}" fill-opacity="0.12" stroke="{t.text}" stroke-opacity="0.35"/>'
                      f'<circle cx="10" cy="10" r="6" fill="{off_knob}" fill-opacity="0.85"/></svg>',
        "switch_on": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 20"><defs>'
                     f'<linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d8f8ff"/>'
                     f'<stop offset="0.49" stop-color="{t.accent}"/><stop offset="0.5" stop-color="{t.accent}" '
                     f'stop-opacity="0.85"/><stop offset="1" stop-color="{t.accent2}"/></linearGradient>'
                     f'<radialGradient id="k" cx="0.4" cy="0.35" r="0.7"><stop offset="0" stop-color="#ffffff"/>'
                     f'<stop offset="1" stop-color="#d6ecff"/></radialGradient></defs>'
                     f'<rect x="0.5" y="0.5" width="35" height="19" rx="9.5" fill="url(#g)" stroke="#ffffff" '
                     f'stroke-opacity="0.8"/><circle cx="26" cy="10" r="6.5" fill="url(#k)" stroke="#000" '
                     f'stroke-opacity="0.12"/></svg>',
    }
    out = {}
    for name, svg in files.items():
        path = folder / f"{t.key.replace(':', '_')}_{abs(hash(svg)) % 10 ** 8}_{name}.svg"
        try:
            if not path.exists():
                path.write_text(svg, encoding="utf-8")
        except OSError:
            pass
        out[name] = path.as_posix()
    return out


def build_qss(t: Theme, high_opacity: bool) -> str:
    """Hoja de estilos mínima: tipografía, colores y vistas de elementos.

    Botones, campos, pestañas, menús, deslizadores y descripciones NO se estilan aquí: los dibuja
    `aero.ui.style.AeroStyle` con bordes nítidos y continuos. Una regla con borde o fondo en esos
    widgets haría que Qt volviera a su dibujado propio (y a los defectos de borde).
    """
    dark = t.dark
    a = _assets(t)
    hover = rgba("#ffffff", 0.10) if dark else rgba("#ffffff", 0.55)
    sel = rgba(t.accent, 0.30 if dark else 0.24)
    checked = rgba(t.accent, 0.26 if dark else 0.20)
    field_border = rgba("#ffffff", 0.22) if dark else rgba("#0a3a66", 0.22)
    track = rgba("#ffffff", 0.16) if dark else rgba("#0a3a66", 0.16)
    c = QColor(t.accent)
    return f"""
* {{ font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif; font-size: 10pt; color: {t.text}; }}
QWidget:disabled {{ color: {rgba(t.text, 0.4)}; }}
QLabel[role="h1"] {{ font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 19pt; font-weight: 600; }}
QLabel[role="h2"] {{ font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 13pt; font-weight: 600; }}
QLabel[role="h3"] {{ font-size: 11pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {t.text2}; }}
QLabel[role="caption"] {{ color: {t.text2}; font-size: 9pt; }}
QLabel[role="accent"] {{ color: {t.accent}; font-weight: 600; }}
QLabel[role="value"] {{ color: {t.text}; font-size: 9pt; font-weight: 600; }}

QToolButton::menu-indicator {{ image: none; }}
QPushButton[kind="primary"] {{ color: {"#00172a" if dark else "#ffffff"}; font-weight: 600; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 36px; height: 20px; image: url("{a['switch_off']}"); }}
QCheckBox::indicator:checked {{ image: url("{a['switch_on']}"); }}
QCheckBox:focus {{ color: {t.accent}; }}

QProgressBar {{ background: {track}; border: none; border-radius: 5px; max-height: 10px; min-height: 10px;
    text-align: center; font-size: 8pt; color: transparent; }}
QProgressBar::chunk {{ border-radius: 5px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {c.name()},
    stop:1 {QColor(t.accent2).name()}); }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {rgba(t.text, 0.22)}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {rgba(t.text, 0.4)}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: {rgba(t.text, 0.22)}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QAbstractItemView {{ background: transparent; border: none; outline: none; selection-background-color: {sel};
    selection-color: {t.text}; alternate-background-color: {rgba("#ffffff", 0.04) if dark else rgba("#ffffff", 0.35)}; }}
QAbstractItemView::item {{ padding: 4px 6px; border-radius: 8px; }}
QAbstractItemView::item:hover {{ background: {hover}; }}
QAbstractItemView::item:selected {{ background: {checked}; color: {t.text}; }}
QAbstractItemView:focus {{ border: none; }}
QComboBox QAbstractItemView {{ padding: 4px; }}
QTableView {{ gridline-color: transparent; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {t.text2}; border: none; border-bottom: 1px solid {field_border};
    padding: 6px 8px; font-size: 9pt; font-weight: 600; }}
QHeaderView::section:hover {{ color: {t.text}; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QTabWidget::pane {{ border: none; }}

QDialog, QMessageBox, QFileDialog, QInputDialog, QColorDialog {{ background: {t.solid}; }}
QTextBrowser, QPlainTextEdit, QTextEdit {{ background: transparent; border: none; selection-background-color: {sel}; }}
QSplitter::handle {{ background: transparent; }}
QSizeGrip {{ width: 12px; height: 12px; }}
"""
