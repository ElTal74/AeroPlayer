"""Motor de reproducción: QMediaPlayer (backend FFmpeg de Qt) + cola, aleatorio, repetición y análisis."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import (QAudioBufferOutput, QAudioFormat, QAudioOutput, QMediaMetaData, QMediaPlayer)

from aero.core.formats import kind_of
from aero.core.metadata import read_cover, read_tags
from aero.core.subtitles import SubtitleTrack, find_sidecar

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = 0, 1, 2
RESUME_MIN_MS = 10 * 60 * 1000  # recordar posición en vídeos y audios largos


@dataclass
class TrackInfo:
    path: str
    kind: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float = 0.0
    cover: QImage | None = None
    extra: dict = field(default_factory=dict)

    @property
    def display_title(self) -> str:
        return self.title or Path(self.path).stem


class PlayerEngine(QObject):
    track_changed = Signal(object)        # TrackInfo
    state_changed = Signal(int)           # QMediaPlayer.PlaybackState
    position_changed = Signal(int)
    duration_changed = Signal(int)
    queue_changed = Signal()
    modes_changed = Signal()
    volume_changed = Signal(float, bool)
    tracks_changed = Signal()
    subtitle_text = Signal(str)
    error = Signal(str)
    played = Signal(str, str, str)        # ruta, título, artista (para historial)

    def __init__(self, settings, db, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.db = db
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        fmt = QAudioFormat()
        fmt.setSampleRate(44100)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        self.buffer_out = QAudioBufferOutput(fmt, self)
        self.buffer_out.audioBufferReceived.connect(self._on_buffer)
        self._analyzer = None    # se crea al primer uso: NumPy no se carga hasta que hace falta (-170 ms al abrir)
        self._analysis_on = False

        self.queue: list[str] = []
        self.index = -1
        self.shuffle = False
        self._shuffle_order: list[int] = []
        self.repeat = REPEAT_OFF
        self.current: TrackInfo | None = None
        self._failures = 0
        self._pending_seek = 0
        self.ext_subs: SubtitleTrack | None = None
        self.sub_offset_ms = 0
        self._last_sub = ""

        vol = float(settings.get("volume")) if settings.get("remember_volume") else 0.8
        self.audio.setVolume(vol)

        self.player.playbackStateChanged.connect(lambda s: self.state_changed.emit(int(s.value)))
        self.player.playbackStateChanged.connect(self._priority)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(lambda d: self.duration_changed.emit(int(d)))
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.errorOccurred.connect(self._on_error)
        self.player.metaDataChanged.connect(self._on_metadata)
        self.player.tracksChanged.connect(lambda: self.tracks_changed.emit())

        self._save_timer = QTimer(self)
        self._save_timer.setInterval(5000)
        self._save_timer.timeout.connect(self.save_position)
        self._save_timer.start()

    # ---------------------------------------------------------------- análisis
    def set_analysis(self, on: bool) -> None:
        """El análisis solo se conecta mientras el visualizador es visible (ahorra CPU)."""
        if on == self._analysis_on:
            return
        self._analysis_on = on
        self.player.setAudioBufferOutput(self.buffer_out if on else None)
        if not on and self._analyzer is not None:
            self._analyzer.reset()

    @property
    def analyzer(self):
        """Analizador de espectro (FFT con NumPy) para los visualizadores; se crea la primera vez que se pide."""
        if self._analyzer is None:
            from aero.player.analyzer import AudioAnalyzer

            self._analyzer = AudioAnalyzer()
        return self._analyzer

    def _on_buffer(self, buf) -> None:
        fmt = buf.format()
        if fmt.sampleFormat() != QAudioFormat.SampleFormat.Float:
            return
        data = buf.constData()
        if data is not None:
            self.analyzer.feed(data, fmt.channelCount(), fmt.sampleRate())

    # ---------------------------------------------------------------- cola
    def play_files(self, paths: list[str], start: int = 0) -> None:
        paths = [p for p in paths if p]
        if not paths:
            return
        self.save_position()
        self.queue = list(paths)
        self._rebuild_shuffle(start)
        self.queue_changed.emit()
        self._load(start)

    def enqueue(self, paths: list[str], play_next: bool = False) -> None:
        if not self.queue:
            self.play_files(paths)
            return
        if play_next:
            at = self.index + 1
            self.queue[at:at] = paths
        else:
            self.queue.extend(paths)
        self._rebuild_shuffle(self.index)
        self.queue_changed.emit()

    def remove_from_queue(self, rows: list[int]) -> None:
        current = self.queue[self.index] if 0 <= self.index < len(self.queue) else None
        for r in sorted(set(rows), reverse=True):
            if 0 <= r < len(self.queue) and r != self.index:
                del self.queue[r]
        self.index = self.queue.index(current) if current in self.queue else -1
        self._rebuild_shuffle(self.index)
        self.queue_changed.emit()

    def move_in_queue(self, src: int, dst: int) -> None:
        if not (0 <= src < len(self.queue)) or not (0 <= dst < len(self.queue)) or src == dst:
            return
        cur = self.index
        item = self.queue.pop(src)
        self.queue.insert(dst, item)
        if cur == src:
            self.index = dst
        elif src < cur <= dst:
            self.index = cur - 1
        elif dst <= cur < src:
            self.index = cur + 1
        self._rebuild_shuffle(self.index)
        self.queue_changed.emit()

    def clear_queue(self) -> None:
        self.stop()
        self.queue = []
        self.index = -1
        self.current = None
        self.player.setSource(QUrl())
        self.queue_changed.emit()
        self.track_changed.emit(None)

    def _rebuild_shuffle(self, first: int) -> None:
        order = list(range(len(self.queue)))
        random.shuffle(order)
        if 0 <= first < len(order):
            order.remove(first)
            order.insert(0, first)
        self._shuffle_order = order

    def _neighbor(self, step: int) -> int | None:
        n = len(self.queue)
        if n == 0:
            return None
        if self.shuffle and len(self._shuffle_order) == n:
            pos = self._shuffle_order.index(self.index) if self.index in self._shuffle_order else -1
            nxt = pos + step
            if 0 <= nxt < n:
                return self._shuffle_order[nxt]
            if self.repeat == REPEAT_ALL:
                return self._shuffle_order[nxt % n]
            return None
        nxt = self.index + step
        if 0 <= nxt < n:
            return nxt
        if self.repeat == REPEAT_ALL:
            return nxt % n
        return None

    def next(self) -> None:
        i = self._neighbor(1)
        if i is not None:
            self._load(i)

    def previous(self) -> None:
        if self.player.position() > 3000:
            self.player.setPosition(0)
            return
        i = self._neighbor(-1)
        if i is not None:
            self._load(i)
        else:
            self.player.setPosition(0)

    def jump_to(self, i: int) -> None:
        if 0 <= i < len(self.queue):
            self._load(i)

    # ---------------------------------------------------------------- carga
    def _load(self, i: int, autoplay: bool = True) -> None:
        self.save_position()
        self.index = i
        path = self.queue[i]
        kind = kind_of(path)
        info = TrackInfo(path=path, kind=kind)
        if kind == "audio":
            tags = read_tags(path)
            info.title, info.artist, info.album = tags.get("title", ""), tags.get("artist", ""), tags.get("album", "")
            info.duration = tags.get("duration", 0.0)
            info.extra = {k: v for k, v in tags.items() if k in ("bitrate", "sample_rate", "channels", "bits_per_sample", "genre", "year")}
            data = read_cover(path)
            if data:
                img = QImage.fromData(data)
                info.cover = img if not img.isNull() else None
        self.current = info
        self.ext_subs = None
        self.sub_offset_ms = 0
        self._set_sub_text("")
        if kind == "video":
            side = find_sidecar(path)
            if side:
                try:
                    self.ext_subs = SubtitleTrack.load(side)
                except (OSError, ValueError):
                    self.ext_subs = None
        self._pending_seek = 0
        if self.settings.get("remember_position"):
            pos = self.db.position(path)
            if pos > 5000:
                self._pending_seek = pos
        if self._analyzer is not None:
            self._analyzer.reset()
        self.player.setSource(QUrl.fromLocalFile(path))
        self.track_changed.emit(info)
        self.queue_changed.emit()
        if autoplay:
            self.player.play()

    def _on_metadata(self) -> None:
        if not self.current:
            return
        md = self.player.metaData()
        changed = False
        if not self.current.title:
            t = md.stringValue(QMediaMetaData.Key.Title)
            if t:
                self.current.title = t
                changed = True
        if not self.current.artist:
            a = md.stringValue(QMediaMetaData.Key.ContributingArtist) or md.stringValue(QMediaMetaData.Key.AlbumArtist)
            if a:
                self.current.artist = a
                changed = True
        if self.current.cover is None:
            for key in (QMediaMetaData.Key.CoverArtImage,):
                img = md.value(key)
                if isinstance(img, QImage) and not img.isNull():
                    self.current.cover = img
                    changed = True
                    break
        if changed:
            self.track_changed.emit(self.current)

    def _on_status(self, status) -> None:
        S = QMediaPlayer.MediaStatus
        if status in (S.LoadedMedia, S.BufferedMedia) and self._pending_seek:
            dur = self.player.duration()
            if self.player.isSeekable() and (dur <= 0 or self._pending_seek < dur - 10000):
                self.player.setPosition(self._pending_seek)
            self._pending_seek = 0
        if status == S.BufferedMedia:
            self._failures = 0
            if self.current:
                self.played.emit(self.current.path, self.current.display_title, self.current.artist)
        elif status == S.EndOfMedia:
            if self.current:
                self.db.save_position(self.current.path, 0)
                if self.current.kind == "video" and self.settings.get("history_enabled"):
                    self.db.mark_watched(self.current.path)
            if self.repeat == REPEAT_ONE:
                self.player.setPosition(0)
                self.player.play()
            else:
                nxt = self._neighbor(1)
                if nxt is not None:
                    self._load(nxt)
        elif status == S.InvalidMedia:
            self._skip_after_failure("Formato no compatible o archivo dañado")

    def _on_error(self, err, msg: str) -> None:
        if err == QMediaPlayer.Error.NoError:
            return
        self._skip_after_failure(msg or "Error de reproducción")

    def _skip_after_failure(self, msg: str) -> None:
        name = Path(self.current.path).name if self.current else ""
        self.error.emit(f"No se puede reproducir «{name}»: {msg}")
        self._failures += 1
        if self._failures < min(5, len(self.queue)):
            nxt = self._neighbor(1)
            if nxt is not None and nxt != self.index:
                QTimer.singleShot(400, lambda: self._load(nxt))

    # ---------------------------------------------------------------- controles
    @property
    def playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def toggle(self) -> None:
        if self.playing:
            self.player.pause()
        elif self.queue:
            if self.player.mediaStatus() == QMediaPlayer.MediaStatus.NoMedia and 0 <= self.index < len(self.queue):
                self._load(self.index)
            else:
                self.player.play()

    def _priority(self, state) -> None:
        """Con vídeo en reproducción, las tareas en segundo plano bajan a una (la imagen no debe tirones)."""
        from PySide6.QtMultimedia import QMediaPlayer

        from aero.core.tasks import tasks

        video = self.current is not None and self.current.kind == "video"
        tasks().mark_busy(self, video and state == QMediaPlayer.PlaybackState.PlayingState)

    def stop(self) -> None:
        self.save_position()
        self.player.stop()

    def seek(self, ms: int) -> None:
        if self.player.isSeekable():
            self.player.setPosition(max(0, min(ms, max(0, self.player.duration() - 250))))

    def seek_relative(self, delta_ms: int) -> None:
        self.seek(self.player.position() + delta_ms)

    def set_volume(self, v: float) -> None:
        v = max(0.0, min(1.0, v))
        self.audio.setVolume(v)
        if v > 0 and self.audio.isMuted():
            self.audio.setMuted(False)
        if self.settings.get("remember_volume"):
            self.settings.set("volume", round(v, 3))
        self.volume_changed.emit(v, self.audio.isMuted())

    def toggle_mute(self) -> None:
        self.audio.setMuted(not self.audio.isMuted())
        self.volume_changed.emit(self.audio.volume(), self.audio.isMuted())

    def set_rate(self, r: float) -> None:
        self.player.setPlaybackRate(r)

    def set_shuffle(self, on: bool) -> None:
        self.shuffle = on
        self._rebuild_shuffle(self.index)
        self.modes_changed.emit()

    def cycle_repeat(self) -> None:
        self.repeat = (self.repeat + 1) % 3
        self.modes_changed.emit()

    # ---------------------------------------------------------------- pistas y subtítulos
    def audio_tracks(self) -> list[str]:
        return [_track_label(md, i) for i, md in enumerate(self.player.audioTracks())]

    def subtitle_tracks(self) -> list[str]:
        return [_track_label(md, i) for i, md in enumerate(self.player.subtitleTracks())]

    def set_audio_track(self, i: int) -> None:
        self.player.setActiveAudioTrack(i)

    def set_subtitle_track(self, i: int) -> None:
        """-1 desactiva las pistas incrustadas."""
        self.player.setActiveSubtitleTrack(i)
        if i >= 0:
            self.ext_subs = None
            self._set_sub_text("")

    def load_external_subtitles(self, path: str) -> None:
        self.ext_subs = SubtitleTrack.load(path)
        self.player.setActiveSubtitleTrack(-1)
        self._update_subs(self.player.position())

    def set_sub_offset(self, ms: int) -> None:
        self.sub_offset_ms = ms
        self._update_subs(self.player.position())

    def _on_position(self, ms: int) -> None:
        self.position_changed.emit(ms)
        self._update_subs(ms)

    def _update_subs(self, ms: int) -> None:
        if self.ext_subs is not None:
            self._set_sub_text(self.ext_subs.text_at(ms - self.sub_offset_ms))

    def _set_sub_text(self, text: str) -> None:
        if text != self._last_sub:
            self._last_sub = text
            self.subtitle_text.emit(text)

    # ---------------------------------------------------------------- persistencia
    def save_position(self) -> None:
        if not self.current or not self.settings.get("remember_position") or not self.settings.get("history_enabled"):
            return
        dur = self.player.duration()
        pos = self.player.position()
        if self.current.kind == "video" or dur >= RESUME_MIN_MS:
            if 5000 < pos < dur - 15000:
                self.db.save_position(self.current.path, pos)
            elif pos >= dur - 15000 > 0:
                self.db.save_position(self.current.path, 0)


def _track_label(md: QMediaMetaData, i: int) -> str:
    lang = md.value(QMediaMetaData.Key.Language)
    title = md.stringValue(QMediaMetaData.Key.Title)
    parts = [f"Pista {i + 1}"]
    try:
        from PySide6.QtCore import QLocale

        if lang is not None and lang != QLocale.Language.AnyLanguage:
            parts.append(QLocale.languageToString(lang))
    except (TypeError, ValueError):
        pass
    if title:
        parts.append(title)
    return " · ".join(parts)
