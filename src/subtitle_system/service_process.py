import json
import os
import sys
import traceback

_DLL_DIR_HANDLES = []
_FAULT_LOG_FH = None


def _sanitize_field(value: str) -> str:
    s = "" if value is None else str(value)
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    while "  " in s:
        s = s.replace("  ", " ")
    return s.strip()


def _emit_progress(value: int, message: str):
    value = max(0, min(100, int(value)))
    sys.stdout.write(f"PROGRESS\t{value}\t{_sanitize_field(message)}\n")
    sys.stdout.flush()


def _emit_result_ok(out_path: str):
    sys.stdout.write(f"RESULT\tOK\t{_sanitize_field(out_path)}\n")
    sys.stdout.flush()


def _emit_result_err(message: str):
    sys.stdout.write(f"RESULT\tERR\t{_sanitize_field(message)}\n")
    sys.stdout.flush()


def main():
    global _FAULT_LOG_FH
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("LUSCREEN_ASR_DEVICE", "cpu")
    os.environ.setdefault("TORCH_COMPILE_DISABLE", "1")
    os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    exe_base = os.path.basename(sys.executable or "").lower()
    is_python_exe = exe_base.startswith("python")
    forced_root = os.environ.get("LUSCREEN_FORCE_PROJECT_ROOT")
    if is_python_exe:
        forced_root = None
    project_root = forced_root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    sys.stdout.write(f"[SubtitleServiceProcess] initial_project_root={project_root}\n")
    sys.stdout.flush()

    try:
        try:
            from src.utils import get_runtime_data_dir
            logs_dir = os.path.join(get_runtime_data_dir(), "logs")
        except Exception:
            logs_dir = os.path.join(project_root, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        fault_path = os.path.join(logs_dir, "subtitle_service_fault.log")
        _FAULT_LOG_FH = open(fault_path, "a", encoding="utf-8", errors="replace")
        _FAULT_LOG_FH.write(f"\n==== start pid={os.getpid()} exe={sys.executable} ====\n")
        _FAULT_LOG_FH.flush()
        import faulthandler
        faulthandler.enable(file=_FAULT_LOG_FH, all_threads=True)
    except Exception:
        _FAULT_LOG_FH = None

    try:
        from src.utils import get_long_windows_path
    except Exception:
        get_long_windows_path = None

    if get_long_windows_path:
        try:
            long_root = get_long_windows_path(project_root)
            if long_root and long_root != project_root:
                project_root = long_root
                try:
                    sys.path = [project_root if p == sys.path[0] else p for p in sys.path]
                except Exception:
                    if project_root not in sys.path:
                        sys.path.insert(0, project_root)
        except Exception:
            pass
    sys.stdout.write(f"[SubtitleServiceProcess] resolved_project_root={project_root}\n")
    sys.stdout.flush()
    sys.stdout.write("[SubtitleServiceProcess] ready\n")
    sys.stdout.flush()

    torch_lib = None
    try:
        if os.name == "nt":
            exe_base = os.path.basename(sys.executable or "").lower()
            is_python_exe = exe_base.startswith("python")
            local_torch_pkg = os.path.join(project_root, "torch", "__init__.py")
            if not is_python_exe or os.path.exists(local_torch_pkg):
                torch_lib = os.path.join(project_root, "torch", "lib")
    except Exception:
        torch_lib = None

    try:
        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            _orig_add_dll_directory = os.add_dll_directory

            try:
                from src.utils import get_short_windows_path
            except Exception:
                get_short_windows_path = None

            def _norm_dir(p: str | None) -> str:
                s = (p or "").strip()
                if s.lower().startswith("\\\\?\\"):
                    s = s[4:]
                return s.replace("/", "\\").rstrip("\\").lower()

            torch_lib_norm = _norm_dir(torch_lib)

            class _NoopDLLDir:
                def close(self):
                    return None

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            def _prefixed(p: str) -> str:
                if not p:
                    return p
                if p.startswith("\\\\?\\") or p.startswith("\\\\.\\"):
                    return p
                return "\\\\?\\" + p

            def _wrap_add_dll_directory(p: str):
                debug_stack = str(os.environ.get("LUSCREEN_DEBUG_DLL_DIR_STACK") or "").strip() == "1"
                device_env = (os.environ.get("LUSCREEN_ASR_DEVICE") or "cpu").strip().lower()
                allow_ignore_any_206 = device_env in ("", "cpu")
                if debug_stack:
                    try:
                        sys.stdout.write(f"[SubtitleServiceProcess] add_dll_directory_call path={p!r}\n")
                        stack = "".join(traceback.format_stack(limit=40))
                        sys.stdout.write("[SubtitleServiceProcess] add_dll_directory_stack_begin\n")
                        sys.stdout.write(stack)
                        sys.stdout.write("[SubtitleServiceProcess] add_dll_directory_stack_end\n")
                        sys.stdout.flush()
                    except Exception:
                        pass
                try:
                    return _orig_add_dll_directory(p)
                except OSError as e:
                    if getattr(e, "winerror", None) != 206:
                        raise
                    if debug_stack:
                        try:
                            sys.stdout.write(f"[SubtitleServiceProcess] add_dll_directory_206 path={p!r}\n")
                            sys.stdout.flush()
                        except Exception:
                            pass
                    candidates = []
                    try:
                        p0 = os.path.abspath(p) if p else p
                    except Exception:
                        p0 = p

                    p_strip = p0
                    try:
                        if isinstance(p_strip, str) and p_strip.lower().startswith("\\\\?\\"):
                            p_strip = p_strip[4:]
                    except Exception:
                        p_strip = p0

                    p_long = p_strip
                    try:
                        p_long = get_long_windows_path(p_strip) if get_long_windows_path else p_strip
                    except Exception:
                        p_long = p_strip

                    p_short = p_strip
                    try:
                        if get_short_windows_path:
                            p_short = get_short_windows_path(p_strip)
                    except Exception:
                        p_short = p_strip

                    for c in [p, p0, p_strip, p_long, p_short, _prefixed(p_long), _prefixed(p_short), _prefixed(p_strip)]:
                        if not c:
                            continue
                        if c not in candidates:
                            candidates.append(c)

                    for c in candidates:
                        try:
                            return _orig_add_dll_directory(c)
                        except Exception:
                            continue

                    if torch_lib_norm and _norm_dir(p0) == torch_lib_norm:
                        if debug_stack:
                            try:
                                sys.stdout.write(f"[SubtitleServiceProcess] add_dll_directory_ignored_206 path={p0!r}\n")
                                sys.stdout.flush()
                            except Exception:
                                pass
                        sys.stdout.write(f"[SubtitleServiceProcess] add_dll_directory=IGNORED_206 path={p0!r}\n")
                        sys.stdout.flush()
                        return _NoopDLLDir()

                    p0_norm = _norm_dir(p0)
                    is_nvtools = "nvidia corporation\\nvtoolsext\\bin" in p0_norm
                    if allow_ignore_any_206 or is_nvtools:
                        sys.stdout.write(f"[SubtitleServiceProcess] add_dll_directory=IGNORED_206 path={p0!r}\n")
                        sys.stdout.flush()
                        return _NoopDLLDir()

                    raise

            os.add_dll_directory = _wrap_add_dll_directory
            sys.stdout.write("[SubtitleServiceProcess] add_dll_directory_wrapper=ON\n")
            sys.stdout.flush()
    except Exception:
        pass

    if torch_lib:
        sys.stdout.write(f"[SubtitleServiceProcess] torch_lib={torch_lib}\n")
        sys.stdout.flush()

    try:
        from src.utils import safe_add_dll_directory
    except Exception:
        safe_add_dll_directory = None

    try:
        if torch_lib and os.path.exists(torch_lib):
            os.environ["PATH"] = torch_lib + os.pathsep + (os.environ.get("PATH") or "")
            if safe_add_dll_directory:
                try:
                    h = safe_add_dll_directory(torch_lib)
                    if h:
                        _DLL_DIR_HANDLES.append(h)
                    sys.stdout.write("[SubtitleServiceProcess] add_dll_directory=OK\n")
                    sys.stdout.flush()
                except Exception as e:
                    sys.stdout.write(f"[SubtitleServiceProcess] add_dll_directory=ERR {type(e).__name__}: {e}\n")
                    sys.stdout.flush()
    except Exception:
        pass

    try:
        from src.subtitle_system.runtime_installer import ensure_subtitle_runtime_on_path
        ensure_subtitle_runtime_on_path()
    except Exception:
        pass

    if str(os.environ.get("LUSCREEN_SUBTITLE_SERVICE_DIAG") or "").strip() == "1":
        return 0

    from src.subtitle_system.formatter import SubtitleFormatter

    engine = None
    engine_name = None
    current_whisperx_model_ref = None
    current_whisperx_device = None
    current_whisperx_compute_type = None

    for raw in sys.stdin:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except Exception:
            _emit_result_err("Invalid request.")
            continue

        cmd = req.get("cmd")
        if cmd == "shutdown":
            return 0

        if cmd != "transcribe":
            _emit_result_err("Unknown command.")
            continue

        req_engine = (req.get("engine") or req.get("backend") or "whisperx")
        req_engine = str(req_engine).strip().lower()
        audio_path = req.get("audio")
        out_path = req.get("out")

        if not audio_path or not out_path:
            _emit_result_err("Missing audio/out.")
            continue

        try:
            if req_engine != "whisperx":
                req_engine = "whisperx"

            model_ref = str(req.get("model_ref") or req.get("model") or "").strip()
            if not model_ref:
                _emit_result_err("Missing model_ref for whisperx.")
                continue

            device = str(req.get("device") or os.environ.get("LUSCREEN_ASR_DEVICE") or "cpu").strip().lower()
            if device not in ("cpu", "cuda"):
                device = "cpu"
            os.environ["LUSCREEN_ASR_DEVICE"] = device

            compute_type = str(req.get("compute_type") or ("float16" if device == "cuda" else "int8")).strip()
            batch_size = int(req.get("batch_size") or (16 if device == "cuda" else 4))
            beam_size = int(req.get("beam_size") or (5 if device == "cuda" else 3))
            language = req.get("language")
            language = str(language).strip() if language else None

            if (
                engine is None
                or engine_name != "whisperx"
                or current_whisperx_model_ref != model_ref
                or current_whisperx_device != device
                or current_whisperx_compute_type != compute_type
            ):
                _emit_progress(30, "正在加载模型...")
                from src.subtitle_system.engines.whisperx_engine import WhisperXEngine
                engine = WhisperXEngine()
                engine_name = "whisperx"
                current_whisperx_model_ref = model_ref
                current_whisperx_device = device
                current_whisperx_compute_type = compute_type

            _emit_progress(60, "正在识别语音...")
            segments, words = engine.transcribe_with_words(
                audio_path=audio_path,
                model_ref=model_ref,
                device=device,
                compute_type=compute_type,
                batch_size=batch_size,
                beam_size=beam_size,
                language=language,
            )

            _emit_progress(90, "正在生成字幕文件...")
            if words:
                segs_by_words = SubtitleFormatter.segments_from_words(words)
                if segs_by_words:
                    segments = segs_by_words
            srt_content = SubtitleFormatter.to_srt(segments, wrap=not bool(words))
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(srt_content)

            try:
                if words:
                    from src.subtitle_system.engines.whisperx_engine import dump_words_json
                    dump_words_json(
                        out_path=str(out_path) + ".words.json",
                        words=words,
                        extra={
                            "engine": "whisperx",
                            "device": device,
                            "compute_type": compute_type,
                            "model_ref": model_ref,
                        },
                    )
            except Exception:
                pass

            _emit_progress(100, "完成")
            _emit_result_ok(out_path)
        except Exception as e:
            try:
                if _FAULT_LOG_FH is not None:
                    _FAULT_LOG_FH.write("---- exception ----\n")
                    _FAULT_LOG_FH.write(traceback.format_exc())
                    _FAULT_LOG_FH.write(f"\n[diag] engine={req_engine!r} model_ref={str(req.get('model_ref') or req.get('model') or '').strip()!r}\n")
                    _FAULT_LOG_FH.write(f"[diag] sys.executable={sys.executable!r}\n")
                    _FAULT_LOG_FH.write(f"[diag] sys.version={sys.version}\n")
                    _FAULT_LOG_FH.write(f"[diag] cwd={os.getcwd()!r}\n")
                    _FAULT_LOG_FH.write(f"[diag] LUSCREEN_ASR_DEVICE={os.environ.get('LUSCREEN_ASR_DEVICE')!r}\n")
                    try:
                        _FAULT_LOG_FH.write(f"[diag] has_torch_dir={os.path.exists(os.path.join(project_root, 'torch'))}\n")
                        _FAULT_LOG_FH.write(f"[diag] has_torch_lib={os.path.exists(os.path.join(project_root, 'torch', 'lib'))}\n")
                    except Exception:
                        pass
                    _FAULT_LOG_FH.write("\n")
                    _FAULT_LOG_FH.flush()
            except Exception:
                pass
            msg = f"{type(e).__name__}: {e}"
            if "cannot import name 'nn' from 'torch'" in msg:
                msg = (msg + " | torch 可能不完整或被同名模块覆盖，请检查打包产物 torch 目录是否完整（torch.nn、torch._C、torch/lib DLL）。").strip()
            if "was actively excluded from Nuitka compilation" in msg and "torch._functorch" in msg:
                msg = (msg + " | 当前打包参数排除了 torch._functorch（--nofollow-import-to=torch._functorch），Torch 导入时会用到它；请取消排除并显式 include（--include-package=torch._functorch）。").strip()
            if "无法导入 whisperx" in msg or "No module named 'whisperx'" in msg:
                msg = (msg + " | 未检测到本地字幕组件（whisperx/torch）。打包版请下载安装“字幕组件包/完整版本”；开发环境请执行 pip install -r requirements.txt").strip()
            _emit_result_err(msg + " | 请查看 logs/subtitle_service_fault.log")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
