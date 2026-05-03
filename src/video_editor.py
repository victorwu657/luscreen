import sys
import os
import re
import tempfile
import subprocess
import shutil
import time
import wave
import threading
import cv2 # Import cv2 for video dimension detection
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QSlider, QLabel, QFileDialog, QMessageBox, QProgressDialog,
                               QApplication, QFrame, QSplitter, QStyle, QGroupBox, QDoubleSpinBox,
                               QLineEdit, QComboBox, QDialog, QListWidget, QListWidgetItem,
                               QCheckBox, QScrollArea, QMenu, QSpinBox, QStackedWidget, QToolButton, QButtonGroup, QInputDialog, QSizePolicy)
from PySide6.QtGui import QIcon, QPixmap, QAction, QPainterPath, QRegion, QBitmap, QPainter, QColor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink, QVideoFrame
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtCore import QUrl, Qt, QTimer, QTime, QSize, QEvent, QThread, Signal, QRectF, QRect, QPointF
import traceback

class VideoRenderWidget(QWidget):
    watermark_moved = Signal(float, float)  # norm_x, norm_y (top-left, 0..1)
    watermark_scale_changed = Signal(float)  # new_size (sync with spinbox)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_frame = None
        self.corner_radius = 0
        self.subtitle_text = ""
        self.subtitle_bg = None
        self.watermark_enabled = False
        self.watermark_pos = "bottom-right"
        self.watermark_size = 1.0
        self.watermark_image_path = None
        self.watermark_custom_x = None
        self.watermark_custom_y = None
        self._watermark_pixmap = None
        self._watermark_pixmap_path = None
        self._watermark_rect = None
        self._watermark_dragging = False
        self._watermark_drag_offset = QPointF(0, 0)
        self.setStyleSheet("background: transparent;")

    def set_subtitle(self, text):
        self.subtitle_text = text
        self.update()

    def set_subtitle_background(self, color):
        self.subtitle_bg = color
        self.update()

    def set_frame(self, frame):

        # Must copy frame to keep it valid until paintEvent
        if frame.isValid():
             # Make a deep copy to detach from decoder pool
             # This is critical for D3D/OpenGL backends to avoid locking the pool
             if frame.handleType() == QVideoFrame.NoHandle:
                 self.current_frame = frame
             else:
                 # If hardware accelerated, convert to image immediately to release GPU resource
                 # This prevents "Unable to copy frame from decoder pool"
                 self.current_frame = frame.toImage()
                 
             self.update()

    def set_corner_radius(self, radius):
        self.corner_radius = radius
        self.update()

    def set_watermark_image(self, *, enabled: bool, image_path: str | None, pos: str, size: float, custom_x: float | None = None, custom_y: float | None = None):
        self.watermark_enabled = bool(enabled)
        self.watermark_pos = pos or "bottom-right"
        try:
            self.watermark_size = float(size) if size is not None else 1.0
        except Exception:
            self.watermark_size = 1.0

        try:
            self.watermark_custom_x = float(custom_x) if custom_x is not None else None
        except Exception:
            self.watermark_custom_x = None
        try:
            self.watermark_custom_y = float(custom_y) if custom_y is not None else None
        except Exception:
            self.watermark_custom_y = None

        p = (image_path or "") or None
        if p != self.watermark_image_path:
            self.watermark_image_path = p
            self._watermark_pixmap = None
            self._watermark_pixmap_path = None
        self.update()

    def _hit_test_watermark(self, pos: QPointF) -> bool:
        try:
            r = self._watermark_rect
            if r is None:
                return False
            return r.contains(pos)
        except Exception:
            return False

    def mousePressEvent(self, event):
        try:
            if event.button() == Qt.LeftButton and self.watermark_enabled and self._hit_test_watermark(event.position()):
                self._watermark_dragging = True
                self._watermark_drag_offset = event.position() - self._watermark_rect.topLeft()
                event.accept()
                return
        except Exception:
            pass
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        try:
            if self._watermark_dragging and self._watermark_rect is not None:
                pm = self._watermark_rect
                wm_w = float(pm.width())
                wm_h = float(pm.height())
                x = float(event.position().x() - self._watermark_drag_offset.x())
                y = float(event.position().y() - self._watermark_drag_offset.y())
                max_x = max(0.0, float(self.width()) - wm_w)
                max_y = max(0.0, float(self.height()) - wm_h)
                x = min(max(0.0, x), max_x)
                y = min(max(0.0, y), max_y)
                norm_x = (x / max_x) if max_x > 1e-6 else 0.0
                norm_y = (y / max_y) if max_y > 1e-6 else 0.0
                self.watermark_moved.emit(float(norm_x), float(norm_y))
                event.accept()
                return
        except Exception:
            pass
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        try:
            if event.button() == Qt.LeftButton and self._watermark_dragging:
                self._watermark_dragging = False
                event.accept()
                return
        except Exception:
            pass
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        try:
            if self.watermark_enabled and self._hit_test_watermark(event.position()):
                steps = 0.0
                try:
                    steps = float(event.angleDelta().y()) / 120.0
                except Exception:
                    steps = 0.0
                if abs(steps) >= 1e-6:
                    new_size = float(self.watermark_size or 1.0) + 0.1 * steps
                    new_size = max(0.5, min(5.0, new_size))
                    self.watermark_scale_changed.emit(float(new_size))
                    event.accept()
                    return
        except Exception:
            pass
        super().wheelEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)

            if not self.current_frame:
                return

            # Check if it's QImage (converted) or QVideoFrame (raw)
            from PySide6.QtGui import QImage
            image = None
            
            if isinstance(self.current_frame, QImage):
                image = self.current_frame
            elif hasattr(self.current_frame, 'isValid') and self.current_frame.isValid():
                image = self.current_frame.toImage()
                
            if image and not image.isNull():
                path = QPainterPath()
                if self.corner_radius > 0:
                    path.addRoundedRect(QRectF(self.rect()), self.corner_radius, self.corner_radius)
                else:
                    path.addRect(QRectF(self.rect()))
                
                painter.setClipPath(path)
                # Scale image to fit widget
                painter.drawImage(self.rect(), image)
            else:
                # Handle cases where image conversion fails
                pass

            if self.watermark_enabled and self.watermark_image_path and os.path.exists(self.watermark_image_path):
                try:
                    if self._watermark_pixmap is None or self._watermark_pixmap_path != self.watermark_image_path:
                        pm = QPixmap(self.watermark_image_path)
                        if not pm.isNull():
                            self._watermark_pixmap = pm
                            self._watermark_pixmap_path = self.watermark_image_path

                    if self._watermark_pixmap and not self._watermark_pixmap.isNull():
                        base_scale = (self.height() / 1080.0) * float(self.watermark_size or 1.0)
                        margin = int(20 * base_scale)
                        max_w = max(16, int(self.width() * 0.35))
                        max_h = max(16, int(self.height() * 0.20))
                        desired_h = max(16, int(self.height() * 0.12 * float(self.watermark_size or 1.0)))

                        pm0 = self._watermark_pixmap
                        target_h = min(max_h, desired_h)
                        pm_scaled = pm0.scaledToHeight(target_h, Qt.SmoothTransformation)
                        if pm_scaled.width() > max_w:
                            pm_scaled = pm0.scaledToWidth(max_w, Qt.SmoothTransformation)

                        canvas_w = pm_scaled.width()
                        canvas_h = pm_scaled.height()

                        x, y = 0.0, 0.0
                        if self.watermark_pos == "custom" and self.watermark_custom_x is not None and self.watermark_custom_y is not None:
                            max_x = max(0.0, float(self.width() - canvas_w))
                            max_y = max(0.0, float(self.height() - canvas_h))
                            x = float(self.watermark_custom_x) * max_x
                            y = float(self.watermark_custom_y) * max_y
                        elif self.watermark_pos == "top-left":
                            x, y = float(margin), float(margin)
                        elif self.watermark_pos == "top-right":
                            x, y = float(self.width() - canvas_w - margin), float(margin)
                        elif self.watermark_pos == "bottom-left":
                            x, y = float(margin), float(self.height() - canvas_h - margin)
                        else:
                            x, y = float(self.width() - canvas_w - margin), float(self.height() - canvas_h - margin)

                        painter.setClipping(True)
                        painter.drawPixmap(int(x), int(y), pm_scaled)
                        self._watermark_rect = QRectF(float(x), float(y), float(canvas_w), float(canvas_h))
                except Exception:
                    pass
            else:
                self._watermark_rect = None

            # Draw subtitle
            if self.subtitle_text:
                painter.setClipping(False) # Ensure subtitle is not clipped if outside rounded corners
                
                # Setup font
                font = painter.font()
                # Reduce font size: was height // 20, now height // 35. Min 12.
                target_size = max(12, self.height() // 35)
                if target_size > 0:
                    font.setPointSize(target_size)
                font.setBold(True)
                painter.setFont(font)

                fm = painter.fontMetrics()
                max_text_w = max(10, self.width() - 40)
                br = fm.boundingRect(QRect(0, 0, max_text_w, 1000), Qt.AlignCenter | Qt.TextWordWrap, self.subtitle_text)
                bottom_margin = max(18, int(self.height() * 0.04))
                center_x = self.width() / 2.0
                center_y = self.height() - bottom_margin - (br.height() / 2.0)
                text_rect = QRect(int(center_x - br.width() / 2.0), int(center_y - br.height() / 2.0), int(br.width()), int(br.height()))

                if self.subtitle_bg is not None:
                    try:
                        pad_x = max(8, int(fm.averageCharWidth() * 0.8))
                        pad_y = max(6, int(fm.height() * 0.35))
                        bg_rect = QRectF(text_rect.adjusted(-pad_x, -pad_y, pad_x, pad_y))
                        radius = 8.0
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(self.subtitle_bg)
                        bg_path = QPainterPath()
                        bg_path.addRoundedRect(bg_rect, radius, radius)
                        painter.drawPath(bg_path)
                    except Exception:
                        pass
                
                # Draw outline/shadow for readability
                path = QPainterPath()
                # Use safer QPointF construction
                center_pt = QPointF(text_rect.center())
                offset_pt = QPointF(painter.fontMetrics().horizontalAdvance(self.subtitle_text)/2, -10)
                text_pos = center_pt - offset_pt
                path.addText(text_pos, font, self.subtitle_text)
                
                # Simplified drawing: White text with black outline
                # 1. Shadow/Stroke
                painter.setPen(QColor("black"))
                for dx, dy in [(-1,-1), (-1,1), (1,-1), (1,1), (0,2)]:
                    painter.drawText(text_rect.translated(dx, dy), Qt.AlignCenter | Qt.TextWordWrap, self.subtitle_text)
                
                # 2. Main Text
                painter.setPen(QColor("white"))
                painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, self.subtitle_text)
        except Exception:
            traceback.print_exc()
        finally:
            painter.end()

from src.video_processor import VideoProcessor
from src.recorder import get_ffmpeg_path, open_folder_and_select_file
from src.timeline_widget import TimelineWidget
from src.license_manager import LicenseManager
from src.config import ConfigManager
from src.utils import get_media_duration_sec, get_wav_duration_sec
from src.subtitle_system.manager import SubtitleManager
from src.subtitle_system.ui import SubtitleGenerationDialog
from src.subtitle_system.formatter import SubtitleFormatter, SubtitleSegment
from src.subtitle_system.extractor import AudioExtractor

class ExportThread(QThread):
    progress_updated = Signal(int, str) # value, label
    finished_success = Signal(str) # output_path
    finished_error = Signal(str) # error_message

    def __init__(self, parent, output_path, params):
        super().__init__(parent)
        self.output_path = output_path
        self.params = params
        self.is_cancelled = False
        self.temp_files = []
        self.export_logger = logging.getLogger("VideoEditor")

    def cancel(self):
        self.is_cancelled = True

    def _run_cmd(self, cmd, startupinfo=None, progress_total_ms=None, progress_range=None):
        if self.is_cancelled:
            raise Exception("Export canceled")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        out_tail = bytearray()
        err_tail = bytearray()
        lock = threading.Lock()
        stop = threading.Event()
        last_pct = {"v": None}
        last_speed = {"v": None}
        last_fps = {"v": None}

        def append_tail(buf: bytearray, new_bytes: bytes, cap: int = 256 * 1024):
            if not new_bytes:
                return
            buf.extend(new_bytes)
            if len(buf) > cap:
                del buf[: max(0, len(buf) - cap)]

        def parse_and_emit_progress():
            if not (progress_total_ms and progress_range and out_tail):
                return
            try:
                txt = out_tail.decode("utf-8", errors="ignore")
                m = re.findall(r"out_time_ms=(\d+)", txt)
                if m:
                    out_ms = int(m[-1])
                else:
                    m2 = re.findall(r"out_time=(\d+):(\d+):(\d+)\.(\d+)", txt)
                    if not m2:
                        return
                    hh, mm, ss, frac = m2[-1]
                    frac_ms = int(str(frac)[:3].ljust(3, "0"))
                    out_ms = (int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1000 + frac_ms

                a, b = progress_range
                pct = a + int((min(out_ms, progress_total_ms) / max(1, progress_total_ms)) * (b - a))
                speed_m = re.findall(r"speed=([0-9]+(?:\.[0-9]+)?)x", txt)
                speed_text = speed_m[-1] if speed_m else ""
                fps_m = re.findall(r"(?:^|\n)fps=([0-9]+(?:\.[0-9]+)?)", txt)
                fps_text = fps_m[-1] if fps_m else ""
                if speed_text and speed_text != last_speed["v"]:
                    last_speed["v"] = speed_text
                    if fps_text:
                        self.export_logger.info(f"[ExportSpeed] speed={speed_text}x fps={fps_text}")
                    else:
                        self.export_logger.info(f"[ExportSpeed] speed={speed_text}x")
                if fps_text and fps_text != last_fps["v"]:
                    last_fps["v"] = fps_text
                if last_pct["v"] != pct:
                    last_pct["v"] = pct
                    label = "正在最终合成..."
                    if speed_text:
                        label = f"正在最终合成... {speed_text}x"
                    self.progress_updated.emit(int(pct), label)
            except Exception:
                return

        def reader(stream, buf: bytearray, is_stdout: bool):
            try:
                while not stop.is_set():
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    with lock:
                        append_tail(buf, chunk)
                        if is_stdout:
                            parse_and_emit_progress()
            except Exception:
                return

        t_out = threading.Thread(target=reader, args=(p.stdout, out_tail, True), daemon=True)
        t_err = threading.Thread(target=reader, args=(p.stderr, err_tail, False), daemon=True)
        t_out.start()
        t_err.start()

        try:
            while True:
                if self.is_cancelled:
                    try:
                        p.terminate()
                    except Exception:
                        pass
                    try:
                        p.kill()
                    except Exception:
                        pass
                    raise Exception("Export canceled")
                rc = p.poll()
                if rc is not None:
                    return int(rc), bytes(out_tail), bytes(err_tail)
                time.sleep(0.05)
        finally:
            stop.set()
            try:
                if p.stdout:
                    p.stdout.close()
            except Exception:
                pass
            try:
                if p.stderr:
                    p.stderr.close()
            except Exception:
                pass
            try:
                t_out.join(timeout=0.5)
            except Exception:
                pass
            try:
                t_err.join(timeout=0.5)
            except Exception:
                pass

    def _ensure_file(self, path: str, min_bytes: int, label: str):
        if not path or not os.path.exists(path):
            raise Exception(f"{label}不存在: {path}")
        try:
            if os.path.getsize(path) < int(min_bytes):
                raise Exception(f"{label}文件过小: {path}")
        except Exception:
            raise Exception(f"{label}无法读取: {path}")

    def _validate_video_file(self, path: str) -> bool:
        ffmpeg_exe = None
        try:
            ffmpeg_exe = get_ffmpeg_path()
        except Exception:
            ffmpeg_exe = None

        if ffmpeg_exe and os.path.exists(ffmpeg_exe):
            startupinfo = None
            if os.name == "nt":
                try:
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                except Exception:
                    startupinfo = None
            cmd = [
                ffmpeg_exe,
                "-v",
                "error",
                "-i",
                path,
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ]
            try:
                p = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    startupinfo=startupinfo,
                    timeout=8,
                )
                return int(p.returncode) == 0
            except Exception:
                return False

        try:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                return False
            ret, frame = cap.read()
            cap.release()
            if not ret or frame is None:
                return False
            h, w = frame.shape[:2]
            return int(w) > 0 and int(h) > 0
        except Exception:
            return False

    def _validate_wav_file(self, path: str) -> bool:
        try:
            with wave.open(path, "rb") as wf:
                return wf.getnchannels() > 0 and wf.getframerate() > 0 and wf.getnframes() >= 0
        except Exception:
            return False

    def _ass_time(self, seconds: float) -> str:
        try:
            total_cs = int(round(float(seconds) * 100.0))
        except Exception:
            total_cs = 0
        if total_cs < 0:
            total_cs = 0
        h = total_cs // 360000
        rem = total_cs % 360000
        m = rem // 6000
        rem = rem % 6000
        s = rem // 100
        cs = rem % 100
        return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

    def _parse_srt(self, srt_path: str):
        blocks = []
        try:
            with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
        except Exception:
            return blocks
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        for chunk in [c for c in raw.split("\n\n") if c.strip()]:
            lines = [ln.strip("\n") for ln in chunk.split("\n") if ln.strip("\n") != ""]
            if len(lines) < 2:
                continue
            time_line = None
            for ln in lines:
                if "-->" in ln:
                    time_line = ln
                    break
            if not time_line:
                continue
            try:
                a, b = [p.strip() for p in time_line.split("-->")]
            except Exception:
                continue

            def to_sec(ts: str) -> float:
                ts = ts.strip()
                if " " in ts:
                    ts = ts.split(" ", 1)[0].strip()
                if "," in ts:
                    left, ms = ts.split(",", 1)
                elif "." in ts:
                    left, ms = ts.split(".", 1)
                else:
                    left, ms = ts, "0"
                hh, mm, ss = [int(x) for x in left.split(":")]
                ms_i = int(re.sub(r"\\D", "", ms)[:3] or 0)
                return hh * 3600.0 + mm * 60.0 + ss + (ms_i / 1000.0)

            try:
                start = to_sec(a)
                end = to_sec(b)
            except Exception:
                continue
            if end <= start:
                continue
            text_lines = []
            for ln in lines:
                if ln == time_line:
                    continue
                if re.fullmatch(r"\d+", ln.strip()):
                    continue
                text_lines.append(ln)
            text = "\n".join([t for t in text_lines if t.strip()])
            if not text.strip():
                continue
            blocks.append((start, end, text))
        return blocks

    def _ass_escape(self, text: str) -> str:
        t = str(text or "")
        t = t.replace("\\", r"\\")
        t = t.replace("{", r"\\{").replace("}", r"\\}")
        t = t.replace("\r\n", "\n").replace("\r", "\n")
        t = "\\N".join([ln.strip() for ln in t.split("\n")])
        return t

    def _ass_round_rect(self, x1: int, y1: int, x2: int, y2: int, r: int) -> str:
        x1 = int(x1)
        y1 = int(y1)
        x2 = int(x2)
        y2 = int(y2)
        r = int(max(0, r))
        w = max(0, x2 - x1)
        h = max(0, y2 - y1)
        r = min(r, w // 2, h // 2)
        if r <= 0:
            return f"m {x1} {y1} l {x2} {y1} l {x2} {y2} l {x1} {y2}"

        k = int(round(r * 0.55228475))
        cmds = []
        cmds.append(f"m {x1 + r} {y1}")
        cmds.append(f"l {x2 - r} {y1}")
        cmds.append(f"b {x2 - r + k} {y1} {x2} {y1 + r - k} {x2} {y1 + r}")
        cmds.append(f"l {x2} {y2 - r}")
        cmds.append(f"b {x2} {y2 - r + k} {x2 - r + k} {y2} {x2 - r} {y2}")
        cmds.append(f"l {x1 + r} {y2}")
        cmds.append(f"b {x1 + r - k} {y2} {x1} {y2 - r + k} {x1} {y2 - r}")
        cmds.append(f"l {x1} {y1 + r}")
        cmds.append(f"b {x1} {y1 + r - k} {x1 + r - k} {y1} {x1 + r} {y1}")
        return " ".join(cmds)

    def _approx_char_w(self, ch: str, fs: int) -> float:
        if not ch:
            return 0.0
        o = ord(ch)
        if o <= 127:
            return float(fs) * 0.58
        return float(fs) * 1.02

    def _wrap_text(self, text: str, max_w_px: float, fs: int):
        out_lines = []
        for raw in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            s = raw.strip()
            if not s:
                continue
            line = ""
            w = 0.0
            for ch in s:
                cw = self._approx_char_w(ch, fs)
                if line and (w + cw) > max_w_px:
                    out_lines.append(line)
                    line = ch
                    w = cw
                else:
                    line += ch
                    w += cw
            if line:
                out_lines.append(line)
        return out_lines

    def _write_bg_ass(self, srt_path: str, out_ass_path: str, w: int, h: int, bg: str):
        items = self._parse_srt(srt_path)
        if not items:
            return False

        bg = str(bg or "none").lower()
        if bg == "yellow":
            box_color = "&H00FFFF&"
        elif bg in ["gray", "grey"]:
            box_color = "&H3C3C3C&"
        else:
            return False

        try:
            w_i = int(w) if int(w) > 0 else 1920
            h_i = int(h) if int(h) > 0 else 1080
        except Exception:
            w_i, h_i = 1920, 1080

        fs = max(18, int(round(h_i / 35.0)))
        pad_x = max(10, int(round(fs * 0.65)))
        pad_y = max(6, int(round(fs * 0.28)))
        line_h = max(fs + 6, int(round(fs * 1.15)))
        max_text_w = max(120, int(round(w_i * 0.9)))

        header = "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                "Collisions: Normal",
                f"PlayResX: {w_i}",
                f"PlayResY: {h_i}",
                "",
                "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
                "Style: Default,Arial,26,&H00FFFFFF,&H000000FF,&H80000000,&H00000000,1,0,0,0,100,100,0,0,1,2,0,2,20,20,20,1",
                "",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            ]
        )

        lines = [header]
        for (start, end, text) in items:
            s = self._ass_time(start)
            e = self._ass_time(end)
            wrapped = self._wrap_text(text, max_text_w - 2 * pad_x, fs)
            if not wrapped:
                continue
            text_w = 0.0
            for ln in wrapped:
                w_ln = sum(self._approx_char_w(ch, fs) for ch in ln)
                text_w = max(text_w, w_ln)
            text_w = min(float(max_text_w), text_w)
            text_h = float(len(wrapped) * line_h)
            box_w = int(round(text_w + 2 * pad_x))
            box_h = int(round(text_h + 2 * pad_y))

            margin_bottom = max(18, int(round(fs * 0.9)))
            box_bottom = h_i - margin_bottom
            box_top = max(0, box_bottom - box_h)
            box_left = max(0, int(round((w_i - box_w) / 2.0)))
            box_right = min(w_i, box_left + box_w)
            radius = 8
            path = self._ass_round_rect(box_left, box_top, box_right, box_bottom, radius)
            draw = f"{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c{box_color}\\1a&H00&}}{path}"

            text_x = w_i / 2.0
            text_y = (box_top + box_bottom) / 2.0
            text_esc = self._ass_escape("\\N".join(wrapped))
            lines.append(f"Dialogue: 0,{s},{e},Default,,0,0,0,,{draw}")
            lines.append(f"Dialogue: 1,{s},{e},Default,,0,0,0,,{{\\an5\\pos({text_x:.1f},{text_y:.1f})\\fs{fs}\\bord2\\shad0\\3c&H000000&\\1c&HFFFFFF&}}{text_esc}")

        try:
            with open(out_ass_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return True
        except Exception:
            return False

    def run(self):
        start_time = time.time()
        try:
            segments = self.params['segments']
            total_segments = len(segments)
            
            # Create temp dir
            temp_dir = os.path.join(os.path.dirname(self.output_path), "temp_export")
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
            self.temp_files.append(temp_dir)

            # --- Step 1: Prepare Audio (20%) ---
            self.progress_updated.emit(5, "正在处理音频...")
            
            has_mic = self.params['audio_mic'] and os.path.exists(self.params['audio_mic'])
            has_sys = self.params['audio_sys'] and os.path.exists(self.params['audio_sys'])
            
            temp_audio_full = os.path.join(temp_dir, "temp_full_audio.wav")
            
            ffmpeg_exe = get_ffmpeg_path()
            
            # Generate Full Mixed Audio First (if audio exists)
            audio_source_path = None
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            if has_mic or has_sys:
                cmd = [ffmpeg_exe, '-y']
                inputs = 0
                if has_mic:
                    cmd.extend(['-i', self.params['audio_mic']])
                    inputs += 1
                if has_sys:
                    cmd.extend(['-i', self.params['audio_sys']])
                    inputs += 1
                
                filter_complex = ""
                mic_vol = self.params['mic_vol']
                sys_vol = self.params['sys_vol']
                is_enhanced = self.params['is_enhanced']
                
                if inputs == 2:
                    # Mix logic
                    filter_complex += f"[0:a]volume={mic_vol}[mic];[1:a]volume={sys_vol}[sys];"
                    if is_enhanced:
                        # Add simple denoise/highpass for mic
                        # Note: This is simplified. 
                        # Ideally apply filter to [mic] before mix.
                        pass
                    filter_complex += "[mic][sys]amix=inputs=2:duration=longest[aout]"
                elif has_mic:
                     filter_complex += f"[0:a]volume={mic_vol}[aout]"
                elif has_sys:
                     filter_complex += f"[0:a]volume={sys_vol}[aout]"
                     
                cmd.extend(['-filter_complex', filter_complex, '-map', '[aout]', temp_audio_full])
                rc, _, err = self._run_cmd(cmd, startupinfo=startupinfo)
                if rc != 0:
                    raise Exception(f"音频处理失败: {(err or b'').decode('utf-8', errors='ignore')}")
                audio_source_path = temp_audio_full
                self.temp_files.append(temp_audio_full)
                self._ensure_file(temp_audio_full, 1024, "音频")
                if not self._validate_wav_file(temp_audio_full):
                    raise Exception(f"音频文件无效: {temp_audio_full}")
            else:
                # Check if video has audio? Usually we assume no if no external tracks for this app context.
                # But let's check if user wants to use video's audio?
                # For now, if no mic/sys, we assume silence or original video audio.
                pass

            audio_cut_scale = 1.0
            try:
                if audio_source_path and os.path.exists(audio_source_path):
                    import soundfile as sf
                    f = sf.SoundFile(audio_source_path)
                    audio_total_sec = float(len(f)) / float(f.samplerate or 1)
                    video_ref_ms = 0
                    try:
                        for seg in segments:
                            video_ref_ms = max(video_ref_ms, int(seg.get("source_end", 0) or 0))
                    except Exception:
                        video_ref_ms = 0
                    video_ref_sec = float(video_ref_ms) / 1000.0 if video_ref_ms > 0 else 0.0
                    if audio_total_sec > 0.2 and video_ref_sec > 0.2:
                        audio_cut_scale = float(audio_total_sec) / float(video_ref_sec)
                        if not (0.8 <= audio_cut_scale <= 1.25):
                            audio_cut_scale = 1.0
                        if abs(audio_cut_scale - 1.0) > 0.0005:
                            try:
                                logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
                                os.makedirs(logs_dir, exist_ok=True)
                                log_path = os.path.join(logs_dir, "export_audio_drift_scale.log")
                                with open(log_path, "a", encoding="utf-8") as lf:
                                    lf.write(
                                        f"audio_source={audio_source_path}\n"
                                        f"audio_total_sec={audio_total_sec:.3f}\n"
                                        f"video_ref_sec={video_ref_sec:.3f}\n"
                                        f"audio_cut_scale={audio_cut_scale:.9f}\n"
                                        "----\n"
                                    )
                            except Exception:
                                pass
            except Exception:
                audio_cut_scale = 1.0

            can_stream_copy = True
            if self.params['watermark_text'] or self.params['watermark_size'] > 0:
                can_stream_copy = False
            if self.params['background_image_path']:
                can_stream_copy = False
            if self.params['video_corner_radius'] > 0:
                can_stream_copy = False
            if self.params['target_w'] > 0:
                can_stream_copy = False
            if self.params['click_zoom'] > 1.001:
                can_stream_copy = False

            attempts = [can_stream_copy]
            if can_stream_copy:
                attempts.append(False)

            last_err = None
            for use_stream_copy in attempts:
                work_dir = os.path.join(temp_dir, "pass_copy" if use_stream_copy else "pass_reencode")
                if not os.path.exists(work_dir):
                    os.makedirs(work_dir)
                self.temp_files.append(work_dir)

                video_parts = []
                failed = False

                for i, seg in enumerate(segments):
                    if self.is_cancelled:
                        raise Exception("Export canceled")

                    seg_progress_base = 20 + (i / max(1, total_segments)) * 60
                    self.progress_updated.emit(int(seg_progress_base), f"正在处理视频片段 {i+1}/{total_segments}...")

                    temp_video_part = os.path.join(work_dir, f"part_{i}.mp4")
                    start_sec = seg['source_start'] / 1000.0
                    end_sec = seg['source_end'] / 1000.0

                    if use_stream_copy:
                        cmd_cut = [
                            ffmpeg_exe,
                            '-y',
                            '-ss', str(start_sec),
                            '-to', str(end_sec),
                            '-i', self.params['video_path'],
                            '-c', 'copy',
                            '-avoid_negative_ts', '1',
                            temp_video_part
                        ]
                        rc, _, err = self._run_cmd(cmd_cut, startupinfo=startupinfo)
                        if rc != 0:
                            last_err = (err or b'').decode('utf-8', errors='ignore')
                            failed = True
                            break
                    else:
                        vp = VideoProcessor(
                            input_path=self.params['video_path'],
                            metadata_path=self.params['metadata_path'],
                            output_path=temp_video_part,
                            base_zoom=self.params['base_zoom'],
                            click_zoom=self.params['click_zoom'],
                            fps=self.params['target_fps'],
                            start_time=start_sec,
                            end_time=end_sec,
                            click_duration=self.params['click_duration'],
                            watermark_text=self.params['watermark_text'],
                            watermark_pos=self.params['watermark_pos'],
                            watermark_pos_x=self.params.get('watermark_pos_x'),
                            watermark_pos_y=self.params.get('watermark_pos_y'),
                            watermark_size=self.params['watermark_size'],
                            watermark_use_image=bool(self.params.get('watermark_use_image')),
                            watermark_image_path=self.params.get('watermark_image_path'),
                            target_resolution=(self.params['target_w'], self.params['target_h']),
                            use_gpu=self.params['use_gpu'],
                            background_path=self.params['background_image_path'],
                            bg_padding_ratio=self.params['bg_padding'] / max(1, self.params['canvas_width']) if self.params['bg_padding'] > 0 else 0.0,
                            video_corner_radius_ratio=self.params['video_corner_radius'] / max(1, self.params['canvas_width']) if self.params['video_corner_radius'] > 0 else 0.0
                        )

                        def update_prog(p):
                            if self.is_cancelled:
                                return
                            current_prog = seg_progress_base + p * (60 / max(1, total_segments))
                            self.progress_updated.emit(int(current_prog), f"正在处理视频片段 {i+1}/{total_segments}...")

                        if not vp.process(progress_callback=update_prog):
                            if self.params.get('use_gpu'):
                                vp.use_gpu = False
                                if not vp.process(progress_callback=update_prog):
                                    last_err = f"Failed to process segment {i}"
                                    failed = True
                                    break
                            else:
                                last_err = f"Failed to process segment {i}"
                                failed = True
                                break

                    try:
                        self._ensure_file(temp_video_part, 50 * 1024, "视频片段")
                        if not self._validate_video_file(temp_video_part):
                            raise Exception(f"视频片段无效: {temp_video_part}")
                    except Exception as e:
                        last_err = str(e)
                        failed = True
                        break

                    video_parts.append(temp_video_part)
                    self.temp_files.append(temp_video_part)

                if failed:
                    if use_stream_copy and (False in attempts):
                        continue
                    raise Exception(last_err or "Export failed")

                self.progress_updated.emit(80, "正在合并视频...")
                list_file_path = os.path.join(work_dir, "list.txt")
                with open(list_file_path, "w", encoding="utf-8") as f:
                    for part in video_parts:
                        safe_path = part.replace("\\", "/").replace("'", "'\\''")
                        f.write(f"file '{safe_path}'\n")
                self.temp_files.append(list_file_path)

                merged_video = os.path.join(work_dir, "merged_video_only.mp4")
                cmd_concat = [ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', list_file_path, '-c', 'copy', merged_video]
                rc, _, err = self._run_cmd(cmd_concat, startupinfo=startupinfo)
                if rc != 0:
                    last_err = (err or b'').decode('utf-8', errors='ignore')
                    if use_stream_copy and (False in attempts):
                        continue
                    raise Exception(f"合并视频失败: {last_err}")
                self.temp_files.append(merged_video)
                try:
                    self._ensure_file(merged_video, 100 * 1024, "合并视频")
                    if not self._validate_video_file(merged_video):
                        raise Exception(f"合并视频无效: {merged_video}")
                except Exception as e:
                    last_err = str(e)
                    if use_stream_copy and (False in attempts):
                        continue
                    raise

                final_audio_path = None
                if audio_source_path:
                    self.progress_updated.emit(85, "正在裁剪并拼接音频...")
                    audio_parts = []
                    audio_list_path = os.path.join(work_dir, "audio_list.txt")
                    for i, seg in enumerate(segments):
                        if self.is_cancelled:
                            raise Exception("Export canceled")
                        start_sec = seg['source_start'] / 1000.0
                        end_sec = seg['source_end'] / 1000.0
                        if audio_cut_scale != 1.0:
                            start_sec = float(start_sec) * float(audio_cut_scale)
                            end_sec = float(end_sec) * float(audio_cut_scale)
                        dur_sec = max(0.0, end_sec - start_sec)
                        part_audio = os.path.join(work_dir, f"aud_{i}.wav")
                        cmd_aud_cut = [
                            ffmpeg_exe, '-y',
                            '-ss', str(start_sec), '-to', str(end_sec),
                            '-i', audio_source_path,
                            '-vn', '-ac', '1', '-ar', '44100', '-c:a', 'pcm_s16le',
                            part_audio
                        ]
                        rc, _, err = self._run_cmd(cmd_aud_cut, startupinfo=startupinfo)
                        if rc != 0 or (not os.path.exists(part_audio)) or os.path.getsize(part_audio) < 1024:
                            cmd_silence = [
                                ffmpeg_exe, '-y',
                                '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono',
                                '-t', str(dur_sec),
                                '-c:a', 'pcm_s16le',
                                part_audio
                            ]
                            rc2, _, err2 = self._run_cmd(cmd_silence, startupinfo=startupinfo)
                            if rc2 != 0:
                                raise Exception(f"音频切片失败: {(err or b'').decode('utf-8', errors='ignore')}\n{(err2 or b'').decode('utf-8', errors='ignore')}")
                        audio_parts.append(part_audio)
                        self.temp_files.append(part_audio)
                    with open(audio_list_path, "w", encoding="utf-8") as f:
                        for part in audio_parts:
                            safe_path = part.replace("\\", "/").replace("'", "'\\''")
                            f.write(f"file '{safe_path}'\n")
                    self.temp_files.append(audio_list_path)
                    merged_audio = os.path.join(work_dir, "merged_audio.wav")
                    cmd_aud_concat = [ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', audio_list_path, '-c', 'copy', merged_audio]
                    rc, _, err = self._run_cmd(cmd_aud_concat, startupinfo=startupinfo)
                    if rc != 0:
                        raise Exception(f"合并音频失败: {(err or b'').decode('utf-8', errors='ignore')}")
                    self.temp_files.append(merged_audio)
                    self._ensure_file(merged_audio, 1024, "合并音频")
                    if not self._validate_wav_file(merged_audio):
                        raise Exception(f"合并音频无效: {merged_audio}")
                    final_audio_path = merged_audio
                elif not use_stream_copy:
                    self.progress_updated.emit(85, "正在提取并裁剪原视频音频...")
                    extracted_audio = os.path.join(work_dir, "extracted_video_audio.wav")
                    cmd_extract = [
                        ffmpeg_exe, '-y',
                        '-i', self.params['video_path'],
                        '-vn', '-ac', '1', '-ar', '44100', '-c:a', 'pcm_s16le',
                        extracted_audio
                    ]
                    rc, _, err = self._run_cmd(cmd_extract, startupinfo=startupinfo)
                    if rc == 0 and os.path.exists(extracted_audio) and os.path.getsize(extracted_audio) > 0:
                        self.temp_files.append(extracted_audio)
                        audio_parts = []
                        audio_list_path = os.path.join(work_dir, "audio_list.txt")
                        for i, seg in enumerate(segments):
                            if self.is_cancelled:
                                raise Exception("Export canceled")
                            start_sec = seg['source_start'] / 1000.0
                            end_sec = seg['source_end'] / 1000.0
                            dur_sec = max(0.0, end_sec - start_sec)
                            part_audio = os.path.join(work_dir, f"aud_{i}.wav")
                            cmd_aud_cut = [
                                ffmpeg_exe, '-y',
                                '-ss', str(start_sec), '-to', str(end_sec),
                                '-i', extracted_audio,
                                '-vn', '-ac', '1', '-ar', '44100', '-c:a', 'pcm_s16le',
                                part_audio
                            ]
                            rc, _, err2 = self._run_cmd(cmd_aud_cut, startupinfo=startupinfo)
                            if rc != 0 or (not os.path.exists(part_audio)) or os.path.getsize(part_audio) < 1024:
                                cmd_silence = [
                                    ffmpeg_exe, '-y',
                                    '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono',
                                    '-t', str(dur_sec),
                                    '-c:a', 'pcm_s16le',
                                    part_audio
                                ]
                                rc3, _, err3 = self._run_cmd(cmd_silence, startupinfo=startupinfo)
                                if rc3 != 0:
                                    raise Exception(f"音频切片失败: {(err2 or b'').decode('utf-8', errors='ignore')}\n{(err3 or b'').decode('utf-8', errors='ignore')}")
                            audio_parts.append(part_audio)
                            self.temp_files.append(part_audio)
                        with open(audio_list_path, "w", encoding="utf-8") as f:
                            for part in audio_parts:
                                safe_path = part.replace("\\", "/").replace("'", "'\\''")
                                f.write(f"file '{safe_path}'\n")
                        self.temp_files.append(audio_list_path)
                        merged_audio = os.path.join(work_dir, "merged_audio.wav")
                        cmd_aud_concat = [ffmpeg_exe, '-y', '-f', 'concat', '-safe', '0', '-i', audio_list_path, '-c', 'copy', merged_audio]
                        rc, _, err4 = self._run_cmd(cmd_aud_concat, startupinfo=startupinfo)
                        if rc == 0 and os.path.exists(merged_audio) and os.path.getsize(merged_audio) > 0:
                            self.temp_files.append(merged_audio)
                            final_audio_path = merged_audio

                self.progress_updated.emit(90, "正在最终合成...")
                cmd_inputs = ['-i', merged_video]
                cmd_maps = ['-map', '0:v']
                cmd_output_opts = ['-c:v', 'copy']

                input_count = 1
                if final_audio_path:
                    cmd_inputs.extend(['-i', final_audio_path])
                    cmd_maps.extend(['-map', f'{input_count}:a'])
                    cmd_output_opts.extend(['-c:a', 'aac', '-b:a', '192k'])
                    input_count += 1
                else:
                    if use_stream_copy:
                        cmd_maps.extend(['-map', '0:a?'])
                        cmd_output_opts.extend(['-c:a', 'copy'])

                srt_path = self.params.get('subtitle_path')
                if srt_path and os.path.exists(srt_path):
                    bg = str(self.params.get('subtitle_bg', 'none') or 'none').lower()
                    sub_path = srt_path
                    if bg in ["yellow", "gray", "grey"]:
                        ass_path = os.path.join(work_dir, "burnin_subs.ass")
                        ok = self._write_bg_ass(srt_path, ass_path, int(self.params.get("target_w") or 0), int(self.params.get("target_h") or 0), bg)
                        if ok and os.path.exists(ass_path):
                            self.temp_files.append(ass_path)
                            sub_path = ass_path
                    sub_filter_path = sub_path.replace('\\', '/').replace(':', '\\:')
                    subtitle_vf = f"subtitles='{sub_filter_path}'"
                    cmd_output_opts.extend(['-vf', subtitle_vf])
                    print(f"[Export] Burn-in subtitles enabled: {sub_path}")
                    try:
                        v_idx = cmd_output_opts.index('-c:v')
                        cmd_output_opts[v_idx + 1] = 'libx264'
                    except Exception:
                        cmd_output_opts.extend(['-c:v', 'libx264'])
                    cmd_output_opts.extend(['-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p'])
                cmd_output_opts.extend(['-movflags', '+faststart'])
                total_out_ms = 0
                try:
                    for seg in segments:
                        total_out_ms += int(seg.get('source_end', 0)) - int(seg.get('source_start', 0))
                except Exception:
                    total_out_ms = 0
                progress_total = max(1, int(total_out_ms))
                final_cmd = [ffmpeg_exe, '-y', '-loglevel', 'info', '-progress', 'pipe:1', '-i', merged_video]
                if final_audio_path:
                    final_cmd.extend(['-i', final_audio_path])
                final_cmd.extend(cmd_output_opts)
                final_cmd.extend(cmd_maps)
                final_cmd.append(self.output_path)
                print(f"[Export] Final CMD: {' '.join(final_cmd)}")

                rc, _, err = self._run_cmd(final_cmd, startupinfo=startupinfo, progress_total_ms=progress_total, progress_range=(90, 99))
                if rc != 0:
                    last_err = (err or b'').decode('utf-8', errors='ignore')
                    if use_stream_copy and (False in attempts):
                        continue
                    raise Exception(f"最终合成失败: {last_err}")

                try:
                    self._ensure_file(self.output_path, 200 * 1024, "导出文件")
                    if not self._validate_video_file(self.output_path):
                        raise Exception(f"导出文件无效: {self.output_path}")
                except Exception as e:
                    last_err = str(e)
                    if use_stream_copy and (False in attempts):
                        continue
                    raise

                self.progress_updated.emit(100, "完成")
                self.cleanup()
                self.finished_success.emit(self.output_path)
                return

            raise Exception(last_err or "Export failed")

        except subprocess.CalledProcessError as e:
            self.cleanup()
            err_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            print(f"[Export Error] FFmpeg failed: {err_msg}")
            self.finished_error.emit(f"Export Error: {err_msg}")
        except Exception as e:
            self.cleanup()
            import traceback
            traceback.print_exc()
            self.finished_error.emit(str(e))

    def cleanup(self):
        try:
            for f in self.temp_files:
                if os.path.isfile(f):
                    os.remove(f)
                elif os.path.isdir(f):
                    try:
                        shutil.rmtree(f)
                    except:
                        pass
            # Try to remove temp dir itself
            try:
                temp_dir = os.path.join(os.path.dirname(self.output_path), "temp_export")
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            except:
                pass
        except:
            pass



class ExportDialog(QDialog):
    def __init__(self, parent=None, target_ratio=None, source_size=None):
        super().__init__(parent)
        self.setWindowTitle("导出设置")
        self.resize(400, 250)
        self.license_manager = LicenseManager()
        
        # Debug Log
        try:
            logger = logging.getLogger('VideoEditor')
            logger.info(f"ExportDialog Init: Ratio={target_ratio}, Size={source_size}")
        except: pass
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("选择导出格式:"))
        
        self.combo_quality = QComboBox()
        
        # Determine base orientation and ratio
        if target_ratio:
            ratio = target_ratio
        else:
            # Default to source ratio
            if source_size and source_size[1] > 0:
                ratio = source_size[0] / source_size[1]
            else:
                ratio = 16/9
        
        self.options = []
        
        # Define base heights (for horizontal) or widths (for vertical)
        # 1080p, 2K (1440p), 4K (2160p)
        bases = [
            ("1080p", 1080, "免费版"),
            ("2k", 1440, "Pro版"),
            ("4k", 2160, "Pro版")
        ]
        
        for key, base_dim, feature_label in bases:
            if ratio >= 1:
                # Horizontal: base_dim is height
                h = base_dim
                w = int(h * ratio)
                # Ensure even numbers for encoding compatibility
                if w % 2 != 0: w += 1
                if h % 2 != 0: h += 1
                label = f"{key.upper()} ({w}x{h}) @ 30 FPS - {feature_label}"
            else:
                # Vertical: base_dim is width
                w = base_dim
                h = int(w / ratio)
                if w % 2 != 0: w += 1
                if h % 2 != 0: h += 1
                label = f"{key.upper()} ({w}x{h}) @ 30 FPS - {feature_label}"
                
            fps = 60 if key == "4k" else 30
            
            self.options.append((key, w, h, fps))
            self.combo_quality.addItem(label, (w, h, fps))
            
            # Visual cue for pro features
            is_pro_feature = key in ["2k", "4k"]
            if is_pro_feature and not self.license_manager.is_pro:
                self.combo_quality.setItemIcon(self.combo_quality.count()-1, self.style().standardIcon(QStyle.SP_MessageBoxWarning))

        # Auto-select best match based on source size
        if source_size and source_size[0] > 0 and source_size[1] > 0:
            s_w, s_h = source_size
            # Use the smaller dimension to match against base_dim (1080, 1440, 2160)
            if ratio >= 1:
                s_dim = s_h
            else:
                s_dim = s_w
            
            best_idx = 0
            min_diff = float('inf')
            
            for i, (_, base_dim, _) in enumerate(bases):
                diff = abs(s_dim - base_dim)
                if diff < min_diff:
                    min_diff = diff
                    best_idx = i
            
            # Downgrade default selection for Free users
            if not self.license_manager.is_pro:
                key = self.options[best_idx][0]
                if key in ["2k", "4k"]:
                    # Fallback to 1080p
                    for i, (k, _, _, _) in enumerate(self.options):
                        if k == "1080p":
                            best_idx = i
                            break
            
            # Block signals to prevent triggering the popup during init
            self.combo_quality.blockSignals(True)
            self.combo_quality.setCurrentIndex(best_idx)
            self.combo_quality.blockSignals(False)

        self.combo_quality.currentIndexChanged.connect(self.on_quality_changed)
        layout.addWidget(self.combo_quality)
        
        # Info label
        self.lbl_info = QLabel("提示: 免费版仅支持 1080p 导出。")
        self.lbl_info.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
        layout.addWidget(self.lbl_info)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_export = QPushButton("开始导出")
        self.btn_export.clicked.connect(self.check_and_accept)
        # Style the export button
        self.btn_export.setStyleSheet("background-color: #007aff; color: white; font-weight: bold;")
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_export)
        
        layout.addLayout(btn_layout)

    def on_quality_changed(self, index):
        key = self.options[index][0]
        
        if key in ["2k", "4k"] and not self.license_manager.is_pro:
             QMessageBox.information(self, "Pro 版功能", 
                "您选择的导出格式仅限 Pro 版用户使用。\n\n"
                "免费版最高支持 1080p @ 30fps。\n"
                "请购买 Pro 版以解锁 2K/4K 和 60FPS 导出。")
             
             # Reset to 1080p
             for i, (k, _, _, _) in enumerate(self.options):
                if k == "1080p":
                    self.combo_quality.blockSignals(True)
                    self.combo_quality.setCurrentIndex(i)
                    self.combo_quality.blockSignals(False)
                    break
        
    def check_and_accept(self):
        w, h, fps = self.combo_quality.currentData()
        idx = self.combo_quality.currentIndex()
        key = self.options[idx][0]
        
        if key in ["2k", "4k"] and not self.license_manager.is_pro:
             # Double check, though on_quality_changed should have handled it
             QMessageBox.warning(self, "Pro 版功能", 
                "您选择的导出格式仅限 Pro 版用户使用。\n\n"
                "免费版最高支持 1080p @ 30fps。\n"
                "请购买 Pro 版以解锁 2K/4K 和 60FPS 导出。")
             return

        self.accept()

    def get_settings(self):
        return self.combo_quality.currentData()

class VideoEditor(QWidget):
    _open_editors = []

    def __init__(self, video_path, audio_mic, audio_sys, metadata_path, default_output_path=None):
        super().__init__()
        self.setWindowTitle("视频编辑器 - LuScreen")
        self.resize(1200, 800)
        # Dark Theme Styling
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #e0e0e0;
                font-family: 'Segoe UI', sans-serif;
                font-size: 10pt;
            }
            QFrame {
                border: none;
            }
            QPushButton {
                background-color: #333333;
                border-radius: 6px;
                padding: 6px 12px;
                border: 1px solid #444;
            }
            QPushButton:hover {
                background-color: #444444;
            }
            QPushButton:pressed {
                background-color: #222222;
            }
            QPushButton#ExportBtn {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                border: none;
            }
            QPushButton#ExportBtn:hover {
                background-color: #45a049;
            }
            QSlider::groove:horizontal {
                border: 1px solid #333;
                height: 6px;
                background: #2a2a2a;
                margin: 2px 0;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #2196F3;
                border: 1px solid #2196F3;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QGroupBox {
                border: 1px solid #333;
                border-radius: 6px;
                margin-top: 12px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
            QLabel#TimeLabel {
                font-family: 'Consolas', monospace;
                font-weight: bold;
            }
        """)
        
        self.video_path = video_path
        self.audio_mic = audio_mic
        self.audio_sys = audio_sys
        self.metadata_path = metadata_path
        self.default_output_path = default_output_path
        self.config_manager = ConfigManager()
        self.license_manager = LicenseManager()
        self.logger = logging.getLogger('VideoEditor')
        
        self.duration = 0
        self.start_trim = 0
        self.end_trim = 0
        
        # Default Settings
        self.base_zoom = 1.0
        self.click_zoom = 1.5
        self.click_duration = 2.0
        
        self.watermark_text = ""
        self.watermark_pos = "bottom-right"
        self.watermark_pos_x = None
        self.watermark_pos_y = None
        self.watermark_size = 1.0
        self.watermark_use_image = False
        self.watermark_image_path = None
        
        self.background_image_path = None
        self.bg_padding = 0
        self.video_corner_radius = 8
        
        self.preview_path = None
        
        self.target_ratio = None # None means Original
        self.target_ratio_name = "原始"
        
        # Detect video dimensions
        self.video_width = 0
        self.video_height = 0
        try:
            cap = cv2.VideoCapture(self.video_path)
            if cap.isOpened():
                self.video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                self.video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
        except Exception as e:
            print(f"Failed to detect video size: {e}")
            
        # Subtitle System
        self.subtitle_manager = SubtitleManager()
        self.subtitle_worker = None
        self.srt_path = None
        self.srt_source_path = None
        self.subtitle_bg = str(self.config_manager.get("subtitle_bg", "none") or "none")
        self.subtitle_segments_source_raw = []
        self.subtitle_segments_source = []
        self.subtitle_line_shift_ms = {}
        self._subtitle_user_select_lock_until = 0.0
        
        self.init_ui()
        QTimer.singleShot(100, self.check_and_generate_preview)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 1. Top Bar ---
        top_bar = QFrame()
        top_bar.setFixedHeight(60)
        top_bar.setStyleSheet("background-color: #252526; border-bottom: 1px solid #333;")
        top_layout = QHBoxLayout(top_bar)
        
        self.btn_open_video = QPushButton("打开文件夹")
        self.btn_open_video.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.btn_open_video.setToolTip("选择本地视频并打开编辑器")
        self.btn_open_video.clicked.connect(self.open_video_from_disk)
        self.btn_open_video.setFixedHeight(34)

        self.lbl_title = QLabel(os.path.basename(self.video_path))
        self.lbl_title.setStyleSheet("font-weight: bold; color: #ccc;")
        
        self.btn_subtitle = QPushButton("生成字幕")
        self.btn_subtitle.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.btn_subtitle.clicked.connect(self.open_subtitle_dialog)
        
        self.btn_export = QPushButton("导出视频")
        self.btn_export.setObjectName("ExportBtn")
        self.btn_export.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.btn_export.clicked.connect(self.export_video)
        
        top_layout.addWidget(self.btn_open_video)
        top_layout.addSpacing(8)
        top_layout.addWidget(self.lbl_title)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_subtitle)
        top_layout.addWidget(self.btn_export)
        
        main_layout.addWidget(top_bar)
        
        # --- 2. Middle Area (Split View) ---
        middle_splitter = QSplitter(Qt.Horizontal)
        middle_splitter.setHandleWidth(0)
        
        # 2.1 Left: Preview Area
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(20, 20, 20, 10)
        
        # Video Widget
        self.video_frame = QFrame()
        self.video_frame.setStyleSheet("background-color: #333; background-position: center; background-repeat: no-repeat;")
        self.video_layout = QVBoxLayout(self.video_frame)
        self.video_layout.setContentsMargins(0, 0, 0, 0)
        self.video_layout.setAlignment(Qt.AlignCenter) 
        
        # Canvas Frame (Handles Ratio & Background Image)
        self.canvas_frame = QFrame()
        self.canvas_frame.setStyleSheet("background-color: #000;") # Default black canvas
        self.canvas_layout = QVBoxLayout(self.canvas_frame)
        self.canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas_layout.setAlignment(Qt.AlignCenter)
        
        # Container for video to support masking/rounding
        self.video_container = QFrame()
        self.video_container.setStyleSheet("background: transparent;")
        self.video_container_layout = QVBoxLayout(self.video_container)
        self.video_container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Using custom VideoRenderWidget instead of QVideoWidget for stable rounding
        self.video_widget = VideoRenderWidget()
        self.video_widget.set_subtitle_background(self._subtitle_bg_qcolor())
        try:
            self.video_widget.watermark_moved.connect(self._on_watermark_moved)
            self.video_widget.watermark_scale_changed.connect(self._on_watermark_scale_changed)
        except Exception:
            pass
        self.video_container_layout.addWidget(self.video_widget)
        
        self.canvas_layout.addWidget(self.video_container)
        
        self.video_layout.addWidget(self.canvas_frame)
        
        self.video_frame.installEventFilter(self) # Install filter to handle resize
        
        # Player Controls (Below Video)
        controls_layout = QHBoxLayout()
        
        self.lbl_current = QLabel("00:00")
        self.lbl_current.setObjectName("TimeLabel")
        self.lbl_total = QLabel("/ 00:00")
        self.lbl_total.setObjectName("TimeLabel")
        self.lbl_total.setStyleSheet("color: #888;")
        
        self.btn_play = QPushButton()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_play.setFixedSize(40, 40)
        self.btn_play.setStyleSheet("border-radius: 20px;")
        self.btn_play.clicked.connect(self.toggle_play)
        
        # Ratio Button
        self.btn_ratio = QPushButton("比例")
        self.btn_ratio.setFixedSize(100, 40)
        self.btn_ratio.setStyleSheet("border-radius: 6px;")
        
        self.ratio_menu = QMenu(self)
        
        # Adapt
        a_adapt = self.ratio_menu.addAction("适应 (原始)")
        a_adapt.triggered.connect(lambda: self.set_ratio(None, "原始"))
        
        self.ratio_menu.addSeparator()
        
        # Horizontal
        self.ratio_menu.addAction("16:9 (横屏)", lambda: self.set_ratio(16/9, "16:9"))
        self.ratio_menu.addAction("4:3 (横屏)", lambda: self.set_ratio(4/3, "4:3"))
        self.ratio_menu.addAction("3:2 (横屏)", lambda: self.set_ratio(3/2, "3:2"))
        
        self.ratio_menu.addSeparator()
        
        # Vertical
        self.ratio_menu.addAction("9:16 (竖屏)", lambda: self.set_ratio(9/16, "9:16"))
        self.ratio_menu.addAction("3:4 (竖屏)", lambda: self.set_ratio(3/4, "3:4"))
        self.ratio_menu.addAction("2:3 (竖屏)", lambda: self.set_ratio(2/3, "2:3"))
        
        self.btn_ratio.setMenu(self.ratio_menu)

        controls_layout.addWidget(self.lbl_current)
        controls_layout.addWidget(self.lbl_total)
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_play)
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_ratio)
        
        preview_layout.addWidget(self.video_frame, stretch=1)
        preview_layout.addLayout(controls_layout)
        
        # 2.2 Right: Properties Panel
        self.properties_panel = QWidget()
        self.properties_panel.setFixedWidth(400)
        self.properties_panel.setMinimumWidth(400)
        self.properties_panel.setMaximumWidth(400)
        self.properties_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.properties_panel.setLayoutDirection(Qt.LeftToRight)
        self.properties_panel.setStyleSheet("background-color: #252526; border-left: 1px solid #333; border-right: 1px solid #333;")
        
        prop_main_layout = QHBoxLayout(self.properties_panel)
        prop_main_layout.setContentsMargins(0, 0, 0, 0)
        prop_main_layout.setSpacing(0)
        
        # 1. Content Stack
        self.prop_stack = QStackedWidget()
        
        # 2. Navigation Sidebar
        self.nav_container = QWidget()
        self.nav_container.setFixedWidth(80)
        self.nav_container.setMinimumWidth(80)
        self.nav_container.setMaximumWidth(80)
        self.nav_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.nav_container.setLayoutDirection(Qt.LeftToRight)
        self.nav_container.setStyleSheet("background-color: #1e1e1e; border-left: 1px solid #333;")
        nav_layout = QVBoxLayout(self.nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)
        
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_group.idClicked.connect(self.prop_stack.setCurrentIndex)
        
        def create_nav_btn(text, icon_std, index):
            btn = QToolButton()
            btn.setText(text)
            btn.setIcon(self.style().standardIcon(icon_std))
            btn.setIconSize(QSize(28, 28))
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setCheckable(True)
            btn.setFixedSize(80, 75)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setStyleSheet("""
                QToolButton {
                    border: none;
                    background: transparent;
                    color: #888;
                    font-size: 12px;
                    padding: 5px;
                }
                QToolButton:checked {
                    background-color: #252526;
                    color: #007aff;
                    border-left: 3px solid #007aff;
                }
                QToolButton:hover {
                    background-color: #2a2a2a;
                }
            """)
            self.nav_group.addButton(btn, index)
            nav_layout.addWidget(btn)
            if index == 0: btn.setChecked(True)
            return btn

        create_nav_btn("属性", QStyle.SP_ComputerIcon, 0)
        create_nav_btn("缩放", QStyle.SP_FileDialogDetailedView, 1)
        create_nav_btn("美化", QStyle.SP_DesktopIcon, 2)
        create_nav_btn("字幕", QStyle.SP_DialogApplyButton, 3)
        
        nav_layout.addStretch()
        
        # Tab 1: Properties (Audio + Watermark)
        tab_props = QWidget()
        layout_props = QVBoxLayout(tab_props)
        layout_props.setContentsMargins(15, 15, 15, 15)
        
        # Audio Settings
        audio_group = QGroupBox("音频设置")
        audio_layout = QVBoxLayout()
        
        has_audio_controls = False
        
        # Mic Volume
        if self.audio_mic:
            audio_layout.addWidget(QLabel("麦克风音量:"))
            self.spin_mic_vol = QDoubleSpinBox()
            self.spin_mic_vol.setRange(0.0, 3.0)
            self.spin_mic_vol.setSingleStep(0.1)
            self.spin_mic_vol.setValue(1.0) # Default 1.0x (Base boost 5.0x is already applied)
            audio_layout.addWidget(self.spin_mic_vol)
            
            # Vocal Enhancement Checkbox
            self.chk_enhance = QCheckBox("启用人声美化 (降噪+增益)")
            self.chk_enhance.setChecked(False) # Default Off to respect "Original Sound" request
            self.chk_enhance.setToolTip("开启后将自动去除背景噪音并优化人声音量。关闭则使用原始录音。")
            self.chk_enhance.stateChanged.connect(lambda: self.check_and_generate_preview(force=True)) # Auto-refresh preview
            audio_layout.addWidget(self.chk_enhance)
            
            has_audio_controls = True

        # Sys Volume
        if self.audio_sys:
            audio_layout.addWidget(QLabel("系统音量:"))
            self.spin_sys_vol = QDoubleSpinBox()
            self.spin_sys_vol.setRange(0.0, 3.0)
            self.spin_sys_vol.setSingleStep(0.1)
            self.spin_sys_vol.setValue(1.0)
            audio_layout.addWidget(self.spin_sys_vol)
            has_audio_controls = True
            
        if has_audio_controls:
            self.btn_refresh_audio = QPushButton("更新音频预览")
            self.btn_refresh_audio.clicked.connect(lambda: self.check_and_generate_preview(force=True))
            audio_layout.addWidget(self.btn_refresh_audio)
            audio_group.setLayout(audio_layout)
            layout_props.addWidget(audio_group)
        
        # Watermark Settings
        watermark_group = QGroupBox("水印设置")
        watermark_layout = QVBoxLayout()
        
        watermark_layout.addWidget(QLabel("文字内容:"))
        self.edit_watermark = QLineEdit()
        self.edit_watermark.setPlaceholderText("输入水印文字...")
        self.edit_watermark.textChanged.connect(self.update_settings)
        watermark_layout.addWidget(self.edit_watermark)
        
        watermark_layout.addWidget(QLabel("位置:"))
        self.combo_watermark_pos = QComboBox()
        self.combo_watermark_pos.addItems(["左上角", "右上角", "左下角", "右下角", "自定义"])
        self.combo_watermark_pos.setCurrentIndex(0) # Default Top-Left
        self.combo_watermark_pos.currentIndexChanged.connect(self.update_settings)
        watermark_layout.addWidget(self.combo_watermark_pos)
        
        watermark_layout.addWidget(QLabel("大小:"))
        self.spin_watermark_size = QDoubleSpinBox()
        self.spin_watermark_size.setRange(0.5, 5.0)
        self.spin_watermark_size.setSingleStep(0.1)
        self.spin_watermark_size.setValue(1.0)
        self.spin_watermark_size.valueChanged.connect(self.update_settings)
        watermark_layout.addWidget(self.spin_watermark_size)

        wm_pro_row = QHBoxLayout()
        self.chk_use_image_watermark = QCheckBox("使用图片水印")
        self.chk_use_image_watermark.stateChanged.connect(self.update_settings)
        wm_pro_row.addWidget(self.chk_use_image_watermark)
        self.lbl_wm_pro = QLabel("Pro")
        self.lbl_wm_pro.setStyleSheet("color: #fff; background: #d35400; border-radius: 4px; padding: 1px 6px; font-weight: bold;")
        wm_pro_row.addWidget(self.lbl_wm_pro)
        wm_pro_row.addStretch()
        watermark_layout.addLayout(wm_pro_row)

        wm_img_row = QHBoxLayout()
        self.btn_select_wm_image = QPushButton("选择图片…")
        self.btn_select_wm_image.clicked.connect(self.select_watermark_image)
        wm_img_row.addWidget(self.btn_select_wm_image)
        self.btn_clear_wm_image = QPushButton("清除")
        self.btn_clear_wm_image.clicked.connect(self.clear_watermark_image)
        wm_img_row.addWidget(self.btn_clear_wm_image)
        watermark_layout.addLayout(wm_img_row)

        self.lbl_wm_image_path = QLabel("未选择图片")
        self.lbl_wm_image_path.setWordWrap(True)
        self.lbl_wm_image_path.setStyleSheet("color: #aaa;")
        watermark_layout.addWidget(self.lbl_wm_image_path)

        self.chk_use_image_watermark.setToolTip("Pro 用户可使用图片水印")
        self.btn_select_wm_image.setToolTip("Pro 用户可使用图片水印")
        self.btn_clear_wm_image.setToolTip("Pro 用户可使用图片水印")
        self.btn_select_wm_image.setEnabled(False)
        self.btn_clear_wm_image.setEnabled(False)
        
        watermark_group.setLayout(watermark_layout)
        layout_props.addWidget(watermark_group)
        
        layout_props.addStretch()
        
        # Tab 2: Smart Zoom
        tab_zoom = QWidget()
        layout_zoom = QVBoxLayout(tab_zoom)
        layout_zoom.setContentsMargins(15, 15, 15, 15)
        
        # Smart Zoom Settings
        zoom_group = QGroupBox("智能缩放")
        zoom_layout = QVBoxLayout()
        
        # Base Zoom
        zoom_layout.addWidget(QLabel("基础缩放倍数:"))
        self.spin_base_zoom = QDoubleSpinBox()
        self.spin_base_zoom.setRange(1.0, 3.0)
        self.spin_base_zoom.setSingleStep(0.1)
        self.spin_base_zoom.setValue(1.0)
        self.spin_base_zoom.valueChanged.connect(self.update_settings)
        zoom_layout.addWidget(self.spin_base_zoom)
        
        # Click Zoom
        zoom_layout.addWidget(QLabel("点击缩放倍数:"))
        self.spin_click_zoom = QDoubleSpinBox()
        self.spin_click_zoom.setRange(1.0, 5.0)
        self.spin_click_zoom.setSingleStep(0.1)
        self.spin_click_zoom.setValue(1.5)
        self.spin_click_zoom.valueChanged.connect(self.update_settings)
        zoom_layout.addWidget(self.spin_click_zoom)
        
        # Zoom Duration
        zoom_layout.addWidget(QLabel("缩放时长(秒):"))
        self.spin_zoom_duration = QDoubleSpinBox()
        self.spin_zoom_duration.setRange(0.5, 5.0)
        self.spin_zoom_duration.setSingleStep(0.5)
        self.spin_zoom_duration.setValue(3.0)
        self.spin_zoom_duration.valueChanged.connect(self.update_settings)
        zoom_layout.addWidget(self.spin_zoom_duration)
        
        zoom_group.setLayout(zoom_layout)
        layout_zoom.addWidget(zoom_group)
        layout_zoom.addStretch()
        
        self.prop_stack.addWidget(tab_props)
        self.prop_stack.addWidget(tab_zoom)

        # Tab 3: Video Beautification (Background + Padding)
        tab_style = QWidget()
        layout_style = QVBoxLayout(tab_style)
        layout_style.setContentsMargins(5, 15, 5, 15) # Reduced side margins
        
        # 1. Background Image Group
        bg_group = QGroupBox("背景图设置")
        bg_layout = QVBoxLayout()
        bg_layout.setContentsMargins(5, 10, 5, 5)
        
        # Enable Checkbox
        self.chk_enable_bg = QCheckBox("启用背景图片")
        self.chk_enable_bg.setChecked(False) # Default off
        self.chk_enable_bg.stateChanged.connect(self.on_bg_enable_changed)
        bg_layout.addWidget(self.chk_enable_bg)

        # Header with Label and Refresh Button
        header_bg_layout = QHBoxLayout()
        self.lbl_bg_hint = QLabel("选择背景图片:")
        header_bg_layout.addWidget(self.lbl_bg_hint)
        header_bg_layout.addStretch()
        
        self.btn_refresh_bg = QPushButton()
        self.btn_refresh_bg.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.btn_refresh_bg.setToolTip("刷新背景图片列表")
        self.btn_refresh_bg.setFixedSize(30, 30)
        self.btn_refresh_bg.clicked.connect(self.load_background_images)
        header_bg_layout.addWidget(self.btn_refresh_bg)
        
        self.btn_import_bg = QPushButton()
        self.btn_import_bg.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.btn_import_bg.setToolTip("导入背景图片")
        self.btn_import_bg.setFixedSize(30, 30)
        self.btn_import_bg.clicked.connect(self.import_background_image)
        header_bg_layout.addWidget(self.btn_import_bg)
        
        bg_layout.addLayout(header_bg_layout)
        
        self.list_bg = QListWidget()
        self.list_bg.setViewMode(QListWidget.IconMode)
        self.list_bg.setIconSize(QSize(75, 42)) # Optimized for 3 per row (16:9 ratio)
        self.list_bg.setSpacing(4)
        self.list_bg.setResizeMode(QListWidget.Adjust)
        self.list_bg.setMovement(QListWidget.Static) # Prevent dragging
        self.list_bg.itemClicked.connect(self.on_bg_selected)
        
        bg_layout.addWidget(self.list_bg)
        bg_group.setLayout(bg_layout)
        layout_style.addWidget(bg_group)

        # 2. Padding Group
        padding_group = QGroupBox("画面调整")
        padding_layout = QVBoxLayout()
        
        padding_top_layout = QHBoxLayout()
        padding_top_layout.addWidget(QLabel("内边距:"))
        
        self.spin_padding = QSpinBox()
        self.spin_padding.setRange(0, 50)
        self.spin_padding.setSingleStep(10)
        self.spin_padding.setSuffix(" px")
        self.spin_padding.setFixedWidth(80)
        padding_top_layout.addWidget(self.spin_padding)
        padding_top_layout.addStretch()
        
        padding_layout.addLayout(padding_top_layout)
        
        self.slider_padding = QSlider(Qt.Horizontal)
        self.slider_padding.setRange(0, 5) # 6 steps: 0, 1, 2, 3, 4, 5 -> *10 -> 0, 10, 20, 30, 40, 50
        self.slider_padding.setValue(0)
        
        # Sync controls
        # When slider changes (0-5), update spinbox (0-50) and logic
        self.slider_padding.valueChanged.connect(self.update_padding)
        
        # When spinbox changes, update slider
        self.spin_padding.valueChanged.connect(lambda v: self.slider_padding.setValue(int(round(v / 10))))
        
        padding_layout.addWidget(self.slider_padding)
        
        # 3. Corner Radius
        radius_top_layout = QHBoxLayout()
        radius_top_layout.addWidget(QLabel("圆角半径:"))
        
        self.spin_radius = QSpinBox()
        self.spin_radius.setRange(0, 100)
        self.spin_radius.setSingleStep(4)
        self.spin_radius.setSuffix(" px")
        self.spin_radius.setFixedWidth(80)
        self.spin_radius.setValue(self.video_corner_radius)
        radius_top_layout.addWidget(self.spin_radius)
        radius_top_layout.addStretch()
        
        padding_layout.addLayout(radius_top_layout)
        
        self.slider_radius = QSlider(Qt.Horizontal)
        self.slider_radius.setRange(0, 25) # 25 steps: 0, 1, 2... 25 -> *4 -> 0...100
        self.slider_radius.setValue(self.video_corner_radius // 4)
        
        # Sync controls
        self.slider_radius.valueChanged.connect(self.update_corner_radius)
        self.spin_radius.valueChanged.connect(lambda v: self.slider_radius.setValue(v // 4))
        
        padding_layout.addWidget(self.slider_radius)
        
        padding_group.setLayout(padding_layout)
        layout_style.addWidget(padding_group)
        
        # Load background images
        self.load_background_images()
        
        self.prop_stack.addWidget(tab_style)

        # Tab 4: Subtitle List
        tab_subs = QWidget()
        layout_subs = QVBoxLayout(tab_subs)
        layout_subs.setContentsMargins(0, 0, 0, 0)

        toolbar_container = QWidget()
        toolbar_layout = QVBoxLayout(toolbar_container)
        toolbar_layout.setContentsMargins(8, 8, 8, 4)
        toolbar_layout.setSpacing(6)

        subs_toolbar_buttons = QHBoxLayout()
        subs_toolbar_buttons.setSpacing(6)
        self.btn_sub_edit = QPushButton("编辑字幕")
        self.btn_sub_edit.clicked.connect(self.edit_selected_subtitle)
        self.btn_sub_edit.setEnabled(False)
        self.btn_sub_save = QPushButton("保存字幕")
        self.btn_sub_save.clicked.connect(self.save_subtitles_to_file)
        self.btn_sub_save.setEnabled(False)
        self.btn_sub_delete = QPushButton("删除字幕")
        self.btn_sub_delete.clicked.connect(self.delete_selected_subtitle)
        self.btn_sub_delete.setEnabled(False)
        self.btn_sub_shift_left = QPushButton("前移")
        self.btn_sub_shift_left.clicked.connect(lambda: self.shift_selected_subtitle(-int(self.spin_sub_line_shift_step.value())))
        self.btn_sub_shift_left.setEnabled(False)
        self.btn_sub_shift_right = QPushButton("后移")
        self.btn_sub_shift_right.clicked.connect(lambda: self.shift_selected_subtitle(int(self.spin_sub_line_shift_step.value())))
        self.btn_sub_shift_right.setEnabled(False)
        self.btn_sub_shift_reset = QPushButton("重置偏移")
        self.btn_sub_shift_reset.clicked.connect(self.reset_selected_subtitle_shift)
        self.btn_sub_shift_reset.setEnabled(False)

        for b in [self.btn_sub_edit, self.btn_sub_save, self.btn_sub_delete, self.btn_sub_shift_left, self.btn_sub_shift_right, self.btn_sub_shift_reset]:
            b.setMinimumWidth(86)
            b.setFixedHeight(32)
            b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        subs_toolbar_buttons.addWidget(self.btn_sub_edit)
        subs_toolbar_buttons.addWidget(self.btn_sub_save)
        subs_toolbar_buttons.addWidget(self.btn_sub_delete)
        subs_toolbar_buttons.addWidget(self.btn_sub_shift_left)
        subs_toolbar_buttons.addWidget(self.btn_sub_shift_right)
        subs_toolbar_buttons.addWidget(self.btn_sub_shift_reset)
        subs_toolbar_buttons.addStretch()

        subs_toolbar_offsets = QHBoxLayout()
        subs_toolbar_offsets.setSpacing(6)
        self.lbl_sub_line_shift = QLabel("单行步长(ms)")
        self.spin_sub_line_shift_step = QSpinBox()
        self.spin_sub_line_shift_step.setRange(10, 10000)
        self.spin_sub_line_shift_step.setSingleStep(10)
        self.spin_sub_line_shift_step.setValue(200)
        self.spin_sub_line_shift_step.setFixedHeight(30)
        subs_toolbar_offsets.addWidget(self.lbl_sub_line_shift)
        subs_toolbar_offsets.addWidget(self.spin_sub_line_shift_step)
        subs_toolbar_offsets.addSpacing(8)
        self.lbl_sub_bg = QLabel("背景")
        self.combo_sub_bg = QComboBox()
        self.combo_sub_bg.addItems(["无", "黄色", "灰色"])
        cur_bg = str(getattr(self, "subtitle_bg", "none") or "none").lower()
        if cur_bg == "yellow":
            self.combo_sub_bg.setCurrentText("黄色")
        elif cur_bg in ["gray", "grey"]:
            self.combo_sub_bg.setCurrentText("灰色")
        else:
            self.combo_sub_bg.setCurrentText("无")
        self.combo_sub_bg.currentTextChanged.connect(self.on_subtitle_bg_changed)
        self.combo_sub_bg.setFixedHeight(30)
        subs_toolbar_offsets.addWidget(self.lbl_sub_bg)
        subs_toolbar_offsets.addWidget(self.combo_sub_bg)
        subs_toolbar_offsets.addStretch()

        toolbar_layout.addLayout(subs_toolbar_buttons)
        toolbar_layout.addLayout(subs_toolbar_offsets)
        layout_subs.addWidget(toolbar_container)
        
        self.list_subtitles = QListWidget()
        self.list_subtitles.setAlternatingRowColors(True)
        self.list_subtitles.setStyleSheet("""
            QListWidget {
                background-color: #252526;
                border: none;
                color: #ccc;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #333;
            }
            QListWidget::item:selected {
                background-color: #007aff;
                color: white;
            }
        """)
        self.list_subtitles.itemClicked.connect(self.on_subtitle_item_clicked)
        self.list_subtitles.itemDoubleClicked.connect(self.edit_subtitle_item)
        self.list_subtitles.itemSelectionChanged.connect(self.on_subtitle_selection_changed)
        layout_subs.addWidget(self.list_subtitles)
        
        self.prop_stack.addWidget(tab_subs)
        
        self.prop_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        prop_main_layout.addWidget(self.prop_stack, 1)
        
        middle_splitter.addWidget(preview_container)
        middle_splitter.addWidget(self.properties_panel)
        middle_splitter.addWidget(self.nav_container)
        middle_splitter.setStretchFactor(0, 1)
        middle_splitter.setStretchFactor(1, 0)
        middle_splitter.setStretchFactor(2, 0)
        middle_splitter.setCollapsible(1, False)
        middle_splitter.setCollapsible(2, False)
        try:
            middle_splitter.setSizes([10000, 400, 80])
        except Exception:
            pass
        
        main_layout.addWidget(middle_splitter, stretch=1)

        # --- 3. Bottom: Timeline Area ---
        timeline_panel = QFrame()
        timeline_panel.setFixedHeight(160)
        timeline_panel.setStyleSheet("background-color: #1e1e1e; border-top: 1px solid #333;")
        timeline_layout = QVBoxLayout(timeline_panel)
        
        # Tools
        tools_layout = QHBoxLayout()
        
        self.btn_undo = QPushButton(" 撤销")
        self.btn_undo.setIcon(self.style().standardIcon(QStyle.SP_ArrowBack))
        self.btn_undo.setToolTip("撤销上一步操作 (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo_action)
        self.btn_undo.setShortcut("Ctrl+Z")

        self.btn_redo = QPushButton(" 重做")
        self.btn_redo.setIcon(self.style().standardIcon(QStyle.SP_ArrowForward))
        self.btn_redo.setToolTip("重做上一步操作 (Ctrl+Y)")
        self.btn_redo.clicked.connect(self.redo_action)
        self.btn_redo.setShortcut("Ctrl+Y")

        self.btn_split = QPushButton(" 分割")
        self.btn_split.setIcon(self.style().standardIcon(QStyle.SP_FileIcon)) 
        self.btn_split.setToolTip("在当前位置分割 (S)")
        self.btn_split.clicked.connect(self.split_clip)
        self.btn_split.setShortcut("S")
        
        self.btn_delete = QPushButton(" 删除")
        self.btn_delete.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.btn_delete.setToolTip("删除选中片段 (Del)")
        self.btn_delete.clicked.connect(self.delete_clip)
        self.btn_delete.setShortcut("Del")
        
        self.lbl_trim_info = QLabel("就绪")
        self.lbl_trim_info.setStyleSheet("color: #888; margin-left: 10px;")
        
        tools_layout.addWidget(self.btn_undo)
        tools_layout.addWidget(self.btn_redo)
        tools_layout.addWidget(self.btn_split)
        tools_layout.addWidget(self.btn_delete)
        tools_layout.addWidget(self.lbl_trim_info)
        tools_layout.addStretch()
        
        # Zoom Controls
        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.setFixedSize(30, 30)
        self.btn_zoom_out.setToolTip("缩小时间轴")
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        
        self.slider_zoom = QSlider(Qt.Horizontal)
        self.slider_zoom.setRange(10, 2000) # 10% to 2000%
        self.slider_zoom.setValue(100)
        self.slider_zoom.setFixedWidth(120)
        self.slider_zoom.valueChanged.connect(self.update_timeline_zoom)
        self.slider_zoom.setToolTip("缩放时间轴")
        
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedSize(30, 30)
        self.btn_zoom_in.setToolTip("放大时间轴 (查看更多帧细节)")
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        
        tools_layout.addWidget(QLabel("缩放:"))
        tools_layout.addWidget(self.btn_zoom_out)
        tools_layout.addWidget(self.slider_zoom)
        tools_layout.addWidget(self.btn_zoom_in)
        
        timeline_layout.addLayout(tools_layout)
        
        # Timeline Widget
        self.timeline = TimelineWidget()
        self.timeline.seekRequested.connect(self.seek_from_timeline)
        # Load audio waveforms
        self.timeline.set_audio_paths(self.audio_mic, self.audio_sys)
        
        # Wrap in ScrollArea
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.timeline)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.installEventFilter(self)
        
        # Adjust panel height to fit scrollbar
        timeline_panel.setFixedHeight(180) 
        
        timeline_layout.addWidget(self.scroll_area)
        
        main_layout.addWidget(timeline_panel)

    def open_video_from_disk(self):
        start_dir = ""
        try:
            start_dir = os.path.dirname(self.video_path) if self.video_path else ""
        except Exception:
            start_dir = ""

        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频文件",
            start_dir,
            "视频文件 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;所有文件 (*.*)"
        )
        if not path:
            return

        editor = VideoEditor(
            video_path=path,
            audio_mic=None,
            audio_sys=None,
            metadata_path=None,
            default_output_path=None,
        )
        VideoEditor._open_editors.append(editor)
        editor.destroyed.connect(lambda *_: VideoEditor._open_editors.remove(editor) if editor in VideoEditor._open_editors else None)
        editor.show()
        self.close()

    def zoom_in(self):
        val = self.slider_zoom.value()
        self.slider_zoom.setValue(min(2000, val + 20))

    def zoom_out(self):
        val = self.slider_zoom.value()
        self.slider_zoom.setValue(max(10, val - 20))

    def update_timeline_zoom(self):
        if not hasattr(self, 'scroll_area'): return
        
        zoom_factor = self.slider_zoom.value() / 100.0
        viewport_width = self.scroll_area.viewport().width()
        
        # Calculate new width
        # If zoom is 1.0 (100%), we want it to fit the viewport exactly
        new_width = int(viewport_width * zoom_factor)
        
        # Ensure it's at least viewport width
        new_width = max(new_width, viewport_width)
        
        # Apply to timeline
        self.timeline.setFixedWidth(new_width)

    def eventFilter(self, source, event):
        try:
            if hasattr(self, 'scroll_area') and source == self.scroll_area and event.type() == QEvent.Resize:
                # When scroll area resizes, we need to update timeline width
                # to maintain the "Fit" relative aspect or update zoom base
                self.update_timeline_zoom()
            elif source == self.video_frame and event.type() == QEvent.Resize:
                self.update_preview_layout()
        except Exception as e:
            print(f"Error in eventFilter: {e}")
            import traceback
            traceback.print_exc()
            
        return super().eventFilter(source, event)

    def set_ratio(self, ratio, name):
        self.target_ratio = ratio
        self.target_ratio_name = name
        self.btn_ratio.setText(f"{name}" if name != "原始" else "比例")
        self.update_preview_layout()

    def update_preview_layout(self):
        # Calculate size for video_widget based on video_frame size and target_ratio
        if not self.video_frame.isVisible(): return
        
        avail_w = self.video_frame.width()
        avail_h = self.video_frame.height()
        
        # Set background to dark gray to distinguish black bars
        self.video_frame.setStyleSheet("background-color: #333; border-radius: 8px;")
        
        if avail_w <= 0 or avail_h <= 0: return

        # 1. Determine Target Ratio (Canvas Ratio)
        if self.target_ratio is None:
            # Original: Use video source ratio
            if self.video_height > 0:
                target_ratio = self.video_width / self.video_height
            else:
                target_ratio = 16/9 # Default fallback
        else:
            target_ratio = self.target_ratio
            
        # 2. Fit Canvas to Available Space (Letterbox/Pillarbox relative to Window)
        canvas_w = avail_w
        canvas_h = int(canvas_w / target_ratio)
        
        if canvas_h > avail_h:
            canvas_h = avail_h
            canvas_w = int(canvas_h * target_ratio)
            
        canvas_w = max(1, canvas_w)
        canvas_h = max(1, canvas_h)

        # Update Canvas Size
        if self.canvas_frame.width() != canvas_w or self.canvas_frame.height() != canvas_h:
            self.canvas_frame.setFixedSize(canvas_w, canvas_h)
            
        # 3. Fit Video Widget to Canvas (Fit Source Video into Canvas)
        # Source Ratio
        if self.video_height > 0:
            source_ratio = self.video_width / self.video_height
        else:
            source_ratio = 16/9
            
        # Fit logic inside canvas
        # Apply padding (reduce available size)
        pad = self.bg_padding * 2
        avail_canvas_w = max(1, canvas_w - pad)
        avail_canvas_h = max(1, canvas_h - pad)
        
        vid_w = avail_canvas_w
        vid_h = int(vid_w / source_ratio)
        
        if vid_h > avail_canvas_h:
            vid_h = avail_canvas_h
            vid_w = int(vid_h * source_ratio)
            
        vid_w = max(1, vid_w)
        vid_h = max(1, vid_h)
        
        # Update Video Widget Size
        if self.video_container.width() != vid_w or self.video_container.height() != vid_h:
            self.video_container.setFixedSize(vid_w, vid_h)
            self.video_container.show()
            
        # Apply Corner Radius to custom render widget
        self.video_widget.set_corner_radius(self.video_corner_radius)


    def import_background_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "导入背景图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp)")
        if not file_path:
            return
            
        # Determine assets path
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
        bg_dir = os.path.join(base_path, 'assets', 'Backgroundpic')
        
        if not os.path.exists(bg_dir):
            try:
                os.makedirs(bg_dir)
            except:
                pass
                
        try:
            filename = os.path.basename(file_path)
            target_path = os.path.join(bg_dir, filename)
            
            # If file already exists, rename it slightly
            if os.path.exists(target_path):
                base, ext = os.path.splitext(filename)
                import time
                filename = f"{base}_{int(time.time())}{ext}"
                target_path = os.path.join(bg_dir, filename)
                
            shutil.copy2(file_path, target_path)
            
            # Refresh list
            self.load_background_images()
            
            # Auto select the imported image
            # Find the item with this path
            for i in range(self.list_bg.count()):
                item = self.list_bg.item(i)
                if item.data(Qt.UserRole) == target_path:
                    self.list_bg.setCurrentItem(item)
                    self.on_bg_selected(item)
                    break
                    
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"无法导入图片: {str(e)}")

    def load_background_images(self):
        self.list_bg.clear()
        
        # Determine assets path
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
        bg_dir = os.path.join(base_path, 'assets', 'Backgroundpic')
        
        if not os.path.exists(bg_dir):
            try:
                os.makedirs(bg_dir)
            except:
                pass
                
        if os.path.exists(bg_dir):
            for f in os.listdir(bg_dir):
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                    path = os.path.join(bg_dir, f)
                    icon = QIcon(path)
                    # Create item with empty text but set tooltip
                    item = QListWidgetItem(icon, "")
                    item.setToolTip(f)
                    item.setData(Qt.UserRole, path)
                    self.list_bg.addItem(item)
    
    def on_bg_enable_changed(self, state):
        enabled = (state == Qt.Checked)
        # self.list_bg.setEnabled(enabled) # Keep enabled
        # self.lbl_bg_hint.setEnabled(enabled)
        # self.btn_refresh_bg.setEnabled(enabled)
        
        if enabled:
            # If enabled, check if we have a selection
            current_item = self.list_bg.currentItem()
            if current_item:
                self.on_bg_selected(current_item)
            elif self.list_bg.count() > 0:
                # Select first by default if nothing selected
                self.list_bg.setCurrentRow(0)
                self.on_bg_selected(self.list_bg.item(0))
        else:
            # Disable background preview only
            self.update_preview_bg()

    def on_bg_selected(self, item):
        # Auto-enable checkbox if user selects an item
        if not self.chk_enable_bg.isChecked():
            self.chk_enable_bg.blockSignals(True)
            self.chk_enable_bg.setChecked(True)
            self.chk_enable_bg.blockSignals(False)
            
        path = item.data(Qt.UserRole)
        self.background_image_path = path
        self.update_preview_bg()
            
    def update_preview_bg(self):
        path = self.background_image_path
        # Check logic: Must have path AND Checkbox must be Checked
        if path and self.chk_enable_bg.isChecked():
            # Update preview frame background
            # Use forward slashes for CSS
            css_path = path.replace('\\', '/')
            # Qt StyleSheet doesn't support background-size. Use border-image for stretching.
            self.canvas_frame.setStyleSheet(f"border-image: url({css_path}) 0 0 0 0 stretch stretch; border-radius: 0px;")
        else:
            self.canvas_frame.setStyleSheet("background-color: #000;")
            
        # Force update layout to refresh mask overlay background
        self.update_preview_layout()

    def update_padding(self, value):
        # value is from slider (0-5)
        pixel_val = value * 10
        
        # Block signals to prevent loop with spinbox
        self.spin_padding.blockSignals(True)
        self.spin_padding.setValue(pixel_val)
        self.spin_padding.blockSignals(False)
        
        self.bg_padding = pixel_val
        self.update_preview_layout()

    def update_corner_radius(self, value):
        # value is from slider (0-25)
        pixel_val = value * 4
        
        self.spin_radius.blockSignals(True)
        self.spin_radius.setValue(pixel_val)
        self.spin_radius.blockSignals(False)
        
        self.video_corner_radius = pixel_val
        self.update_preview_layout()

    def open_subtitle_dialog(self):
        if not self.audio_mic and not self.audio_sys:
            QMessageBox.information(self, "提示", "当前视频没有关联的音频录制文件，可能无法生成字幕。\n将尝试从视频中提取音频。")
            
        if getattr(self, "subtitle_config_dlg", None) is not None:
            try:
                self.subtitle_config_dlg.raise_()
                self.subtitle_config_dlg.activateWindow()
            except Exception:
                pass
            return

        dlg = SubtitleGenerationDialog(self, self.video_path, self.audio_mic)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.setWindowModality(Qt.WindowModal)
        self.subtitle_config_dlg = dlg

        def _cleanup():
            try:
                if getattr(self, "subtitle_config_dlg", None) is dlg:
                    self.subtitle_config_dlg = None
            except Exception:
                pass

        def _accepted():
            try:
                config = dlg.get_config()
            except Exception:
                _cleanup()
                return

            _cleanup()
            self._start_subtitle_generation(config)

        dlg.accepted.connect(_accepted)
        dlg.rejected.connect(_cleanup)
        dlg.open()

    def _start_subtitle_generation(self, config: dict):
        cfg = dict(config or {})
        try:
            cfg.setdefault("output_path", os.path.splitext(self.video_path)[0] + ".srt")
        except Exception:
            pass

        try:
            has_ext = False
            try:
                has_ext = bool(self.audio_mic and os.path.exists(self.audio_mic)) or bool(self.audio_sys and os.path.exists(self.audio_sys))
            except Exception:
                has_ext = False

            if has_ext and (not getattr(self, "preview_path", None) or not os.path.exists(self.preview_path)):
                try:
                    self.check_and_generate_preview(force=True)
                except Exception:
                    pass

            if getattr(self, "preview_path", None) and os.path.exists(self.preview_path):
                cfg["preview_path"] = self.preview_path
                cfg["prefer_preview_audio"] = True
        except Exception:
            pass

        self.subtitle_worker = self.subtitle_manager.start_generation(cfg)

        self.progress_dlg = QProgressDialog("正在生成字幕...", "取消", 0, 100, self)
        self.progress_dlg.setWindowModality(Qt.WindowModal)
        self.progress_dlg.setMinimumDuration(0)
        self.progress_dlg.canceled.connect(self.cancel_subtitle)

        self.subtitle_worker.progress.connect(self.update_subtitle_progress)
        self.subtitle_worker.finished.connect(self.on_subtitle_finished)
        self.subtitle_worker.error.connect(self.on_subtitle_error)

        self.subtitle_worker.start()
            
    def cancel_subtitle(self):
        if self.subtitle_worker:
            self.subtitle_worker.cancel()
            
    def update_subtitle_progress(self, val, msg):
        if self.progress_dlg:
            self.progress_dlg.setValue(val)
            self.progress_dlg.setLabelText(msg)
            
    def on_subtitle_finished(self, srt_path):
        if self.progress_dlg:
            self.progress_dlg.close()
        
        self.srt_path = srt_path
        # Removed incorrect self.params reference
        QMessageBox.information(self, "成功", f"字幕生成成功！\n已自动加载。")
        self.load_subtitle(srt_path)
        
    def on_subtitle_error(self, err_msg):
        if self.progress_dlg:
            self.progress_dlg.close()
        QMessageBox.critical(self, "错误", f"生成失败: {err_msg}")

    def load_subtitle(self, path):
        self.srt_source_path = path
        self.subtitle_segments_source_raw = []
        self.subtitle_segments_source = []
        self.subtitles = []
        self.list_subtitles.clear()
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Simple SRT Parser
            import re
            # Pattern: Index\nTime --> Time\nText\n\n
            # Time: 00:00:00,000
            pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n((?:.|\n)*?)(?=\n\n|\Z)', re.MULTILINE)
            matches = pattern.findall(content.strip() + '\n\n')
            
            def time_to_sec(t_str):
                h, m, s = t_str.replace(',', '.').split(':')
                return int(h)*3600 + int(m)*60 + float(s)
            
            # Regex for cleaning ASR tokens with potential spaces (e.g. < | zh | >)
            token_pattern = re.compile(r'<\s*\|\s*.*?\s*\|\s*>', re.DOTALL)
            
            is_dirty = False
            cleaned_subs = []
            
            for m in matches:
                start = time_to_sec(m[1])
                end = time_to_sec(m[2])
                raw_text = m[3].strip()
                
                # Double clean text to remove ASR tokens
                text = token_pattern.sub('', raw_text).strip()
                
                if text != raw_text:
                    is_dirty = True
                
                text2 = self._sanitize_subtitle_text(text)
                if text2 != text:
                    is_dirty = True
                text = text2
                if text:
                    cleaned_subs.append([m[1], m[2], text])
                    self.subtitle_segments_source_raw.append(SubtitleSegment(start=float(start), end=float(end), text=text))
                    
                    # Add to UI List
                    # Format: [00:00] Text
                    start_str = m[1].split(',')[0] # 00:00:00
                    # Simplified time: MM:SS
                    mm_ss = start_str[3:] 
                    
                    pass
            self.subtitle_segments_source = list(self.subtitle_segments_source_raw or [])
            self.subtitle_line_shift_ms = {}
            
            # If we cleaned anything, rewrite the SRT file to ensure consistency for Export
            if is_dirty:
                try:
                    print(f"Cleaning SRT file: {path}")
                    with open(path, "w", encoding="utf-8") as f:
                        for i, (s, e, t) in enumerate(cleaned_subs):
                            f.write(f"{i+1}\n{s} --> {e}\n{t}\n\n")
                except Exception as e:
                    print(f"Failed to rewrite cleaned SRT: {e}")
                
        except Exception as e:
            print(f"Failed to parse SRT: {e}")
            import traceback
            traceback.print_exc()
        self.sync_subtitles_with_timeline(silent=True)

    def _subtitle_shift_key(self, src_idx: int, base_start_ms: int) -> str:
        try:
            return f"{int(src_idx)}:{int(base_start_ms)}"
        except Exception:
            return f"{src_idx}:{base_start_ms}"

    def _shift_subtitle_range_ms(self, start_ms: int, end_ms: int, delta_ms: int) -> tuple[int, int]:
        s0 = int(round(float(start_ms)))
        e0 = int(round(float(end_ms)))
        if e0 <= s0:
            e0 = s0 + 50
        d = int(round(float(delta_ms)))
        s1 = s0 + d
        e1 = e0 + d
        dur = max(50, e1 - s1)
        s2 = max(0, s1)
        e2 = s2 + dur
        return int(s2), int(e2)

    def on_subtitle_selection_changed(self):
        item = self.list_subtitles.currentItem() if hasattr(self, "list_subtitles") else None
        ok = item is not None
        if hasattr(self, "btn_sub_shift_left"):
            self.btn_sub_shift_left.setEnabled(ok)
        if hasattr(self, "btn_sub_shift_right"):
            self.btn_sub_shift_right.setEnabled(ok)
        if hasattr(self, "btn_sub_shift_reset"):
            self.btn_sub_shift_reset.setEnabled(ok)

    def shift_selected_subtitle(self, delta_ms: int):
        item = self.list_subtitles.currentItem() if hasattr(self, "list_subtitles") else None
        if item is None:
            return
        try:
            self._subtitle_user_select_lock_until = time.monotonic() + 2.0
        except Exception:
            pass
        src_idx = item.data(Qt.UserRole + 4)
        base_start_ms = item.data(Qt.UserRole + 5)
        if src_idx is None or base_start_ms is None:
            return
        key = self._subtitle_shift_key(int(src_idx), int(base_start_ms))
        cur = int(self.subtitle_line_shift_ms.get(key, 0) or 0)
        new_val = int(cur + int(delta_ms))
        if new_val == 0:
            if key in self.subtitle_line_shift_ms:
                del self.subtitle_line_shift_ms[key]
        else:
            self.subtitle_line_shift_ms[key] = new_val
        try:
            logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
            os.makedirs(logs_dir, exist_ok=True)
            log_path = os.path.join(logs_dir, "subtitle_line_shift.log")
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"key={key}\nshift_ms={self.subtitle_line_shift_ms.get(key, 0)}\n----\n")
        except Exception:
            pass
        self.sync_subtitles_with_timeline(silent=True)

    def reset_selected_subtitle_shift(self):
        item = self.list_subtitles.currentItem() if hasattr(self, "list_subtitles") else None
        if item is None:
            return
        try:
            self._subtitle_user_select_lock_until = time.monotonic() + 2.0
        except Exception:
            pass
        src_idx = item.data(Qt.UserRole + 4)
        base_start_ms = item.data(Qt.UserRole + 5)
        if src_idx is None or base_start_ms is None:
            return
        key = self._subtitle_shift_key(int(src_idx), int(base_start_ms))
        if key in self.subtitle_line_shift_ms:
            del self.subtitle_line_shift_ms[key]
        self.sync_subtitles_with_timeline(silent=True)

    def _derive_edited_srt_path(self, source_path: str) -> str:
        if not source_path:
            return source_path
        base, ext = os.path.splitext(source_path)
        if base.endswith("_timeline") or base.endswith("_edited"):
            return source_path
        return base + "_timeline" + (ext or ".srt")

    def sync_subtitles_with_timeline(self, silent: bool = True):
        if not getattr(self, "subtitle_segments_source", None):
            if hasattr(self, "btn_sub_edit"):
                self.btn_sub_edit.setEnabled(False)
                self.btn_sub_save.setEnabled(False)
                if hasattr(self, "btn_sub_delete"):
                    self.btn_sub_delete.setEnabled(False)
            return

        if not getattr(self, "srt_source_path", None):
            return

        if not getattr(self, "srt_path", None) or self.srt_path == self.srt_source_path:
            self.srt_path = self._derive_edited_srt_path(self.srt_source_path)

        selected_key = None
        try:
            cur_item = self.list_subtitles.currentItem() if hasattr(self, "list_subtitles") else None
            if cur_item is not None:
                src_idx0 = cur_item.data(Qt.UserRole + 4)
                base_start_ms0 = cur_item.data(Qt.UserRole + 5)
                if src_idx0 is not None and base_start_ms0 is not None:
                    selected_key = self._subtitle_shift_key(int(src_idx0), int(base_start_ms0))
        except Exception:
            selected_key = None

        tl_segs = self.timeline.get_segments() if hasattr(self, "timeline") else []
        mapped = []
        for src_idx, seg in enumerate(self.subtitle_segments_source):
            t0 = self._sanitize_subtitle_text(seg.text)
            if not t0:
                continue
            s_ms = float(seg.start) * 1000.0
            e_ms = float(seg.end) * 1000.0
            if e_ms <= s_ms:
                continue
            for tl in tl_segs:
                o_s = max(s_ms, float(tl["source_start"]))
                o_e = min(e_ms, float(tl["source_end"]))
                if o_e <= o_s:
                    continue
                l_s = float(tl["start"]) + (o_s - float(tl["source_start"]))
                l_e = float(tl["start"]) + (o_e - float(tl["source_start"]))
                mapped.append((l_s / 1000.0, l_e / 1000.0, t0, src_idx))

        mapped.sort(key=lambda x: x[0])
        merged = []
        for s, e, t, idx in mapped:
            if not merged:
                merged.append([s, e, t, idx])
                continue
            ps, pe, pt, pidx = merged[-1]
            if idx == pidx and t == pt and (s - pe) <= 0.08:
                merged[-1][1] = max(pe, e)
            else:
                merged.append([s, e, t, idx])

        self.list_subtitles.clear()
        self.subtitles = []
        max_chars = int(os.environ.get("LUSCREEN_ASR_MAX_CHARS") or 18)
        for i in range(len(merged)):
            merged[i][2] = self._strip_trailing_punc(str(merged[i][2]))

        for s, e, t, idx in merged:
            if e <= s:
                continue
            t = self._sanitize_subtitle_text(str(t))
            if not t:
                continue
            base_s_ms = int(round(float(s) * 1000.0))
            base_e_ms = int(round(float(e) * 1000.0))
            key = self._subtitle_shift_key(int(idx), int(base_s_ms))
            delta_ms = int(self.subtitle_line_shift_ms.get(key, 0) or 0)
            s_ms, e_ms = self._shift_subtitle_range_ms(base_s_ms, base_e_ms, delta_ms)
            s_sec = float(s_ms) / 1000.0
            e_sec = float(e_ms) / 1000.0
            self.subtitles.append((float(s_sec), float(e_sec), str(t)))
            item = QListWidgetItem(self._format_subtitle_item_text(float(s_sec), str(t)))
            item.setData(Qt.UserRole, int(s_ms))
            item.setData(Qt.UserRole + 1, float(s_sec))
            item.setData(Qt.UserRole + 2, float(e_sec))
            item.setData(Qt.UserRole + 3, str(t))
            item.setData(Qt.UserRole + 4, int(idx))
            item.setData(Qt.UserRole + 5, int(base_s_ms))
            self.list_subtitles.addItem(item)

        if selected_key:
            try:
                self.list_subtitles.blockSignals(True)
                for i in range(self.list_subtitles.count()):
                    it = self.list_subtitles.item(i)
                    src_idx1 = it.data(Qt.UserRole + 4)
                    base_start_ms1 = it.data(Qt.UserRole + 5)
                    if src_idx1 is None or base_start_ms1 is None:
                        continue
                    k1 = self._subtitle_shift_key(int(src_idx1), int(base_start_ms1))
                    if k1 == selected_key:
                        self.list_subtitles.setCurrentItem(it)
                        self.list_subtitles.scrollToItem(it, QListWidget.EnsureVisible)
                        break
            except Exception:
                pass
            finally:
                try:
                    self.list_subtitles.blockSignals(False)
                except Exception:
                    pass

        if hasattr(self, "btn_sub_edit"):
            has_items = self.list_subtitles.count() > 0
            self.btn_sub_edit.setEnabled(has_items)
            self.btn_sub_save.setEnabled(has_items and bool(self.srt_path))
            if hasattr(self, "btn_sub_delete"):
                self.btn_sub_delete.setEnabled(has_items)
            self.on_subtitle_selection_changed()

        self.save_subtitles_to_file(silent=True)

    def on_subtitle_item_clicked(self, item):
        try:
            self._subtitle_user_select_lock_until = time.monotonic() + 2.0
        except Exception:
            pass
        start_ms = item.data(Qt.UserRole)
        if start_ms is not None:
            self.seek_from_timeline(start_ms)

    def _format_subtitle_item_text(self, start_sec: float, text: str) -> str:
        try:
            mm_ss = QTime(0, 0).addMSecs(int(round(float(start_sec) * 1000))).toString("mm:ss.zzz")
        except Exception:
            mm_ss = "00:00.000"
        return f"[{mm_ss}] {text}"

    def _visible_len(self, s: str) -> int:
        return len(re.sub(r'\s+', '', s or ""))

    def _is_punc_only(self, s: str) -> bool:
        return re.fullmatch(r'[\s\.,。！？!?，,、；;：:…—\-]+', (s or "").strip()) is not None

    def _strip_trailing_punc(self, s: str) -> str:
        return re.sub(r'[\s，,。\.!！？\?；;：:、]+$', '', s or "").strip()

    def _sanitize_subtitle_text(self, text: str) -> str:
        t = (text or "").strip()
        if not t:
            return ""
        if self._is_punc_only(t):
            return ""
        t = self._strip_trailing_punc(t)
        if not t or self._is_punc_only(t):
            return ""
        return t

    def _pulse_button(self, btn, text: str | None = None, duration_ms: int = 900, ok: bool = True):
        if btn is None:
            return
        try:
            token = int(btn.property("_luscreen_pulse_token") or 0) + 1
        except Exception:
            token = 1
        btn.setProperty("_luscreen_pulse_token", token)

        old_text = btn.text()
        old_style = btn.styleSheet()
        if text:
            btn.setText(text)
        color = "#2ea043" if ok else "#d73a49"
        btn.setStyleSheet((old_style or "") + f"\nQPushButton{{background-color:{color}; border: 1px solid {color}; color: white;}}")

        def restore():
            try:
                if int(btn.property("_luscreen_pulse_token") or 0) != token:
                    return
            except Exception:
                pass
            btn.setText(old_text)
            btn.setStyleSheet(old_style)

        QTimer.singleShot(max(200, int(duration_ms)), restore)

    def _subtitle_bg_qcolor(self):
        name = str(getattr(self, "subtitle_bg", "none") or "none").lower()
        if name in ["yellow", "黄色"]:
            return QColor(255, 235, 59, 255)
        if name in ["gray", "grey", "灰色"]:
            return QColor(60, 60, 60, 255)
        return None

    def on_subtitle_bg_changed(self, text: str):
        mapping = {
            "无": "none",
            "黄色": "yellow",
            "灰色": "gray",
        }
        self.subtitle_bg = mapping.get(str(text), "none")
        try:
            self.config_manager.set("subtitle_bg", self.subtitle_bg)
            self.config_manager.save()
        except Exception:
            pass
        if hasattr(self, "video_widget"):
            self.video_widget.set_subtitle_background(self._subtitle_bg_qcolor())

    def _rebuild_subtitles_from_list(self):
        subs = []
        for i in range(self.list_subtitles.count()):
            item = self.list_subtitles.item(i)
            start = item.data(Qt.UserRole + 1)
            end = item.data(Qt.UserRole + 2)
            text = self._sanitize_subtitle_text(item.data(Qt.UserRole + 3) or "")
            if start is None or end is None:
                continue
            if not text:
                continue
            subs.append((float(start), float(end), text))
        subs.sort(key=lambda x: x[0])
        self.subtitles = subs

    def edit_selected_subtitle(self):
        item = self.list_subtitles.currentItem()
        if item is None:
            return
        self.edit_subtitle_item(item)

    def edit_subtitle_item(self, item):
        start_sec = item.data(Qt.UserRole + 1) or 0.0
        old_text = item.data(Qt.UserRole + 3) or ""
        new_text, ok = QInputDialog.getMultiLineText(self, "编辑字幕", "字幕内容：", str(old_text))
        if not ok:
            return
        new_text = (new_text or "").strip()
        if not new_text:
            row = self.list_subtitles.row(item)
            if row >= 0:
                if QMessageBox.question(self, "删除字幕", "内容为空，是否删除该字幕？") == QMessageBox.Yes:
                    src_idx = item.data(Qt.UserRole + 4)
                    if src_idx is not None and isinstance(src_idx, int) and 0 <= src_idx < len(getattr(self, "subtitle_segments_source", [])):
                        self.subtitle_segments_source[src_idx].text = ""
                        if 0 <= src_idx < len(getattr(self, "subtitle_segments_source_raw", [])):
                            self.subtitle_segments_source_raw[src_idx].text = ""
                    self.list_subtitles.takeItem(row)
                    self._rebuild_subtitles_from_list()
                    self.save_subtitles_to_file(silent=True)
            return
        if self._is_punc_only(new_text):
            self.delete_selected_subtitle()
            return
        item.setData(Qt.UserRole + 3, new_text)
        item.setText(self._format_subtitle_item_text(float(start_sec), new_text))
        src_idx = item.data(Qt.UserRole + 4)
        if src_idx is not None and isinstance(src_idx, int) and 0 <= src_idx < len(getattr(self, "subtitle_segments_source", [])):
            self.subtitle_segments_source[src_idx].text = new_text
            if 0 <= src_idx < len(getattr(self, "subtitle_segments_source_raw", [])):
                self.subtitle_segments_source_raw[src_idx].text = new_text
        self._rebuild_subtitles_from_list()
        self.save_subtitles_to_file(silent=True)
        if hasattr(self, "btn_sub_edit"):
            self._pulse_button(self.btn_sub_edit, "已更新", 900, ok=True)

    def delete_selected_subtitle(self):
        item = self.list_subtitles.currentItem()
        if item is None:
            return
        row = self.list_subtitles.row(item)
        if row < 0:
            return
        src_idx = item.data(Qt.UserRole + 4)
        if src_idx is not None and isinstance(src_idx, int) and 0 <= src_idx < len(getattr(self, "subtitle_segments_source", [])):
            self.subtitle_segments_source[src_idx].text = ""
            if 0 <= src_idx < len(getattr(self, "subtitle_segments_source_raw", [])):
                self.subtitle_segments_source_raw[src_idx].text = ""
        self.list_subtitles.takeItem(row)
        self._rebuild_subtitles_from_list()
        self.save_subtitles_to_file(silent=True)
        if hasattr(self, "btn_sub_delete"):
            self._pulse_button(self.btn_sub_delete, "已删除", 900, ok=True)

    def save_subtitles_to_file(self, silent: bool = False):
        if not getattr(self, "srt_path", None):
            if not silent:
                QMessageBox.warning(self, "提示", "当前没有可保存的字幕文件。")
            return
        segments = []
        for i in range(self.list_subtitles.count()):
            item = self.list_subtitles.item(i)
            start = item.data(Qt.UserRole + 1)
            end = item.data(Qt.UserRole + 2)
            text = self._sanitize_subtitle_text(item.data(Qt.UserRole + 3) or "")
            if start is None or end is None:
                continue
            if not text:
                continue
            segments.append(SubtitleSegment(start=float(start), end=float(end), text=text))
        if not segments:
            if not silent:
                QMessageBox.warning(self, "提示", "字幕为空，未保存。")
            return
        try:
            srt_content = SubtitleFormatter.to_srt(segments)
            with open(self.srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            if not silent:
                QMessageBox.information(self, "成功", "字幕已保存。")
            if hasattr(self, "btn_sub_save"):
                self._pulse_button(self.btn_sub_save, "已保存", 900, ok=True)
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "错误", f"保存失败: {e}")
            if hasattr(self, "btn_sub_save"):
                self._pulse_button(self.btn_sub_save, "保存失败", 1100, ok=False)

    def update_subtitle_preview(self, current_time):
        if not hasattr(self, 'subtitles') or not self.subtitles:
            return
            
        text = ""
        current_idx = -1
        current_ms = int(round(float(current_time) * 1000.0))
        
        best_start_ms = None
        for idx, (start, end, txt) in enumerate(self.subtitles):
            try:
                start_ms = int(round(float(start) * 1000.0))
                end_ms = int(round(float(end) * 1000.0))
            except Exception:
                continue
            active = start_ms <= current_ms < end_ms or (idx == len(self.subtitles) - 1 and start_ms <= current_ms <= end_ms)
            if not active:
                continue
            if best_start_ms is None or start_ms >= best_start_ms:
                best_start_ms = start_ms
                text = txt
                current_idx = idx
            # Also check if we are just past this subtitle but before next (gap)
            # Or just highlight the upcoming one? Usually highlight active.
            
        if hasattr(self, 'video_widget'):
            self.video_widget.set_subtitle(text)
            
        # Sync List Selection
        try:
            if float(getattr(self, "_subtitle_user_select_lock_until", 0.0) or 0.0) > time.monotonic():
                return
        except Exception:
            pass

        if current_idx >= 0:
            if self.list_subtitles.count() > current_idx:
                item = self.list_subtitles.item(current_idx)
                # Only scroll if not currently selected (to avoid jitter if user is scrolling)
                if not item.isSelected():
                    self.list_subtitles.setCurrentItem(item)
                    self.list_subtitles.scrollToItem(item, QListWidget.EnsureVisible)
        else:
            self.list_subtitles.clearSelection()

    def init_player(self):
        try:
            source = self.preview_path if self.preview_path and os.path.exists(self.preview_path) else self.video_path
            self.logger.info(f"Initializing player with source: {source}")
            self.player = QMediaPlayer()
            
            # Use QVideoSink for custom rendering (to support rounded corners in preview)
            self.video_sink = QVideoSink()
            self.player.setVideoSink(self.video_sink)
            # Use queued connection to ensure thread safety when passing frames
            self.video_sink.videoFrameChanged.connect(self.video_widget.set_frame, Qt.QueuedConnection)
            
            self.audio_output = QAudioOutput()
            self.audio_output.setVolume(1.0) # Player volume at 100%
            self.player.setAudioOutput(self.audio_output)
            
            # 调试音频输出
            self.logger.info(f"Audio output device: {self.audio_output.device().description()}")
            self.logger.info(f"Audio output volume: {self.audio_output.volume()}")
            
            self.player.errorOccurred.connect(lambda error, errorString: self.logger.error(f"Player Error: {error} - {errorString}"))
            self.player.playbackStateChanged.connect(lambda state: self.logger.info(f"Playback state changed to: {state}"))
            
            if not source or not os.path.exists(source):
                print(f"Error: Video source not found: {source}")
                return

            self.player.setSource(QUrl.fromLocalFile(source))
            self.player.durationChanged.connect(self.duration_changed)
            # self.player.positionChanged.connect(self.position_changed) # Disable default mapping
            self.player.mediaStatusChanged.connect(self.handle_media_status)
            
            # self.player.play() # Removed, handled in handle_media_status
            # self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
            
            # Custom Playback Timer for Timeline Sync
            self.play_timer = QTimer(self)
            self.play_timer.setInterval(30) # ~30 FPS UI update
            self.play_timer.timeout.connect(self.update_playback)
            self.play_timer.start()
            
            # Logical playback position (ms)
            self.logical_position = 0
            self.is_playing = False # Wait for media to load
            
            # Force layout update once player is ready
            QTimer.singleShot(100, self.update_preview_layout)
        except Exception as e:
            print(f"Error in init_player: {e}")
            import traceback
            traceback.print_exc()

    def update_playback(self):
        if not self.is_playing: return
        
        # Sync UI to Player (Master Clock)
        current_source = self.player.position()
        
        mapped_logical = self.timeline.map_source_to_timeline(current_source)
        
        if mapped_logical is not None:
            # Valid playback region
            self.logical_position = mapped_logical
            
            # Update Subtitle Preview
            self.update_subtitle_preview(self.logical_position / 1000.0)
            
            # Update UI
            self.timeline.set_position(self.logical_position)
            self.lbl_current.setText(self.format_time(self.logical_position))
            
            # Auto-scroll timeline if playing
            if hasattr(self, 'scroll_area'):
                # Calculate playhead X position in timeline widget
                duration = self.timeline.duration
                if duration > 0:
                    width = self.timeline.width()
                    playhead_x = (self.logical_position / duration) * width
                    
                    # Get current scroll info
                    scrollbar = self.scroll_area.horizontalScrollBar()
                    scroll_x = scrollbar.value()
                    viewport_w = self.scroll_area.viewport().width()
                    
                    # Check if playhead is out of view (or close to edge)
                    margin = 50 # px
                    if playhead_x > (scroll_x + viewport_w - margin):
                        # Scroll forward
                        scrollbar.setValue(int(playhead_x - margin))
                    elif playhead_x < scroll_x:
                        # Scroll backward (e.g. looped or seeked)
                        scrollbar.setValue(int(playhead_x - margin))

            # Check for end
            if self.logical_position >= self.timeline.duration:
                self.pause_video()
                self.seek_from_timeline(0)
        else:
            # In a gap (deleted region) -> Skip to next segment
            next_seg = None
            min_dist = float('inf')
            
            # Find nearest next segment
            for seg in self.timeline.get_segments():
                if seg['source_start'] > current_source:
                    dist = seg['source_start'] - current_source
                    if dist < min_dist:
                        min_dist = dist
                        next_seg = seg
            
            if next_seg:
                # Seek to next segment
                self.player.setPosition(next_seg['source_start'])
                # Update logical position immediately to avoid flicker
                self.logical_position = next_seg['start']
                self.timeline.set_position(self.logical_position)
            else:
                # End of content
                self.pause_video()
                self.seek_from_timeline(0)

    def handle_media_status(self, status):
        self.logger.info(f"Media status changed to: {status}")
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            # Media loaded, safe to play
            self.player.play()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
            self.is_playing = True
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.logger.error("Failed to load media (InvalidMedia)")
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            pass

    def duration_changed(self, duration):
        # Initial duration set only
        if self.timeline.duration == 0:
            self.timeline.set_duration(duration)
            self.lbl_total.setText(f"/ {self.format_time(duration)}")

    def position_changed(self, position):
        # Legacy slot, now unused
        pass

    def seek_from_timeline(self, position):
        self.logical_position = position
        source_pos = self.timeline.map_timeline_to_source(position)
        if source_pos is not None:
            self.player.setPosition(source_pos)
        
        self.timeline.set_position(position)
        self.lbl_current.setText(self.format_time(position))
        self.update_subtitle_preview(position / 1000.0)
        
        # Ensure it doesn't autoplay if paused
        self.pause_video()

    def set_position(self, position):
        self.seek_from_timeline(position)

    def pause_video(self):
        self.is_playing = False
        self.player.pause()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        
    def play_video(self):
        self.is_playing = True
        self.player.play()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        
    def toggle_play(self):
        if not hasattr(self, 'player') or self.player is None:
            return
            
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.pause_video()
        else:
            self.play_video()

    def split_clip(self):
        if self.timeline.split_at_current():
            self.lbl_trim_info.setText("片段已分割")
            self.sync_subtitles_with_timeline(silent=True)
        else:
            self.lbl_trim_info.setText("此处无法分割")

    def undo_action(self):
        if self.timeline.undo():
            self.lbl_trim_info.setText("已撤销")
            self.sync_subtitles_with_timeline(silent=True)
        else:
            self.lbl_trim_info.setText("无法撤销")

    def redo_action(self):
        if self.timeline.redo():
            self.lbl_trim_info.setText("已重做")
            self.sync_subtitles_with_timeline(silent=True)
        else:
            self.lbl_trim_info.setText("无法重做")

    def delete_clip(self):
        self.timeline.delete_selected()
        self.lbl_trim_info.setText("片段已删除")
        self.sync_subtitles_with_timeline(silent=True)

    def update_settings(self):
        self.base_zoom = self.spin_base_zoom.value()
        self.click_zoom = self.spin_click_zoom.value()
        self.click_duration = self.spin_zoom_duration.value()
        
        self.watermark_text = self.edit_watermark.text()
        idx = self.combo_watermark_pos.currentIndex()
        mapping = {0: 'top-left', 1: 'top-right', 2: 'bottom-left', 3: 'bottom-right', 4: 'custom'}
        self.watermark_pos = mapping.get(idx, 'bottom-right')
        self.watermark_size = self.spin_watermark_size.value()
        if self.watermark_pos != "custom":
            self.watermark_pos_x = None
            self.watermark_pos_y = None

        use_img = False
        has_chk = hasattr(self, "chk_use_image_watermark")
        is_pro = getattr(self, "license_manager", None) is not None and self.license_manager.is_pro
        if has_chk:
            try:
                if self.chk_use_image_watermark.isChecked() and not is_pro:
                    self.chk_use_image_watermark.blockSignals(True)
                    self.chk_use_image_watermark.setChecked(False)
                    self.chk_use_image_watermark.blockSignals(False)
                    QMessageBox.information(self, "提示", "图片水印为 Pro 功能。")
            except Exception:
                try:
                    self.chk_use_image_watermark.blockSignals(False)
                except Exception:
                    pass
        if is_pro:
            use_img = has_chk and self.chk_use_image_watermark.isChecked()
        self.watermark_use_image = bool(use_img)
        try:
            if hasattr(self, "btn_select_wm_image"):
                self.btn_select_wm_image.setEnabled(self.watermark_use_image)
            if hasattr(self, "btn_clear_wm_image"):
                self.btn_clear_wm_image.setEnabled(self.watermark_use_image and bool(self.watermark_image_path))
            if hasattr(self, "edit_watermark"):
                self.edit_watermark.setEnabled(not self.watermark_use_image)
        except Exception:
            pass
        try:
            if hasattr(self, "video_widget"):
                self.video_widget.set_watermark_image(
                    enabled=bool(self.watermark_use_image and self.watermark_image_path),
                    image_path=self.watermark_image_path,
                    pos=self.watermark_pos,
                    size=self.watermark_size,
                    custom_x=self.watermark_pos_x,
                    custom_y=self.watermark_pos_y,
                )
        except Exception:
            pass

    def _on_watermark_moved(self, norm_x: float, norm_y: float):
        try:
            if not self.license_manager.is_pro:
                return
        except Exception:
            return
        self.watermark_pos_x = float(norm_x)
        self.watermark_pos_y = float(norm_y)
        try:
            if hasattr(self, "combo_watermark_pos"):
                self.combo_watermark_pos.blockSignals(True)
                self.combo_watermark_pos.setCurrentIndex(4)
                self.combo_watermark_pos.blockSignals(False)
        except Exception:
            try:
                self.combo_watermark_pos.blockSignals(False)
            except Exception:
                pass
        self.update_settings()

    def _on_watermark_scale_changed(self, new_size: float):
        try:
            if not self.license_manager.is_pro:
                return
        except Exception:
            return
        try:
            if hasattr(self, "spin_watermark_size"):
                self.spin_watermark_size.blockSignals(True)
                self.spin_watermark_size.setValue(float(new_size))
                self.spin_watermark_size.blockSignals(False)
        except Exception:
            try:
                self.spin_watermark_size.blockSignals(False)
            except Exception:
                pass
        self.update_settings()

    def select_watermark_image(self):
        if not self.license_manager.is_pro:
            QMessageBox.information(self, "提示", "图片水印为 Pro 功能。")
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择水印图片", "", "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        self.watermark_image_path = path
        try:
            if hasattr(self, "lbl_wm_image_path"):
                self.lbl_wm_image_path.setText(path)
        except Exception:
            pass
        self.update_settings()

    def clear_watermark_image(self):
        self.watermark_image_path = None
        try:
            if hasattr(self, "lbl_wm_image_path"):
                self.lbl_wm_image_path.setText("未选择图片")
        except Exception:
            pass
        self.update_settings()

    def format_time(self, ms):
        seconds = (ms // 1000) % 60
        minutes = (ms // 60000)
        return f"{minutes:02}:{seconds:02}"

    def check_and_generate_preview(self, force=False):
        self.logger.info(f"Checking preview requirements (force={force})")
        # 增加文件就绪检查
        max_retries = 5
        for i in range(max_retries):
            if os.path.exists(self.video_path) and os.path.getsize(self.video_path) > 0:
                break
            self.logger.info(f"Waiting for video file to be ready... (Attempt {i+1})")
            time.sleep(0.5)

        # 优化：优先检查是否已存在有效的预览文件
        base, _ = os.path.splitext(self.video_path)
        self.preview_path = f"{base}_preview.mp4"
        
        # Check for background generation marker
        marker_path = self.preview_path + ".generating"
        wait_count = 0
        # Wait up to 15s (30 * 0.5s) for background generation to finish
        while os.path.exists(marker_path) and wait_count < 30: 
            if wait_count == 0:
                self.logger.info(f"Found generation marker {marker_path}, waiting for background process...")
            
            if wait_count % 4 == 0: # Log every 2s
                self.logger.info(f"Waiting for preview generation... ({wait_count/2}s)")
            
            QApplication.processEvents()
            time.sleep(0.5)
            wait_count += 1
            
        if not force and os.path.exists(self.preview_path) and os.path.getsize(self.preview_path) > 1024:
             # 尝试短暂等待文件锁释放（如果是 recorder 刚生成的）
            try:
                with open(self.preview_path, 'rb') as f:
                    pass
                self.logger.info(f"Preview file found and accessible: {self.preview_path}, using it.")
                self.init_player()
                return
            except IOError:
                self.logger.warning(f"Preview file exists but is locked or inaccessible: {self.preview_path}")

        has_mic = self.audio_mic and os.path.exists(self.audio_mic)
        has_sys = self.audio_sys and os.path.exists(self.audio_sys)
        
        self.logger.info(f"Audio status - Video: {os.path.exists(self.video_path)} ({os.path.getsize(self.video_path) if os.path.exists(self.video_path) else 0} bytes), "
                         f"Mic: {has_mic}, Sys: {has_sys}")
        
        # 只有在完全没有额外音轨的情况下，才跳过预览生成
        if not force and not has_mic and not has_sys:
            self.logger.info("No external audio files and not forced. Using original video.")
            self.preview_path = None
            self.init_player()
            return

        # Stop playback and release file lock if re-generating
        if hasattr(self, 'player'):
            self.logger.info("Stopping existing player to re-generate preview")
            self.pause_video()
            self.player.setSource(QUrl())

        base, _ = os.path.splitext(self.video_path)
        self.preview_path = f"{base}_preview.mp4"
        self.logger.info(f"Target preview path: {self.preview_path}")
        
        progress = QProgressDialog("正在生成音频预览...", "", 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()
        
        try:
            mic_vol = self.spin_mic_vol.value() if hasattr(self, 'spin_mic_vol') else 5.0
            sys_vol = self.spin_sys_vol.value() if hasattr(self, 'spin_sys_vol') else 1.5
            
            # Determine if enhancement is enabled
            is_enhanced = False
            if hasattr(self, 'chk_enhance') and self.chk_enhance.isChecked():
                is_enhanced = True
            
            self.logger.info(f"Preview params - MicVol: {mic_vol}, SysVol: {sys_vol}, Enhanced: {is_enhanced}")

            atempo_factor = 1.0
            try:
                vid_dur = get_media_duration_sec(self.video_path)
                mic_dur = get_wav_duration_sec(self.audio_mic) if has_mic else None
                sys_dur = get_wav_duration_sec(self.audio_sys) if has_sys else None
                ref_audio_dur = max(float(mic_dur or 0.0), float(sys_dur or 0.0))
                if vid_dur and ref_audio_dur and float(vid_dur) > 0.2 and float(ref_audio_dur) > 0.2:
                    atempo_factor = float(ref_audio_dur) / float(vid_dur)
                    if not (0.8 <= atempo_factor <= 1.25):
                        atempo_factor = 1.0
                    if abs(atempo_factor - 1.0) > 0.0005:
                        try:
                            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                            logs_dir = os.path.join(base, "logs")
                            os.makedirs(logs_dir, exist_ok=True)
                            log_path = os.path.join(logs_dir, "preview_audio_drift_scale.log")
                            with open(log_path, "a", encoding="utf-8") as lf:
                                lf.write(
                                    f"video={self.video_path}\n"
                                    f"mic={self.audio_mic}\n"
                                    f"sys={self.audio_sys}\n"
                                    f"video_dur_sec={float(vid_dur):.3f}\n"
                                    f"ref_audio_dur_sec={float(ref_audio_dur):.3f}\n"
                                    f"atempo_factor={atempo_factor:.9f}\n"
                                    "----\n"
                                )
                        except Exception:
                            pass
            except Exception:
                atempo_factor = 1.0
            
            ffmpeg_exe = get_ffmpeg_path()
            cmd = [ffmpeg_exe, '-y', '-i', self.video_path]
            inputs = 1
            
            if has_mic:
                cmd.extend(['-i', self.audio_mic])
                inputs += 1
            if has_sys:
                cmd.extend(['-i', self.audio_sys])
                inputs += 1
            
            # Filter Construction
            filter_complex = ""
            if inputs == 3: # Video + Mic + Sys
                # 优化：同步录制端的高增益逻辑 (Mic 5.0x, Sys 1.5x, Global 1.5x)
                # 确保预览音量与录制出的视频完全一致
                if atempo_factor != 1.0:
                    filter_complex = (
                        f"[1:a]atempo={atempo_factor:.9f},volume={mic_vol * 5.0}[mic];"
                        f"[2:a]atempo={atempo_factor:.9f},volume={sys_vol * 1.5}[sys];"
                        f"[mic][sys]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,volume=1.5[aout]"
                    )
                else:
                    filter_complex = f"[1:a]volume={mic_vol * 5.0}[mic];[2:a]volume={sys_vol * 1.5}[sys];[mic][sys]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,volume=1.5[aout]"
                cmd.extend(['-filter_complex', filter_complex, '-map', '0:v', '-map', '[aout]'])
                
            elif inputs == 2: # Video + (Mic OR Sys)
                # Determine which audio source acts as input 1:a
                is_mic_only = has_mic
                vol_factor = 5.0 if is_mic_only else 1.5
                vol = (mic_vol if is_mic_only else sys_vol) * vol_factor
                if atempo_factor != 1.0:
                    filter_complex = f"[1:a]atempo={atempo_factor:.9f},volume={vol},volume=1.5[aout]"
                else:
                    filter_complex = f"[1:a]volume={vol},volume=1.5[aout]"
                cmd.extend(['-filter_complex', filter_complex, '-map', '0:v', '-map', '[aout]'])
                
            # Use 'aac' codec for preview to ensure compatibility and quality
            # 优化：添加 -preset ultrafast 和 -movflags faststart 提升生成和加载速度
            cmd.extend([
                '-c:v', 'copy', 
                '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
                '-preset', 'ultrafast',
                '-movflags', '+faststart',
                self.preview_path
            ])
            
            self.logger.info(f"FFmpeg Preview Command: {' '.join(cmd)}")
            
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            # Capture output and check return code manually for better logging
            result = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
            if result.returncode != 0:
                err_msg = result.stderr.decode('utf-8', errors='ignore')
                self.logger.error(f"FFmpeg Preview Generation Failed (code {result.returncode}): {err_msg}")
                self.preview_path = None
            else:
                self.logger.info(f"Preview successfully generated at: {self.preview_path} ({os.path.getsize(self.preview_path)} bytes)")
            
        except Exception as e:
            self.logger.error(f"Preview generation exception: {e}", exc_info=True)
            self.preview_path = None
            
        progress.close()
        self.init_player()

    def closeEvent(self, event):
        if hasattr(self, 'player'):
            self.pause_video()
            self.player.setSource(QUrl())
        
        try:
            if getattr(sys, 'frozen', False):
                base_path = os.path.dirname(sys.executable)
            else:
                base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            recordings_dir = os.path.join(base_path, 'recordings')
            
            if os.path.exists(recordings_dir):
                self.logger.info(f"Cleaning up recordings dir: {recordings_dir}")
                for f in os.listdir(recordings_dir):
                    file_path = os.path.join(recordings_dir, f)
                    if os.path.isdir(file_path) and f == 'temp_export':
                        try:
                            shutil.rmtree(file_path)
                            self.logger.info(f"Deleted dir: {f}")
                        except Exception as e:
                            self.logger.error(f"Failed to delete dir {f}: {e}")
                        continue
                    # Modify: Do NOT delete temp_ files in root recordings dir to prevent data loss
                    # if os.path.isfile(file_path):
                    #     name_lower = f.lower()
                    #     if name_lower.startswith('temp_'):
                    #         try:
                    #             os.remove(file_path)
                    #             self.logger.info(f"Deleted: {f}")
                    #         except Exception as e:
                    #             self.logger.error(f"Failed to delete {f}: {e}")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

        super().closeEvent(event)


        
    def export_video(self):
        self.logger.info("Export button clicked")
        self.pause_video()
        self.sync_subtitles_with_timeline(silent=True)
        
        segments = self.timeline.get_segments()
        if not segments:
            QMessageBox.warning(self, "导出", "没有可导出的视频片段！")
            return

        # 1. Show Export Dialog
        try:
            self.logger.info("Opening Export Dialog...")
            dialog = ExportDialog(self, target_ratio=self.target_ratio, source_size=(self.video_width, self.video_height))
            if dialog.exec() != QDialog.Accepted:
                self.logger.info("Export Dialog cancelled")
                return
            target_w, target_h, target_fps = dialog.get_settings()
            self.logger.info(f"Export Settings: {target_w}x{target_h} @ {target_fps}fps")
        except Exception as e:
            self.logger.error(f"Dialog Error: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"打开导出窗口失败: {e}")
            return

        default_name = "LuScreen_edit.mp4"
        try:
            # 获取原始文件名（去除 _preview 后缀）
            base_name = os.path.basename(self.video_path)
            if "_preview" in base_name:
                base_name = base_name.replace("_preview", "")
            base_no_ext = os.path.splitext(base_name)[0]
            default_name = f"{base_no_ext}_edit.mp4"
        except Exception:
            pass

        # 优先使用视频文件所在的目录作为默认导出目录
        try:
            recordings_dir = os.path.dirname(os.path.abspath(self.video_path))
        except Exception:
            if getattr(sys, 'frozen', False):
                base_path = os.path.dirname(sys.executable)
            else:
                base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            recordings_dir = os.path.join(base_path, 'recordings')
        
        if not os.path.exists(recordings_dir):
            os.makedirs(recordings_dir)
            
        default_path = os.path.join(recordings_dir, default_name)
            
        path, _ = QFileDialog.getSaveFileName(self, "导出视频", default_path, "MP4 视频 (*.mp4)")
        if not path:
            return

        # Prepare Params
        use_gpu = self.config_manager.get("gpu_acceleration", False)
        # Double check license for GPU
        if not self.license_manager.can_use_gpu():
            use_gpu = False
        
        # Prepare Export Params
        export_params = {
            'segments': segments,
            'video_path': self.video_path,
            'metadata_path': self.metadata_path,
            'audio_mic': self.audio_mic,
            'audio_sys': self.audio_sys,
            'base_zoom': self.base_zoom,
            'click_zoom': self.click_zoom,
            'click_duration': self.click_duration,
            'watermark_text': self.watermark_text,
            'watermark_pos': self.watermark_pos,
            'watermark_pos_x': getattr(self, "watermark_pos_x", None),
            'watermark_pos_y': getattr(self, "watermark_pos_y", None),
            'watermark_size': self.watermark_size,
            'watermark_use_image': bool(getattr(self, "watermark_use_image", False)),
            'watermark_image_path': getattr(self, "watermark_image_path", None),
            'target_w': target_w,
            'target_h': target_h,
            'target_fps': target_fps,
            'use_gpu': use_gpu,
            'mic_vol': self.spin_mic_vol.value() if hasattr(self, 'spin_mic_vol') else 1.0,
            'sys_vol': self.spin_sys_vol.value() if hasattr(self, 'spin_sys_vol') else 1.0,
            'is_enhanced': hasattr(self, 'chk_enhance') and self.chk_enhance.isChecked(),
            'background_image_path': self.background_image_path,
            'bg_padding': self.bg_padding,
            'video_corner_radius': self.video_corner_radius,
            'canvas_width': self.canvas_frame.width(),
            'subtitle_path': self.srt_path,
            'subtitle_bg': getattr(self, "subtitle_bg", "none")
        }

        # Setup Progress Dialog
        self.export_progress = QProgressDialog("正在准备导出...", "取消", 0, 100, self)
        self.export_progress.setWindowModality(Qt.WindowModal)
        self.export_progress.setMinimumDuration(0)
        self.export_progress.setValue(0)
        self.export_progress.show()
        
        # Start Thread
        self.export_thread = ExportThread(self, path, export_params)
        self.export_thread.progress_updated.connect(self.on_export_progress)
        self.export_thread.finished_success.connect(self.on_export_success)
        self.export_thread.finished_error.connect(self.on_export_error)
        
        # Handle cancel
        self.export_progress.canceled.connect(self.export_thread.cancel)
        
        self.export_thread.start()

    def on_export_progress(self, value, label):
        if hasattr(self, 'export_progress'):
            self.export_progress.setValue(value)
            self.export_progress.setLabelText(label)

    def on_export_success(self, output_path):
        if hasattr(self, 'export_progress'):
            self.export_progress.close()
        QMessageBox.information(self, "导出成功", f"视频已保存至:\n{output_path}")
        open_folder_and_select_file(output_path)

    def on_export_error(self, error_msg):
        if hasattr(self, 'export_progress'):
            self.export_progress.close()
        
        if "Export canceled" in error_msg:
             print("Export canceled.")
        else:
             QMessageBox.critical(self, "导出失败", error_msg)
