import threading
import time
import cv2
import numpy as np
import mss
import os
import subprocess
import imageio_ffmpeg
import sys
import queue
import json
import socket
import shutil
import wave
from datetime import datetime
from src.audio_recorder import AudioRecorder
# from src.system_audio_recorder import SystemAudioRecorder # 延迟导入以避免COM冲突
import ctypes

import logging
from src.video_processor import VideoProcessor

# Use global logger if available, otherwise fallback
logger = logging.getLogger('ScreenRecorder')
_FFPROBE_PATH_CACHE = None
_FFPROBE_PATH_RESOLVED = False

def get_ffmpeg_path():
    """
    获取 FFmpeg 可执行文件路径。
    优先查找当前程序目录下的 ffmpeg.exe (用于打包后的环境)，
    如果未找到，则使用 imageio_ffmpeg 提供的内置版本。
    """
    # 1. 检查应用程序根目录 (打包后 ffmpeg.exe 通常放在这里)
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        # 开发环境：src/recorder.py -> src -> root
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
    local_ffmpeg = os.path.join(base_path, 'ffmpeg.exe')
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg
        
    # 2. 回退到 imageio_ffmpeg (开发环境通常用这个)
    return imageio_ffmpeg.get_ffmpeg_exe()


def get_ffprobe_path():
    """
    获取 FFprobe 可执行文件路径。
    仅返回已通过 `-version` 校验、确认真的是 ffprobe 的绝对路径；
    若当前环境没有可用 ffprobe，则返回 None。
    """
    global _FFPROBE_PATH_CACHE, _FFPROBE_PATH_RESOLVED
    if _FFPROBE_PATH_RESOLVED:
        return _FFPROBE_PATH_CACHE

    candidates = []

    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    local_ffprobe = os.path.join(base_path, 'ffprobe.exe')
    if os.path.exists(local_ffprobe):
        candidates.append(local_ffprobe)

    try:
        ffmpeg_path = get_ffmpeg_path()
        ffmpeg_dir = os.path.dirname(ffmpeg_path)
        ffmpeg_name = os.path.basename(ffmpeg_path)
        sibling_candidates = [
            os.path.join(ffmpeg_dir, 'ffprobe.exe'),
        ]
        if 'ffmpeg' in ffmpeg_name:
            sibling_candidates.append(os.path.join(ffmpeg_dir, ffmpeg_name.replace('ffmpeg', 'ffprobe')))
        if 'FFMPEG' in ffmpeg_name:
            sibling_candidates.append(os.path.join(ffmpeg_dir, ffmpeg_name.replace('FFMPEG', 'FFPROBE')))
        for candidate in sibling_candidates:
            if os.path.exists(candidate):
                candidates.append(candidate)
    except Exception:
        pass

    path_ffprobe = shutil.which('ffprobe')
    if path_ffprobe:
        candidates.append(path_ffprobe)

    seen = set()
    startupinfo = None
    if os.name == "nt":
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        except Exception:
            startupinfo = None

    for candidate in candidates:
        if not candidate:
            continue
        candidate_norm = os.path.normcase(os.path.abspath(candidate))
        if candidate_norm in seen:
            continue
        seen.add(candidate_norm)
        try:
            result = subprocess.run(
                [candidate, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                startupinfo=startupinfo,
            )
            output = "\n".join([result.stdout or "", result.stderr or ""]).strip().lower()
            if result.returncode == 0 and "ffprobe version" in output:
                _FFPROBE_PATH_CACHE = os.path.abspath(candidate)
                _FFPROBE_PATH_RESOLVED = True
                return _FFPROBE_PATH_CACHE
        except Exception:
            continue

    _FFPROBE_PATH_CACHE = None
    _FFPROBE_PATH_RESOLVED = True
    return None

from src.logger import get_log_dir
from src.utils import open_folder_and_select_file

def _get_preview_temp_path(preview_path: str) -> str:
    base, ext = os.path.splitext(preview_path)
    if not ext:
        return preview_path + ".tmp"
    return f"{base}.tmp{ext}"

def _create_preview_with_audio(*, video_path: str, mic_wav: str | None, sys_wav: str | None, preview_path: str, logger_obj=None) -> bool:
    log = logger_obj or logger
    marker_path = preview_path + ".generating"
    temp_preview = _get_preview_temp_path(preview_path)
    
    try:
        ffmpeg_exe = get_ffmpeg_path()
    except Exception:
        ffmpeg_exe = None
    if not ffmpeg_exe or not os.path.exists(ffmpeg_exe):
        # Clean up marker if we fail early
        if os.path.exists(marker_path):
            try: os.remove(marker_path)
            except: pass
        return False

    v = (video_path or "").strip()
    # out = (preview_path or "").strip() # Use temp_preview instead
    out = temp_preview
    
    if not v or not preview_path or (not os.path.exists(v)):
        if os.path.exists(marker_path):
            try: os.remove(marker_path)
            except: pass
        return False
    try:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    except Exception:
        pass

    mic_ok = bool(mic_wav and os.path.exists(mic_wav) and os.path.getsize(mic_wav) > 0)
    sys_ok = bool(sys_wav and os.path.exists(sys_wav) and os.path.getsize(sys_wav) > 0)
    if not (mic_ok or sys_ok):
        if os.path.exists(marker_path):
            try: os.remove(marker_path)
            except: pass
        return False

    cmd = [ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error", "-i", v]
    filter_complex = None
    if mic_ok and sys_ok:
        cmd.extend(["-i", mic_wav, "-i", sys_wav])
        filter_complex = "[1:a]aresample=48000,volume=5.0[mic];[2:a]aresample=48000,volume=1.5[sys];[mic][sys]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,volume=1.5[aout]"
        cmd.extend(["-filter_complex", filter_complex, "-map", "0:v:0", "-map", "[aout]"])
    elif mic_ok:
        cmd.extend(["-i", mic_wav])
        filter_complex = "[1:a]aresample=48000,volume=5.0[aout]"
        cmd.extend(["-filter_complex", filter_complex, "-map", "0:v:0", "-map", "[aout]"])
    else:
        cmd.extend(["-i", sys_wav])
        filter_complex = "[1:a]aresample=48000,volume=1.5[aout]"
        cmd.extend(["-filter_complex", filter_complex, "-map", "0:v:0", "-map", "[aout]"])

    cmd.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", "-f", "mp4", out])

    startupinfo = None
    if os.name == "nt":
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        except Exception:
            startupinfo = None

    try:
        t0 = time.time()
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, check=False)
        dt = time.time() - t0
        
        if res.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 10 * 1024:
            # Rename temp to final
            try:
                if os.path.exists(preview_path):
                    os.remove(preview_path)
                os.rename(out, preview_path)
                log.info(f"Preview mux OK: {preview_path} ({os.path.getsize(preview_path)} bytes) in {dt:.2f}s")
                return True
            except Exception as e:
                log.error(f"Failed to rename preview temp file: {e}")
                return False
        
        try:
            err = (res.stderr or b"").decode("utf-8", errors="ignore")
            log.error(f"Preview mux failed (code {res.returncode}): {err}")
        except Exception:
            pass
        return False
    except Exception as e:
        try:
            log.error(f"Preview mux exception: {e}")
        except Exception:
            pass
        return False
    finally:
        # Cleanup marker and temp
        if os.path.exists(marker_path):
            try: os.remove(marker_path)
            except: pass
        if os.path.exists(temp_preview):
            try: os.remove(temp_preview)
            except: pass

from ctypes import windll, Structure, c_long, byref

class POINT(Structure):
    _fields_ = [("x", c_long), ("y", c_long)]

def get_mouse_pos():
    pt = POINT()
    windll.user32.GetCursorPos(byref(pt))
    return pt.x, pt.y

class ScreenRecorder(threading.Thread):
    def __init__(self, region=None, output_filename=None, record_audio=True, audio_device_index=None, audio_device_name=None, record_system_audio=False, output_dir=None, video_quality="1080p", use_gpu=False, camera_only=False, camera_index=0, audio_only=False, frame_provider=None):
        super().__init__()
        # Use Global Logger (from src.logger setup) if available, otherwise setup fallback
        if logging.getLogger("Global").handlers:
             self.logger = logging.getLogger("Global") # Reuse global logger config
        else:
             # Fallback if global logger not set (e.g. running recorder isolated)
             self.logger = logging.getLogger('ScreenRecorder')
             if not self.logger.handlers:
                 handler = logging.StreamHandler(sys.stdout)
                 formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                 handler.setFormatter(formatter)
                 self.logger.addHandler(handler)
                 self.logger.setLevel(logging.INFO)

        self.cursor_img = self.create_cursor_image()
        self.region = region 
        self.frame_provider = frame_provider
        self.is_recording = False
        self.is_paused = False
        self.pause_event = threading.Event()
        self.pause_event.set() # Set means NOT paused (running)
        self.stop_event = threading.Event()
        self.record_audio = record_audio
        self.audio_device_index = audio_device_index
        self.audio_device_name = audio_device_name
        self.record_system_audio = record_system_audio
        self.video_quality = video_quality
        self.use_gpu = use_gpu
        self.camera_only = camera_only
        self.camera_index = camera_index
        self.audio_only = audio_only
        
        # 实时音视频混流端口
        self.mic_port = None
        self.sys_port = None
        self.mic_server = None
        self.sys_server = None
        
        # 确保输出目录存在
        if output_dir:
            self.output_dir = output_dir
        else:
            self.output_dir = os.path.join(os.getcwd(), "recordings")

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # 文件名生成
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.base_name = f"LuScreen_{timestamp}"
        if output_filename is None:
            ext = ".mp3" if self.audio_only else ".mp4"
            self.final_output = os.path.join(self.output_dir, f"{self.base_name}{ext}")
        else:
            self.final_output = output_filename
            self.base_name = os.path.splitext(os.path.basename(self.final_output))[0]
            
        # 临时文件 (使用统一的前缀以确保编辑器能自动关联音轨)
        self.temp_video = os.path.join(self.output_dir, f"temp_{self.base_name}.mp4")
        self.temp_audio_mic = os.path.join(self.output_dir, f"{self.base_name}_mic.wav")
        self.temp_audio_sys = os.path.join(self.output_dir, f"{self.base_name}_sys.wav")
        
        # 屏幕捕获设置 (在run中初始化mss以确保线程安全)
        self.sct = None 
        
        # 视频编码设置
        self.out = None
        
        # 解析画质和帧率
        # 兼容旧配置
        if self.video_quality == "1080p": self.video_quality = "1080p_30"
        elif self.video_quality == "2k": self.video_quality = "2k_30"
        elif self.video_quality == "4k": self.video_quality = "4k_60"
        
        if "60" in self.video_quality:
            self.fps = 60.0
        else:
            self.fps = 30.0
        self._perf_window_size = max(30, int(self.fps))
            
        # 音频录制器
        self.mic_recorder = None
        self.sys_recorder = None
        self.last_pause_start = 0
        self.ffmpeg_process = None
        self.write_thread = None
        self.mouse_data = []
        self._last_queue_full_log_at = 0.0
        self._last_loop_error_log_at = 0.0
        self._last_pipe_broken_log_at = 0.0
        
        # Camera recording robustness
        self.last_valid_camera_frame = None
        self.camera_frame_none_count = 0
        self.camera_frame_total_count = 0
        
        # 阶段 0 性能埋点
        self._perf_file = None
        self._perf_path = None
        self._perf_mode = "unknown"
        self._perf_session_started = None
        self._perf_sample_index = 0
        self._perf_window = None
        self._perf_total = None
        self._perf_ffmpeg_startup_ms = 0.0
        self._perf_write_join_ms = 0.0
        self._perf_stop_audio_ms = 0.0
        self._perf_stop_video_ms = 0.0
        
        # self.logger = logger # Removed, using self.logger initialized in __init__

    def create_cursor_image(self):
        # 尝试加载自定义光标
        cursor_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'cursor.png')
        if getattr(sys, 'frozen', False):
             cursor_path = os.path.join(os.path.dirname(sys.executable), 'assets', 'cursor.png')
             
        if os.path.exists(cursor_path):
            try:
                # 使用 cv2.imread 读取带 Alpha 通道的 PNG
                cursor = cv2.imread(cursor_path, cv2.IMREAD_UNCHANGED)
                if cursor is not None:
                    # 确保是 4 通道
                    if cursor.shape[2] == 3:
                        cursor = cv2.cvtColor(cursor, cv2.COLOR_BGR2BGRA)
                    
                    # 调整大小到合理尺寸 (例如 32x32)，如果太大
                    h, w = cursor.shape[:2]
                    if w > 64 or h > 64:
                        cursor = cv2.resize(cursor, (32, 32), interpolation=cv2.INTER_AREA)
                        
                    return cursor
            except Exception as e:
                print(f"Failed to load cursor.png: {e}")

        w, h = 16, 24
        cursor = np.zeros((h, w, 4), dtype=np.uint8)
        pts = np.array([[0, 0], [0, 16], [4, 13], [7, 20], [9, 19], [6, 12], [11, 12]], np.int32)
        pts = pts.reshape((-1, 1, 2))
        cv2.fillPoly(cursor, [pts], (0, 0, 0, 255))
        pts_inner = np.array([[1, 2], [1, 14], [4, 11], [6, 17], [7, 16], [5, 11], [9, 11]], np.int32)
        cv2.fillPoly(cursor, [pts_inner], (255, 255, 255, 255))
        return cursor

    def _make_perf_bucket(self):
        return {
            "samples": 0,
            "capture_ms_total": 0.0,
            "capture_ms_max": 0.0,
            "cursor_ms_total": 0.0,
            "cursor_ms_max": 0.0,
            "contiguous_ms_total": 0.0,
            "contiguous_ms_max": 0.0,
            "queue_wait_ms_total": 0.0,
            "queue_wait_ms_max": 0.0,
            "loop_ms_total": 0.0,
            "loop_ms_max": 0.0,
            "sleep_ms_total": 0.0,
            "sleep_ms_max": 0.0,
            "missed_frames_total": 0,
            "queue_full_events": 0,
            "camera_none_events": 0,
            "frame_size_mismatches": 0,
            "last_queue_size": -1,
        }

    def _perf_avg(self, total, count):
        return (float(total) / float(count)) if count else 0.0

    def _open_perf_log(self, mode):
        self._close_perf_log()
        self._perf_mode = mode
        self._perf_session_started = time.perf_counter()
        self._perf_sample_index = 0
        self._perf_window = self._make_perf_bucket()
        self._perf_total = self._make_perf_bucket()
        self._perf_ffmpeg_startup_ms = 0.0
        self._perf_write_join_ms = 0.0
        self._perf_stop_audio_ms = 0.0
        self._perf_stop_video_ms = 0.0
        try:
            logs_dir = get_log_dir()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._perf_path = os.path.join(logs_dir, f"record_perf_{ts}.csv")
            self._perf_file = open(self._perf_path, "w", encoding="utf-8")
            self._perf_file.write(
                "kind,sample_idx,samples,source_mode,capture_avg_ms,capture_max_ms,"
                "cursor_avg_ms,cursor_max_ms,contiguous_avg_ms,contiguous_max_ms,"
                "queue_wait_avg_ms,queue_wait_max_ms,loop_avg_ms,loop_max_ms,"
                "sleep_avg_ms,sleep_max_ms,missed_frames,queue_full_events,"
                "camera_none_events,frame_size_mismatches,last_queue_size,"
                "ffmpeg_startup_ms,write_join_ms,stop_audio_ms,stop_video_ms,"
                "total_runtime_ms,reason\n"
            )
            self._perf_file.flush()
            self.logger.info("Recording perf logging enabled: %s", self._perf_path)
        except Exception as e:
            self._perf_file = None
            self._perf_path = None
            self.logger.warning("Failed to open recording perf log: %s", e)

    def _update_perf_bucket(self, bucket, *, capture_ms, cursor_ms, contiguous_ms, queue_wait_ms, loop_ms, sleep_ms,
                            missed_frames, queue_full_events, camera_none_events, frame_size_mismatches, queue_size):
        bucket["samples"] += 1
        bucket["capture_ms_total"] += capture_ms
        bucket["capture_ms_max"] = max(bucket["capture_ms_max"], capture_ms)
        bucket["cursor_ms_total"] += cursor_ms
        bucket["cursor_ms_max"] = max(bucket["cursor_ms_max"], cursor_ms)
        bucket["contiguous_ms_total"] += contiguous_ms
        bucket["contiguous_ms_max"] = max(bucket["contiguous_ms_max"], contiguous_ms)
        bucket["queue_wait_ms_total"] += queue_wait_ms
        bucket["queue_wait_ms_max"] = max(bucket["queue_wait_ms_max"], queue_wait_ms)
        bucket["loop_ms_total"] += loop_ms
        bucket["loop_ms_max"] = max(bucket["loop_ms_max"], loop_ms)
        bucket["sleep_ms_total"] += sleep_ms
        bucket["sleep_ms_max"] = max(bucket["sleep_ms_max"], sleep_ms)
        bucket["missed_frames_total"] += int(missed_frames)
        bucket["queue_full_events"] += int(queue_full_events)
        bucket["camera_none_events"] += int(camera_none_events)
        bucket["frame_size_mismatches"] += int(frame_size_mismatches)
        bucket["last_queue_size"] = queue_size

    def _emit_perf_bucket(self, kind, bucket, reason="", include_totals=False):
        if not self._perf_file or not bucket:
            return
        samples = bucket["samples"]
        total_runtime_ms = 0.0
        if include_totals and self._perf_session_started is not None:
            total_runtime_ms = (time.perf_counter() - self._perf_session_started) * 1000.0
        self._perf_file.write(
            f"{kind},{self._perf_sample_index},{samples},{self._perf_mode},"
            f"{self._perf_avg(bucket['capture_ms_total'], samples):.3f},{bucket['capture_ms_max']:.3f},"
            f"{self._perf_avg(bucket['cursor_ms_total'], samples):.3f},{bucket['cursor_ms_max']:.3f},"
            f"{self._perf_avg(bucket['contiguous_ms_total'], samples):.3f},{bucket['contiguous_ms_max']:.3f},"
            f"{self._perf_avg(bucket['queue_wait_ms_total'], samples):.3f},{bucket['queue_wait_ms_max']:.3f},"
            f"{self._perf_avg(bucket['loop_ms_total'], samples):.3f},{bucket['loop_ms_max']:.3f},"
            f"{self._perf_avg(bucket['sleep_ms_total'], samples):.3f},{bucket['sleep_ms_max']:.3f},"
            f"{bucket['missed_frames_total']},{bucket['queue_full_events']},"
            f"{bucket['camera_none_events']},{bucket['frame_size_mismatches']},{bucket['last_queue_size']},"
            f"{self._perf_ffmpeg_startup_ms:.3f},{self._perf_write_join_ms:.3f},"
            f"{self._perf_stop_audio_ms:.3f},{self._perf_stop_video_ms:.3f},{total_runtime_ms:.3f},{reason}\n"
        )
        self._perf_file.flush()

    def _record_perf_sample(self, *, capture_ms, cursor_ms, contiguous_ms, queue_wait_ms, loop_ms, sleep_ms,
                            missed_frames=0, queue_full_events=0, camera_none_events=0,
                            frame_size_mismatches=0, queue_size=-1):
        if self._perf_window is None or self._perf_total is None:
            return
        self._update_perf_bucket(
            self._perf_window,
            capture_ms=capture_ms,
            cursor_ms=cursor_ms,
            contiguous_ms=contiguous_ms,
            queue_wait_ms=queue_wait_ms,
            loop_ms=loop_ms,
            sleep_ms=sleep_ms,
            missed_frames=missed_frames,
            queue_full_events=queue_full_events,
            camera_none_events=camera_none_events,
            frame_size_mismatches=frame_size_mismatches,
            queue_size=queue_size,
        )
        self._update_perf_bucket(
            self._perf_total,
            capture_ms=capture_ms,
            cursor_ms=cursor_ms,
            contiguous_ms=contiguous_ms,
            queue_wait_ms=queue_wait_ms,
            loop_ms=loop_ms,
            sleep_ms=sleep_ms,
            missed_frames=missed_frames,
            queue_full_events=queue_full_events,
            camera_none_events=camera_none_events,
            frame_size_mismatches=frame_size_mismatches,
            queue_size=queue_size,
        )
        if self._perf_window["samples"] >= self._perf_window_size:
            self._perf_sample_index += 1
            self._emit_perf_bucket("window", self._perf_window, reason="window")
            self._perf_window = self._make_perf_bucket()

    def _finalize_perf_log(self, reason):
        if self._perf_window and self._perf_window["samples"] > 0:
            self._perf_sample_index += 1
            self._emit_perf_bucket("window", self._perf_window, reason="flush")
            self._perf_window = self._make_perf_bucket()
        if self._perf_total and self._perf_total["samples"] > 0:
            self._emit_perf_bucket("summary", self._perf_total, reason=reason, include_totals=True)
        self._close_perf_log()

    def _close_perf_log(self):
        if self._perf_file:
            try:
                self._perf_file.close()
            except Exception:
                pass
        self._perf_file = None
        self._perf_path = None

    def draw_cursor(self, frame):
        try:
            mx, my = get_mouse_pos()
            rel_x = mx - self.region['left']
            rel_y = my - self.region['top']
            h, w = frame.shape[:2]
            ch, cw = self.cursor_img.shape[:2]
            if rel_x >= -cw and rel_y >= -ch and rel_x < w and rel_y < h:
                x1 = max(0, rel_x)
                y1 = max(0, rel_y)
                x2 = min(w, rel_x + cw)
                y2 = min(h, rel_y + ch)
                cx1 = x1 - rel_x
                cy1 = y1 - rel_y
                cx2 = cx1 + (x2 - x1)
                cy2 = cy1 + (y2 - y1)
                if x2 > x1 and y2 > y1:
                    cursor_crop = self.cursor_img[cy1:cy2, cx1:cx2]
                    frame_crop = frame[y1:y2, x1:x2]
                    alpha = cursor_crop[:, :, 3] / 255.0
                    alpha = alpha[:, :, np.newaxis]
                    frame_crop[:, :, :3] = (cursor_crop[:, :, :3] * alpha + frame_crop[:, :, :3] * (1 - alpha)).astype(np.uint8)
                    frame_crop[:, :, 3] = np.maximum(frame_crop[:, :, 3], cursor_crop[:, :, 3])
                    frame[y1:y2, x1:x2] = frame_crop
        except Exception:
            pass
        return frame

    def _write_frames(self):
        """Separate thread for writing frames to FFmpeg"""
        while not self.stop_event.is_set() or not self.frame_queue.empty():
            try:
                frame_data = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            
            # 主要修改：增加 FFmpeg 进程检查，增加队列异常捕获，增加日志
            if self.ffmpeg_process:
                if self.ffmpeg_process.poll() is not None:
                    self.logger.error("FFmpeg process exited unexpectedly during write")
                    break
                try:
                    self.ffmpeg_process.stdin.write(frame_data)
                except (BrokenPipeError, IOError):
                    self.logger.error("FFmpeg stdin pipe broken")
                    break
                except Exception as e:
                    print(f"Write error: {e}")
                    break
            
            self.frame_queue.task_done()

    def _should_use_rust_core(self):
        """Check if we should use the high-performance Rust Core backend."""
        try:
            rust_core = VideoProcessor._load_rust_core(required_attrs=("ScreenRecorder",), context="recorder_probe")
        except Exception as e:
            self.logger.warning(f"Rust Core backend unavailable: {e}")
            return False
            
        # Rust Core limitations:
        # - No camera-only mode
        # - No audio-only mode
        # - No custom frame provider
        if self.camera_only or self.audio_only or self.frame_provider:
            return False
            
        if self.region is None:
            return True
            
        try:
            if not self.sct:
                self.sct = mss.mss()
            monitor = self.sct.monitors[1]
            left = int(self.region.get('left', 0))
            top = int(self.region.get('top', 0))
            width = int(self.region.get('width', 0))
            height = int(self.region.get('height', 0))
            if width <= 1 or height <= 1:
                return False
            return (
                left >= monitor['left'] and
                top >= monitor['top'] and
                left + width <= monitor['left'] + monitor['width'] and
                top + height <= monitor['top'] + monitor['height']
            )
        except Exception:
            return False

    def _get_rust_capture_region(self):
        if self.region is None:
            return None
        try:
            if not self.sct:
                self.sct = mss.mss()
            monitor = self.sct.monitors[1]
            left = max(0, int(self.region.get('left', 0)) - int(monitor['left']))
            top = max(0, int(self.region.get('top', 0)) - int(monitor['top']))
            width = max(2, (int(self.region.get('width', 0)) // 2) * 2)
            height = max(2, (int(self.region.get('height', 0)) // 2) * 2)
            max_width = max(2, int(monitor['width']) - left)
            max_height = max(2, int(monitor['height']) - top)
            return {
                "left": left,
                "top": top,
                "width": min(width, max_width),
                "height": min(height, max_height),
            }
        except Exception as e:
            self.logger.warning(f"Failed to build Rust capture region, fallback to Python backend: {e}")
            return None

    def _get_video_duration(self, filename):
        """Get duration of a video file in seconds using ffprobe."""
        try:
            ffprobe_path = get_ffprobe_path()
            if ffprobe_path:
                cmd = [
                ffprobe_path,
                '-v', 'error', 
                '-show_entries', 'format=duration', 
                '-of', 'default=noprint_wrappers=1:nokey=1', 
                filename
                ]
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout = (result.stdout or "").strip()
                if result.returncode == 0 and stdout:
                    duration = float(stdout)
                    if duration > 0:
                        return duration
                if result.returncode != 0:
                    self.logger.warning(
                        "ffprobe duration probe failed for %s with code=%s stderr=%s",
                        filename,
                        result.returncode,
                        (result.stderr or "").strip(),
                    )
            else:
                self.logger.info("ffprobe unavailable, using cv2 duration fallback for %s", filename)
        except Exception as e:
            self.logger.error(f"Failed to get duration for {filename}: {e}")

        try:
            cap = cv2.VideoCapture(filename)
            if not cap.isOpened():
                return 0.0
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            cap.release()
            if fps > 0 and frames > 0:
                duration = frames / fps
                if duration > 0:
                    self.logger.info("Video duration fallback via cv2 for %s: %.6fs", filename, duration)
                    return duration
        except Exception as e:
            self.logger.error(f"Fallback duration probe failed for {filename}: {e}")
        return 0.0

    def _trim_wav_to_duration(self, wav_path, target_duration_sec, label="audio"):
        """Trim a WAV file in place so segment audio does not overrun its video segment."""
        if not wav_path or not os.path.exists(wav_path):
            return False
        try:
            target_duration_sec = float(target_duration_sec or 0.0)
        except Exception:
            target_duration_sec = 0.0
        if target_duration_sec <= 0.0:
            return False

        try:
            with wave.open(wav_path, "rb") as wf:
                params = wf.getparams()
                sample_rate = int(wf.getframerate() or 0)
                actual_frames = int(wf.getnframes() or 0)
                if sample_rate <= 0 or actual_frames <= 0:
                    return False

                target_frames = int(round(target_duration_sec * sample_rate))
                if target_frames <= 0 or actual_frames <= target_frames:
                    return False

                trimmed_frames = wf.readframes(target_frames)

            temp_trimmed = wav_path + ".trim.tmp"
            with wave.open(temp_trimmed, "wb") as out_wf:
                out_wf.setparams(params)
                out_wf.writeframes(trimmed_frames)

            os.replace(temp_trimmed, wav_path)
            self.logger.info(
                "Trimmed %s to match video duration: path=%s target_sec=%.6f actual_sec=%.6f",
                label,
                wav_path,
                target_duration_sec,
                float(actual_frames) / float(sample_rate),
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to trim {label} WAV {wav_path}: {e}")
            try:
                temp_trimmed = wav_path + ".trim.tmp"
                if os.path.exists(temp_trimmed):
                    os.remove(temp_trimmed)
            except Exception:
                pass
            return False

    def _merge_segments(self):
        """Merge all recorded segments into one continuous file."""
        if not hasattr(self, 'segments') or not self.segments:
            return

        self.logger.info(f"Merging {len(self.segments)} segments...")

        def final_mix_video_with_audio(target_video_file):
            if os.path.exists(target_video_file):
                self.logger.info(f"Rust Core: Starting final audio mix for {target_video_file}")
                ffmpeg_exe = get_ffmpeg_path()

                has_mic = self.record_audio and os.path.exists(self.temp_audio_mic) and os.path.getsize(self.temp_audio_mic) > 0
                has_sys = self.record_system_audio and os.path.exists(self.temp_audio_sys) and os.path.getsize(self.temp_audio_sys) > 0

                mixed_audio_wav = target_video_file.replace('.mp4', '_mixed_audio.wav')
                ready_to_mux = False
                audio_source_to_mux = None

                if has_mic or has_sys:
                    try:
                        cmd_mix_audio = [ffmpeg_exe, '-y']

                        if has_mic:
                            cmd_mix_audio.extend(['-i', self.temp_audio_mic])
                        if has_sys:
                            cmd_mix_audio.extend(['-i', self.temp_audio_sys])

                        filter_complex = ""
                        if has_mic and not has_sys:
                            filter_complex = "[0:a]aresample=48000,volume=5.0[aout]"
                        elif not has_mic and has_sys:
                            filter_complex = "[0:a]aresample=48000,volume=1.5[aout]"
                        elif has_mic and has_sys:
                            filter_complex = "[0:a]aresample=48000,volume=5.0[mic];[1:a]aresample=48000,volume=1.5[sys];[mic][sys]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,volume=1.5[aout]"

                        cmd_mix_audio.extend(['-filter_complex', filter_complex, '-map', '[aout]', '-c:a', 'pcm_s16le', '-ar', '48000', mixed_audio_wav])

                        self.logger.info(f"Generating mixed audio WAV: {' '.join(cmd_mix_audio)}")
                        res = subprocess.run(cmd_mix_audio, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)

                        if res.returncode == 0 and os.path.exists(mixed_audio_wav) and os.path.getsize(mixed_audio_wav) > 0:
                            self.logger.info(f"Mixed audio WAV created: {mixed_audio_wav}")
                            ready_to_mux = True
                            audio_source_to_mux = mixed_audio_wav
                        else:
                            self.logger.error(f"Failed to create mixed audio WAV. Code: {res.returncode}, Stderr: {res.stderr.decode('utf-8', errors='ignore')}")
                            if has_mic:
                                self.logger.info("Fallback: Using raw Mic audio for muxing")
                                audio_source_to_mux = self.temp_audio_mic
                                ready_to_mux = True
                            elif has_sys:
                                self.logger.info("Fallback: Using raw Sys audio for muxing")
                                audio_source_to_mux = self.temp_audio_sys
                                ready_to_mux = True

                    except Exception as e:
                        self.logger.error(f"Exception during audio mixing: {e}")

                if ready_to_mux and audio_source_to_mux:
                    final_output_temp = target_video_file.replace('.mp4', '_final_mux.mp4')
                    try:
                        cmd_mux = [
                            ffmpeg_exe, '-y',
                            '-i', target_video_file,
                            '-i', audio_source_to_mux,
                            '-c:v', 'copy',
                            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
                            '-map', '0:v', '-map', '1:a',
                            '-shortest',
                            '-movflags', '+faststart',
                            final_output_temp
                        ]

                        self.logger.info(f"Muxing Final Video: {' '.join(cmd_mux)}")
                        res_mux = subprocess.run(cmd_mux, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)

                        if res_mux.returncode == 0 and os.path.exists(final_output_temp) and os.path.getsize(final_output_temp) > 0:
                            self.logger.info("Final Mux Successful.")
                            try:
                                os.remove(target_video_file)
                                os.rename(final_output_temp, target_video_file)
                            except Exception as e:
                                self.logger.error(f"Failed to rename muxed file: {e}")
                        else:
                            self.logger.error(f"Final Mux Failed. Code: {res_mux.returncode}, Stderr: {res_mux.stderr.decode('utf-8', errors='ignore')}")
                            print(f"FFmpeg Error: {res_mux.stderr.decode('utf-8', errors='ignore')}")

                    except Exception as e:
                        self.logger.error(f"Exception during final muxing: {e}")
                else:
                    self.logger.warning("No audio ready to mux. Output will be silent.")

                if os.path.exists(mixed_audio_wav):
                    try:
                        os.remove(mixed_audio_wav)
                    except:
                        pass
            else:
                self.logger.error(f"Cannot find target video file for mixing: {target_video_file}")
        
        if len(self.segments) == 1:
            # Single segment case: just rename/move to expected temp paths
            seg = self.segments[0]
            if os.path.exists(seg['video']):
                if os.path.exists(self.temp_video): os.remove(self.temp_video)
                os.rename(seg['video'], self.temp_video)
            
            if seg['mic'] and os.path.exists(seg['mic']):
                if os.path.exists(self.temp_audio_mic): os.remove(self.temp_audio_mic)
                os.rename(seg['mic'], self.temp_audio_mic)
                
            if seg['sys'] and os.path.exists(seg['sys']):
                if os.path.exists(self.temp_audio_sys): os.remove(self.temp_audio_sys)
                os.rename(seg['sys'], self.temp_audio_sys)
            
            # Metadata
            if os.path.exists(seg['meta']):
                dest_meta = self.temp_video.replace('.mp4', '.json')
                if os.path.exists(dest_meta): os.remove(dest_meta)
                os.rename(seg['meta'], dest_meta)

            final_mix_video_with_audio(self.temp_video)
            return

        # Multiple segments case
        ffmpeg_exe = get_ffmpeg_path()
        segment_durations = []
        for idx, seg in enumerate(self.segments):
            seg_duration = 0.0
            if os.path.exists(seg['video']):
                seg_duration = self._get_video_duration(seg['video'])
            segment_durations.append(seg_duration)
            self.logger.info("[Seg %s] video duration for merge: %.6fs", idx, seg_duration)
        
        # 1. Merge Video
        video_list_file = os.path.join(os.path.dirname(self.temp_video), 'video_list.txt')
        with open(video_list_file, 'w', encoding='utf-8') as f:
            for seg in self.segments:
                if os.path.exists(seg['video']):
                    # FFmpeg concat requires forward slashes and escaped paths
                    path = seg['video'].replace('\\', '/')
                    f.write(f"file '{path}'\n")
        
        try:
            cmd = [
                ffmpeg_exe, '-f', 'concat', '-safe', '0', 
                '-i', video_list_file, '-c', 'copy', '-y', 
                '-movflags', '+faststart', # 优化长视频加载
                self.temp_video
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            self.logger.error(f"Failed to concat videos: {e}")
        finally:
            if os.path.exists(video_list_file): os.remove(video_list_file)

        # 2. Merge Mic Audio
        if self.record_audio:
            mic_list_file = os.path.join(os.path.dirname(self.temp_video), 'mic_list.txt')
            mic_segments_found = 0
            with open(mic_list_file, 'w', encoding='utf-8') as f:
                for idx, seg in enumerate(self.segments):
                    if seg['mic'] and os.path.exists(seg['mic']) and os.path.getsize(seg['mic']) > 100:
                        self._trim_wav_to_duration(seg['mic'], segment_durations[idx], f"mic seg {idx}")
                        path = seg['mic'].replace('\\', '/')
                        f.write(f"file '{path}'\n")
                        mic_segments_found += 1
            
            # Log list content
            # try:
            #     with open(mic_list_file, 'r', encoding='utf-8') as f:
            #         self.logger.info(f"Mic List Content:\n{f.read()}")
            # except: pass

            if mic_segments_found > 0:
                try:
                    # Concat audio (wav)
                    cmd = [
                        ffmpeg_exe, '-f', 'concat', '-safe', '0', 
                        '-i', mic_list_file, '-c', 'copy', '-y', self.temp_audio_mic
                    ]
                    res = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if res.returncode == 0 and os.path.exists(self.temp_audio_mic):
                        self.logger.info(f"Mic audio concat success. Size: {os.path.getsize(self.temp_audio_mic)}")
                    else:
                        self.logger.error(f"Mic audio concat failed. Code: {res.returncode}, Stderr: {res.stderr.decode('utf-8', errors='ignore')}")
                except Exception as e:
                    self.logger.error(f"Failed to concat mic audio: {e}")
                finally:
                    if os.path.exists(mic_list_file): os.remove(mic_list_file)
            else:
                self.logger.warning("No mic segments found to merge.")
                # IMPORTANT: If we have NO mic segments, we must ensure self.temp_audio_mic does NOT exist
                # or is empty, so subsequent checks don't think we have mic audio.
                if os.path.exists(self.temp_audio_mic):
                    try: os.remove(self.temp_audio_mic)
                    except: pass

        # 3. Merge System Audio
        if self.record_system_audio:
            sys_list_file = os.path.join(os.path.dirname(self.temp_video), 'sys_list.txt')
            sys_segments_found = 0
            with open(sys_list_file, 'w', encoding='utf-8') as f:
                for idx, seg in enumerate(self.segments):
                    if seg['sys'] and os.path.exists(seg['sys']) and os.path.getsize(seg['sys']) > 100:
                        self._trim_wav_to_duration(seg['sys'], segment_durations[idx], f"sys seg {idx}")
                        path = seg['sys'].replace('\\', '/')
                        f.write(f"file '{path}'\n")
                        sys_segments_found += 1
            
            if sys_segments_found > 0:
                try:
                    cmd = [
                        ffmpeg_exe, '-f', 'concat', '-safe', '0', 
                        '-i', sys_list_file, '-c', 'copy', '-y', self.temp_audio_sys
                    ]
                    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if os.path.exists(self.temp_audio_sys):
                        self.logger.info(f"Sys audio concat success. Size: {os.path.getsize(self.temp_audio_sys)}")
                    else:
                        self.logger.error("Sys audio concat failed: Output file not found.")
                except Exception as e:
                    self.logger.error(f"Failed to concat system audio: {e}")
                finally:
                    if os.path.exists(sys_list_file): os.remove(sys_list_file)
            else:
                self.logger.warning("No sys segments found to merge.")
                if os.path.exists(self.temp_audio_sys):
                    try: os.remove(self.temp_audio_sys)
                    except: pass

        # 4. Merge Metadata
        final_mouse_data = []
        current_time_offset = 0.0
        cursor_burned_in = False
        
        for idx, seg in enumerate(self.segments):
            if os.path.exists(seg['meta']):
                try:
                    with open(seg['meta'], 'r') as f:
                        data = json.load(f)
                        
                        # Handle new dict format
                        events = []
                        if isinstance(data, dict):
                            events = data.get('events', [])
                            if data.get('cursor_burned_in'):
                                cursor_burned_in = True
                        elif isinstance(data, list):
                            events = data
                            
                        # Shift timestamps
                        for item in events:
                            item['t'] += current_time_offset
                        final_mouse_data.extend(events)
                except Exception as e:
                    self.logger.error(f"Error reading metadata {seg['meta']}: {e}")
            
            # Update offset by duration of this video segment
            if os.path.exists(seg['video']):
                duration = segment_durations[idx] if idx < len(segment_durations) else self._get_video_duration(seg['video'])
                current_time_offset += duration
        
        # Save merged metadata
        meta_file = self.temp_video.replace('.mp4', '.json')
        with open(meta_file, 'w') as f:
            # Preserve the flag in merged file
            if cursor_burned_in:
                json.dump({"cursor_burned_in": True, "events": final_mouse_data}, f)
            else:
                json.dump(final_mouse_data, f) # Legacy list format for compatibility if mixed

        
        # 4. Final Mix: Combine Video + Mic + Sys into the final MP4
        final_mix_video_with_audio(self.temp_video)
        
        # 5. Cleanup segment files
        for seg in self.segments:
            try:
                if os.path.exists(seg['video']): os.remove(seg['video'])
                if seg['mic'] and os.path.exists(seg['mic']): os.remove(seg['mic'])
                if seg['sys'] and os.path.exists(seg['sys']): os.remove(seg['sys'])
                if os.path.exists(seg['meta']): os.remove(seg['meta'])
            except: pass

    def _finalize_recording(self):
        """Execute post-recording tasks: preview generation, audio-only merge, and folder opening."""
        if self.audio_only:
             self.merge_audio_only()
        else:
            try:
                if os.path.exists(self.final_output) and str(self.final_output).lower().endswith(".mp4"):
                    # 不再生成 _preview 文件，而是直接生成 _preview.json 供编辑器使用
                    # 因为现在录制的 MP4 文件已经包含了音频（实时混流），所以 _preview.mp4 实际上就是原文件
                    # 但为了兼容旧逻辑，我们还是生成一下，或者让编辑器直接读原文件
                    # 编辑器逻辑：_create_preview_with_audio 是为了把分离的 wav 和无声 mp4 合并成有声 mp4
                    # 现在 Python 模式是无声 mp4 + wav，所以需要合并
                    # Rust Core 模式现在也是分段录制后合并，最终也是生成一个有声 mp4
                    
                    # 关键修复：确保 preview 文件生成逻辑被调用
                    preview_path = os.path.splitext(self.final_output)[0] + "_preview.mp4"
                    
                    # Create marker file synchronously to prevent race condition with Editor
                    marker_path = preview_path + ".generating"
                    try:
                        with open(marker_path, 'w') as f:
                            f.write("generating")
                    except Exception:
                        pass
                    
                    # 如果 final_output 已经包含音频（Rust Core 模式下最终 mux 过了），那么直接复制即可，不需要再 ffmpeg
                    # 但 Python 模式下，temp_video 是无声的，final_output 只是重命名了 temp_video
                    # 所以 Python 模式下 final_output 还是无声的，必须运行 _create_preview_with_audio 来合并音频
                    
                    threading.Thread(
                        target=_create_preview_with_audio,
                        kwargs={
                            "video_path": self.final_output,
                            "mic_wav": self.temp_audio_mic,
                            "sys_wav": self.temp_audio_sys,
                            "preview_path": preview_path,
                            "logger_obj": self.logger,
                        },
                        daemon=True,
                    ).start()
            except Exception:
                pass
            
            # Open output folder
            try:
                if os.name == 'nt':
                    threading.Thread(target=self._open_output_folder, args=(self.final_output,), daemon=True).start()
                else:
                    os.startfile(self.output_dir)
            except Exception as e:
                print(f"Failed to open output folder: {e}")

    def _run_rust_core(self):
        """Execute recording using the Rust Core backend with segmentation support."""
        self.logger.info("Starting Rust Core recording session (Segmented Mode)")
        self.is_recording = True
        rust_core = VideoProcessor._load_rust_core(required_attrs=("ScreenRecorder",), context="recorder_runtime")
        
        # Rust Core Mode does NOT use real-time streaming, so we must ensure ports are None
        # to prevent AudioRecorder from trying to connect to non-existent listeners.
        # This was causing a 5-second delay/timeout per segment and potentially empty audio files.
        rust_mic_port = None
        rust_sys_port = None

        self.segments = []
        segment_index = 0
        
        # Helper to stop recorders safely
        def stop_current_recorders(save_segment=True):
            mouse_data = []
            try:
                self.logger.info("stop_current_recorders start seg=%s save_segment=%s", segment_index, save_segment)

                # Rust segmented mode records video/cursor independently from Python audio recorders.
                # Stop the Rust recorder first to avoid racing native teardown against audio shutdown.
                self.logger.info("Stopping rust recorder before audio recorders")
                mouse_data = recorder.stop()
                self.logger.info("Rust recorder stop finished seg=%s mouse_events=%s", segment_index, len(mouse_data) if mouse_data else 0)
            except Exception as e:
                self.logger.exception(f"Error stopping segment: {e}")
            finally:
                if self.mic_recorder:
                    self.logger.info("Stopping mic recorder after rust stop. alive=%s", self.mic_recorder.is_alive())
                    self.mic_recorder.stop()
                    self.logger.info("Mic recorder stop finished alive=%s", self.mic_recorder.is_alive())
                    if self.mic_recorder.is_alive():
                        self.logger.warning("Mic recorder still alive after rust stop")
                
                if self.sys_recorder:
                    self.logger.info("Stopping system audio recorder after rust stop. alive=%s", self.sys_recorder.is_alive())
                    self.sys_recorder.stop()
                    self.logger.info("System audio recorder stop finished alive=%s", self.sys_recorder.is_alive())
                    if self.sys_recorder.is_alive():
                        self.logger.warning("System audio recorder still alive after rust stop")

                if save_segment:
                    # Log Segment Audio Sizes
                    if self.record_audio and current_mic and os.path.exists(current_mic):
                         self.logger.info(f"[Seg {segment_index}] Mic Audio Size: {os.path.getsize(current_mic)} bytes")
                    elif self.record_audio:
                         self.logger.warning(f"[Seg {segment_index}] Mic Audio File NOT FOUND: {current_mic}")
                         
                    if self.record_system_audio and current_sys and os.path.exists(current_sys):
                         self.logger.info(f"[Seg {segment_index}] Sys Audio Size: {os.path.getsize(current_sys)} bytes")

                    # Save metadata
                    meta_file = current_video.replace('.mp4', '.json')
                    if mouse_data:
                        # Inject region info
                        rx = self.region.get('left', 0)
                        ry = self.region.get('top', 0)
                        for m in mouse_data:
                            m['region_x'] = rx
                            m['region_y'] = ry
                        
                        # Save as structured object to pass flags
                        meta_content = {
                            "cursor_burned_in": True,
                            "events": mouse_data
                        }
                        with open(meta_file, 'w') as f:
                            json.dump(meta_content, f)
                    else:
                        # Empty list if no data
                        with open(meta_file, 'w') as f:
                            json.dump({"cursor_burned_in": True, "events": []}, f)

                    self.segments.append({
                        'video': current_video,
                        'mic': current_mic if self.record_audio else None,
                        'sys': current_sys if self.record_system_audio else None,
                        'meta': meta_file
                    })

        try:
            while not self.stop_event.is_set():
                # Define filenames for this segment
                # Use absolute paths to avoid issues
                base_dir = os.path.dirname(self.temp_video)
                base_name = os.path.basename(self.temp_video).replace('.mp4', '')
                
                current_video = os.path.join(base_dir, f"{base_name}_seg{segment_index}.mp4")
                current_mic = os.path.join(base_dir, f"{base_name}_mic_seg{segment_index}.wav")
                current_sys = os.path.join(base_dir, f"{base_name}_sys_seg{segment_index}.wav")
                
                self.logger.info(f"Starting Segment {segment_index}: {current_video}")

                # 1. Start Audio
                if self.record_audio:
                    try:
                        if self.audio_device_name:
                            idx = AudioRecorder.get_device_index_by_name(self.audio_device_name)
                            if idx is not None:
                                self.audio_device_index = idx
                        self.mic_recorder = AudioRecorder(current_mic, device_index=self.audio_device_index, stream_port=rust_mic_port)
                        self.mic_recorder.start()
                    except Exception as e:
                        self.logger.error(f"Failed to start AudioRecorder (mic) in Rust Core mode. Audio will be disabled. Error: {e}")
                        self.record_audio = False
                        self.mic_recorder = None
                else:
                    self.mic_recorder = None

                # 2. Start System Audio
                if self.record_system_audio:
                    try:
                        from src.system_audio_recorder import SystemAudioRecorder
                        self.sys_recorder = SystemAudioRecorder(current_sys, stream_port=rust_sys_port)
                        self.sys_recorder.start()
                        self.logger.info("SystemAudioRecorder started")
                    except Exception as e:
                        self.logger.error(f"Failed to start SystemAudioRecorder: {e}")
                        self.sys_recorder = None
                else:
                    self.sys_recorder = None
                
                # 3. Start Rust Video
                recorder = rust_core.ScreenRecorder()
                rust_region = self._get_rust_capture_region()
                if rust_region:
                    recorder.start(
                        current_video,
                        rust_region["left"],
                        rust_region["top"],
                        rust_region["width"],
                        rust_region["height"],
                    )
                else:
                    recorder.start(current_video)
                
                # --- Recording Loop for this segment ---
                segment_active = True
                while segment_active and not self.stop_event.is_set():
                    if not self.pause_event.is_set():
                        # Paused!
                        self.logger.info("Pause detected. Ending current segment.")
                        segment_active = False # Break inner loop
                        break
                    
                    time.sleep(0.1)
                
                # Stop current segment
                stop_current_recorders(save_segment=True)
                
                if self.stop_event.is_set():
                    break
                
                # Wait while paused
                self.logger.info("Waiting in pause state...")
                while not self.pause_event.is_set() and not self.stop_event.is_set():
                    time.sleep(0.1)
                
                if self.stop_event.is_set():
                    break
                
                # Prepare for next segment
                segment_index += 1
                self.logger.info("Resuming... Starting next segment.")

        except Exception as e:
            self.logger.error(f"Rust recording loop error: {e}")
        finally:
            self.logger.info("Rust recording session finished. Merging...")
            self.is_recording = False
            
            # Merge all segments
            try:
                self._merge_segments()
            except Exception as e:
                self.logger.error(f"Merge failed: {e}")
            
            # 优化：Rust Core 模式现在也使用实时混流后的文件，不再需要 merge_av
            # 但由于 Rust Core 是分段录制的，我们需要确保重命名逻辑正确 (包括 JSON 元数据)
            if os.path.exists(self.temp_video):
                try:
                    # 1. 重命名视频
                    if os.path.exists(self.final_output):
                        os.remove(self.final_output)
                    os.rename(self.temp_video, self.final_output)
                    self.logger.info(f"Rust Core: Renamed {self.temp_video} to {self.final_output}")
                    
                    # 2. 重命名配套的 JSON 元数据
                    temp_meta = self.temp_video.replace('.mp4', '.json')
                    final_meta = self.final_output.replace('.mp4', '.json')
                    if os.path.exists(temp_meta):
                        if os.path.exists(final_meta):
                            os.remove(final_meta)
                        os.rename(temp_meta, final_meta)
                        self.logger.info(f"Rust Core: Renamed metadata {temp_meta} to {final_meta}")
                except Exception as e:
                    self.logger.error(f"Rust Core: Failed to rename output files: {e}")
                    self.final_output = self.temp_video
            
            # 发送鼠标元数据异步保存 (Rust Core 已经合并好了 metadata)
            # 这里不需要重复保存，因为 _merge_segments 已经处理了
            
            self.logger.info("Rust Core recording finished. Ready.")
            self._finalize_recording()

    def run(self):
        self.logger.info("Starting ScreenRecorder thread")
        self.is_recording = True
        
        # 初始化 MSS
        self.sct = mss.mss()
        
        if self.region is None:
            monitor = self.sct.monitors[1]
            self.region = {'top': monitor['top'], 'left': monitor['left'], 'width': monitor['width'], 'height': monitor['height']}
            
        # Hook: Try to use Rust Core if applicable
        if self._should_use_rust_core():
            self.logger.info(">>> Switching to Rust Core Backend <<<")
            try:
                return self._run_rust_core()
            except Exception as e:
                self.logger.error(f"Rust Core startup failed, fallback to Python backend: {e}")

        self._open_perf_log("python_camera" if self.frame_provider else "python_screen")
            
        self.region['top'] = int(self.region['top'])
        self.region['left'] = int(self.region['left'])
        self.region['width'] = int(self.region['width']) // 2 * 2
        self.region['height'] = int(self.region['height']) // 2 * 2
        
        # 初始化 FFmpeg 录制进程 (替代 cv2.VideoWriter)
        # 直接在录制时进行 H.264 编码，避免后期合并时的耗时重编码
        ffmpeg_exe = get_ffmpeg_path()
        
        # 视频编码参数配置
        crf = '23'
        scale_filter = []
        
        # 兼容性修复：强制宽度和高度为 8 的倍数，以获得最佳兼容性
        # 某些编码器（如 hevc_nvenc, libx264 4:2:0）甚至部分播放器（如 Qt/WMF）
        # 在非标准分辨率（非 4 或 8 的倍数）下可能出现花屏或无法播放
        w = self.region['width']
        h = self.region['height']
        
        # Align to 32 (Standard for H.264/HEVC/WMF compatibility and max performance)
        w = (w // 32) * 32
        h = (h // 32) * 32
        
        # 避免为 0
        if w < 32: w = 32
        if h < 32: h = 32
        
        self.region['width'] = w
        self.region['height'] = h

        try:
            self.logger.info(
                f"Recording settings: video_quality={self.video_quality} use_gpu={self.use_gpu} fps={self.fps} "
                f"region={self.region['width']}x{self.region['height']} top={self.region['top']} left={self.region['left']}"
            )
        except Exception:
            pass
        
        # 构建缩放滤镜 (如果需要)
        # 注意：如果启用了硬件加速，某些滤镜可能不兼容，最好在 CPU 端缩放或使用 hw 滤镜
        # 这里为了兼容性，我们只在目标分辨率与当前不符时才缩放
        # scale='min(W,iw)':-2 自动保持比例并确保偶数
        
        if self.video_quality.startswith('4k'):
            crf = '17'
            # 4K resolution
            if self.region['width'] > 3840:
                scale_filter = ['-vf', "scale='min(3840,iw)':-2"]
        elif self.video_quality.startswith('2k'):
            crf = '20'
            # 2K resolution
            if self.region['width'] > 2560:
                scale_filter = ['-vf', "scale='min(2560,iw)':-2"]
        else: # 1080p
            crf = '23'
            # 1080p - 只有当源大于 1080p 时才缩小，否则保持原样（避免把小图放大模糊）
            # scale_filter = ['-vf', "scale='min(1920,iw)':-2"]
            # 优化：对于 1080p 屏幕录制，不缩放能获得最佳清晰度和性能
            # 只有当宽度 > 1920 时才应用缩放
            if self.region['width'] > 1920:
                scale_filter = ['-vf', "scale='min(1920,iw)':-2"]
            else:
                # 即使不缩放，也要确保偶数尺寸
                # pad 滤镜可以用来填充奇数像素，比 scale 更快且无损
                # 或者依靠上面的 width/height 调整逻辑（已经减1处理了）
                scale_filter = []

        try:
            max_width = None
            if self.video_quality.startswith("4k"):
                max_width = 3840
            elif self.video_quality.startswith("2k"):
                max_width = 2560
            else:
                max_width = 1920 if self.region["width"] > 1920 else None

            if max_width:
                self.logger.info(
                    f"Resolution cap enabled: max_width={max_width}; will_downscale={bool(scale_filter)}; no_upscale=True"
                )
            else:
                self.logger.info("Resolution cap disabled: will_downscale=False; no_upscale=True")
        except Exception:
            pass

        # 尝试检测硬件加速器 (借鉴 Cap 的多厂商优先策略)
        hw_encoder = None
        if self.use_gpu:
            try:
                # 1. 获取支持的编码器列表
                result = subprocess.run([ffmpeg_exe, '-encoders'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                encoders_list = result.stdout
                
                # 2. 优先级链: NVENC -> MF (MediaFoundation) -> CPU
                candidates = ['h264_nvenc', 'h264_mf']
                
                for codec in candidates:
                    if codec in encoders_list:
                        # 深度检查：尝试实际编码一帧
                        try:
                            dummy_cmd = [
                                ffmpeg_exe, '-y',
                                '-f', 'lavfi', '-i', 'color=c=black:s=1920x1080:r=30',
                                '-c:v', codec, '-frames:v', '1',
                                '-f', 'null', '-'
                            ]
                            si = subprocess.STARTUPINFO()
                            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                            subprocess.run(dummy_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=si)
                            
                            hw_encoder = codec
                            self.logger.info(f"Hardware accelerator '{codec}' verified and ready.")
                            break
                        except subprocess.CalledProcessError:
                            self.logger.warning(f"Hardware codec '{codec}' detected but failed verification. Trying next...")
                            continue
                
                if not hw_encoder:
                    self.logger.warning("No supported hardware encoder found. Falling back to CPU.")
            except Exception as e:
                self.logger.error(f"GPU detection failed: {e}")
        else:
            self.logger.info("GPU acceleration disabled by user.")

        # 构建 FFmpeg 命令: 输入 Raw BGRA -> 输出 H.264 MP4
        # 使用 -pix_fmt bgra 匹配 MSS 在 Windows 上的默认输出
        input_pix_fmt = 'bgra'
        # if self.frame_provider:
        #     input_pix_fmt = 'rgb24' # 统一改为 BGRA 以提高兼容性
            
        cmd = [
            ffmpeg_exe, '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-pix_fmt', input_pix_fmt,
            '-s', f"{self.region['width']}x{self.region['height']}",
            '-r', str(self.fps),
            '-i', '-'
        ]
        
        # --- 方案A: 实时音视频混流配置 ---
        audio_inputs = []
        filter_parts = []
        input_idx = 1 # 0 is video
        
        mix_inputs = []
        
        # 优化：不直接使用网络流，而是先录制到本地 WAV 文件，最后再合并
        # 原因：FFmpeg 的 TCP 监听模式非常脆弱，启动时序要求极高，容易导致 FFmpeg 进程秒退。
        # 回归到最稳健的方案：录制时只录视频（和本地音频文件），结束后合并。
        # 这也统一了 Rust Core 模式和 Python 模式的行为。
        
        # if self.record_audio: ... (Removed real-time streaming args)
        # if self.record_system_audio: ... (Removed real-time streaming args)
            
        # 插入音频输入参数到视频输入之后
        # cmd[11:11] = audio_inputs (Removed)
        
        # 构建混音过滤器
        # (Removed real-time filter complex)
        
        cmd.extend(['-map', '0:v'])
        # -----------------------------
        # -----------------------------
        
        if hw_encoder == 'h264_nvenc':
            # NVENC 编码 (NVIDIA)
            cq = '26'
            if self.video_quality.startswith('4k'): cq = '19'
            elif self.video_quality.startswith('2k'): cq = '23'
            
            cmd.extend([
                '-c:v', 'h264_nvenc',
                '-preset', 'p1',    # 优化：使用 P1 (Fastest) 以极大提高实时性，减少停止时的等待
                '-tune', 'll',      # 低延迟
                '-rc', 'vbr',
                '-cq', cq,
                '-spatial-aq', '1', # 开启空间自适应量化提升动态质量
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '128k' # 音频参数
            ])
        elif hw_encoder == 'h264_mf':
            # MediaFoundation 编码 (通用 Windows 加速)
            cmd.extend([
                '-c:v', 'h264_mf',
                '-rate_control', '3', # 3 = VBR
                '-quality', '1',      # 1 = Highest quality
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '128k' # 音频参数
            ])
        else:
            # CPU libx264 编码
            cmd.extend([
                '-c:v', 'libx264',
                '-preset', 'ultrafast', # 提高编码速度以保证帧率
                '-tune', 'zerolatency', # 降低延迟
                '-crf', crf,
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '128k' # 音频参数
            ])
            
        cmd.extend(scale_filter)
        cmd.append(self.temp_video)

        # 启动 FFmpeg 进程
        if not self.audio_only:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            try:
                ffmpeg_start_started = time.perf_counter()
                self.logger.info(f"Starting FFmpeg process: {' '.join(cmd)}")
                
                # 增大 pipe buffer size (Windows default is small, causing blocking if write is fast)
                # But Popen doesn't support bufsize for stdin directly in a way that increases OS pipe buffer easily without win32api.
                # Just rely on the queue.
                
                self.ffmpeg_process = subprocess.Popen(cmd, stdin=subprocess.PIPE, startupinfo=startupinfo)
                self.logger.info(f"FFmpeg process started with PID: {self.ffmpeg_process.pid}")
                
                # Wait a bit to check if it crashes immediately
                try:
                    ret = self.ffmpeg_process.wait(timeout=0.5)
                    self.logger.error(f"FFmpeg exited immediately with code {ret}!")
                    self.is_recording = False
                    self._perf_ffmpeg_startup_ms = (time.perf_counter() - ffmpeg_start_started) * 1000.0
                    self._finalize_perf_log("ffmpeg_exited_immediately")
                    return
                except subprocess.TimeoutExpired:
                    self.logger.info("FFmpeg process is running stable.")
                self._perf_ffmpeg_startup_ms = (time.perf_counter() - ffmpeg_start_started) * 1000.0
                    
            except Exception as e:
                self.logger.error(f"Failed to start FFmpeg process: {e}")
                self.is_recording = False
                self._finalize_perf_log("ffmpeg_start_failed")
                return
            
            # 初始化写入队列和线程
            # Increase queue size to buffer more frames against jitter
            self.frame_queue = queue.Queue(maxsize=60) # Increased from 30 to 60 (2 seconds at 30fps, 1s at 60fps)
            self.write_thread = threading.Thread(target=self._write_frames)
            self.write_thread.daemon = True
            self.write_thread.start()
            self.logger.info("Video write thread started")
        
        # 启动麦克风录制
        if self.record_audio:
            try:
                if self.audio_device_name:
                    new_index = AudioRecorder.get_device_index_by_name(self.audio_device_name)
                    if new_index is not None:
                        if new_index != self.audio_device_index:
                            self.logger.info(f"Audio device reconnected. Updated index from {self.audio_device_index} to {new_index}")
                            self.audio_device_index = new_index
                    else:
                        self.logger.warning(f"Audio device '{self.audio_device_name}' not found. Falling back to default.")
                        self.audio_device_index = None
                self.mic_recorder = AudioRecorder(self.temp_audio_mic, device_index=self.audio_device_index, stream_port=self.mic_port)
                self.mic_recorder.start()
            except Exception as e:
                self.logger.error(f"Failed to start AudioRecorder (mic). Audio will be disabled. Error: {e}")
                self.record_audio = False
                self.mic_recorder = None

        # 启动系统声音录制
        if self.record_system_audio:
            self.logger.info("Initializing SystemAudioRecorder...")
            # 延迟导入，避免主线程 COM 冲突
            try:
                from src.system_audio_recorder import SystemAudioRecorder
                self.sys_recorder = SystemAudioRecorder(self.temp_audio_sys, stream_port=self.sys_port)
                self.sys_recorder.start()
                self.logger.info("SystemAudioRecorder started")
            except Exception as e:
                self.logger.error(f"Failed to start SystemAudioRecorder: {e}")
                self.sys_recorder = None
        
        frame_duration = 1.0 / self.fps
        self.logger.info(f"Started recording region: {self.region}")
        
        start_time = time.time()
        next_frame_time = start_time
        
        # Mouse metadata
        # (Already initialized in __init__ to allow test injection)
        
        while not self.stop_event.is_set():
            loop_started = time.perf_counter()
            capture_ms = 0.0
            cursor_ms = 0.0
            contiguous_ms = 0.0
            queue_wait_ms = 0.0
            queue_full_events = 0
            camera_none_events = 0
            frame_size_mismatches = 0
            missed_frames_this_loop = 0
            queue_size = self.frame_queue.qsize() if hasattr(self, "frame_queue") and self.frame_queue else -1
            # 检查暂停
            if not self.pause_event.is_set():
                if self.last_pause_start == 0:
                    self.last_pause_start = time.time()
                    if self.mic_recorder: self.mic_recorder.pause()
                    if self.sys_recorder: self.sys_recorder.pause()
                time.sleep(0.1)
                continue
            else:
                if self.last_pause_start > 0:
                    # 刚从暂停恢复，重置下一帧时间
                    pause_duration = time.time() - self.last_pause_start
                    next_frame_time += pause_duration
                    
                    self.last_pause_start = 0
                    if self.mic_recorder: self.mic_recorder.resume()
                    if self.sys_recorder: self.sys_recorder.resume()
            
            # 纯音频模式下，不需要处理视频帧，只需要 sleep 维持循环
            if self.audio_only:
                # 增加对 stop_event 的响应频率
                if self.stop_event.is_set():
                    break
                time.sleep(0.05) # 降低 sleep 时间，提高响应速度
                continue

            try:
                capture_started = time.perf_counter()
                if self.frame_provider:
                    frame = self.frame_provider.get_current_frame()
                    self.camera_frame_total_count += 1
                    
                    if frame is not None:
                        # 成功获取到帧，更新缓存
                        self.last_valid_camera_frame = frame
                        
                        # Ensure frame matches the target size (even numbers)
                        target_h = self.region['height']
                        target_w = self.region['width']
                        
                        # IMPORTANT: Flip for preview consistency if needed
                        # Camera frames from camera.py are already flipped horizontally (mirrored) for preview.
                        # However, when we record "Camera Only", we might want the recorded video to be MIRRORED 
                        # so it matches what the user sees in the preview window (WYSIWYG).
                        # Or we want it UNMIRRORED (Reality).
                        # Currently, camera.py stores the FLIPPED frame in `last_frame_full_res`.
                        # So recorder receives a FLIPPED frame.
                        # If we see one frame UNFLIPPED, it might be a race condition where camera.py updated `last_frame_full_res` 
                        # partially or before flip? (Unlikely, Python GIL usually protects assignment).
                        
                        # BUT: If we fallback to `last_valid_camera_frame` which is also from `camera.py`, it should be consistent.
                        
                        # WAIT: If `frame_provider` is NOT `camera.py` (e.g. some other source), behavior might differ.
                        # Assuming frame_provider IS CameraWidget.
                        
                        if frame.shape[0] != target_h or frame.shape[1] != target_w:
                            frame = cv2.resize(frame, (target_w, target_h))
                            
                        # Debug: Log frame properties occasionally
                        if self.camera_frame_total_count % 300 == 1:
                            self.logger.info(f"[CamDebug] Valid frame: {frame.shape}, Mean: {np.mean(frame)}")
                            
                    else:
                        camera_none_events = 1
                        # 获取失败（None），尝试使用上一帧缓存
                        self.camera_frame_none_count += 1
                        
                        # Log every single drop for detailed analysis
                        self.logger.warning(f"[CamDebug] DROP! Frame is None. Count: {self.camera_frame_none_count}/{self.camera_frame_total_count}")
                        
                        if self.last_valid_camera_frame is not None:
                            # Use cached frame to prevent black flashing
                            frame = self.last_valid_camera_frame
                            # Still need to resize if cached frame size differs (unlikely but safe)
                            target_h = self.region['height']
                            target_w = self.region['width']
                            if frame.shape[0] != target_h or frame.shape[1] != target_w:
                                frame = cv2.resize(frame, (target_w, target_h))
                            self.logger.info(f"[CamDebug] Using cached frame fallback.")
                        else:
                            # If no frame available yet (start of recording), create black frame
                            # IMPORTANT: Set Alpha to 255 (Opaque) to avoid potential encoder/player issues with fully transparent frames
                            frame = np.zeros((self.region['height'], self.region['width'], 4), dtype=np.uint8)
                            frame[:, :, 3] = 255
                            self.logger.warning(f"[CamDebug] Using BLACK frame fallback (No cache yet).")
                else:
                    img = self.sct.grab(self.region)
                    frame = np.array(img)
                    capture_ms = (time.perf_counter() - capture_started) * 1000.0
                    cursor_started = time.perf_counter()
                    self.draw_cursor(frame) # Enable baked-in cursor for perfect sync and avoiding dual cursor
                    cursor_ms = (time.perf_counter() - cursor_started) * 1000.0
                if self.frame_provider:
                    capture_ms = (time.perf_counter() - capture_started) * 1000.0
                
                if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                    # 关键修复：确保帧数据在内存中是连续的，否则 FFmpeg 会报错 "Invalid NAL unit size"
                    contiguous_started = time.perf_counter()
                    frame = np.ascontiguousarray(frame)
                    
                    # 严格校验数据大小，防止写入错误数据导致视频流损坏
                    expected_bytes = self.region['width'] * self.region['height'] * 4
                    contiguous_ms = (time.perf_counter() - contiguous_started) * 1000.0
                    if frame.nbytes != expected_bytes:
                        self.logger.error(f"Frame size mismatch! Expected {expected_bytes}, got {frame.nbytes} (Shape: {frame.shape}). Skipping frame.")
                        frame_size_mismatches = 1
                        self._record_perf_sample(
                            capture_ms=capture_ms,
                            cursor_ms=cursor_ms,
                            contiguous_ms=contiguous_ms,
                            queue_wait_ms=queue_wait_ms,
                            loop_ms=(time.perf_counter() - loop_started) * 1000.0,
                            sleep_ms=0.0,
                            frame_size_mismatches=frame_size_mismatches,
                            camera_none_events=camera_none_events,
                            queue_size=queue_size,
                        )
                        continue

                    # 使用 memoryview 避免复制
                    frame_view = memoryview(frame)
                    
                    # 放入队列，如果队列满则阻塞等待，保证不丢帧以维持音画同步
                    queue_started = time.perf_counter()
                    try:
                        self.frame_queue.put(frame_view, timeout=1.0)
                        queue_wait_ms = (time.perf_counter() - queue_started) * 1000.0
                        
                        # Record mouse data for this frame
                        mx, my = get_mouse_pos()
                        l_click = (ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000) != 0
                        current_meta = {
                            "t": len(self.mouse_data) * frame_duration,
                            "x": mx,
                            "y": my,
                            "click": l_click,
                            "region_x": self.region['left'],
                            "region_y": self.region['top']
                        }
                        self.mouse_data.append(current_meta)
                    except queue.Full:
                        queue_wait_ms = (time.perf_counter() - queue_started) * 1000.0
                        queue_full_events = 1
                        now = time.time()
                        if now - self._last_queue_full_log_at >= 2.0:
                            self._last_queue_full_log_at = now
                            self.logger.warning(
                                "Frame queue full, skipping frame. qsize=%s region=%sx%s fps=%s",
                                self.frame_queue.qsize() if self.frame_queue else -1,
                                self.region["width"],
                                self.region["height"],
                                self.fps,
                            )
                    
                    # 补帧逻辑
                    current_time = time.time()
                    if current_time > next_frame_time + frame_duration:
                        missed_frames = int((current_time - next_frame_time) / frame_duration) - 1
                        missed_frames = min(missed_frames, 5) 
                        missed_frames_this_loop = max(0, missed_frames)
                        
                        if missed_frames > 0:
                            # 补帧也放入队列
                            if not self.frame_queue.full():
                                for _ in range(missed_frames):
                                    try:
                                        self.frame_queue.put(frame_view, block=False)
                                        # Duplicate metadata for the extra frame
                                        if 'current_meta' in locals():
                                            dup_meta = current_meta.copy()
                                            dup_meta["t"] = len(self.mouse_data) * frame_duration
                                            self.mouse_data.append(dup_meta)
                                    except queue.Full:
                                        break
                            next_frame_time += missed_frames * frame_duration
                            
            except (BrokenPipeError, IOError):
                now = time.time()
                if now - self._last_pipe_broken_log_at >= 2.0:
                    self._last_pipe_broken_log_at = now
                    self.logger.error("FFmpeg process pipe broken, stopping recording.")
                break
            except Exception as e:
                now = time.time()
                if now - self._last_loop_error_log_at >= 1.0:
                    self._last_loop_error_log_at = now
                    self.logger.exception(f"Error during recording loop: {e}")
            
            # 更新下一帧理论时间
            next_frame_time += frame_duration
            
            # 精确睡眠
            delay = max(0, next_frame_time - time.time())
            queue_size = self.frame_queue.qsize() if hasattr(self, "frame_queue") and self.frame_queue else -1
            self._record_perf_sample(
                capture_ms=capture_ms,
                cursor_ms=cursor_ms,
                contiguous_ms=contiguous_ms,
                queue_wait_ms=queue_wait_ms,
                loop_ms=(time.perf_counter() - loop_started) * 1000.0,
                sleep_ms=delay * 1000.0,
                missed_frames=missed_frames_this_loop,
                queue_full_events=queue_full_events,
                camera_none_events=camera_none_events,
                frame_size_mismatches=frame_size_mismatches,
                queue_size=queue_size,
            )
            time.sleep(delay)
            
        # 等待写入线程结束
        if self.write_thread and self.write_thread.is_alive():
            join_started = time.perf_counter()
            self.write_thread.join(timeout=5.0)
            self._perf_write_join_ms = (time.perf_counter() - join_started) * 1000.0

        # 停止视频写入
        self.logger.info("Stopping ScreenRecorder...")
        self.stop_event.set()
        
        # 1. 首先停止音频录制 (关闭连接，让 FFmpeg 知道流已结束)
        stop_audio_start = time.time()
        if self.mic_recorder:
            self.mic_recorder.stop()
        if self.sys_recorder:
            self.sys_recorder.stop()
            
        # 等待音频线程稍微清理一下连接 (短时间 join)
        if self.mic_recorder and self.mic_recorder.is_alive():
            self.mic_recorder.join(timeout=0.5)
        if self.sys_recorder and self.sys_recorder.is_alive():
            self.sys_recorder.join(timeout=0.5)
        self._perf_stop_audio_ms = (time.time() - stop_audio_start) * 1000.0
        self.logger.info(f"Audio stop signals sent in: {self._perf_stop_audio_ms / 1000.0:.2f}s")

        # 2. 然后停止视频写入 (关闭 stdin)
        stop_video_start = time.time()
        self.logger.info("Stopping video recording...")
        if self.ffmpeg_process:
            self.logger.info(f"FFmpeg process status before stop: {self.ffmpeg_process.poll()}")
            if self.ffmpeg_process.poll() is None:
                try:
                    # 关闭 stdin 会导致 FFmpeg 正常结束并写入索引
                    self.logger.info("Closing FFmpeg stdin...")
                    self.ffmpeg_process.stdin.close()
                except Exception as e:
                    self.logger.error(f"Error closing stdin: {e}")
            
            # 这里的 wait 不应太久，因为音频流已经关闭
            try:
                self.logger.info("Waiting for FFmpeg to exit...")
                self.ffmpeg_process.wait(timeout=10.0) # 增加等待时间，因为写文件可能慢
                self.logger.info(f"FFmpeg exited with code: {self.ffmpeg_process.returncode}")
                
                # Check if file exists immediately after exit
                if os.path.exists(self.temp_video):
                    self.logger.info(f"Temp video file created successfully: {self.temp_video} ({os.path.getsize(self.temp_video)} bytes)")
                else:
                    self.logger.error(f"Temp video file NOT FOUND after FFmpeg exit: {self.temp_video}")
                    
            except subprocess.TimeoutExpired:
                self.logger.warning("FFmpeg did not exit in time, killing...")
                self.ffmpeg_process.kill()
        else:
             self.logger.warning("FFmpeg process was None during stop")
        self._perf_stop_video_ms = (time.time() - stop_video_start) * 1000.0
        self.logger.info(f"Stop video writing took: {self._perf_stop_video_ms / 1000.0:.2f}s")

        # 3. 异步保存鼠标元数据 (14分钟的数据量很大，不要阻塞主流程)
        def save_meta_async(video_path, mouse_data):
            try:
                start_meta = time.time()
                meta_file = video_path.replace('.mp4', '.json')
                meta_content = {
                    "cursor_burned_in": True,
                    "events": mouse_data
                }
                with open(meta_file, 'w') as f:
                    json.dump(meta_content, f)
                self.logger.info(f"Metadata saved asynchronously in {time.time() - start_meta:.2f}s (Events: {len(mouse_data)})")
            except Exception as e:
                self.logger.error(f"Failed to save mouse metadata async: {e}")

        if self.mouse_data:
            # 使用 final_output 的路径来保存 JSON，确保编辑器能找到它
            threading.Thread(target=save_meta_async, args=(self.final_output, self.mouse_data.copy()), daemon=True).start()
            
        self.is_recording = False
        
        # 4. 合并音视频 (恢复 merge_av 逻辑以支持非实时混流)
        if not self.audio_only:
            if os.path.exists(self.temp_video) and os.path.getsize(self.temp_video) > 0:
                self.logger.info(f"Temp video verified: {self.temp_video} ({os.path.getsize(self.temp_video)} bytes)")
                
                # 调用合并逻辑 (包含音频合并和 metadata 处理)
                try:
                    self.merge_av()
                except Exception as e:
                    self.logger.error(f"Merge AV failed: {e}")
                    # Fallback: 如果合并失败，至少保留视频
                    if not os.path.exists(self.final_output):
                         try:
                             os.rename(self.temp_video, self.final_output)
                         except: pass
            else:
                self.logger.error(f"Temp video file not found or empty: {self.temp_video}")
            
            # Double check final output existence
            if os.path.exists(self.final_output):
                 self.logger.info(f"Final output file verified: {self.final_output} ({os.path.getsize(self.final_output)} bytes)")
            else:
                 self.logger.error(f"CRITICAL: Final output file DOES NOT EXIST: {self.final_output}")
        
        self.logger.info("Recording stopped. File ready.")
        self._finalize_perf_log("recording_stopped")
        
        # 5. 执行后续处理 (生成预览、打开文件夹等)
        self._finalize_recording()

    def _open_output_folder(self, file_path):
        """Helper to open folder and select file without blocking"""
        try:
            if not open_folder_and_select_file(file_path):
                subprocess.run(['explorer', '/select,', os.path.normpath(file_path)], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            self.logger.error(f"Async open folder failed: {e}")

    def pause(self):
        self.is_paused = True
        self.pause_event.clear()
        self.logger.info("Recording paused")

    def resume(self):
        self.is_paused = False
        self.pause_event.set()
        self.logger.info("Recording resumed")

    def merge_av(self):
        self.logger.info("Starting merge_av")
        ffmpeg_exe = get_ffmpeg_path()
        self.logger.info(f"FFmpeg path: {ffmpeg_exe}")
        
        has_mic = self.record_audio and os.path.exists(self.temp_audio_mic)
        has_sys = self.record_system_audio and os.path.exists(self.temp_audio_sys)
        
        self.logger.info(f"Has Mic: {has_mic} (Path: {self.temp_audio_mic})")
        if has_mic:
            self.logger.info(f"Mic file size: {os.path.getsize(self.temp_audio_mic)}")
            
        self.logger.info(f"Has Sys: {has_sys} (Path: {self.temp_audio_sys})")

        # Check video file
        if os.path.exists(self.temp_video):
            self.logger.info(f"Video file exists: {self.temp_video} (Size: {os.path.getsize(self.temp_video)})")
        else:
            self.logger.error(f"Video file NOT found: {self.temp_video}")
            return # Cannot merge without video

        if self.record_system_audio and not has_sys:
            self.logger.warning(f"System audio recording enabled but file not found: {self.temp_audio_sys}")
            
        cmd = [ffmpeg_exe, '-y', '-threads', '0', '-i', self.temp_video]
        
        # 添加音频输入
        if has_mic:
            cmd.extend(['-i', self.temp_audio_mic])
        if has_sys:
            cmd.extend(['-i', self.temp_audio_sys])
            
        # 视频参数: 使用流复制 (Stream Copy) 以极大减少合并时间
        video_args = ['-c:v', 'copy']
        
        # 构建映射和过滤器
        # 优化：统一预览和导出音量标准 (Mic 5.0, Sys 1.5)
        # 使用 duration=longest 避免截断
        if has_mic and has_sys:
            # 混合两个音频流，增加音量
            cmd.extend([
                '-filter_complex', '[1:a]aresample=48000,volume=5.0[mic];[2:a]aresample=48000,volume=1.5[sys];[mic][sys]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,volume=1.5[aout]',
                '-map', '0:v',
                '-map', '[aout]',
            ])
        elif has_mic:
            # 单麦克风增强
            cmd.extend(['-filter_complex', '[1:a]aresample=48000,volume=5.0[aout]', '-map', '0:v', '-map', '[aout]'])
        elif has_sys:
            # 单系统音增强
            cmd.extend(['-filter_complex', '[1:a]aresample=48000,volume=1.5[aout]', '-map', '0:v', '-map', '[aout]'])
        else:
            # 无音频，只处理视频
            cmd.extend(['-map', '0:v'])

        # 应用视频参数
        cmd.extend(video_args)
        
        # 应用音频参数 (如果有)
        # 优化：统一使用 192k 以保证音质
        if has_mic or has_sys:
            cmd.extend(['-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest'])
            
        cmd.append(self.final_output)

        self.logger.info(f"FFmpeg merge command: {' '.join(cmd)}")

        try:
            # 创建启动信息以隐藏控制台窗口
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            merge_start = time.time()
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
            self.logger.info(f"Merge took: {time.time() - merge_start:.2f}s")
            print(f"Merged successfully (Fast Mode): {self.final_output}")
            
            # 不再删除临时文件，以便编辑器使用
            # ...
            
            # 打开输出文件夹并选中文件 -> 移至 _finalize_recording 统一处理
            # try:
            #     if os.name == 'nt':
            #         threading.Thread(target=self._open_output_folder, args=(self.final_output,), daemon=True).start()
            #     else:
            #         os.startfile(self.output_dir)
            # except Exception as e:
            #     print(f"Failed to open output folder: {e}")
                
        except subprocess.CalledProcessError as e:
            self.logger.error(f"FFmpeg merge failed: {e}")
            if e.stderr:
                self.logger.error(f"FFmpeg stderr: {e.stderr}")
            print(f"FFmpeg merge failed: {e}")

    def stop(self):
        self.pause_event.set() # Ensure we are not paused when stopping
        self.stop_event.set()
        
        # 不要在这里 join，因为 stop 是被主线程调用的，而 join 会等待 run 方法结束
        # run 方法里会调用 stop，导致死锁吗？
        # 这里的 run 方法循环依赖 stop_event。
        # 当 stop() 被调用时，stop_event set，run loop 结束。
        # run 方法结束前会调用 merge_av。
        # 如果我们在 stop() 里 join()，我们需要确保 run() 能正常退出。
        # 这里的实现逻辑是：ControlBar 调用 stop() -> self.stop_event.set() -> run loop breaks -> run finishes.
        # 所以在 stop() 里调用 join() 是安全的，只要 run() 不阻塞。
        
        # 但是！原代码的 stop() 里面还负责了清理资源和合并。
        # 而 run() 方法末尾也调用了 cleanup 和 merge。
        # 这会导致重复调用。
        # 我们应该让 run() 负责生命周期。
        
        # 为了兼容现有调用方式，我们只设置标志位，然后等待线程结束。
        self.join()

    def merge_audio_only(self):
        print("Merging audio only...")
        ffmpeg_exe = get_ffmpeg_path()
        
        has_mic = os.path.exists(self.temp_audio_mic) and os.path.getsize(self.temp_audio_mic) > 100
        has_sys = os.path.exists(self.temp_audio_sys) and os.path.getsize(self.temp_audio_sys) > 100
        
        cmd = [ffmpeg_exe, '-y', '-threads', '0']
        
        if has_mic and has_sys:
            cmd.extend(['-i', self.temp_audio_mic])
            cmd.extend(['-i', self.temp_audio_sys])
            # 优化：统一音量标准 (Mic 5.0, Sys 1.5)
            filter_complex = "[0:a]aresample=48000,volume=5.0[mic];[1:a]aresample=48000,volume=1.5[sys];[mic][sys]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,volume=1.5[aout]"
            cmd.extend(['-filter_complex', filter_complex, '-map', '[aout]'])
        elif has_mic:
            cmd.extend(['-i', self.temp_audio_mic])
            # 单麦克风增强
            cmd.extend(['-filter_complex', '[0:a]aresample=48000,volume=5.0[aout]', '-map', '[aout]'])
        elif has_sys:
            cmd.extend(['-i', self.temp_audio_sys])
            # 单系统音增强
            cmd.extend(['-filter_complex', '[0:a]aresample=48000,volume=1.5[aout]', '-map', '[aout]'])
        else:
            print("No audio recorded.")
            return

        # Output format mp3 or wav with high bitrate
        cmd.extend(['-b:a', '192k', self.final_output])

        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            merge_start = time.time()
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
            self.logger.info(f"Audio merge took: {time.time() - merge_start:.2f}s")
            print(f"Audio merged successfully: {self.final_output}")
            
            # Clean up
            if os.path.exists(self.temp_audio_mic): os.remove(self.temp_audio_mic)
            if os.path.exists(self.temp_audio_sys): os.remove(self.temp_audio_sys)
            
            # Open folder
            try:
                if os.name == 'nt':
                    threading.Thread(target=self._open_output_folder, args=(self.final_output,), daemon=True).start()
            except Exception as e:
                print(f"Failed to open output folder: {e}")
                
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg merge failed: {e}")
