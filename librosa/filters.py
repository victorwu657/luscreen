from __future__ import annotations

import numpy as np

__all__ = ["mel"]


def _hz_to_mel(f: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + (f / 700.0))


def _mel_to_hz(m: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


def mel(
    sr: int,
    n_fft: int,
    n_mels: int = 128,
    fmin: float = 0.0,
    fmax: float | None = None,
    htk: bool = True,
    norm: str | None = "slaney",
    **kwargs,
) -> np.ndarray:
    sr = int(sr)
    n_fft = int(n_fft)
    n_mels = int(n_mels)
    fmin = float(fmin)
    fmax = float(sr / 2.0) if fmax is None else float(fmax)

    n_freqs = 1 + n_fft // 2
    fft_freqs = np.linspace(0.0, float(sr) / 2.0, num=n_freqs, dtype=np.float32)

    min_mel = _hz_to_mel(np.array([fmin], dtype=np.float32))[0]
    max_mel = _hz_to_mel(np.array([fmax], dtype=np.float32))[0]
    mels = np.linspace(min_mel, max_mel, num=n_mels + 2, dtype=np.float32)
    hz = _mel_to_hz(mels)

    fb = np.zeros((n_mels, n_freqs), dtype=np.float32)
    for i in range(n_mels):
        f_left = hz[i]
        f_center = hz[i + 1]
        f_right = hz[i + 2]
        if f_center <= f_left or f_right <= f_center:
            continue

        left_slope = (fft_freqs - f_left) / max(1e-12, (f_center - f_left))
        right_slope = (f_right - fft_freqs) / max(1e-12, (f_right - f_center))
        fb[i] = np.maximum(0.0, np.minimum(left_slope, right_slope))

    if norm and str(norm).lower() == "slaney":
        enorm = 2.0 / (hz[2 : n_mels + 2] - hz[:n_mels])
        fb *= enorm[:, None]

    return fb

