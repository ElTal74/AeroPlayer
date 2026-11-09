"""Cola de conversión: ejecuta trabajos en paralelo (FFmpeg, Pillow, LibreOffice) sin bloquear la interfaz."""

from __future__ import annotations

import ctypes
import itertools
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QRunnable, QThreadPool, QTimer, Signal

from aero.core import tools
from aero.core.builtin_convert import ConversionCancelled, run_builtin
from aero.core.convert_spec import (ConvertOptions, build_ffmpeg_args, friendly_ffmpeg_error, method_for,
                                    output_path, reserve_path)
from aero.core.paths import cache_dir

PENDING, PROBING, RUNNING, PAUSED, DONE, ERROR, CANCELLED = (
    "En cola", "Analizando", "Convirtiendo", "En pausa", "Completado", "Error", "Cancelado")
ACTIVE = (PROBING, RUNNING, PAUSED)
FINISHED = (DONE, ERROR, CANCELLED)

OFFICE_FILTERS = {
    "docx": "docx:MS Word 2007 XML", "xlsx": "xlsx:Calc MS Excel 2007 XML", "pptx": "pptx:Impress MS PowerPoint 2007 XML",
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1", "txt": "txt:Text (encoded):UTF8",
}

_ids = itertools.count(1)


@dataclass
class Job:
    src: Path
    opts: ConvertOptions
    out_dir: Path
    rel_dir: str = ""
    id: int = field(default_factory=lambda: next(_ids))
    state: str = PENDING
    progress: float = 0.0
    eta: float | None = None
    message: str = ""
    dst: Path | None = None
    outputs: list[Path] = field(default_factory=list)
    method: str = ""
    info: dict | None = None
    duration: float = 0.0
    started: float = 0.0
    # internos
    proc: QProcess | None = None
    cancel_flag: bool = False
    slot: bool = False          # plaza reservada en la cola común de tareas pesadas
    stderr_tail: str = ""
    tmpdir: str = ""


def _suspend(pid: int, resume: bool) -> bool:
    if os.name != "nt" or not pid:
        return False
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
    if not handle:
        return False
    try:
        fn = ctypes.windll.ntdll.NtResumeProcess if resume else ctypes.windll.ntdll.NtSuspendProcess
        return fn(handle) == 0
    finally:
        k32.CloseHandle(handle)


class _Bridge(QObject):
    done = Signal(int, object, str)      # id, outputs|None, error
    progressed = Signal(int, float)
    probed = Signal(int, object)

    def safe_emit(self, signal: str, *args) -> None:
        """Emitir desde un hilo de trabajo aunque el gestor ya se haya destruido."""
        try:
            getattr(self, signal).emit(*args)
        except RuntimeError:
            pass


class _Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        self.fn()


class ConversionManager(QObject):
    job_added = Signal(int)
    job_changed = Signal(int)
    job_removed = Signal(int)
    queue_idle = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.jobs: dict[int, Job] = {}
        self.order: list[int] = []
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(2, os.cpu_count() or 2))
        self.bridge = _Bridge(self)
        self.bridge.done.connect(self._worker_done)
        self.bridge.progressed.connect(self._worker_progress)
        self.bridge.probed.connect(self._probed)
        self._sched = QTimer(self)
        self._sched.setSingleShot(True)
        self._sched.setInterval(0)
        self._sched.timeout.connect(self._schedule)
        self._finished_procs: list[QProcess] = []
        from aero.core.tasks import tasks

        # Las conversiones comparten plazas «pesadas» con el resto de módulos (OCR, exportaciones…).
        # método y no lambda: la cola de tareas es global y vive más que este gestor
        tasks().slot_freed.connect(self._slot_freed)
        self._activity: dict[int, str] = {}
        self.job_changed.connect(self._report)

    def _slot_freed(self, kind: str) -> None:
        if kind == "heavy":
            self._sched.start()

    def _report(self, jid: int) -> None:
        """Refleja cada conversión en el centro de tareas común."""
        from aero.core import activity as act

        job = self.jobs.get(jid)
        if job is None:
            return
        center = act.activities()
        aid = self._activity.get(jid)
        if aid is None and job.state not in FINISHED:
            aid = center.start(f"{job.src.name} → {job.opts.target.upper()}", "convert",
                               cancel=lambda j=jid: self.cancel(j))
            self._activity[jid] = aid
        if aid is None:
            return
        if job.state in FINISHED:
            state = {DONE: act.DONE, ERROR: act.ERROR, CANCELLED: act.CANCELLED}[job.state]
            center.finish(aid, state, str(job.dst or ""), job.message if job.state == ERROR else "")
            self._activity.pop(jid, None)
        else:
            center.update(aid, job.progress if job.state == RUNNING else None, job.state)

    # ---------------------------------------------------------------- API pública
    def add(self, items: list[tuple[str, str]], opts: ConvertOptions, out_dir: str | Path) -> list[int]:
        ids = []
        office = tools.find_tool("soffice") is not None
        for src, rel in items:
            o = ConvertOptions(**{**opts.__dict__, "extra": dict(opts.extra)})
            job = Job(Path(src), o, Path(out_dir), rel if self.settings.get("keep_structure") else "")
            job.method = method_for(src, o.target, office)
            self.jobs[job.id] = job
            self.order.append(job.id)
            self.job_added.emit(job.id)
            ids.append(job.id)
        self._sched.start()
        return ids

    def cancel(self, jid: int) -> None:
        job = self.jobs.get(jid)
        if not job or job.state in FINISHED:
            return
        job.cancel_flag = True
        if job.proc is not None:
            if job.state == PAUSED:
                _suspend(job.proc.processId(), True)
            job.proc.kill()
        if job.state in (PENDING, PAUSED) and job.proc is None:
            self._finish(job, CANCELLED, "Cancelado por el usuario")
        elif job.state == PROBING:
            self._finish(job, CANCELLED, "Cancelado por el usuario")

    def pause(self, jid: int) -> None:
        job = self.jobs.get(jid)
        if job and job.state == RUNNING and job.proc is not None and _suspend(job.proc.processId(), False):
            job.state = PAUSED
            job.eta = None
            self.job_changed.emit(jid)

    def resume(self, jid: int) -> None:
        job = self.jobs.get(jid)
        if job and job.state == PAUSED and job.proc is not None and _suspend(job.proc.processId(), True):
            job.state = RUNNING
            self.job_changed.emit(jid)

    def can_pause(self, jid: int) -> bool:
        job = self.jobs.get(jid)
        return bool(job and job.method == "ffmpeg" and os.name == "nt")

    def retry(self, jid: int) -> None:
        job = self.jobs.get(jid)
        if not job or job.state not in (ERROR, CANCELLED):
            return
        job.state, job.progress, job.message, job.eta = PENDING, 0.0, "", None
        job.cancel_flag, job.outputs, job.dst, job.stderr_tail = False, [], None, ""
        self.job_changed.emit(jid)
        self._sched.start()

    def remove(self, jid: int) -> None:
        job = self.jobs.get(jid)
        if job and job.state not in ACTIVE:
            del self.jobs[jid]
            self.order.remove(jid)
            self.job_removed.emit(jid)

    def clear_finished(self) -> None:
        for jid in [j for j in self.order if self.jobs[j].state in FINISHED]:
            self.remove(jid)

    def cancel_all(self) -> None:
        for jid in list(self.order):
            self.cancel(jid)

    def overall(self) -> tuple[int, int, float]:
        """(terminados, total, progreso global 0..1)."""
        if not self.order:
            return 0, 0, 0.0
        done = sum(1 for j in self.jobs.values() if j.state in FINISHED)
        prog = sum(1.0 if j.state in FINISHED else j.progress for j in self.jobs.values()) / len(self.jobs)
        return done, len(self.jobs), prog

    def busy(self) -> bool:
        return any(j.state in ACTIVE or j.state == PENDING for j in self.jobs.values())

    # ---------------------------------------------------------------- planificación
    def _schedule(self) -> None:
        for proc in self._finished_procs:
            proc.setParent(None)  # al soltar la referencia, Python libera el objeto de forma segura
        self._finished_procs.clear()
        from aero.core.tasks import tasks

        limit = max(1, int(self.settings.get("max_parallel_jobs") or 1))
        running = sum(1 for j in self.jobs.values() if j.state in ACTIVE)
        for jid in self.order:
            if running >= limit:
                break
            job = self.jobs[jid]
            if job.state == PENDING:
                if not tasks().acquire("heavy"):
                    break  # el perfil de rendimiento no admite más tareas pesadas ahora
                job.slot = True
                running += 1
                self._start(job)
        if not self.busy():
            self.queue_idle.emit()

    def _start(self, job: Job) -> None:
        job.started = time.monotonic()
        try:
            job.out_dir.mkdir(parents=True, exist_ok=True)
            (job.out_dir / job.rel_dir).mkdir(parents=True, exist_ok=True)
            job.dst = reserve_path(output_path(job.src, job.out_dir, job.opts.target, job.rel_dir))
        except OSError as e:
            self._finish(job, ERROR, f"No se puede usar la carpeta de destino: {e.strerror or e}")
            return
        if not job.src.is_file():
            self._finish(job, ERROR, "El archivo de origen ya no existe.")
            return
        if job.method == "ffmpeg":
            if not tools.find_tool("ffmpeg"):
                self._finish(job, ERROR, "FFmpeg no está disponible. Configúralo en Ajustes › Conversión.")
                return
            job.state = PROBING
            self.job_changed.emit(job.id)
            jid, src, bridge = job.id, str(job.src), self.bridge
            hw = bool(self.settings.get("use_hw_encoding")) and job.opts.hw

            # Las tareas en segundo plano no deben retener `self`: si el gestor se libera desde un hilo
            # de trabajo, Qt destruiría objetos en el hilo equivocado.
            def probe():
                info = tools.probe(src)
                tools.encoders()
                if hw:  # el primer sondeo de hardware es lento; hacerlo fuera del hilo de la interfaz
                    for n in ("h264_nvenc", "hevc_nvenc", "h264_qsv", "h264_amf"):
                        tools.hw_encoder_works(n)
                bridge.safe_emit("probed", jid, info)

            self.pool.start(_Task(probe))
        elif job.method == "office":
            self._start_office(job)
        else:
            job.state = RUNNING
            self.job_changed.emit(job.id)
            jid, src, dst, opts, bridge = job.id, job.src, job.dst, job.opts, self.bridge

            def work():
                try:
                    outs = run_builtin(src, dst, opts, lambda f: bridge.safe_emit("progressed", jid, f),
                                       lambda: job.cancel_flag)
                    bridge.safe_emit("done", jid, outs, "")
                except ConversionCancelled:
                    bridge.safe_emit("done", jid, None, "__cancel__")
                except PermissionError:
                    bridge.safe_emit("done", jid, None, "Sin permiso para leer el origen o escribir el destino.")
                except OSError as e:
                    msg = "No queda espacio en disco." if getattr(e, "errno", 0) == 28 else str(e)
                    bridge.safe_emit("done", jid, None, msg)
                except Exception as e:  # noqa: BLE001 - se muestra al usuario
                    bridge.safe_emit("done", jid, None, f"No se pudo convertir: {e}")

            self.pool.start(_Task(work))

    # ---------------------------------------------------------------- FFmpeg
    def _probed(self, jid: int, info) -> None:
        job = self.jobs.get(jid)
        if not job or job.state != PROBING:
            return
        job.info = info
        try:
            job.duration = float((info or {}).get("format", {}).get("duration") or 0)
        except ValueError:
            job.duration = 0
        hw = bool(self.settings.get("use_hw_encoding")) and job.opts.hw
        job.opts.hw = hw
        try:
            args = build_ffmpeg_args(tools.find_tool("ffmpeg"), str(job.src), str(job.dst), job.opts, info,
                                     tools.encoders(), tools.hw_encoder_works, overwrite_reserved=True)
        except ValueError as e:
            self._finish(job, ERROR, str(e))
            return
        proc = QProcess(self)
        job.proc = proc
        proc.setProgram(args[0])
        proc.setArguments(args[1:])
        proc.readyReadStandardOutput.connect(lambda j=job: self._ff_stdout(j))
        proc.readyReadStandardError.connect(lambda j=job: self._ff_stderr(j))
        proc.finished.connect(lambda code, status, j=job: self._proc_finished(j, code))
        proc.errorOccurred.connect(lambda err, j=job: self._proc_error(j, err))
        job.state = RUNNING
        self.job_changed.emit(job.id)
        proc.start()

    def _ff_stdout(self, job: Job) -> None:
        data = bytes(job.proc.readAllStandardOutput()).decode("utf-8", "replace")
        out_us = speed = None
        for line in data.splitlines():
            k, _, v = line.partition("=")
            if k == "out_time_us" and v.strip().lstrip("-").isdigit():
                out_us = int(v)
            elif k == "speed" and v.strip().endswith("x"):
                try:
                    speed = float(v.strip()[:-1])
                except ValueError:
                    pass
        if out_us is not None and job.duration > 0:
            pos = max(0.0, out_us / 1e6)
            job.progress = min(0.999, pos / job.duration)
            if speed and speed > 0:
                job.eta = max(0.0, (job.duration - pos) / speed)
            self.job_changed.emit(job.id)

    def _ff_stderr(self, job: Job) -> None:
        data = bytes(job.proc.readAllStandardError()).decode("utf-8", "replace")
        job.stderr_tail = (job.stderr_tail + data)[-6000:]
        if not job.duration:
            m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", job.stderr_tail)
            if m:
                job.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    def _proc_error(self, job: Job, err) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self._finish(job, ERROR, "No se pudo iniciar el programa externo.")

    def _proc_finished(self, job: Job, code: int) -> None:
        proc, job.proc = job.proc, None
        if proc is not None:
            # No usar deleteLater() dentro de su propia señal: con PySide provoca una doble liberación
            # si el gestor se destruye después. Se libera más tarde, fuera de la emisión.
            self._finished_procs.append(proc)
        if job.state in FINISHED:
            return
        if job.cancel_flag:
            self._discard_partial(job)
            self._finish(job, CANCELLED, "Cancelado por el usuario")
            return
        if job.method == "office":
            self._office_done(job, code)
            return
        if code == 0 and job.dst and job.dst.exists() and job.dst.stat().st_size > 0:
            job.outputs = [job.dst]
            self._finish(job, DONE, "")
        else:
            self._discard_partial(job)
            self._finish(job, ERROR, friendly_ffmpeg_error(job.stderr_tail))

    def _discard_partial(self, job: Job) -> None:
        """Elimina solo el archivo incompleto creado por este trabajo (nunca el original)."""
        if job.dst and job.dst.exists() and job.dst != job.src:
            try:
                job.dst.unlink()
            except OSError:
                pass

    # ---------------------------------------------------------------- LibreOffice
    def _start_office(self, job: Job) -> None:
        soffice = tools.find_tool("soffice")
        if not soffice:
            self._finish(job, ERROR, "Esta conversión necesita LibreOffice (no se ha encontrado).")
            return
        job.tmpdir = tempfile.mkdtemp(prefix="aero_lo_", dir=cache_dir())
        profile = (cache_dir() / "lo_profile").as_uri()
        target = job.opts.target
        args = [f"-env:UserInstallation={profile}", "--headless", "--norestore", "--nologo"]
        if job.src.suffix.lower() == ".pdf":
            args.append("--infilter=writer_pdf_import")
        args += ["--convert-to", OFFICE_FILTERS.get(target, target), "--outdir", job.tmpdir, str(job.src)]
        proc = QProcess(self)
        job.proc = proc
        proc.setProgram(soffice)
        proc.setArguments(args)
        proc.readyReadStandardError.connect(lambda j=job: self._ff_stderr(j))
        proc.finished.connect(lambda code, status, j=job: self._proc_finished(j, code))
        proc.errorOccurred.connect(lambda err, j=job: self._proc_error(j, err))
        job.state = RUNNING
        job.progress = 0.05
        self.job_changed.emit(job.id)
        proc.start()

    def _office_done(self, job: Job, code: int) -> None:
        produced = list(Path(job.tmpdir).glob(f"*.{job.opts.target}")) if job.tmpdir else []
        if code == 0 and produced:
            try:
                os.replace(str(produced[0]), str(job.dst))
                job.outputs = [job.dst]
                self._finish(job, DONE, "")
            except OSError as e:
                self._finish(job, ERROR, f"No se pudo mover el resultado: {e}")
        else:
            self._finish(job, ERROR, "LibreOffice no pudo convertir el archivo.")
        shutil.rmtree(job.tmpdir, ignore_errors=True)

    # ---------------------------------------------------------------- hilos de trabajo
    def _worker_progress(self, jid: int, frac: float) -> None:
        job = self.jobs.get(jid)
        if job and job.state == RUNNING:
            job.progress = min(0.999, frac)
            elapsed = time.monotonic() - job.started
            if frac > 0.05:
                job.eta = elapsed * (1 - frac) / frac
            self.job_changed.emit(jid)

    def _worker_done(self, jid: int, outs, err: str) -> None:
        job = self.jobs.get(jid)
        if not job:
            return
        if err == "__cancel__" or job.cancel_flag:
            self._discard_partial(job)
            self._finish(job, CANCELLED, "Cancelado por el usuario")
        elif err:
            self._discard_partial(job)
            self._finish(job, ERROR, err)
        else:
            job.outputs = list(outs or [])
            self._finish(job, DONE, "")

    def _finish(self, job: Job, state: str, message: str) -> None:
        # Quitar el marcador reservado si no llegó a usarse (p. ej. PDF → carpeta de imágenes).
        if job.dst is not None and job.dst not in job.outputs:
            try:
                if job.dst.exists() and job.dst.stat().st_size == 0:
                    job.dst.unlink()
            except OSError:
                pass
        job.state = state
        job.message = message
        job.eta = None
        if job.slot:
            from aero.core.tasks import tasks

            job.slot = False
            tasks().release("heavy")
        if state == DONE:
            job.progress = 1.0
        self.job_changed.emit(job.id)
        self._sched.start()
