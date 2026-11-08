"""Biblioteca de efectos y transiciones del editor de vídeo (registro ampliable).

Cada efecto declara identificador, nombre, categoría, descripción corta, parámetros con su rango y valor por
defecto, a qué tipos de clip se aplica y cómo se traduce a filtros de FFmpeg. La exportación y la vista previa
exacta usan exactamente esos filtros, así que lo que se ve en la biblioteca es lo que sale en el vídeo final.

Para añadir uno nuevo basta con registrarlo aquí: el panel, el inspector y la exportación lo recogen solos.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    lo: float
    hi: float
    default: float
    step: float = 1.0


@dataclass(frozen=True)
class Effect:
    id: str
    name: str
    category: str
    desc: str
    params: tuple[Param, ...] = ()
    kinds: frozenset = frozenset({"video", "image"})
    build: object = None            # función(params) -> lista de filtros (cadena lineal de FFmpeg)

    def defaults(self) -> dict:
        return {p.key: p.default for p in self.params}

    def filters(self, values: dict) -> list[str]:
        v = {**self.defaults(), **{k: values[k] for k in values if k in self.defaults()}}
        for p in self.params:
            v[p.key] = max(p.lo, min(p.hi, float(v[p.key])))
        return list(self.build(v))


CATEGORIES = ["Cinematográficos", "Color", "Desenfoque", "Nitidez", "Luz", "Distorsión", "Estilizados", "Retro",
              "Movimiento", "Corrección"]

_SEPIA = "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131"


def _e(id_, name, cat, desc, params, build, kinds=("video", "image")) -> Effect:
    return Effect(id_, name, cat, desc, tuple(params), frozenset(kinds), build)


EFFECTS: dict[str, Effect] = {e.id: e for e in [
    _e("gblur", "Desenfoque gaussiano", "Desenfoque", "Suaviza toda la imagen",
       [Param("sigma", "Intensidad", 0.5, 40, 6, 0.5)], lambda v: [f"gblur=sigma={v['sigma']:.2f}"]),
    _e("motion_blur", "Desenfoque de movimiento", "Desenfoque", "Estela en una dirección",
       [Param("radius", "Longitud", 1, 60, 12), Param("angle", "Ángulo", 0, 360, 0, 5)],
       lambda v: [f"dblur=angle={v['angle']:.0f}:radius={v['radius']:.0f}"]),
    _e("sharpen", "Nitidez", "Nitidez", "Realza los detalles",
       [Param("amount", "Cantidad", 0.1, 3, 1.0, 0.1)], lambda v: [f"unsharp=5:5:{v['amount']:.2f}:5:5:0"]),
    _e("vignette", "Viñeta", "Cinematográficos", "Oscurece los bordes",
       [Param("strength", "Intensidad", 0.1, 1.5, 0.6, 0.05)],
       lambda v: [f"vignette=angle={0.3 + 0.9 * v['strength'] / 1.5:.3f}"]),
    _e("grain", "Grano de película", "Cinematográficos", "Textura de película analógica",
       [Param("amount", "Cantidad", 1, 60, 18)], lambda v: [f"noise=alls={v['amount']:.0f}:allf=t+u"]),
    _e("cinema", "Look cinematográfico", "Cinematográficos", "Contraste suave y tonos fríos y cálidos",
       [Param("amount", "Intensidad", 0, 1, 0.6, 0.05)],
       lambda v: [f"colorbalance=rs={-0.08 * v['amount']:.3f}:bs={0.10 * v['amount']:.3f}:"
                  f"rh={0.08 * v['amount']:.3f}:bh={-0.06 * v['amount']:.3f}",
                  f"eq=contrast={1 + 0.15 * v['amount']:.3f}:saturation={1 - 0.1 * v['amount']:.3f}"]),
    _e("bw", "Blanco y negro", "Color", "Sin color",
       [Param("contrast", "Contraste", 0.5, 2, 1.1, 0.05)], lambda v: ["hue=s=0", f"eq=contrast={v['contrast']:.2f}"]),
    _e("sepia", "Sepia", "Retro", "Tono marrón de foto antigua", [], lambda v: [_SEPIA]),
    _e("saturation", "Saturación", "Color", "Más o menos color",
       [Param("value", "Saturación", 0, 3, 1.5, 0.05)], lambda v: [f"eq=saturation={v['value']:.2f}"]),
    _e("contrast", "Contraste", "Corrección", "Diferencia entre luces y sombras",
       [Param("value", "Contraste", 0.3, 2.5, 1.3, 0.05)], lambda v: [f"eq=contrast={v['value']:.2f}"]),
    _e("exposure", "Exposición", "Luz", "Aclara u oscurece como la cámara",
       [Param("ev", "Pasos (EV)", -3, 3, 0.7, 0.1)], lambda v: [f"exposure=exposure={v['ev']:.2f}"]),
    _e("temperature", "Temperatura de color", "Color", "Más cálido o más frío",
       [Param("kelvin", "Kelvin", 2000, 12000, 4500, 100)],
       lambda v: [f"colortemperature=temperature={v['kelvin']:.0f}"]),
    _e("tint", "Tinte", "Color", "Verdoso o magenta",
       [Param("value", "Tinte", -1, 1, 0.3, 0.05)],
       lambda v: [f"colorbalance=gm={-0.3 * v['value']:.3f}:rm={0.15 * v['value']:.3f}:bm={0.15 * v['value']:.3f}"]),
    _e("glow", "Resplandor", "Luz", "Luces suaves y brillantes",
       [Param("amount", "Intensidad", 0.1, 1, 0.5, 0.05)],
       lambda v: [f"curves=all='0/0 0.5/{0.5 + 0.15 * v['amount']:.3f} 1/1'",
                  f"exposure=exposure={0.25 * v['amount']:.3f}", f"gblur=sigma={0.6 + 1.5 * v['amount']:.2f}"]),
    _e("chroma", "Aberración cromática", "Distorsión", "Separa los canales de color en los bordes",
       [Param("shift", "Separación", 1, 30, 6)],
       lambda v: [f"rgbashift=rh={-int(v['shift'])}:bh={int(v['shift'])}"]),
    _e("pixelate", "Pixelado", "Estilizados", "Bloques grandes de color",
       [Param("size", "Tamaño del bloque", 2, 64, 16)], lambda v: [f"pixelize=w={int(v['size'])}:h={int(v['size'])}"]),
    _e("negative", "Negativo", "Estilizados", "Invierte los colores", [], lambda v: ["negate"]),
    _e("edges", "Contornos", "Estilizados", "Dibujo de los bordes", [], lambda v: ["edgedetect=mode=colormix"]),
    _e("retro", "Retro", "Retro", "Colores lavados y cálidos con grano",
       [Param("amount", "Intensidad", 0, 1, 0.7, 0.05)],
       lambda v: [f"colortemperature=temperature={6500 - 2200 * v['amount']:.0f}",
                  f"eq=saturation={1 - 0.35 * v['amount']:.2f}:contrast={1 - 0.12 * v['amount']:.2f}",
                  f"noise=alls={8 + 14 * v['amount']:.0f}:allf=t"]),
    _e("zoom", "Zoom", "Movimiento", "Acerca la imagen (recorta y amplía)",
       [Param("factor", "Aumento", 1.05, 3, 1.3, 0.05)],
       lambda v: [f"crop=iw/{v['factor']:.3f}:ih/{v['factor']:.3f}", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]),
    _e("mirror", "Espejo", "Distorsión", "Voltea horizontalmente", [], lambda v: ["hflip"]),
    _e("trail", "Estela", "Movimiento", "Rastro luminoso del movimiento",
       [Param("decay", "Persistencia", 0.5, 0.98, 0.9, 0.01)], lambda v: [f"lagfun=decay={v['decay']:.2f}"],
       kinds=("video",)),
]}


def new_instance(effect_id: str) -> dict:
    e = EFFECTS[effect_id]
    return {"id": effect_id, "on": True, "params": e.defaults()}


def chain_for(instances: list[dict] | None) -> list[str]:
    """Filtros de FFmpeg de los efectos activos de un clip, en orden. Ignora los desconocidos."""
    out: list[str] = []
    for inst in instances or []:
        e = EFFECTS.get(inst.get("id", ""))
        if e is not None and inst.get("on", True):
            out += e.filters(inst.get("params") or {})
    return out


# ---------------------------------------------------------------------------------------------- transiciones
@dataclass(frozen=True)
class Transition:
    id: str
    name: str
    desc: str
    default: float = 0.8
    needs_previous: bool = True   # se ve mejor con un clip anterior debajo (si no, aparece sobre el fondo)


TRANSITIONS: dict[str, Transition] = {t.id: t for t in [
    Transition("dissolve", "Disolución", "El clip aparece poco a poco sobre el anterior"),
    Transition("fade", "Fundido de entrada", "Aparece desde negro", needs_previous=False),
    Transition("fade_black", "Fundido a negro", "El anterior se va a negro y este sale de negro"),
    Transition("fade_white", "Fundido a blanco", "Paso por blanco entre los dos clips"),
    Transition("slide_left", "Deslizar a la izquierda", "Entra desde la derecha"),
    Transition("slide_right", "Deslizar a la derecha", "Entra desde la izquierda"),
    Transition("slide_up", "Deslizar hacia arriba", "Entra desde abajo"),
    Transition("slide_down", "Deslizar hacia abajo", "Entra desde arriba"),
    Transition("zoom_in", "Zoom de entrada", "Entra ampliado y se asienta mientras aparece"),
    Transition("wipe", "Barrido", "Se descubre de izquierda a derecha"),
    Transition("curtain", "Cortina", "Se abre desde el centro"),
    Transition("blur", "Desenfoque", "Entra desenfocado y se enfoca"),
    Transition("spin", "Giro", "Entra girando mientras aparece"),
]}
LEGACY = {"slide": "slide_left"}
EXIT = {"fade_out": "Fundido de salida", "zoom_out": "Zoom de salida"}   # efectos de salida del clip


@dataclass
class TransitionPlan:
    """Lo que la exportación necesita para una transición de entrada de duración d (segundos)."""
    filters: list[str] = field(default_factory=list)   # en la cadena del clip entrante (tiempo local 0…)
    x: str = ""                                         # suma a la posición x del overlay (expresión)
    y: str = ""
    prev_filters: list[str] = field(default_factory=list)   # en la cadena del clip anterior (tiempo local)


def plan(tid: str, d: float, start: float, prev_dur: float | None) -> TransitionPlan:
    """`start`: inicio del clip en la línea de tiempo (para las expresiones del overlay); `prev_dur`: duración
    del clip anterior (fin en su tiempo local) si lo hay."""
    tid = LEGACY.get(tid, tid)
    D = f"{d:.3f}"
    S = f"{start:.3f}"
    p = TransitionPlan()
    alpha_in = f"fade=t=in:st=0:d={D}:alpha=1"
    if tid == "dissolve":
        p.filters = [alpha_in]
    elif tid == "fade":
        p.filters = [f"fade=t=in:st=0:d={D}"]
    elif tid in ("fade_black", "fade_white"):
        color = "white" if tid == "fade_white" else "black"
        half = f"{d / 2:.3f}"
        p.filters = [f"fade=t=in:st=0:d={half}:color={color}"]
        if prev_dur is not None:
            p.prev_filters = [f"fade=t=out:st={max(0.0, prev_dur - d / 2):.3f}:d={half}:color={color}"]
    elif tid.startswith("slide_"):
        prog = f"(1-min(1\\,(t-{S})/{D}))"
        p.filters = []
        if tid == "slide_left":
            p.x = f"+W*{prog}"
        elif tid == "slide_right":
            p.x = f"-W*{prog}"
        elif tid == "slide_up":
            p.y = f"+H*{prog}"
        else:
            p.y = f"-H*{prog}"
    elif tid == "zoom_in":
        p.filters = [f"zoompan=z='if(lt(it\\,{D})\\,1.5-0.5*it/{D}\\,1)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:"
                     f"s=hd1080", "format=yuva420p", alpha_in]
    elif tid in ("wipe", "curtain"):
        cond = f"lt(X\\,W*T/{D})" if tid == "wipe" else f"lt(abs(X-W/2)\\,W/2*T/{D})"
        p.filters = ["format=yuva420p",
                     f"geq=lum='lum(X\\,Y)':cb='cb(X\\,Y)':cr='cr(X\\,Y)':a='if({cond}\\,255\\,0)':"
                     f"enable='lt(t\\,{D})'"]
    elif tid == "blur":
        p.filters = [f"gblur=sigma=18:enable='lt(t\\,{d / 2:.3f})'", f"gblur=sigma=6:enable='between(t\\,"
                     f"{d / 2:.3f}\\,{D})'", alpha_in]
    elif tid == "spin":
        p.filters = ["format=yuva420p", f"rotate='2*PI*max(0\\,1-t/{D})':c=none:ow=iw:oh=ih", alpha_in]
    return p


def max_duration(clip_dur: float, prev_dur: float | None) -> float:
    """Una transición nunca puede durar más que la mitad del clip (ni del anterior, si lo hay)."""
    lim = clip_dur / 2
    if prev_dur is not None:
        lim = min(lim, prev_dur / 2)
    return max(0.1, lim)
