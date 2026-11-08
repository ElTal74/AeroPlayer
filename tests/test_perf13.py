"""Pruebas del requisito 18: perfiles de calidad, hardware, cola común de tareas y optimización automática."""

import threading
import time


def wait_until(qapp, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


def test_quality_normalize_and_auto_steps():
    from aero.core import quality

    q = quality.normalize({"fps": 500, "bubbles": -1, "viz": "nope", "motion": 0, "x": 1})
    assert q["fps"] == 30 and q["bubbles"] == 0.0 and q["viz"] == "normal" and q["motion"] is False
    assert "x" not in q
    high = quality.normalize({}, "high")
    low = quality.apply_auto(high, 2)
    assert low["fps"] <= 8 and low["max_moving"] <= 4 and low["particles"] == 0 and low["viz"] == "low"
    assert quality.apply_auto(high, 0) == high
    for name in ("ultra", "balanced", "high"):
        assert set(quality.PROFILES[name]) == set(quality.PROFILES["balanced"])


def test_hardware_recommendation_thresholds():
    from aero.core.hardware import GB, Hardware, detect, recommend

    assert recommend(Hardware(4 * GB, 1 * GB, 4))[0] == "ultra"
    assert recommend(Hardware(16 * GB, 8 * GB, 2))[0] == "ultra"
    assert recommend(Hardware(8 * GB, 4 * GB, 8))[0] == "balanced"
    big_igpu = Hardware(16 * GB, 8 * GB, 8, gpus=["Intel(R) UHD Graphics"], screen=(3840, 2160))
    assert recommend(big_igpu)[0] == "balanced"
    strong = Hardware(32 * GB, 20 * GB, 16, gpus=["NVIDIA GeForce RTX 4070"], screen=(3840, 2160))
    assert recommend(strong)[0] == "high"
    hw = detect()
    assert hw.cores >= 1 and hw.ram_total > 0


def test_profiles_change_real_mechanisms(qapp, controller):
    from aero.core.tasks import tasks
    from aero.ui import backdrop_fx
    from aero.ui.glass import tm
    from aero.ui.theme import PRESETS, theme_from_spec
    from aero.ui.visualizer import Visualizer

    s = controller.settings
    s.set("glass_mode", "blur")
    s.set("quality_profile", "ultra")
    qapp.processEvents()
    assert not tm().blur_enabled, "ultra ligero: sin desenfoque acrílico"
    assert tm().reduce_motion, "ultra ligero: sin transiciones"
    assert tasks().limits == {"background": 1, "heavy": 1}
    spec = dict(PRESETS["burbuja"])
    spec["deco"] = {k: dict(v) for k, v in spec.get("deco", {}).items()}
    spec["deco"]["particles"] = {"on": True, "amount": 1.0, "size": 1.0}
    spec["deco"]["bubbles"] = {"on": True, "amount": 1.0, "size": 1.0}
    t = theme_from_spec("x", spec)
    assert not backdrop_fx._deco(t, "particles")["on"], "partículas desactivadas en ultra ligero"
    n_ultra = len(backdrop_fx.build_sprites(t, 1200, 800))
    v = Visualizer(None)
    v.configure(s)
    assert v.low_power, "visualizador sencillo en ultra ligero"

    s.set("quality_profile", "high")
    qapp.processEvents()
    assert tm().blur_enabled and not tm().reduce_motion
    assert tasks().limits == {"background": 3, "heavy": 2}
    assert len(backdrop_fx.build_sprites(t, 1200, 800)) > n_ultra
    assert not v.low_power and v.detail == "high"
    moving, _static = backdrop_fx.split_sprites(backdrop_fx.build_sprites(t, 1200, 800))
    assert len(moving) <= 24
    s.set("quality_profile", "balanced")
    qapp.processEvents()


def test_custom_profile_edit_and_user_profiles(qapp, controller):
    from aero.core import quality
    from aero.ui.pages.perf_settings import PerformanceSettings

    s = controller.settings
    s.set("quality_profile", "balanced")
    w = PerformanceSettings(s)
    w.checks["blur"].setChecked(False)          # cualquier ajuste crea un perfil personalizado
    assert s.get("quality_profile") == "custom"
    w.spins["fps"].setValue(12)
    q = quality.resolve(s)
    assert q["fps"] == 12 and q["blur"] is False and q["bubbles"] == 1.0
    s.set("quality_user", {"Portátil": q})
    s.set("quality_profile", "user:Portátil")
    w.load()
    assert w.mine.currentData() == "user:Portátil" and w.spins["fps"].value() == 12
    w._choose("ultra")
    assert quality.resolve(s)["fps"] == 10
    s.set("quality_profile", "balanced")


def test_task_queue_limits_priority_and_cancel(qapp):
    from aero.core.tasks import TaskManager

    tq = TaskManager()
    tq.set_limits(2, 1)
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}
    order = []
    started = []

    def job(i):
        def run():
            with lock:
                started.append(i)
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            return i
        return run

    tickets = [tq.submit(job(i), "background", on_done=order.append) for i in range(8)]
    tickets[3].cancel()
    assert wait_until(qapp, lambda: len(order) == 7)
    assert state["peak"] <= 2, "nunca más tareas a la vez que el límite"
    assert 3 not in order, "las tareas canceladas en cola no se ejecutan"
    assert sorted(started[:2]) == [0, 1] and started[2:] == [7, 6, 5, 4, 2], "lo último pedido va primero"
    tq.set_foreground_busy(True)
    assert tq.limit("background") == 1
    tq.set_foreground_busy(False)
    assert tq.acquire("heavy") and not tq.acquire("heavy"), "una sola tarea pesada a la vez"
    tq.release("heavy")
    assert tq.acquire("heavy")
    tq.release("heavy")


def test_converter_respects_heavy_slots(qapp, tmp_path, media):
    from aero.core.config import Settings
    from aero.core.convert_spec import ConvertOptions
    from aero.core.converter import ACTIVE, ConversionManager
    from aero.core.tasks import tasks

    s = Settings()
    s.set("max_parallel_jobs", 4)
    tasks().set_limits(2, 1)
    assert tasks().acquire("heavy"), "otra tarea pesada (p. ej. un OCR) ocupa la única plaza"
    cm = ConversionManager(s)
    cm.add([(str(media / "img.png"), "")], ConvertOptions(target="jpg"), tmp_path)
    for _ in range(5):
        qapp.processEvents()
    assert not any(j.state in ACTIVE for j in cm.jobs.values()), "espera a que haya plaza"
    tasks().release("heavy")
    assert wait_until(qapp, lambda: not cm.busy(), 20)
    assert tasks().held == 0, "la plaza se libera al terminar"


def test_auto_tuner_hysteresis_and_idle_cost(qapp):
    from PySide6.QtCore import QObject

    from aero.ui.perf import AutoTuner

    t = AutoTuner()
    t.set_enabled(True)
    assert not t._timer.isActive(), "sin nada animándose no se mide nada"
    t.feed(0.95, now=100)
    assert t.step == 0, "una lectura alta no basta"
    t.feed(0.95, now=103)
    assert t.step == 1
    t.feed(0.97, now=106)
    t.feed(0.97, now=109)
    assert t.step == 1, "espera entre cambios: la interfaz no parpadea"
    t.feed(0.97, now=115)
    assert t.step == 2
    for i in range(4):
        t.feed(0.2, now=130 + i * 3)
    assert t.step == 2, "recupera solo tras 5 lecturas tranquilas"
    t.feed(0.2, now=145)
    assert t.step == 1
    o = QObject()
    t.animating(o, True)
    assert t._timer.isActive()
    t.animating(o, False)
    assert not t._timer.isActive()
    t.set_enabled(False)
    assert t.step == 0, "al desactivarla se recupera la calidad completa"


def test_profiles_never_remove_features(qapp, media, controller):
    """Las mismas páginas, visores y vista rápida existen en todos los perfiles."""
    from aero.ui.main_window import PAGE_KEYS

    s = controller.settings
    win = controller.show_main()
    for prof in ("ultra", "balanced", "high"):
        s.set("quality_profile", prof)
        qapp.processEvents()
        for key in PAGE_KEYS:
            assert win.page(key) is not None
        controller.show_quicklook(str(media / "img.png"))
        ql = controller.quicklook
        assert wait_until(qapp, lambda: not ql._views["image"].item.pixmap().isNull())
        ql.close_preview()
    s.set("quality_profile", "balanced")
