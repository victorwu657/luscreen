from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Any, Tuple

import numpy as np

from . import filters as filters

__version__ = "0.0.0-luscreen"
__all__ = ["__version__", "load", "stft", "filters"]


def load(path: str, sr: int | None = 22050, mono: bool = True, **kwargs) -> Tuple[np.ndarray, int]:
    p = str(path)
    suffix = Path(p).suffix.lower()
    if suffix not in (".wav",):
        raise RuntimeError(f"librosa stub only supports wav input, got: {suffix}")

    with wave.open(p, "rb") as wf:
        file_sr = int(wf.getframerate())
        n_channels = int(wf.getnchannels())
        sampwidth = int(wf.getsampwidth())
        n_frames = int(wf.getnframes())
        frames = wf.readframes(n_frames)

    if sampwidth == 2:
        x = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        x = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise RuntimeError(f"librosa stub only supports PCM16/PCM32 wav, sampwidth={sampwidth}")

    if n_channels > 1:
        x = x.reshape(-1, n_channels)
        if mono:
            x = x.mean(axis=1)
        else:
            x = x.T

    target_sr = file_sr if sr is None else int(sr)
    if target_sr != file_sr and x.size > 0:
        ratio = float(target_sr) / float(file_sr)
        new_len = max(1, int(round(x.shape[-1] * ratio)))
        t_old = np.linspace(0.0, 1.0, num=x.shape[-1], endpoint=False, dtype=np.float32)
        t_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False, dtype=np.float32)
        x = np.interp(t_new, t_old, x).astype(np.float32)

    return x.astype(np.float32), target_sr


def stft(
    y: np.ndarray,
    n_fft: int = 2048,
    hop_length: int | None = None,
    win_length: int | None = None,
    window: Any = "hann",
    center: bool = True,
    **kwargs,
) -> np.ndarray:
    y = np.asarray(y, dtype=np.float32).reshape(-1)
    n_fft = int(n_fft)
    hop_length = int(hop_length) if hop_length is not None else n_fft // 4
    win_length = int(win_length) if win_length is not None else n_fft

    if isinstance(window, str):
        if window.lower() in ("hann", "hanning"):
            win = np.hanning(win_length).astype(np.float32)
        else:
            win = np.ones(win_length, dtype=np.float32)
    else:
        win = np.asarray(window, dtype=np.float32).reshape(-1)
        win_length = int(win.shape[0])

    if win_length < n_fft:
        left = (n_fft - win_length) // 2
        right = n_fft - win_length - left
        win = np.pad(win, (left, right), mode="constant")
    elif win_length > n_fft:
        win = win[:n_fft]

    if center:
        pad = n_fft // 2
        y = np.pad(y, (pad, pad), mode="constant")

    if y.size < n_fft:
        y = np.pad(y, (0, n_fft - y.size), mode="constant")

    n_frames = 1 + (y.size - n_fft) // hop_length
    frames = np.lib.stride_tricks.as_strided(
        y,
        shape=(n_frames, n_fft),
        strides=(y.strides[0] * hop_length, y.strides[0]),
        writeable=False,
    )

    windowed = frames * win[None, :]
    spec = np.fft.rfft(windowed, n=n_fft, axis=1)
    return spec.T

