"""Pruebas de la versión 1.2: alineación, álbumes, bordes y estilo, temas, Quick Look y visualizadores."""

import json
import time

import numpy as np
import pytest

from tests.test_v11 import wait_until


def _center_y(w, ref):
    return w.mapTo(ref, w.rect().center()).y()


# ----------------------------------------------------------------------------- 1 · Play alineado
@pytest.mark.parametrize("width", [700, 1000, 1600])
def test_player_bar_controls_share_center_line(qapp, width):
    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.player.engine import PlayerEngine
    from aero.ui.main_window import apply_theme
    from aero.ui.player_bar import PlayerBar

    s = Settings()
    apply_theme(qapp, s)
    bar = PlayerBar(PlayerEngine(s, Database()), Database())
    bar.resize(width, PlayerBar.HEIGHT)
    bar.show()
    qapp.processEvents()
    ys = {_center_y(w, bar) for w in (bar.shuffle, bar.prev, bar.play, bar.next, bar.repeat)}
    assert max(ys) - min(ys) <= 1, ys
    # Nada se sale de la barra (antes Play se desbordaba hacia abajo)
    assert bar.play.mapTo(bar, bar.play.rect().bottomLeft()).y() < bar.height()
    bar.close()


def test_hover_never_scales_beyond_widget(qapp):
    from aero.ui.glass import IconButton, PlayButton
    from aero.ui.pages.home_page import ActionTile

    assert IconButton("play", "x").squish.hover_scale == 1.0
    assert ActionTile("open", "Abrir", "x").squish.hover_scale == 1.0
    pb = PlayButton(size=40)
    # El crecimiento del Play cabe en su relleno
    assert pb.bubble * pb.squish.hover_scale < pb.width() / 2 - 2


# ----------------------------------------------------------------------------- 2 · álbumes
def test_album_customisation_persists(qapp, tmp_path):
    from PySide6.QtGui import QColor, QImage

    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.ui.main_window import apply_theme
    from aero.ui.pages.albums import ALBUM_ROLE
    from aero.ui.pages.library_page import LibraryPage

    db = Database(tmp_path / "l.db")
    db.upsert_media([{"path": f"C:/m/{i}.mp3", "root": "C:/m", "folder": "C:/m", "name": str(i), "ext": ".mp3",
                      "kind": "audio", "size": 1, "mtime": 1.0, "title": f"T{i}", "artist": "Art", "album": "Disco",
                      "duration": 60.0} for i in range(3)])
    s = Settings()
    apply_theme(qapp, s)
    lib = LibraryPage(db, s)
    img = QImage(400, 300, QImage.Format.Format_RGB32)
    img.fill(QColor("#ff0000"))
    lib.apply_album_edit("Disco", {"title": "Mi disco", "artist": "Yo", "cover": img})
    db.close()
    db2 = Database(tmp_path / "l.db")       # «cerrar y volver a abrir»
    info = db2.album_info("Disco")
    assert info["title"] == "Mi disco" and info["artist"] == "Yo"
    assert QImage(info["cover"]).width() == 600
    lib2 = LibraryPage(db2, s)
    lib2.tabs.setCurrentIndex(3)
    data = lib2.groups.item(0).data(ALBUM_ROLE)
    assert data["title"] == "Mi disco" and data["artist"] == "Yo"
    # Restaurar original: se borra la portada personalizada
    lib2.apply_album_edit("Disco", {"title": "", "artist": "", "cover": ""})
    assert db2.album_info("Disco") == {}
    db2.close()


def test_hidden_files_are_not_rescanned(qapp, media, tmp_path):
    from aero.core.db import Database
    from aero.core.scanner import LibraryScanner

    folder = tmp_path / "musica"
    folder.mkdir()
    (folder / "a.mp3").write_bytes((media / "tono.mp3").read_bytes())
    (folder / "b.mp3").write_bytes((media / "tono.mp3").read_bytes())
    db_path = tmp_path / "s.db"

    def scan():
        sc = LibraryScanner([str(folder)], [], db_path)
        sc.start()
        assert wait_until(qapp, lambda: sc.isFinished(), 20)

    scan()
    db = Database(db_path)
    assert db.count_media("audio") == 2
    db.hide_paths([str(folder / "a.mp3")])
    assert db.count_media("audio") == 1
    scan()
    assert db.count_media("audio") == 1, "un archivo retirado no debe volver al escanear"
    assert (folder / "a.mp3").exists(), "retirar de la biblioteca nunca borra el archivo"
    db.close()


def test_album_delegate_elides_long_names(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QFontMetrics

    from aero.ui.pages.albums import COVER

    fm = QFontMetrics(QFont())
    long = "Un nombre de álbum larguísimo que nunca cabría debajo de la portada " * 2
    assert fm.horizontalAdvance(fm.elidedText(long, Qt.TextElideMode.ElideRight, COVER + 10)) <= COVER + 10


# ----------------------------------------------------------------------------- 3-4 · estilo y bordes
def test_qss_does_not_style_bordered_controls():
    """Botones, campos, pestañas, menús y deslizadores los dibuja AeroStyle (bordes nítidos y continuos)."""
    from aero.ui.theme import build_qss, get_theme

    qss = build_qss(get_theme("burbuja"), False)
    for sel in ("QPushButton {", "QPushButton:hover", "QTabBar::tab", "QMenu {", "QSlider::", "QLineEdit",
                "border-bottom-color", "border-top-color", "QWidget { background"):
        assert sel not in qss, sel


def test_button_border_is_continuous(qapp):
    """El borde inferior de un botón es tan visible como el superior (captura del pintado real)."""
    from PySide6.QtGui import QColor, QImage, QPainter

    from aero.core.config import Settings
    from aero.ui.main_window import apply_theme
    from aero.ui.style import paint_glass_button

    apply_theme(qapp, Settings())
    img = QImage(120, 40, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(20, 20, 40))
    p = QPainter(img)
    paint_glass_button(p, img.rect())
    p.end()
    top = QColor(img.pixel(60, 0)).lightness()
    bottom = QColor(img.pixel(60, 39)).lightness()
    bg = QColor(20, 20, 40).lightness()
    assert top - bg > 30 and bottom - bg > 30, (top, bottom, bg)
    assert abs(top - bottom) < 25


# ----------------------------------------------------------------------------- 5 · temas y deslizadores
def test_transparency_slider_is_fast_path(qapp, controller):
    from aero.ui.glass import tm

    w = controller.show_main()
    w.navigate("settings")
    qapp.processEvents()
    calls = {"changed": 0, "levels": 0}
    tm().changed.connect(lambda: calls.__setitem__("changed", calls["changed"] + 1))
    tm().levels_changed.connect(lambda: calls.__setitem__("levels", calls["levels"] + 1))
    sp = w.page("settings")
    qss = qapp.styleSheet()
    times = []
    for v in range(20, 40):
        t0 = time.perf_counter()
        sp.transp.slider.setValue(v)
        sp.transp._flush()
        w.repaint()
        qapp.processEvents()
        times.append(time.perf_counter() - t0)
    assert calls["changed"] == 0 and calls["levels"] >= 19
    assert qapp.styleSheet() is qss or qapp.styleSheet() == qss
    assert sorted(times)[len(times) // 2] < 0.06, times
    assert abs(controller.settings.get("window_transparency") - 0.39) < 1e-6


def test_value_slider_accepts_typed_value(qapp):
    from aero.ui.pages.theme_studio import ValueSlider

    got = []
    vs = ValueSlider(0.5, "x")
    vs.changed.connect(got.append)
    vs.spin.setValue(73)
    assert got[-1] == pytest.approx(0.73) and vs.slider.value() == 73


def test_presets_render_with_decorations(qapp):
    from aero.ui.glass import render_background
    from aero.ui.theme import PRESETS, theme_from_spec

    assert len(PRESETS) >= 7
    for name in ("Frutiger Aero Classic", "Frutiger Nature", "Frutiger Sky", "Aqua Glass", "Ocean",
                 "Minimal Glass", "Zen Crystal"):
        assert any(p["name"] == name for p in PRESETS.values()), name
    for key, spec in PRESETS.items():
        img = render_background(theme_from_spec(key, spec), 160, 100, 0.8)
        assert not img.isNull()


def test_theme_export_import_roundtrip(tmp_path):
    from aero.ui.pages.theme_studio import EXPORT_TAG, import_theme
    from aero.ui.theme import PRESETS

    spec = json.loads(json.dumps(PRESETS["nature"]))
    spec["deco"]["clouds"]["amount"] = 0.9
    spec["inyectado"] = "x"
    f = tmp_path / "t.json"
    f.write_text(json.dumps({EXPORT_TAG: 1, "spec": spec}), encoding="utf-8")
    out = import_theme(str(f))
    assert out["name"] == "Frutiger Nature" and out["deco"]["clouds"]["amount"] == 0.9
    assert "inyectado" not in out
    bad = tmp_path / "b.json"
    bad.write_text('{"otra": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        import_theme(str(bad))


def test_user_theme_applies_and_animates_only_dirty_regions(qapp, controller):
    from aero.ui.theme import PRESETS

    spec = json.loads(json.dumps(PRESETS["burbuja"]))
    spec["motion"]["speed"] = 0.6
    spec["deco"]["particles"]["on"] = True
    s = controller.settings
    s.set("user_themes", {"t1": spec})
    s.set("theme", "user:t1")
    w = controller.show_main()
    qapp.processEvents()
    bd = w.backdrop
    assert bd._sprites, "el tema con movimiento debe crear elementos móviles"
    assert wait_until(qapp, lambda: bd._motion.isActive(), 3)
    w.hide()
    qapp.processEvents()
    assert not bd._motion.isActive(), "sin ventana visible no se anima nada"
    s.set("theme", "burbuja")


# ----------------------------------------------------------------------------- 6-7 · Quick Look
@pytest.mark.parametrize("width", [380, 520, 900])
def test_quicklook_audio_progress_row_aligned(qapp, media, controller, width):
    controller.show_quicklook(str(media / "tono.mp3"))
    ql = controller.quicklook
    ql.resize(width, 640)
    assert wait_until(qapp, lambda: ql._total.text() != "--:--", 10)
    qapp.processEvents()
    ref = ql.pill
    e, sk, t = ql._elapsed, ql._seek, ql._total
    re_ = e.geometry().translated(e.parentWidget().mapTo(ref, e.parentWidget().rect().topLeft()))
    rs = sk.geometry().translated(sk.parentWidget().mapTo(ref, sk.parentWidget().rect().topLeft()))
    rt = t.geometry().translated(t.parentWidget().mapTo(ref, t.parentWidget().rect().topLeft()))
    assert re_.right() < rs.left() and rs.right() < rt.left(), (re_, rs, rt)
    assert abs(re_.center().y() - rs.center().y()) <= 2 and abs(rt.center().y() - rs.center().y()) <= 2
    play = ql._play.mapTo(ref, ql._play.rect().center()).y()
    assert play > rs.bottom(), "los controles van debajo del progreso"
    assert all(w.mapTo(ref, w.rect().bottomRight()).x() <= ref.width() for w in (ql._play, ql._vol, t) if w.isVisible())
    ql.close_preview()


def test_quicklook_controls_autohide(qapp, media, controller, monkeypatch):
    controller.show_quicklook(str(media / "img.png"))
    ql = controller.quicklook
    monkeypatch.setattr(ql, "controls_in_use", lambda: False)
    ql.wake()
    assert ql._controls_visible
    assert ql.IDLE_MS <= 2000
    assert wait_until(qapp, lambda: not ql._controls_visible, 3), "los controles no se ocultaron"
    assert wait_until(qapp, lambda: ql.overlay.windowOpacity() < 0.05, 4)  # con el equipo cargado la animación tarda más
    ql.wake()
    assert ql._controls_visible
    # Mientras se usa un control no desaparecen
    monkeypatch.setattr(ql, "controls_in_use", lambda: True)
    ql._hide_controls()
    assert ql._controls_visible
    ql.close_preview()


# ----------------------------------------------------------------------------- 9 · visualizadores
def _render(key, analyzer):
    from PySide6.QtGui import QImage, QPainter

    from aero.ui.visualizer import Visualizer

    v = Visualizer(analyzer)
    v.set_scene_key(key)
    v.resize(240, 140)
    img = QImage(240, 140, QImage.Format.Format_ARGB32_Premultiplied)
    for _ in range(12):
        v.advance(1 / 30)
        p = QPainter(img)
        v.paint_frame(p, 240, 140, rounded=False)
        p.end()
    return img


def test_visualizers_are_distinct_and_react(qapp):
    from aero.player.analyzer import AudioAnalyzer
    from aero.ui.visualizer import SCENE_KEYS

    assert len(SCENE_KEYS) >= 10
    a = AudioAnalyzer()
    sr = 44100
    t = np.arange(sr // 10) / sr
    loud = np.repeat((0.8 * np.sin(2 * np.pi * 120 * t) + 0.3 * np.sin(2 * np.pi * 3000 * t)).astype(np.float32), 2)

    class Feed:
        """Analizador real alimentado con señal en cada fotograma."""
        def __getattr__(self, n):
            return getattr(a, n)

        def update(self, dt=1 / 60):
            a.feed(loud.tobytes(), 2, sr)
            a.update(dt)

    imgs = {}
    for key in SCENE_KEYS:
        img = _render(key, Feed())
        arr = np.frombuffer(img.constBits(), np.uint8).reshape(140, 240, 4).astype(int)
        assert arr.std() > 3, f"{key} no dibuja nada"
        imgs[key] = arr
    keys = list(imgs)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            diff = np.abs(imgs[keys[i]] - imgs[keys[j]]).mean()
            assert diff > 2, f"{keys[i]} y {keys[j]} son casi iguales"


def test_visualizer_follows_settings_without_stopping(qapp):
    from aero.core.config import Settings
    from aero.ui.visualizer import DemoAnalyzer, Visualizer

    s = Settings()
    v = Visualizer(DemoAnalyzer())
    v.configure(s)
    v.start()
    s.set("visualizer_key", "nebula")
    s.set("visualizer_intensity", 0.2)
    assert v.key == "nebula" and v.intensity == pytest.approx(0.2) and v.active
    v.stop()


def test_quicklook_audio_has_visualizer_selector(qapp, media, controller):
    controller.show_quicklook(str(media / "tono.mp3"))
    ql = controller.quicklook
    assert ql._audio_viz.active
    ql._set_ql_viz("water_rings")
    assert ql._audio_viz.key == "water_rings" and controller.settings.get("visualizer_key") == "water_rings"
    ql._set_ql_viz(None)
    assert not ql._audio_viz.active
    ql._set_ql_viz("aero_waves")
    assert ql._audio_viz.active
    ql.close_preview()
