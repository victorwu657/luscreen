from dataclasses import dataclass
from typing import List
import re

@dataclass
class SubtitleSegment:
    start: float  # seconds
    end: float    # seconds
    text: str

class SubtitleFormatter:
    _CJK_BREAK_CHARS = set("，。！？；：、,.!?;: )]】》〉」』」")

    @staticmethod
    def _has_cjk(text: str) -> bool:
        for ch in text:
            o = ord(ch)
            if (
                0x4E00 <= o <= 0x9FFF
                or 0x3400 <= o <= 0x4DBF
                or 0x3040 <= o <= 0x30FF
                or 0xAC00 <= o <= 0xD7AF
            ):
                return True
        return False

    @staticmethod
    def _wrap_text(text: str, *, max_chars_per_line: int) -> str:
        t = (text or "").strip()
        if not t:
            return ""
        t = t.replace("\r\n", "\n").replace("\r", "\n")
        t = re.sub(r"[ \t]+", " ", t.replace("\n", " ")).strip()
        if len(t) <= max_chars_per_line:
            return t

        has_space = " " in t
        has_cjk = SubtitleFormatter._has_cjk(t)
        if has_space and not has_cjk:
            words = [w for w in t.split(" ") if w]
            lines: list[str] = []
            cur = ""
            for w in words:
                if not cur:
                    cur = w
                    continue
                if len(cur) + 1 + len(w) <= max_chars_per_line:
                    cur = f"{cur} {w}"
                else:
                    lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)
            return "\n".join(lines)

        lines: list[str] = []
        i = 0
        n = len(t)
        while i < n:
            end = min(n, i + max_chars_per_line)
            chunk = t[i:end]
            if end < n:
                cut = -1
                for j in range(len(chunk) - 1, -1, -1):
                    if chunk[j] in SubtitleFormatter._CJK_BREAK_CHARS:
                        cut = j + 1
                        break
                if cut > 0 and cut >= max(1, int(max_chars_per_line * 0.6)):
                    lines.append(chunk[:cut].rstrip())
                    i += cut
                    continue
            lines.append(chunk.rstrip())
            i = end
        return "\n".join([ln for ln in lines if ln])

    @staticmethod
    def segments_from_words(
        words: list[dict],
        *,
        max_chars_per_cue: int | None = None,
        max_cue_seconds: float | None = None,
        pause_seconds: float | None = None,
        max_gap_seconds: float = 0.8,
        min_cue_seconds: float = 0.2,
    ) -> List[SubtitleSegment]:
        items: list[dict] = []
        for w in words or []:
            try:
                ws = w.get("start")
                we = w.get("end")
                word = str(w.get("word") or "")
                if ws is None or we is None:
                    continue
                ws = float(ws)
                we = float(we)
                if not word.strip():
                    continue
                items.append({"start": ws, "end": we, "word": word})
            except Exception:
                continue
        if not items:
            return []

        sample_text = "".join([str(w.get("word") or "") for w in items[:200]])
        is_cjk = SubtitleFormatter._has_cjk(sample_text)
        limit = int(max_chars_per_cue or (12 if is_cjk else 32))
        max_dur = float(max_cue_seconds) if max_cue_seconds is not None else (2.0 if is_cjk else 3.5)
        pause = float(pause_seconds) if pause_seconds is not None else None

        def _text_len(s: str) -> int:
            return len(re.sub(r"\s+", " ", (s or "").strip()))

        def _norm_text(s: str) -> str:
            if is_cjk:
                return re.sub(r"\s+", "", (s or "")).strip()
            return re.sub(r"\s+", " ", (s or "")).strip()

        def _is_punct(word: str) -> bool:
            t = (word or "").strip()
            if not t:
                return False
            for ch in t:
                if ch.isalnum():
                    return False
            return True

        def _is_single_cjk_char(word: str) -> bool:
            t = (word or "").strip()
            return len(t) == 1 and SubtitleFormatter._has_cjk(t)

        def _ends_with_break_punct(text: str) -> bool:
            t = (text or "").rstrip()
            if not t:
                return False
            return t[-1] in SubtitleFormatter._CJK_BREAK_CHARS

        gaps: list[float] = []
        for a, b in zip(items, items[1:]):
            try:
                gaps.append(float(b["start"]) - float(a["end"]))
            except Exception:
                continue
        gaps = [g for g in gaps if g is not None and g >= 0]
        gaps_sorted = sorted(gaps)
        med_gap = gaps_sorted[len(gaps_sorted) // 2] if gaps_sorted else 0.0
        pause_thr = pause if pause is not None else max(0.28 if is_cjk else 0.35, min(0.75, med_gap * 4.0 if med_gap > 0 else (0.45 if is_cjk else 0.6)))
        pause_min_len = 4 if is_cjk else 12

        out: list[SubtitleSegment] = []
        cur = ""
        cur_start: float | None = None
        cur_end: float | None = None
        candidates: list[tuple[float, float, str]] = []

        for idx, w in enumerate(items):
            ws = float(w["start"])
            we = float(w["end"])
            wd = str(w["word"])
            if cur_start is None:
                cur = wd
                cur_start = ws
                cur_end = we
                candidates = []
                continue

            gap = ws - float(cur_end or ws)
            cand = cur + wd
            cand_len = _text_len(cand)
            wd_is_orphan = is_cjk and _is_single_cjk_char(wd) and (not _is_punct(wd))

            if gap >= pause_thr and cur_start is not None:
                cur_len = _text_len(cur)
                cur_dur = float(cur_end or ws) - float(cur_start)
                if cur_len >= pause_min_len and cur_dur >= max(0.6, float(min_cue_seconds)):
                    st = float(cur_start)
                    ed = float(cur_end or st)
                    if ed <= st:
                        ed = st + float(min_cue_seconds)
                    out.append(SubtitleSegment(start=st, end=ed, text=_norm_text(cur)))
                    cur = wd
                    cur_start = ws
                    cur_end = we
                    candidates = []
                    continue

            if gap >= pause_thr and _text_len(cur) >= pause_min_len:
                score = gap * 3.0 + (1.0 if _ends_with_break_punct(cur) else 0.0)
                candidates.append((score, float(cur_end or ws), _norm_text(cur)))

            if _ends_with_break_punct(cand) and _text_len(cand) >= pause_min_len:
                candidates.append((0.5, float(we), _norm_text(cand)))

            force_break = False
            if max_dur > 0 and cur_start is not None and (we - float(cur_start)) > max_dur and _text_len(cur) >= max(4, int(limit * 0.3)):
                force_break = True
            if cand_len > limit and _text_len(cur) > 0 and not _is_punct(wd):
                force_break = True
            if gap > float(max_gap_seconds) and _text_len(cur) >= max(6, int(limit * 0.4)):
                force_break = True

            if force_break:
                st = float(cur_start)

                if wd_is_orphan:
                    can_soft_overflow = cand_len <= (limit + 1)
                    dur_ok = (max_dur <= 0) or (cur_start is None) or ((we - float(cur_start)) <= (max_dur + 0.35))
                    if can_soft_overflow and dur_ok:
                        out.append(SubtitleSegment(start=st, end=float(we), text=_norm_text(cand)))
                        cur = ""
                        cur_start = None
                        cur_end = None
                        candidates = []
                        continue

                pick = None
                if candidates:
                    pick = max(candidates, key=lambda x: x[0])
                if pick is not None and pick[1] > st:
                    out.append(SubtitleSegment(start=st, end=pick[1], text=pick[2]))
                    cur = wd
                    cur_start = ws
                    cur_end = we
                    candidates = []
                    continue

                ed = float(cur_end or st)
                if ed <= st:
                    ed = st + float(min_cue_seconds)
                out.append(SubtitleSegment(start=st, end=ed, text=_norm_text(cur)))
                cur = wd
                cur_start = ws
                cur_end = we
                candidates = []
                continue

            cur = cand
            cur_end = we

        if cur_start is not None:
            st = float(cur_start)
            ed = float(cur_end or st)
            if ed <= st:
                ed = st + float(min_cue_seconds)
            out.append(SubtitleSegment(start=st, end=ed, text=_norm_text(cur)))

        if min_cue_seconds > 0:
            fixed: list[SubtitleSegment] = []
            for seg in out:
                st = float(seg.start)
                ed = float(seg.end)
                if ed - st < float(min_cue_seconds):
                    ed = st + float(min_cue_seconds)
                fixed.append(SubtitleSegment(start=st, end=ed, text=seg.text))
            out = fixed

        return out

    @staticmethod
    def format_time(seconds: float) -> str:
        """Convert seconds to SRT timestamp format: HH:MM:SS,mmm"""
        seconds = float(seconds or 0.0)
        if seconds < 0:
            seconds = 0.0

        total_ms = int(round(seconds * 1000.0))
        hours = total_ms // 3600000
        rem = total_ms % 3600000
        minutes = rem // 60000
        rem = rem % 60000
        secs = rem // 1000
        millis = rem % 1000
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    @staticmethod
    def to_srt(segments: List[SubtitleSegment], *, wrap: bool = True) -> str:
        """Convert segments to SRT string"""
        output = []
        for idx, seg in enumerate(segments, 1):
            start_str = SubtitleFormatter.format_time(seg.start)
            end_str = SubtitleFormatter.format_time(seg.end)
            output.append(f"{idx}")
            output.append(f"{start_str} --> {end_str}")
            raw_text = seg.text if seg and seg.text is not None else ""
            if wrap:
                max_len = 18 if SubtitleFormatter._has_cjk(raw_text) else 42
                output.append(SubtitleFormatter._wrap_text(raw_text, max_chars_per_line=max_len))
            else:
                output.append(str(raw_text).strip())
            output.append("") # Empty line after each subtitle
        return "\n".join(output)
