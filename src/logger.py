import atexit
import logging
import logging.handlers
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import Any

from src.version import APP_VERSION


_PROCESS_START_TS = time.time()
_FAULT_HANDLER_STREAM = None
_ATEXIT_REGISTERED = False
_ROTATE_MAX_BYTES = 5 * 1024 * 1024
_ROTATE_BACKUP_COUNT = 5


class StreamToLogger:
    """
    File-like stream object that redirects writes to a logger instance.
    """

    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self.linebuf = ""

    def write(self, buf):
        if not buf:
            return 0
        for line in str(buf).rstrip().splitlines():
            text = line.rstrip()
            if text:
                self.logger.log(self.level, text)
        return len(buf)

    def flush(self):
        for handler in getattr(self.logger, "handlers", []) or []:
            try:
                handler.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def _resolve_runtime_base_dir(base_path=None):
    if base_path:
        return os.path.abspath(base_path)
    try:
        from src.utils import get_runtime_data_dir

        return os.path.abspath(get_runtime_data_dir())
    except Exception:
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_log_dir(base_path=None):
    log_dir = os.path.join(_resolve_runtime_base_dir(base_path), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _safe_text(value: Any, limit: int = 800) -> str:
    try:
        text = repr(value)
    except Exception:
        text = f"<unrepresentable {type(value).__name__}>"
    text = text.replace("\r", " ").replace("\n", " ")
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def _get_daily_log_path(base_path=None):
    timestamp = datetime.now().strftime("%Y%m%d")
    return os.path.join(get_log_dir(base_path), f"luscreen_{timestamp}.log")


def _get_crash_log_path(base_path=None):
    return os.path.join(get_log_dir(base_path), "crash.log")


def _get_faulthandler_log_path(base_path=None):
    timestamp = datetime.now().strftime("%Y%m%d")
    return os.path.join(get_log_dir(base_path), f"faulthandler_{timestamp}.log")


def _write_session_banner(log_file):
    with open(log_file, "a", encoding="utf-8", errors="replace") as f:
        f.write(f"\n{'-' * 80}\n")
        f.write(f"Session Started: {datetime.now()} | Version: {APP_VERSION}\n")
        f.write(f"PID: {os.getpid()} | Executable: {sys.executable}\n")
        f.write(f"CWD: {os.getcwd()}\n")
        f.write(f"ARGV: {sys.argv!r}\n")
        f.write(f"Frozen: {getattr(sys, 'frozen', False)}\n")
        f.write(f"{'-' * 80}\n")


def _append_crash_report(title, exc_type=None, exc_value=None, exc_traceback=None, details=None, base_path=None):
    crash_file = _get_crash_log_path(base_path)
    with open(crash_file, "a", encoding="utf-8", errors="replace") as f:
        f.write(f"\n{'=' * 80}\n")
        f.write(f"{title}\n")
        f.write(f"Crash Time: {datetime.now()}\n")
        f.write(f"Version: {APP_VERSION}\n")
        f.write(f"PID: {os.getpid()}\n")
        f.write(f"Thread: {threading.current_thread().name}\n")
        f.write(f"Executable: {sys.executable}\n")
        f.write(f"CWD: {os.getcwd()}\n")
        f.write(f"ARGV: {sys.argv!r}\n")
        if details:
            for key, value in details.items():
                f.write(f"{key}: {value}\n")
        f.write("-" * 80 + "\n")
        if exc_type is not None:
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
        else:
            f.write("No traceback available.\n")


def _log_process_exit():
    try:
        logging.getLogger("Global").info(
            "Process exiting. uptime_sec=%.2f pid=%s",
            time.time() - _PROCESS_START_TS,
            os.getpid(),
        )
    except Exception:
        pass


def _ensure_exit_logging():
    global _ATEXIT_REGISTERED
    if _ATEXIT_REGISTERED:
        return
    atexit.register(_log_process_exit)
    _ATEXIT_REGISTERED = True


def setup_global_logger(redirect_stdout=True, base_path=None):
    log_file = _get_daily_log_path(base_path)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=_ROTATE_MAX_BYTES,
        backupCount=_ROTATE_BACKUP_COUNT,
        encoding="utf-8",
    )
    handlers = [file_handler]

    if not redirect_stdout:
        handlers.append(logging.StreamHandler(sys.__stdout__))

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.captureWarnings(True)
    _write_session_banner(log_file)
    _ensure_exit_logging()

    logger = logging.getLogger("Global")
    logger.info("Global logger initialized. Version: %s", APP_VERSION)
    logger.info("Log file: %s", log_file)
    logger.info("Runtime log directory: %s", get_log_dir(base_path))

    if redirect_stdout:
        sys.stdout = StreamToLogger(logging.getLogger("STDOUT"), logging.INFO)
        sys.stderr = StreamToLogger(logging.getLogger("STDERR"), logging.ERROR)
        logger.info("Stdout/Stderr redirected to log file.")

    return logger


def install_faulthandler(base_path=None):
    global _FAULT_HANDLER_STREAM
    try:
        import faulthandler

        fault_path = _get_faulthandler_log_path(base_path)
        if _FAULT_HANDLER_STREAM and not _FAULT_HANDLER_STREAM.closed:
            try:
                faulthandler.disable()
            except Exception:
                pass
            try:
                _FAULT_HANDLER_STREAM.close()
            except Exception:
                pass
        _FAULT_HANDLER_STREAM = open(fault_path, "a", encoding="utf-8", errors="replace")
        _FAULT_HANDLER_STREAM.write(
            f"\n{'=' * 80}\nFaulthandler Enabled: {datetime.now()} | pid={os.getpid()}\n"
        )
        _FAULT_HANDLER_STREAM.flush()
        faulthandler.enable(file=_FAULT_HANDLER_STREAM, all_threads=True)
        return fault_path
    except Exception:
        logging.getLogger("Global").exception("Failed to enable faulthandler.")
        return None


def handle_exception(exc_type, exc_value, exc_traceback):
    """
    全局异常捕获钩子
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger = logging.getLogger("Global")
    logger.critical(
        "Uncaught exception in main thread",
        exc_info=(exc_type, exc_value, exc_traceback),
    )
    _append_crash_report(
        "Unhandled exception (sys.excepthook)",
        exc_type=exc_type,
        exc_value=exc_value,
        exc_traceback=exc_traceback,
    )


def handle_thread_exception(args):
    exc_type = getattr(args, "exc_type", None)
    if exc_type is SystemExit:
        return
    exc_value = getattr(args, "exc_value", None)
    exc_traceback = getattr(args, "exc_traceback", None)
    thread_obj = getattr(args, "thread", None)
    thread_name = getattr(thread_obj, "name", "<unknown>")
    logging.getLogger("Global").critical(
        "Uncaught thread exception. thread=%s",
        thread_name,
        exc_info=(exc_type, exc_value, exc_traceback),
    )
    _append_crash_report(
        "Unhandled thread exception (threading.excepthook)",
        exc_type=exc_type,
        exc_value=exc_value,
        exc_traceback=exc_traceback,
        details={"thread_name": thread_name},
    )


def handle_unraisable_exception(unraisable):
    exc_type = getattr(unraisable, "exc_type", None)
    exc_value = getattr(unraisable, "exc_value", None)
    exc_traceback = getattr(unraisable, "exc_traceback", None)
    err_msg = getattr(unraisable, "err_msg", None)
    obj = getattr(unraisable, "object", None)
    logging.getLogger("Global").error(
        "Unraisable exception captured. err_msg=%s object=%s",
        err_msg,
        _safe_text(obj),
        exc_info=(exc_type, exc_value, exc_traceback),
    )
    _append_crash_report(
        "Unraisable exception (sys.unraisablehook)",
        exc_type=exc_type,
        exc_value=exc_value,
        exc_traceback=exc_traceback,
        details={
            "err_msg": err_msg or "",
            "object": _safe_text(obj),
        },
    )


def install_global_exception_hooks():
    sys.excepthook = handle_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = handle_thread_exception
    if hasattr(sys, "unraisablehook"):
        sys.unraisablehook = handle_unraisable_exception


install_global_exception_hooks()
