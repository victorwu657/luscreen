import os
import sys
import json
import tempfile
import threading
import uuid
import subprocess
import shutil
import re
import datetime
import wave
from PySide6.QtCore import QObject, Signal, QThread

from src.subtitle_system.extractor import AudioExtractor
from src.subtitle_system.formatter import SubtitleFormatter
from src.subtitle_system.engines.openai_engine import OpenAIEngine
from src.subtitle_system.model_registry import list_available_local_models, get_default_whisperx_model_id
from src.subtitle_system.device_policy import is_cuda_available, log_cuda_status
from src.utils import get_long_windows_path, get_media_duration_sec, get_runtime_base_dir


def _resolve_current_executable() -> str:
    argv0 = (sys.argv[0] if sys.argv else "") or ""
    if argv0 and argv0.lower().endswith(".exe"):
        argv0_abs = argv0 if os.path.isabs(argv0) else os.path.abspath(argv0)
        base = os.path.basename(argv0_abs).lower()
        if os.path.exists(argv0_abs) and not base.startswith("python"):
            return argv0_abs

    candidates = []
    if sys.executable:
        candidates.append(sys.executable)
    if argv0:
        candidates.append(argv0)

    for raw in candidates:
        p = raw or ""
        if not p:
            continue
        if not os.path.isabs(p):
            p = os.path.abspath(p)
        if os.path.exists(p):
            return p
        resolved = shutil.which(p) or shutil.which(os.path.basename(p))
        if resolved:
            return resolved

    return shutil.which("python") or "python"


_SRT_TS_RE = re.compile(r"(?P<s>\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(?P<e>\d{2}:\d{2}:\d{2},\d{3})")


def _srt_time_to_ms(t: str) -> int:
    s = (t or "").strip()
    try:
        hh, mm, rest = s.split(":", 2)
        ss, ms = rest.split(",", 1)
        return int(hh) * 3600000 + int(mm) * 60000 + int(ss) * 1000 + int(ms)
    except Exception:
        return 0


def _ms_to_srt_time(ms: int) -> str:
    v = int(max(0, ms))
    hh = v // 3600000
    v -= hh * 3600000
    mm = v // 60000
    v -= mm * 60000
    ss = v // 1000
    v -= ss * 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d},{v:03d}"


def _scale_srt_content(content: str, factor: float) -> str:
    f = float(factor)
    if not content:
        return content
    if not (0.2 <= f <= 5.0) or abs(f - 1.0) < 1e-9:
        return content

    def repl(m: re.Match) -> str:
        s_ms = _srt_time_to_ms(m.group("s"))
        e_ms = _srt_time_to_ms(m.group("e"))
        s2 = int(round(float(s_ms) * f))
        e2 = int(round(float(e_ms) * f))
        if e2 <= s2:
            e2 = s2 + 50
        return f"{_ms_to_srt_time(s2)} --> {_ms_to_srt_time(e2)}"

    return _SRT_TS_RE.sub(repl, content)


def _wav_duration_sec(path: str) -> float | None:
    if not path or not os.path.exists(path):
        return None
    try:
        with wave.open(path, "rb") as wf:
            fr = float(wf.getframerate() or 1)
            return float(wf.getnframes()) / fr
    except Exception:
        return None


def _maybe_fix_srt_timing(*, srt_path: str, audio_wav_path: str, media_path: str | None):
    if not srt_path or not os.path.exists(srt_path):
        return
    if not audio_wav_path or not os.path.exists(audio_wav_path):
        return

    media_dur = get_media_duration_sec(media_path) if media_path else None
    wav_dur = _wav_duration_sec(audio_wav_path)
    if not media_dur or not wav_dur:
        return
    if media_dur <= 0.2 or wav_dur <= 0.2:
        return

    factor = float(media_dur) / float(wav_dur)
    if not (0.8 <= factor <= 1.25):
        return
    if abs(factor - 1.0) <= 0.0008:
        return

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return

    new_content = _scale_srt_content(content, factor)
    if not new_content or new_content == content:
        return

    try:
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception:
        return

    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        logs_dir = os.path.join(project_root, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "subtitle_time_scale.log")
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(
                f"[{ts}] srt={srt_path}\n"
                f"media={media_path}\n"
                f"media_dur_sec={float(media_dur):.3f}\n"
                f"wav_dur_sec={float(wav_dur):.3f}\n"
                f"scale_factor={float(factor):.9f}\n"
                "----\n"
            )
    except Exception:
        pass


def _append_log(name: str, content: str):
    try:
        base = get_runtime_base_dir()
        logs_dir = os.path.join(base, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        path = os.path.join(logs_dir, name)
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(content)
    except Exception:
        return None


class _SubtitleService:
    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._engine = None
        self._model_key = None
        self._pipeline = None

    def _start(self, project_root: str):
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        pr = get_long_windows_path(project_root)
        env = os.environ.copy()
        env["PYTHONPATH"] = pr + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        torch_lib = os.path.join(pr, "torch", "lib")
        if os.path.exists(torch_lib):
            env["PATH"] = torch_lib + os.pathsep + (env.get("PATH") or "")
        exe_path = _resolve_current_executable()

        exe_base = os.path.basename(exe_path).lower()
        if exe_base.startswith("python"):
            env.pop("LUSCREEN_FORCE_PROJECT_ROOT", None)
            env.pop("LUSCREEN_DEBUG_DLL_DIR_STACK", None)
            env.pop("LUSCREEN_SUBTITLE_SERVICE_DIAG", None)
            env.setdefault("LUSCREEN_ASR_DEVICE", "cpu")
            cmd = [exe_path, "-m", "src.subtitle_system.service_process"]
        else:
            cmd = [exe_path, "--subtitle-service"]

        print("[SubtitleService] Spawning service process...")
        print(f"[SubtitleService] sys.executable={sys.executable!r}")
        print(f"[SubtitleService] sys.argv0={(sys.argv[0] if sys.argv else None)!r}")
        print(f"[SubtitleService] resolved_exe_path={exe_path!r} exists={os.path.exists(exe_path) if exe_path else False}")
        print(f"[SubtitleService] cwd={pr!r} exists={os.path.exists(pr)}")
        print(f"[SubtitleService] cmd={cmd!r}")
        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=pr,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo
            )
        except Exception as e:
            print(f"[SubtitleService] Spawn failed: {type(e).__name__}: {e}")
            raise

    def _stop(self):
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                self._proc.stdin.flush()
        except Exception:
            pass
        try:
            self._proc.terminate()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=3)
        except Exception:
            pass
        self._proc = None
        self._engine = None
        self._model_key = None
        self._pipeline = None

    def transcribe_to_srt(
        self,
        *,
        engine: str,
        audio_path: str,
        srt_output_path: str,
        model_dir: str | None,
        pipeline: str | None,
        extra: dict | None,
        progress_cb,
    ):
        project_root = get_long_windows_path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._stop()
                self._start(project_root)
            eng = (engine or "whisperx").strip().lower()
            model_key = (extra or {}).get("model_ref")
            if eng != self._engine or model_key != self._model_key or pipeline != self._pipeline:
                self._engine = eng
                self._model_key = model_key
                self._pipeline = pipeline
            try:
                pid = getattr(self._proc, "pid", None)
            except Exception:
                pid = None
            print(f"[SubtitleService] Using service pid={pid} engine={eng!r} model_key={model_key!r} pipeline={pipeline!r}")

            req = {"cmd": "transcribe", "engine": eng, "audio": audio_path, "out": srt_output_path}
            req.update(extra or {})
            if not self._proc or not self._proc.stdin or not self._proc.stdout:
                raise RuntimeError("Subtitle service unavailable.")
            self._proc.stdin.write(json.dumps(req) + "\n")
            self._proc.stdin.flush()

            diag_lines = []
            for line in self._proc.stdout:
                line = (line or "").strip()
                if line.startswith("PROGRESS\t"):
                    parts = line.split("\t", 2)
                    if len(parts) == 3:
                        try:
                            progress_cb(int(parts[1]), parts[2])
                        except Exception:
                            pass
                    continue
                if line.startswith("RESULT\t"):
                    parts = line.split("\t", 2)
                    if len(parts) == 3 and parts[1] == "OK":
                        return parts[2]
                    if len(parts) == 3 and parts[1] == "ERR":
                        msg = parts[2]
                        if diag_lines:
                            msg = (msg + "\n" + "\n".join(diag_lines[-40:])).strip()
                        raise RuntimeError(msg)
                    raise RuntimeError("Subtitle service invalid response.")
                if line:
                    diag_lines.append(line)
                    if len(diag_lines) > 80:
                        diag_lines = diag_lines[-80:]

            try:
                rc = self._proc.poll() if self._proc else None
            except Exception:
                rc = None
            if rc is None and self._proc is not None:
                try:
                    rc = self._proc.wait(timeout=0.2)
                except Exception:
                    rc = None
            diag = "\n".join(diag_lines[-40:])
            msg = f"Subtitle service terminated unexpectedly (exit={rc}).\n{diag}".strip()
            try:
                fault_path = os.path.join(project_root, "logs", "subtitle_service_fault.log")
                if os.path.exists(fault_path):
                    msg = (msg + f"\n\nFault log: {fault_path}").strip()
            except Exception:
                pass
            raise RuntimeError(msg)


_SUBTITLE_SERVICE = _SubtitleService()

class SubtitleWorker(QThread):
    progress = Signal(int, str) # value (0-100), message
    finished = Signal(str)      # srt_path
    error = Signal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._is_cancelled = False
        # Move heavy initialization to run() to avoid thread affinity issues
        # Objects created in __init__ belong to the caller thread (Main Thread)
        # But we want to use them in run() (Worker Thread)
        
    def run(self):
        audio_wav_path = None
        proc = None
        try:
            # print(f"[SubtitleWorker] Thread ID: {int(QThread.currentThreadId())}")
            # 1. Prepare Paths
            video_path = self.config['video_path']
            mic_path = self.config.get('mic_path')
            prefer_preview_audio = bool(self.config.get("prefer_preview_audio"))
            preview_path = self.config.get("preview_path")
            audio_source_path = preview_path if (prefer_preview_audio and preview_path and os.path.exists(preview_path)) else video_path
            if audio_source_path != video_path:
                mic_path = None
                try:
                    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    logs_dir = os.path.join(project_root, "logs")
                    os.makedirs(logs_dir, exist_ok=True)
                    log_path = os.path.join(logs_dir, "subtitle_audio_source.log")
                    with open(log_path, "a", encoding="utf-8") as lf:
                        lf.write(
                            f"video_path={video_path}\n"
                            f"preview_path={preview_path}\n"
                            f"audio_source_path={audio_source_path}\n"
                            "----\n"
                        )
                except Exception:
                    pass

            try:
                max_minutes = int(self.config.get("max_audio_minutes") or 60)
            except Exception:
                max_minutes = 60
            try:
                dur = get_media_duration_sec(audio_source_path)
            except Exception:
                dur = None
            if dur is not None and float(dur) > float(max_minutes) * 60.0 + 1.0:
                try:
                    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    logs_dir = os.path.join(project_root, "logs")
                    os.makedirs(logs_dir, exist_ok=True)
                    log_path = os.path.join(logs_dir, "subtitle_duration_limit.log")
                    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    with open(log_path, "a", encoding="utf-8") as lf:
                        lf.write(
                            f"[{ts}] duration_sec={float(dur):.3f} limit_min={int(max_minutes)}\n"
                            f"audio_source_path={audio_source_path}\n"
                            "----\n"
                        )
                except Exception:
                    pass
                raise RuntimeError(f"当前版本最长支持 {int(max_minutes)} 分钟/条（检测到 {float(dur)/60.0:.1f} 分钟），请先分割后再生成字幕。")
            
            temp_dir = tempfile.gettempdir()
            audio_wav_path = os.path.join(temp_dir, f"luscreen_asr_input_{uuid.uuid4().hex}.wav")
            srt_output_path = self.config.get('output_path') or \
                             os.path.splitext(video_path)[0] + ".srt"

            # 2. Extract Audio
            print(f"[SubtitleWorker] Extracting audio to {audio_wav_path}")
            self.progress.emit(10, "正在提取音频...")
            if self._is_cancelled: return

            # Audio extraction (CPU/IO bound) - safe
            try:
                AudioExtractor.extract_audio(audio_source_path, audio_wav_path, mic_path)
            except Exception as e:
                if audio_source_path != video_path and os.path.exists(video_path):
                    try:
                        print(f"[SubtitleWorker] Preview audio extract failed, retrying with original video. err={e}")
                        AudioExtractor.extract_audio(video_path, audio_wav_path, mic_path)
                    except Exception as e2:
                        raise RuntimeError(f"{e}\n---\nFallback extract failed: {e2}")
                else:
                    raise

            try:
                if not os.path.exists(audio_wav_path) or os.path.getsize(audio_wav_path) < 64:
                    raise RuntimeError("Audio extraction produced empty WAV.")
            except Exception as e:
                raise RuntimeError(f"Audio extraction verification failed: {e}")
            
            # 3. Initialize Engine
            # CRITICAL: Engine must be initialized INSIDE run() 
            # so that all its internal QObjects/Threads (if any) or CUDA contexts
            # are bound to this thread.
            print("[SubtitleWorker] Initializing Engine...")
            self.progress.emit(30, "正在加载模型...")
            
            engine_type = self.config.get('engine_type', 'whisperx')
            print(f"[SubtitleWorker] Engine Type: {engine_type}")

            model_dir = None
            pipeline = None
            api_key = self.config.get('api_key')
            base_url = self.config.get('base_url')

            if engine_type != "openai":
                print("[SubtitleWorker] Using local WhisperX engine")

            if self._is_cancelled: return

            # 4. Transcribe
            print("[SubtitleWorker] Starting transcription...")
            self.progress.emit(50, "正在识别语音...")
            if engine_type == "openai":
                exe_path = _resolve_current_executable()
                exe_base = os.path.basename(exe_path).lower()
                if exe_base.startswith("python"):
                    cmd = [exe_path, "-m", "src.subtitle_system.worker_process"]
                else:
                    cmd = [exe_path, "--subtitle-worker"]
                cmd.extend(["--engine", engine_type, "--audio", audio_wav_path, "--out", srt_output_path])
                if api_key:
                    cmd.extend(["--api_key", api_key])
                if base_url:
                    cmd.extend(["--base_url", base_url])
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                env = os.environ.copy()
                env["PYTHONPATH"] = project_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
                proc = subprocess.Popen(cmd, cwd=project_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", startupinfo=startupinfo)
                last_progress = 50
                if proc.stdout:
                    for line in proc.stdout:
                        if self._is_cancelled:
                            try:
                                proc.terminate()
                            except Exception:
                                pass
                            break
                        line = (line or "").strip()
                        if line.startswith("PROGRESS\t"):
                            parts = line.split("\t", 2)
                            if len(parts) == 3:
                                try:
                                    val = int(parts[1])
                                    msg = parts[2]
                                    last_progress = val
                                    self.progress.emit(val, msg)
                                except Exception:
                                    pass
                        else:
                            print(f"[SubtitleWorker][Subprocess] {line}")
                rc = proc.wait()
                proc = None
                if self._is_cancelled:
                    return
                if rc != 0 or (not os.path.exists(srt_output_path)):
                    raise RuntimeError(f"Subtitle subprocess failed (code {rc})")

                try:
                    _maybe_fix_srt_timing(srt_path=srt_output_path, audio_wav_path=audio_wav_path, media_path=audio_source_path)
                except Exception:
                    pass

                self.progress.emit(max(last_progress, 100), "完成")
                self.finished.emit(srt_output_path)
            else:
                def progress_cb(val, msg):
                    if not self._is_cancelled:
                        self.progress.emit(val, msg)
                requested_device = str(self.config.get("asr_device") or "cpu").strip().lower()
                device = requested_device
                downgrade_reason = ""
                if device == "cuda" and (not is_cuda_available()):
                    device = "cpu"
                    downgrade_reason = "cuda_unavailable"
                    try:
                        log_cuda_status(context="subtitle_worker_cuda_downgrade")
                    except Exception:
                        pass

                model_id = str(self.config.get("local_model_id") or "").strip()
                if not model_id:
                    model_id = get_default_whisperx_model_id()
                avail = {m.model_id: m for m in list_available_local_models(backend="whisperx")}
                chosen = avail.get(model_id)
                if chosen:
                    if device == "cpu" and not bool(getattr(chosen, "allow_cpu", True)):
                        chosen = None
                    if device == "cuda" and not bool(getattr(chosen, "allow_gpu", True)):
                        chosen = None
                if chosen is None:
                    fallback_id = get_default_whisperx_model_id()
                    chosen = avail.get(fallback_id) or (next(iter(avail.values()), None))
                    if chosen:
                        model_id = chosen.model_id
                model_ref = (chosen.model_ref if chosen else model_id).strip()
                if not model_ref:
                    model_ref = "large-v3"

                compute_type = str(self.config.get("compute_type") or ("float16" if device == "cuda" else "int8")).strip()
                batch_size = int(self.config.get("batch_size") or (16 if device == "cuda" else 4))
                beam_size = int(self.config.get("beam_size") or (5 if device == "cuda" else 3))
                language = self.config.get("language")
                language = str(language).strip() if language else None

                _append_log(
                    "subtitle_asr_device_selected.log",
                    (
                        f"engine=whisperx\n"
                        f"requested_device={requested_device}\n"
                        f"final_device={device}\n"
                        f"downgrade_reason={downgrade_reason}\n"
                        f"compute_type={compute_type}\n"
                        f"batch_size={batch_size}\n"
                        f"beam_size={beam_size}\n"
                        "----\n"
                    ),
                )

                _SUBTITLE_SERVICE.transcribe_to_srt(
                    engine="whisperx",
                    audio_path=audio_wav_path,
                    srt_output_path=srt_output_path,
                    model_dir=None,
                    pipeline=None,
                    extra={
                        "model_id": model_id,
                        "model_ref": model_ref,
                        "device": device,
                        "compute_type": compute_type,
                        "batch_size": batch_size,
                        "beam_size": beam_size,
                        "language": language,
                    },
                    progress_cb=progress_cb,
                )
                if self._is_cancelled:
                    return

                try:
                    _maybe_fix_srt_timing(srt_path=srt_output_path, audio_wav_path=audio_wav_path, media_path=audio_source_path)
                except Exception:
                    pass
                self.finished.emit(srt_output_path)
            
        except Exception as e:
            print("[SubtitleWorker] Exception occurred!")
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))
        finally:
            if proc is not None:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass
            if audio_wav_path and os.path.exists(audio_wav_path):
                try:
                    os.remove(audio_wav_path)
                except:
                    pass
            # Ensure engine is cleaned up within the thread
            if 'engine' in locals():
                try:
                    del engine
                except:
                    pass
            print("[SubtitleWorker] Thread finished cleanup.")
            
    def cancel(self):
        self._is_cancelled = True

class SubtitleManager(QObject):
    def __init__(self):
        super().__init__()
        self.worker = None

    def start_generation(self, config):
        """
        Start subtitle generation.
        Config dict:
            video_path: str
            mic_path: str (optional)
            engine_type: 'whisperx' | 'openai'
            output_path: str (optional)
            # Engine specific
            api_key: str (for openai)
            base_url: str (optional)
        """
        if self.worker and self.worker.isRunning():
            return False
            
        self.worker = SubtitleWorker(config)
        return self.worker
