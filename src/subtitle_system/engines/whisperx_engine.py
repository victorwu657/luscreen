import json
import os
import sys
import datetime
from typing import Any

from src.subtitle_system.formatter import SubtitleSegment
from src.utils import get_runtime_base_dir, get_runtime_data_dir


def _ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def get_whisperx_models_root() -> str:
    return os.path.join(get_runtime_data_dir(), "models", "whisperx")


def prepare_whisperx_cache_env() -> dict[str, str]:
    root = get_whisperx_models_root()
    hf_home = _ensure_dir(os.path.join(root, "hf_home"))
    whisper_root = _ensure_dir(os.path.join(root, "whisper"))
    align_root = _ensure_dir(os.path.join(root, "align"))

    env = {}
    env["HF_HOME"] = hf_home
    env["HF_HUB_CACHE"] = os.path.join(hf_home, "hub")
    env["TRANSFORMERS_CACHE"] = os.path.join(hf_home, "transformers")
    env["TORCH_HOME"] = os.path.join(hf_home, "torch")
    env["WHISPERX_WHISPER_ROOT"] = whisper_root
    env["WHISPERX_ALIGN_ROOT"] = align_root
    return env


def _append_log(name: str, content: str):
    try:
        base = get_runtime_data_dir()
        logs_dir = os.path.join(base, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        path = os.path.join(logs_dir, name)
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            lines = (content or "").splitlines(True)
            if not lines:
                f.write(f"[{ts}]\n")
                return None
            for ln in lines:
                if ln.strip() == "":
                    f.write(ln)
                else:
                    f.write(f"[{ts}] {ln}")
    except Exception:
        return None


class WhisperXEngine:
    def __init__(self):
        for k, v in prepare_whisperx_cache_env().items():
            os.environ.setdefault(k, v)
        self._model_ref: str | None = None
        self._device: str | None = None
        self._compute_type: str | None = None
        self._beam_size: int | None = None
        self._model = None
        self._align_cache: dict[tuple[str, str], tuple[object, dict[str, Any]]] = {}

    def transcribe_with_words(
        self,
        *,
        audio_path: str,
        model_ref: str,
        device: str,
        compute_type: str,
        batch_size: int,
        beam_size: int,
        language: str | None = None,
    ) -> tuple[list[SubtitleSegment], list[dict[str, Any]]]:
        try:
            import whisperx
        except Exception as e:
            pyver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            hint = (
                "未检测到本地字幕组件（whisperx/torch），无法使用本地字幕。"
                "打包版请下载安装“字幕组件包/完整版本”；开发环境请执行：pip install -r requirements.txt"
                f" | python={pyver} exe={sys.executable}"
            )
            raise RuntimeError(f"{hint} | {type(e).__name__}: {e}")

        audio = whisperx.load_audio(audio_path)

        download_root = os.environ.get("WHISPERX_WHISPER_ROOT") or os.path.join(get_whisperx_models_root(), "whisper")
        try:
            if (
                self._model is None
                or self._model_ref != model_ref
                or self._device != device
                or self._compute_type != compute_type
                or self._beam_size != int(beam_size)
            ):
                asr_options = {"beam_size": int(beam_size), "best_of": int(beam_size)}
                self._model = whisperx.load_model(
                    model_ref,
                    device,
                    compute_type=compute_type,
                    download_root=download_root,
                    vad_method="pyannote",
                    asr_options=asr_options,
                )
                self._model_ref = model_ref
                self._device = device
                self._compute_type = compute_type
                self._beam_size = int(beam_size)
                _append_log(
                    "subtitle_whisperx_model_load.log",
                    f"model_ref={model_ref}\ndevice={device}\ncompute_type={compute_type}\nbeam_size={int(beam_size)}\ndownload_root={download_root}\n----\n",
                )
            model = self._model
        except TypeError:
            if (
                self._model is None
                or self._model_ref != model_ref
                or self._device != device
                or self._compute_type != compute_type
                or self._beam_size != int(beam_size)
            ):
                asr_options = {"beam_size": int(beam_size), "best_of": int(beam_size)}
                self._model = whisperx.load_model(
                    model_ref,
                    device,
                    compute_type=compute_type,
                    vad_method="pyannote",
                    asr_options=asr_options,
                )
                self._model_ref = model_ref
                self._device = device
                self._compute_type = compute_type
                self._beam_size = int(beam_size)
                _append_log(
                    "subtitle_whisperx_model_load.log",
                    f"model_ref={model_ref}\ndevice={device}\ncompute_type={compute_type}\nbeam_size={int(beam_size)}\ndownload_root={download_root}\n----\n",
                )
            model = self._model

        kwargs = {"batch_size": int(batch_size)}
        if language:
            kwargs["language"] = str(language)
        result = model.transcribe(audio, **kwargs)

        lang = str(result.get("language") or "").strip() or "en"
        aligned = None
        try:
            cache_key = (lang, str(device))
            cached = self._align_cache.get(cache_key)
            if cached is None:
                model_a, metadata = whisperx.load_align_model(language_code=lang, device=device)
                self._align_cache[cache_key] = (model_a, metadata)
            else:
                model_a, metadata = cached
            aligned = whisperx.align(
                result["segments"],
                model_a,
                metadata,
                audio,
                device,
                return_char_alignments=False,
            )
        except Exception as e:
            _append_log(
                "subtitle_whisperx_align_error.log",
                f"audio_path={audio_path}\nmodel_ref={model_ref}\ndevice={device}\ncompute_type={compute_type}\nlang={lang}\nerror={type(e).__name__}: {e}\n----\n",
            )
            aligned = {"segments": result.get("segments") or []}

        segments_out: list[SubtitleSegment] = []
        words_out: list[dict[str, Any]] = []

        for seg in (aligned.get("segments") if isinstance(aligned, dict) else None) or []:
            try:
                start = float(seg.get("start") or 0.0)
                end = float(seg.get("end") or 0.0)
                text = str(seg.get("text") or "").strip()
            except Exception:
                continue
            if text:
                segments_out.append(SubtitleSegment(start=start, end=end, text=text))
            for w in (seg.get("words") or []):
                try:
                    ws = w.get("start")
                    we = w.get("end")
                    word = str(w.get("word") or "")
                    if ws is None or we is None or not word:
                        continue
                    words_out.append({"start": float(ws), "end": float(we), "word": word})
                except Exception:
                    continue

        return segments_out, words_out


def dump_words_json(*, out_path: str, words: list[dict[str, Any]], extra: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {"words": words}
    if extra:
        payload.update(extra)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return out_path
