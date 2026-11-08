"""Monitor de las tareas de desarrollo (independiente de AERO Player).

Genera `.devrun/monitor.html`: una página local que se recarga sola cada 5 s y muestra cada tarea de
`tools/devrun.py` (orden, estado, duración, código de salida) con las últimas líneas de su registro. No abre
ventanas por su cuenta: la abres tú cuando quieras ver qué se está haciendo.

Uso:
    python tools/devmonitor.py            # escribe la página una vez
    python tools/devmonitor.py --watch    # la mantiene al día (sin ventana; para con `devrun.py stop monitor`)
    python tools/devmonitor.py --open     # además la abre en tu navegador
"""

from __future__ import annotations

import html
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import devrun  # noqa: E402

STATE = {"running": ("En marcha", "#2f80ed"), "starting": ("Arrancando", "#2f80ed"), "done": ("Terminada", "#1e9e5a"),
         "failed": ("Falló", "#d64545"), "stopped": ("Detenida", "#a87b14"), "lost": ("Perdida", "#888")}


def page() -> str:
    rows = []
    for d in sorted(devrun.status(), key=lambda d: -d.get("started", 0)):
        name = d.get("name", "?")
        label, color = STATE.get(d.get("state", ""), (d.get("state", "?"), "#888"))
        dur = (d.get("finished") or time.time()) - d.get("started", time.time())
        try:
            tail = Path(d.get("log", "")).read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
        except OSError:
            tail = []
        rows.append(f"""<section><h2>{html.escape(name)} <span style="background:{color}">{label}</span></h2>
<p>{time.strftime('%H:%M:%S', time.localtime(d.get('started', 0)))} · {dur:,.0f} s · código {d.get('exit')} ·
{html.escape(d.get('desktop') or '')}</p><code>{html.escape(d.get('cmd', ''))}</code>
<pre>{html.escape(chr(10).join(tail))}</pre></section>""")
    body = "".join(rows) or "<p>No hay tareas.</p>"
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta http-equiv="refresh" content="5">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Tareas de AERO Player</title><style>
:root{{color-scheme:light dark;--bg:#f4f6f9;--card:#fff;--fg:#1d2430;--mut:#667}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14171c;--card:#1d2128;--fg:#e6e9ee;--mut:#99a}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px "Segoe UI",system-ui,sans-serif}}
h1{{font-size:20px}} section{{background:var(--card);border-radius:12px;padding:12px 16px;margin:0 0 12px}}
h2{{font-size:16px;margin:0}} h2 span{{color:#fff;border-radius:8px;padding:2px 8px;font-size:12px;margin-left:6px}}
p{{color:var(--mut);margin:4px 0}} code{{font-size:12px;word-break:break-all;color:var(--mut)}}
pre{{font:12px Consolas,monospace;overflow:auto;max-height:260px;white-space:pre-wrap}}</style></head>
<body><h1>Tareas de desarrollo de AERO Player</h1><p>Actualizado {time.strftime('%H:%M:%S')}.
Detener una tarea: <code>python tools/devrun.py stop &lt;nombre&gt;</code></p>{body}</body></html>"""


def write() -> Path:
    devrun.DIR.mkdir(exist_ok=True)
    out = devrun.DIR / "monitor.html"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(page(), encoding="utf-8")
    os.replace(tmp, out)
    return out


if __name__ == "__main__":
    path = write()
    print(path)
    if "--open" in sys.argv:
        os.startfile(path)  # noqa: S606 - página local generada aquí
    if "--watch" in sys.argv:
        while True:
            time.sleep(5)
            write()
