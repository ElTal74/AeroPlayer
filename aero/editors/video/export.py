"""Exportación del proyecto con FFmpeg (un único proceso, un grafo de filtros).

* Vídeo: lienzo negro del tamaño del proyecto; cada pista de abajo arriba superpone sus clips en su
  intervalo (recorte, giro, escala para encajar, color, velocidad, fundidos y transiciones de entrada).
* Textos: `drawtext` con fundido por transparencia (el texto se pasa por archivo: sin problemas de escape).
* Audio: cada clip con audio se recorta, cambia de velocidad (`atempo`), volumen y fundidos, se coloca en
  su instante (`adelay`) y todo se mezcla (`amix`).
* Vista previa exacta: el mismo grafo para un intervalo corto, a baja resolución y codificación rápida.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import replace

from aero.editors.video import geometry
from aero.editors.video.project import Clip, Project

CODECS = {"h264": "H.264", "hevc": "H.265 (HEVC)", "vp9": "VP9", "prores": "ProRes 422"}
FORMATS = {"mp4": ("MP4", ["h264", "hevc"]), "mkv": ("MKV", ["h264", "hevc", "vp9"]),
           "webm": ("WebM", ["vp9"]), "mov": ("MOV", ["h264", "prores"])}
FONT = r"C:\Windows\Fonts\segoeuib.ttf"


def _f(x: float) -> str:
    return f"{x:.3f}"


def _atempo(speed: float) -> list[str]:
    out = []
    s = speed
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-3:
        out.append(f"atempo={s:.4f}")
    return out


_SIZES: dict[str, tuple[int, int]] = {}


def _src_size(c: Clip) -> tuple[int, int]:
    """Tamaño del original (guardado en el clip; los proyectos antiguos lo leen una vez con ffprobe)."""
    if c.src_w and c.src_h:
        return c.src_w, c.src_h
    if c.src not in _SIZES:
        from aero.editors.video.project import media_info

        try:
            info = media_info(c.src)
            _SIZES[c.src] = (int(info.get("width") or 0), int(info.get("height") or 0))
        except Exception:  # noqa: BLE001 - sin tamaño se usa el encaje clásico
            _SIZES[c.src] = (0, 0)
    return _SIZES[c.src]


def _escape_path(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _window(project: Project, start: float, end: float) -> list[tuple[str, str, bool, Clip]]:
    """Clips que tocan [start, end), ajustados a ese intervalo. (tipo de pista, nombre, pista silenciada, clip)"""
    out = []
    for tr in project.tracks:
        if tr.kind == "video" and tr.hidden:
            continue
        for c in tr.clips:
            if c.end <= start or c.start >= end or c.missing():
                continue
            c2 = replace(c)
            if c.start < start:
                k = c.speed if c.kind in ("video", "audio") else 1.0
                cut = start - c.start
                c2.in_s = c.in_s + cut * k
                c2.fade_in, c2.transition = 0.0, "none"
                c2.start = start
            if c2.end > end:
                k = c2.speed if c2.kind in ("video", "audio") else 1.0
                c2.out_s = c2.in_s + (end - c2.start) * k
                c2.fade_out = 0.0
            c2.start -= start
            out.append((tr.kind, tr.name, tr.muted, c2))
    return out


def build_command(project: Project, out_path: str, fmt: str = "mp4", codec: str = "h264", quality: int = 23,
                  audio_kbps: int = 192, start: float = 0.0, end: float | None = None, scale_to: int = 0,
                  fast: bool = False, ffmpeg: str = "ffmpeg", still: bool = False
                  ) -> tuple[list[str], float, list[str]]:
    """Devuelve (argumentos, duración, archivos temporales a borrar). Con `still`, un solo fotograma PNG en
    `start` (vista previa de efectos en el editor)."""
    end = project.duration if end is None else min(end, project.duration)
    total = max(0.1, end - start)
    W, H, fps = project.width, project.height, project.fps
    if scale_to:
        k = scale_to / max(W, H)
        W, H = max(2, int(W * k) // 2 * 2), max(2, int(H * k) // 2 * 2)
    clips = _window(project, start, end)
    order = {t.name: i for i, t in enumerate(reversed(project.tracks))}  # de abajo arriba
    # Los títulos van encima de todo (como en el visor); el resto, de la pista inferior a la superior
    clips.sort(key=lambda x: (x[3].kind == "text", order.get(x[1], 0), x[3].start))
    # -nostdin: FFmpeg no debe esperar órdenes por teclado (se quedaba colgado sin consola)
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-nostats", "-progress", "pipe:1"]
    filt: list[str] = [f"color=c=black:s={W}x{H}:r={fps:g}:d={_f(total)}[base]"]
    temps: list[str] = []
    cur = "base"
    audio_labels: list[str] = []
    n_in = 0
    vn = 0
    # Transiciones de entrada: el clip anterior de la misma pista se prolonga por debajo (con su propio
    # material si lo hay, o congelando su último fotograma) mientras el nuevo aparece encima.
    from aero.editors.video import effects as fx

    prev_of: dict[str, Clip] = {}
    extend: dict[str, float] = {}
    plans: dict[str, fx.TransitionPlan] = {}
    by_track: dict[str, list[Clip]] = {}
    for kind_track, name, _m, c in clips:
        if kind_track == "video" and c.kind in ("video", "image"):
            by_track.setdefault(name, []).append(c)
    for lst in by_track.values():
        lst.sort(key=lambda x: x.start)
        for a, b in zip([None] + lst[:-1], lst):
            tid = fx.LEGACY.get(b.transition, b.transition)
            if tid not in fx.TRANSITIONS or b.transition_d <= 0:
                continue
            adjacent = a is not None and abs(a.end - b.start) < 0.05
            d = min(b.transition_d, fx.max_duration(b.duration, a.duration if adjacent else None))
            plans[b.id] = fx.plan(tid, d, b.start, a.duration if adjacent else None)
            plans[b.id].d = d
            if adjacent:
                prev_of[b.id] = a
                if tid not in ("fade", "fade_black", "fade_white"):
                    extend[a.id] = d
    for kind_track, _name, track_muted, c in clips:
        src_path, size = c.src, None
        if c.kind == "text":
            if not c.text.strip():
                continue
            # El título se dibuja con Qt (igual que en el visor) y se superpone como imagen transformable
            from aero.editors.video.titles import render_title

            img = render_title(c, H / project.height)
            fd, tpath = tempfile.mkstemp(prefix="aero_title_", suffix=".png")
            os.close(fd)
            img.save(tpath, "PNG")
            temps.append(tpath)
            src_path, size = tpath, (img.width(), img.height())
        span = max(0.04, c.out_s - c.in_s)
        ext = extend.get(c.id, 0.0)
        handles = c.kind == "video" and (not c.src_duration or c.out_s + ext * c.speed <= c.src_duration + 0.01)
        if c.kind in ("image", "text"):
            args += ["-loop", "1", "-framerate", f"{fps:g}", "-t", _f(c.duration + ext), "-i", src_path]
        else:
            args += ["-ss", _f(c.in_s), "-t", _f(span + (ext * c.speed if handles else 0.0)), "-i", c.src]
        idx = n_in
        n_in += 1
        s, e = c.start, c.end + ext
        if (kind_track == "video" and c.kind in ("video", "image")) or c.kind == "text":
            ch = [f"setpts=(PTS-STARTPTS)/{c.speed:g}" if c.kind == "video" else "setpts=PTS-STARTPTS", f"fps={fps:g}"]
            l, t, r, b = (float(x) for x in (c.crop or [0, 0, 0, 0]))
            if any((l, t, r, b)):
                ch.append(f"crop=iw*{1 - l - r:.4f}:ih*{1 - t - b:.4f}:iw*{l:.4f}:ih*{t:.4f}")
            ch += {90: ["transpose=1"], 180: ["hflip", "vflip"], 270: ["transpose=2"]}.get(int(c.rotation) % 360, [])
            ch += fx.chain_for(getattr(c, "effects", None))
            if ext and not handles and c.kind == "video":
                ch.append(f"tpad=stop_mode=clone:stop_duration={_f(ext / max(0.01, c.speed))}")
            pl = plans.get(c.id)
            if pl is not None and fx.LEGACY.get(c.transition, c.transition) == "zoom_in":
                # el zoom trabaja sobre un fotograma del tamaño del lienzo (con márgenes transparentes)
                ch += ["format=yuva420p", f"scale={W}:{H}:force_original_aspect_ratio=decrease",
                       f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black@0"]
                pl.filters = [x.replace("s=hd1080", f"s={W}x{H}") for x in pl.filters]
            pl_geo = None if pl is not None and fx.LEGACY.get(c.transition, c.transition) == "zoom_in" else \
                geometry.place(W, H, *(size or _src_size(c)), c)
            if pl_geo is not None:
                # Tamaño exacto (escala X/Y incluida), el mismo que dibuja el visor
                ow, oh = geometry.export_size(pl_geo)
                ch.append(f"scale={ow}:{oh}")
            else:
                sw, sh = max(2, int(W * c.scale)), max(2, int(H * c.scale))
                ch.append(f"scale=w={sw}:h={sh}:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2")
            angle = float(getattr(c, "angle", 0.0)) % 360
            if (c.brightness, c.contrast, c.saturation, c.gamma) != (0.0, 1.0, 1.0, 1.0):
                ch.append(f"eq=brightness={c.brightness:.3f}:contrast={c.contrast:.3f}:saturation={c.saturation:.3f}"
                          f":gamma={c.gamma:.3f}")
            ch.append("format=yuva420p")
            if angle:
                rad = f"{angle:.3f}*PI/180"
                ch.append(f"rotate={rad}:c=none:ow=rotw({rad}):oh=roth({rad})")
            opacity = max(0.0, min(1.0, float(getattr(c, "opacity", 1.0))))
            if opacity < 0.999:
                ch.append(f"colorchannelmixer=aa={opacity:.3f}")
            dur = c.duration
            if pl is not None:
                ch += pl.filters
            nxt = next((p for b_id, p in plans.items() if prev_of.get(b_id) is c), None)
            if nxt is not None:
                ch += nxt.prev_filters  # p. ej. fundido a negro: este clip se va a negro al final
            # Los títulos aparecen y desaparecen por transparencia; el resto, desde o hacia negro
            alpha = ":alpha=1" if c.kind == "text" else ""
            if c.fade_in > 0:
                ch.append(f"fade=t=in:st=0:d={_f(min(c.fade_in, dur))}{alpha}")
            if c.fade_out > 0:
                ch.append(f"fade=t=out:st={_f(max(0, dur - c.fade_out))}:d={_f(min(c.fade_out, dur))}{alpha}")
            ch.append(f"setpts=PTS+{_f(s)}/TB")
            filt.append(f"[{idx}:v]{','.join(ch)}[v{vn}]")
            if pl_geo is not None:
                # El centro del elemento (tras girar alrededor de su anclaje) queda donde lo pone el visor
                x = f"{pl_geo.center.x():.3f}-w/2"
                y = f"{pl_geo.center.y():.3f}-h/2"
            else:
                px, py = float(getattr(c, "pos_x", 0.0)), float(getattr(c, "pos_y", 0.0))
                x = f"(W-w)/2+{px:.4f}*W/2"
                y = f"(H-h)/2+{py:.4f}*H/2"
            if pl is not None:
                x += pl.x
                y += pl.y
            filt.append(f"[{cur}][v{vn}]overlay=x={x}:y={y}:eof_action=pass:"
                        f"enable='between(t,{_f(s)},{_f(e)})'[o{vn}]")
            cur = f"o{vn}"
            vn += 1
        has_audio = c.kind == "audio" or (c.kind == "video" and c.has_audio)
        if has_audio and not c.muted and not track_muted and c.volume > 0:
            ach = ["asetpts=PTS-STARTPTS", f"atrim=end={_f(span)}", *_atempo(c.speed), f"volume={c.volume:.3f}"]
            if c.fade_in > 0:
                ach.append(f"afade=t=in:st=0:d={_f(min(c.fade_in, c.duration))}")
            if c.fade_out > 0:
                ach.append(f"afade=t=out:st={_f(max(0, c.duration - c.fade_out))}:d={_f(min(c.fade_out, c.duration))}")
            ms = int(round(c.start * 1000))
            ach.append(f"adelay={ms}|{ms}")
            filt.append(f"[{idx}:a]{','.join(ach)}[a{len(audio_labels)}]")
            audio_labels.append(f"[a{len(audio_labels)}]")
    filt.append(f"[{cur}]format=yuv420p[vout]")
    if audio_labels:
        filt.append(f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:normalize=0:duration=longest,"
                    f"apad=whole_dur={_f(total)},atrim=0:{_f(total)}[aout]")
    else:
        filt.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{_f(total)}[aout]")
    if still:
        # el audio no hace falta para un fotograma: se descarta dentro del grafo
        args += ["-filter_complex", ";".join(filt + ["[aout]anullsink"]), "-map", "[vout]", "-frames:v", "1",
                 out_path]
        return args, total, temps
    args += ["-filter_complex", ";".join(filt), "-map", "[vout]", "-map", "[aout]", "-t", _f(total),
             "-r", f"{fps:g}"]
    if fast:
        args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-c:a", "aac", "-b:a", "128k"]
    elif codec == "hevc":
        args += ["-c:v", "libx265", "-preset", "medium", "-crf", str(quality + 4), "-tag:v", "hvc1"]
    elif codec == "vp9":
        args += ["-c:v", "libvpx-vp9", "-crf", str(quality + 8), "-b:v", "0", "-row-mt", "1"]
    elif codec == "prores":
        args += ["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le"]
    else:
        args += ["-c:v", "libx264", "-preset", "medium", "-crf", str(quality)]
    if not fast:
        if fmt == "webm":
            args += ["-c:a", "libopus", "-b:a", f"{audio_kbps}k"]
        elif codec == "prores":
            args += ["-c:a", "pcm_s16le"]
        else:
            args += ["-c:a", "aac", "-b:a", f"{audio_kbps}k"]
    if fmt in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]
    args.append(out_path)
    return args, total, temps


_TIME = re.compile(r"out_time_(?:us|ms)=(\d+)")


def parse_progress(chunk: str, total: float) -> float | None:
    """Fracción completada a partir de la salida de `-progress` (out_time_us en microsegundos)."""
    if "progress=end" in chunk:
        return 1.0          # FFmpeg terminó (con el equipo cargado puede no informar del último tiempo)
    vals = _TIME.findall(chunk)
    if not vals:
        return None
    return min(1.0, int(vals[-1]) / 1e6 / max(0.1, total))
