import math
import wave
from dataclasses import dataclass
from typing import Iterable, List, Tuple

from src.subtitle_system.formatter import SubtitleSegment


def _read_wav_activity(
    wav_path: str,
    start_s: float,
    end_s: float,
    hop_ms: int = 20,
) -> List[int]:
    start_s = max(0.0, float(start_s))
    end_s = max(start_s, float(end_s))
    hop_ms = int(hop_ms)
    if hop_ms <= 0:
        hop_ms = 20

    with wave.open(wav_path, "rb") as wf:
        sr = int(wf.getframerate())
        n_channels = int(wf.getnchannels())
        sampwidth = int(wf.getsampwidth())
        if sampwidth != 2:
            raise ValueError("仅支持16-bit PCM WAV")
        hop = max(1, int(sr * hop_ms / 1000))
        start_frame = int(start_s * sr)
        end_frame = int(end_s * sr)
        total_frames = max(0, end_frame - start_frame)
        wf.setpos(min(start_frame, wf.getnframes()))

        energies: List[float] = []
        frames_read = 0
        while frames_read < total_frames:
            need = min(hop, total_frames - frames_read)
            data = wf.readframes(need)
            if not data:
                break
            frames_read += need
            samples = memoryview(data).cast("h")
            if n_channels > 1:
                acc = 0.0
                count = 0
                for i in range(0, len(samples), n_channels):
                    acc += abs(int(samples[i]))
                    count += 1
                e = acc / max(1, count)
            else:
                acc = 0.0
                for v in samples:
                    acc += abs(int(v))
                e = acc / max(1, len(samples))
            energies.append(float(e))

    if not energies:
        return []

    sorted_e = sorted(energies)
    p20 = sorted_e[int(0.2 * (len(sorted_e) - 1))]
    p80 = sorted_e[int(0.8 * (len(sorted_e) - 1))]
    thr = p20 + (p80 - p20) * 0.35
    thr = max(thr, p20 * 2.0, 80.0)

    act = [1 if e > thr else 0 for e in energies]
    for _ in range(2):
        for i in range(1, len(act) - 1):
            if act[i] == 0 and act[i - 1] == 1 and act[i + 1] == 1:
                act[i] = 1
        for i in range(1, len(act) - 1):
            if act[i] == 1 and act[i - 1] == 0 and act[i + 1] == 0:
                act[i] = 0
    return act


def _subtitle_activity(
    segments: Iterable[SubtitleSegment],
    start_s: float,
    end_s: float,
    hop_ms: int = 20,
) -> List[int]:
    start_s = float(start_s)
    end_s = float(end_s)
    hop_s = max(0.001, float(hop_ms) / 1000.0)
    n = int(math.ceil(max(0.0, end_s - start_s) / hop_s))
    if n <= 0:
        return []
    segs = [(float(s.start), float(s.end)) for s in segments if getattr(s, "text", None)]
    segs.sort()
    out = [0] * n
    j = 0
    for i in range(n):
        t = start_s + i * hop_s
        while j < len(segs) and segs[j][1] <= t:
            j += 1
        if j < len(segs) and segs[j][0] <= t < segs[j][1]:
            out[i] = 1
    return out


def _best_offset_ms(
    audio_act: List[int],
    sub_act: List[int],
    search_ms: int,
    hop_ms: int,
) -> int:
    if not audio_act or not sub_act:
        return 0
    n = min(len(audio_act), len(sub_act))
    audio_act = audio_act[:n]
    sub_act = sub_act[:n]

    w = [(2 * a - 1) for a in audio_act]
    max_shift = int(round(float(search_ms) / float(hop_ms)))
    best = 0
    best_score = None
    for shift in range(-max_shift, max_shift + 1):
        score = 0
        if shift >= 0:
            for i in range(shift, n):
                if sub_act[i - shift]:
                    score += w[i]
        else:
            k = -shift
            for i in range(0, n - k):
                if sub_act[i + k]:
                    score += w[i]
        if best_score is None or score > best_score or (score == best_score and abs(shift) < abs(best)):
            best_score = score
            best = shift
    return int(best * hop_ms)


def estimate_offsets_for_drift(
    audio_wav_path: str,
    segments: List[SubtitleSegment],
    window_s: float = 60.0,
    search_ms: int = 1500,
    hop_ms: int = 20,
) -> Tuple[int, int]:
    if not segments:
        return 0, 0

    try:
        with wave.open(audio_wav_path, "rb") as wf:
            dur_s = float(wf.getnframes()) / float(wf.getframerate())
    except Exception:
        dur_s = max(float(s.end) for s in segments)

    window_s = float(window_s)
    if window_s <= 5:
        window_s = 5.0
    w = min(window_s, dur_s)

    a0 = _read_wav_activity(audio_wav_path, 0.0, w, hop_ms=hop_ms)
    s0 = _subtitle_activity(segments, 0.0, w, hop_ms=hop_ms)
    start_ms = _best_offset_ms(a0, s0, search_ms=search_ms, hop_ms=hop_ms)

    tail_start = max(0.0, dur_s - w)
    a1 = _read_wav_activity(audio_wav_path, tail_start, dur_s, hop_ms=hop_ms)
    s1 = _subtitle_activity(segments, tail_start, dur_s, hop_ms=hop_ms)
    end_ms = _best_offset_ms(a1, s1, search_ms=search_ms, hop_ms=hop_ms)
    return int(start_ms), int(end_ms)

