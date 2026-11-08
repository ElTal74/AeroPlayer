"""Análisis de audio real (FFT) a partir de las muestras que entrega QAudioBufferOutput."""

from __future__ import annotations

import numpy as np

FFT_SIZE = 2048
BANDS = 64


class AudioAnalyzer:
    """Anillo de muestras mono + espectro logarítmico suavizado. Coste: ~0.2 ms por fotograma."""

    def __init__(self, bands: int = BANDS, sample_rate: int = 44100):
        self.ring = np.zeros(FFT_SIZE * 2, dtype=np.float32)
        self.write = 0
        self.sample_rate = sample_rate
        self.window = np.hanning(FFT_SIZE).astype(np.float32)
        self.bands = bands
        self.spectrum = np.zeros(bands, dtype=np.float32)
        self.peaks = np.zeros(bands, dtype=np.float32)
        self.level = 0.0
        self.bass = 0.0
        self.beat = 0.0
        self._bass_avg = 0.0
        self._edges = self._band_edges(sample_rate)
        self.fresh = False

    def _band_edges(self, sr: int) -> np.ndarray:
        nyq = sr / 2
        freqs = np.geomspace(32, min(16000, nyq * 0.95), self.bands + 1)
        idx = np.clip((freqs / nyq * (FFT_SIZE // 2)).astype(int), 1, FFT_SIZE // 2)
        # Garantizar al menos un bin por banda.
        for i in range(1, len(idx)):
            if idx[i] <= idx[i - 1]:
                idx[i] = idx[i - 1] + 1
        return np.clip(idx, 1, FFT_SIZE // 2)

    def reset(self) -> None:
        self.ring[:] = 0
        self.spectrum[:] = 0
        self.peaks[:] = 0
        self.level = self.bass = self.beat = 0.0

    def feed(self, data, channels: int, sample_rate: int) -> None:
        samples = np.frombuffer(data, dtype=np.float32)
        if channels > 1:
            n = len(samples) // channels
            samples = samples[: n * channels].reshape(n, channels).mean(axis=1)
        if sample_rate != self.sample_rate:
            self.sample_rate = sample_rate
            self._edges = self._band_edges(sample_rate)
        n = len(samples)
        if n == 0:
            return
        if n >= len(self.ring):
            self.ring[:] = samples[-len(self.ring):]
            self.write = 0
        else:
            end = self.write + n
            if end <= len(self.ring):
                self.ring[self.write:end] = samples
            else:
                k = len(self.ring) - self.write
                self.ring[self.write:] = samples[:k]
                self.ring[: n - k] = samples[k:]
            self.write = end % len(self.ring)
        self.fresh = True

    def latest(self, count: int) -> np.ndarray:
        idx = (np.arange(self.write - count, self.write)) % len(self.ring)
        return self.ring[idx]

    def update(self, dt: float = 1 / 60) -> None:
        """Recalcula espectro, nivel y detección de pulsos. Llamar una vez por fotograma."""
        if not self.fresh:
            # Sin audio nuevo (pausa): caída suave hacia cero.
            self.spectrum *= 0.86
            self.peaks *= 0.95
            self.level *= 0.86
            self.bass *= 0.86
            self.beat *= 0.8
            return
        self.fresh = False
        frame = self.latest(FFT_SIZE) * self.window
        mag = np.abs(np.fft.rfft(frame)) / (FFT_SIZE / 4)
        cums = np.concatenate(([0.0], np.cumsum(mag)))
        e = self._edges
        bands = (cums[e[1:]] - cums[e[:-1]]) / np.maximum(1, e[1:] - e[:-1])
        db = 20 * np.log10(bands + 1e-6)
        target = np.clip((db + 62) / 58, 0, 1).astype(np.float32)
        # Ligera compensación para que los agudos no queden siempre bajos.
        target *= np.linspace(0.9, 1.25, self.bands, dtype=np.float32)
        np.clip(target, 0, 1, out=target)
        rise = target > self.spectrum
        self.spectrum = np.where(rise, self.spectrum + (target - self.spectrum) * 0.65,
                                 self.spectrum * 0.88 + target * 0.12)
        self.peaks = np.maximum(self.peaks - 0.012, self.spectrum)
        rms = float(np.sqrt(np.mean(frame ** 2)) * 2.2)
        self.level = self.level * 0.7 + min(1.0, rms) * 0.3
        bass = float(self.spectrum[: max(1, self.bands // 8)].mean())
        self.bass = bass
        self._bass_avg = self._bass_avg * 0.94 + bass * 0.06
        if bass > self._bass_avg * 1.18 and bass > 0.35:
            self.beat = 1.0
        else:
            self.beat *= 0.85
