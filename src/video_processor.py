import cv2
import json
import numpy as np
import os
import subprocess
import imageio_ffmpeg
import sys
import logging
import ctypes
import time
import threading
import queue
import importlib
import importlib.util
import importlib.machinery
from PIL import Image, ImageDraw, ImageFont
from src.utils import safe_add_dll_directory, get_runtime_base_dir

logger = logging.getLogger("VideoProcessor")

class SpringVariable:
    def __init__(self, value, stiffness=200.0, damping=20.0, mass=1.0):
        self.value = value
        self.target = value
        self.velocity = 0.0
        self.stiffness = stiffness
        self.damping = damping
        self.mass = mass

    def set_target(self, target):
        self.target = target

    def update(self, dt=1.0/30.0):
        force = -self.stiffness * (self.value - self.target) - self.damping * self.velocity
        acceleration = force / self.mass
        self.velocity += acceleration * dt
        self.value += self.velocity * dt
        return self.value

class VideoProcessor:
    def __init__(self, input_path, metadata_path, output_path, base_zoom=1.0, click_zoom=2.0, fps=30, start_time=0, end_time=None, click_duration=2.0, watermark_text="", watermark_pos="bottom-right", watermark_pos_x=None, watermark_pos_y=None, watermark_size=1.0, watermark_use_image=False, watermark_image_path=None, target_resolution=None, use_gpu=False, background_path=None, bg_padding_ratio=0.0, video_corner_radius_ratio=0.0):
        self.input_path = input_path
        self.metadata_path = metadata_path
        self.output_path = output_path
        self.base_zoom = max(1.0, base_zoom)
        self.click_zoom = max(self.base_zoom, click_zoom)
        self.target_fps = fps # The FPS user wants to export
        self.source_fps = fps # Will be detected from file
        self.start_time = start_time
        self.end_time = end_time
        self.click_duration = click_duration
        self.watermark_text = watermark_text
        self.watermark_pos = watermark_pos
        self.watermark_pos_x = watermark_pos_x
        self.watermark_pos_y = watermark_pos_y
        self.watermark_size = watermark_size
        self.watermark_use_image = bool(watermark_use_image)
        self.watermark_image_path = watermark_image_path
        self.target_resolution = target_resolution # (width, height)
        self.use_gpu = use_gpu
        self.background_path = background_path
        self.bg_padding_ratio = bg_padding_ratio
        self.video_corner_radius_ratio = video_corner_radius_ratio
        self.cursor_img = self._create_cursor()
        self.clicks = [] 
        self.watermark_overlay = None
        self.watermark_pos_xy = (0, 0)
        self.draw_cursor = True
        self.dpi_scale_x = 1.0
        self.dpi_scale_y = 1.0
        
        # Spring Physics State
        # Cap params: stiffness=200, damping=40, mass=2.25
        # Adjusted slightly for 30fps discrete steps
        self.spring_zoom = SpringVariable(self.base_zoom, stiffness=150.0, damping=25.0, mass=2.0)
        self.spring_cam_x = SpringVariable(0.0, stiffness=100.0, damping=20.0, mass=2.0) 
        self.spring_cam_y = SpringVariable(0.0, stiffness=100.0, damping=20.0, mass=2.0)
        self.rust_processor = None
        
    def _create_cursor(self):
        # Try to load custom cursor
        try:
            cursor_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'cursor.png')
            if getattr(sys, 'frozen', False):
                 cursor_path = os.path.join(os.path.dirname(sys.executable), 'assets', 'cursor.png')
            
            if os.path.exists(cursor_path):
                cursor = cv2.imread(cursor_path, cv2.IMREAD_UNCHANGED)
                if cursor is not None:
                    # Ensure 4 channels (BGRA)
                    if len(cursor.shape) == 2: # Grayscale
                        cursor = cv2.cvtColor(cursor, cv2.COLOR_GRAY2BGRA)
                    elif cursor.shape[2] == 3: # BGR
                        cursor = cv2.cvtColor(cursor, cv2.COLOR_BGR2BGRA)
                    
                    # Resize if too large
                    h, w = cursor.shape[:2]
                    if w > 64 or h > 64:
                        cursor = cv2.resize(cursor, (32, 32), interpolation=cv2.INTER_AREA)
                    
                    return cursor
        except Exception as e:
            print(f"Failed to load cursor.png: {e}")

        # Fallback to drawing default cursor
        w, h = 16, 24
        cursor = np.zeros((h, w, 4), dtype=np.uint8)
        pts = np.array([[0, 0], [0, 16], [4, 13], [7, 20], [9, 19], [6, 12], [11, 12]], np.int32)
        pts = pts.reshape((-1, 1, 2))
        cv2.fillPoly(cursor, [pts], (0, 0, 0, 255))
        pts_inner = np.array([[1, 2], [1, 14], [4, 11], [6, 17], [7, 16], [5, 11], [9, 11]], np.int32)
        cv2.fillPoly(cursor, [pts_inner], (255, 255, 255, 255))
        return cursor

    def _get_ffmpeg_path(self):
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
            local_ffmpeg = os.path.join(base_path, 'ffmpeg.exe')
            if os.path.exists(local_ffmpeg):
                return local_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()

    def process(self, progress_callback=None):
        # Set process priority to "Below Normal" to keep system responsive
        try:
            if sys.platform == 'win32':
                # 0x00004000 is BELOW_NORMAL_PRIORITY_CLASS
                ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
                print("[VideoProcessor] Process priority set to Below Normal (Windows)")
            else:
                os.nice(10) # Increase nice value (lower priority) on Unix
                print("[VideoProcessor] Process priority lowered (Unix)")
        except Exception as e:
            print(f"[VideoProcessor] Failed to set process priority: {e}")

        if not os.path.exists(self.input_path):
            print(f"[VideoProcessor] Input video not found: {self.input_path}")
            return False

        mouse_data = []
        self.draw_cursor = True # Default enabled

        if self.metadata_path and os.path.exists(self.metadata_path):
            print(f"[VideoProcessor] Loading metadata from {self.metadata_path}")
            try:
                with open(self.metadata_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        mouse_data = data.get('events', [])
                        if data.get('cursor_burned_in', False):
                            self.draw_cursor = False
                            print("[VideoProcessor] Cursor already burned in (Rust Core). Disabling software cursor.")
                    elif isinstance(data, list):
                        mouse_data = data
                
                # DPI Awareness Correction: 
                # If mouse_data exists, calculate the scale factor between recorded mouse coords (logical)
                # and video dimensions (physical).
                if len(mouse_data) > 0:
                    try:
                        # Get logical screen size
                        user32 = ctypes.windll.user32
                        logical_w = user32.GetSystemMetrics(0)
                        logical_h = user32.GetSystemMetrics(1)
                        
                        if logical_w > 0 and logical_h > 0:
                            self.dpi_scale_x = width / logical_w
                            self.dpi_scale_y = height / logical_h
                            if abs(self.dpi_scale_x - 1.0) > 0.05:
                                print(f"[VideoProcessor] DPI Scaling detected: {self.dpi_scale_x:.2f}x. Correcting coordinates.")
                    except:
                        pass # Fallback to 1.0
            except Exception as e:
                print(f"[VideoProcessor] Failed to load metadata: {e}")
                # Continue without metadata
        else:
            print("[VideoProcessor] No metadata found, processing as standard video.")

        cap = cv2.VideoCapture(self.input_path)
        if not cap.isOpened():
            print("[VideoProcessor] Failed to open input video")
            return False

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        real_fps = cap.get(cv2.CAP_PROP_FPS)
        if real_fps > 0:
            self.source_fps = real_fps
            
        ffmpeg_exe = self._get_ffmpeg_path()
        
        # Output resolution logic
        if self.target_resolution:
            out_w, out_h = self.target_resolution
        else:
            out_w, out_h = width, height
            
        # Ensure output dimensions are even (required for yuv420p / h264)
        out_w = (out_w // 2) * 2
        out_h = (out_h // 2) * 2
        
        # Aspect Ratio Handling: Fit inner video to output size without stretching
        # Calculate aspect ratios
        target_aspect = out_w / out_h
        source_aspect = width / height
        
        # Determine inner dimensions (letterboxing or pillarboxing)
        # Apply padding if background is active
        padding_px = 0
        if self.background_path and os.path.exists(self.background_path):
            padding_px = int(out_w * self.bg_padding_ratio)
            
        avail_w = max(1, out_w - padding_px * 2)
        avail_h = max(1, out_h - padding_px * 2)
        
        # Recalculate aspect fit within available area
        target_aspect = avail_w / avail_h
        
        if abs(target_aspect - source_aspect) > 0.01:
            # Aspect ratios differ, need to fit
            if source_aspect > target_aspect:
                # Source is wider than target -> Letterbox (black bars top/bottom)
                # Fit width
                inner_w = avail_w
                inner_h = int(avail_w / source_aspect)
                offset_x = padding_px
                offset_y = padding_px + (avail_h - inner_h) // 2
            else:
                # Source is taller than target -> Pillarbox (black bars left/right)
                # Fit height
                inner_h = avail_h
                inner_w = int(avail_h * source_aspect)
                offset_x = padding_px + (avail_w - inner_w) // 2
                offset_y = padding_px
        else:
            # Same aspect ratio
            inner_w, inner_h = avail_w, avail_h
            offset_x, offset_y = padding_px, padding_px
            
        # Background Image Logic (Overrides black bars if present)
        bg_image = None
        
        if self.background_path and os.path.exists(self.background_path):
            try:
                bg_raw = cv2.imread(self.background_path)
                if bg_raw is not None:
                    bg_image = cv2.resize(bg_raw, (out_w, out_h), interpolation=cv2.INTER_AREA)
            except Exception as e:
                print(f"[VideoProcessor] Failed to load background: {e}")
            
        # Pre-render watermark
        self._prepare_watermark(out_w, out_h)

        # Initialize processors (Rust/GPU) before starting FFmpeg so we can choose pipe pix_fmt safely
        self.rust_processor = None
        self.gpu_processor = None
        try:
            rust_core = self._load_rust_core()
            ParallelProcessor = getattr(rust_core, "ParallelProcessor", None)
            GpuProcessor = getattr(rust_core, "GpuProcessor", None)
            if ParallelProcessor is None or GpuProcessor is None:
                raise ImportError("rust_core extension not available")

            bg_bytes = bg_image.tobytes() if bg_image is not None else None

            use_cursor = self.cursor_img is not None and self.draw_cursor
            cursor_bytes = self.cursor_img.tobytes() if use_cursor else None
            cursor_w = self.cursor_img.shape[1] if use_cursor else 0
            cursor_h = self.cursor_img.shape[0] if use_cursor else 0

            wm_bytes = self.watermark_overlay.tobytes() if self.watermark_overlay is not None else None

            if self.use_gpu:
                try:
                    self.gpu_processor = GpuProcessor(
                        out_w, out_h,
                        bg_bytes,
                        cursor_bytes, cursor_w, cursor_h,
                        wm_bytes, self.watermark_overlay.shape[1] if self.watermark_overlay is not None else 0,
                        self.watermark_overlay.shape[0] if self.watermark_overlay is not None else 0,
                        self.watermark_pos_xy[0] if self.watermark_overlay is not None else 0,
                        self.watermark_pos_xy[1] if self.watermark_overlay is not None else 0,
                        self.bg_padding_ratio,
                        self.video_corner_radius_ratio
                    )
                    print(f"[VideoProcessor] VIP Extreme Engine (GPU) Initialized")
                except Exception as gpu_e:
                    logger.error(f"GPU Processor initialization failed: {gpu_e}")
                    self.gpu_processor = None

            if self.gpu_processor is None:
                try:
                    self.rust_processor = ParallelProcessor(
                        out_w, out_h,
                        bg_bytes,
                        cursor_bytes,
                        cursor_w, cursor_h,
                        wm_bytes, self.watermark_overlay.shape[1] if self.watermark_overlay is not None else 0,
                        self.watermark_overlay.shape[0] if self.watermark_overlay is not None else 0,
                        self.watermark_pos_xy[0] if self.watermark_overlay is not None else 0,
                        self.watermark_pos_xy[1] if self.watermark_overlay is not None else 0,
                        self.bg_padding_ratio,
                        self.video_corner_radius_ratio,
                        None,
                        True,
                    )
                    print(f"[VideoProcessor] Rust Parallel Processor (CPU) Initialized")
                except Exception as cpu_e:
                    logger.error(f"Parallel Processor initialization failed: {cpu_e}")
                    self.rust_processor = None
        except ImportError:
            self.rust_processor = None
            self.gpu_processor = None

        # Input parameters (raw stream)
        input_fps = self.source_fps
        if self.source_fps > self.target_fps + 0.1: # Downsampling
             input_fps = self.target_fps
        
        # VIP GPU Optimization: Enable Hardware Decoding for input if GPU is active
        # This reduces CPU load during frame extraction
        hwaccel_args = []
        if self.use_gpu:
            # We use 'auto' to support NVIDIA/Intel/AMD based on availability
            hwaccel_args = ['-hwaccel', 'auto']
            print(f"[VideoProcessor] VIP GPU Optimization: Hardware Decoding Enabled (-hwaccel auto)")

        if self.gpu_processor is not None:
            input_pix_fmt = 'nv12'
        elif self.rust_processor is not None:
            input_pix_fmt = 'yuv420p'
        else:
            input_pix_fmt = 'bgr24'

        input_args = hwaccel_args + [
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-pix_fmt', input_pix_fmt,
            '-s', f"{out_w}x{out_h}", 
            '-r', str(input_fps),
            '-i', '-'
        ]
        
        # Output encoding parameters
        # Output FPS is what user requested
        output_args = []
        
        if self.use_gpu:
            # VIP Optimization: High Quality NVENC settings
            # CQ 19 is visually near-lossless for 1080p
            cq_value = '19' 
            if out_w >= 3000: # 4K
                cq_value = '23'
            elif out_w >= 2000: # 2K
                cq_value = '21'

            # NVENC encoding
            # VIP Optimization: Use 'p4' instead of 'p6' for significantly higher speed with minimal quality loss
            # 借鉴 Cap: 开启空间和时间自适应量化 (AQ) 提升缩放场景下的画面锐度
            output_args = [
                '-c:v', 'h264_nvenc',
                '-preset', 'p4',    # P1-P7, P4 is a good balance (Medium)
                '-tune', 'll',      # Low latency tuning for speed
                '-rc', 'vbr',       # Variable Bitrate
                '-cq', cq_value, 
                '-spatial-aq', '1', # 开启空间自适应量化
                '-temporal-aq', '1',# 开启时间自适应量化
                '-b:v', '0',        # Let CQ control bitrate
                '-profile:v', 'high',
                '-pix_fmt', 'yuv420p',
                '-color_range', '1', # 1 = Limited range (Standard for video)
                '-r', str(self.target_fps),
                self.output_path
            ]
        else:
            # CPU encoding
            # Use ultrafast for maximum speed
            output_args = [
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-tune', 'zerolatency', # Added for speed
                '-crf', '20', 
                '-pix_fmt', 'yuv420p',
                '-r', str(self.target_fps),
                self.output_path
            ]
    
        # VIP Pipe Optimization: Increase buffer size
        cmd = [ffmpeg_exe, '-y'] + input_args + output_args
        
        print(f"[VideoProcessor] Starting FFmpeg (GPU={self.use_gpu}).")
        print(f"[VideoProcessor] Output Configuration: {out_w}x{out_h} @ {self.target_fps}fps")
        mode = "GPU Extreme" if self.gpu_processor is not None else ("Rust Parallel" if self.rust_processor is not None else "Python Serial")
        print(f"[VideoProcessor] Input FPS: {self.source_fps}, Processing Mode: {mode}")
        print(f"[VideoProcessor] Cmd: {' '.join(cmd)}")

        # DEBUG: Debug CSV Logging
        debug_log_file = None
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            logs_dir = os.path.join(base_dir, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            debug_csv_path = os.path.join(logs_dir, f"vp_debug_{int(time.time())}.csv")
            debug_log_file = open(debug_csv_path, "w", encoding="utf-8")
            debug_log_file.write("frame,zoom,cam_x,cam_y,mx,my,click,vw,vh,cx1,cy1,cx2,cy2\n")
            print(f"[VideoProcessor] Debug logging enabled: {debug_csv_path}")
        except Exception as e:
            print(f"[VideoProcessor] Failed to open debug log: {e}")

        try:
            # Set creationflags to BELOW_NORMAL_PRIORITY_CLASS (0x00004000) for the subprocess
            creation_flags = 0
            if sys.platform == 'win32':
                creation_flags = 0x00004000 # BELOW_NORMAL_PRIORITY_CLASS
                
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=creation_flags)
        except Exception as e:
            print(f"[VideoProcessor] Failed to start FFmpeg: {e}")
            return False

        # 虚拟摄像机状态
        # Initialize spring variables with correct starting position
        self.spring_cam_x.value = width / 2.0
        self.spring_cam_x.target = width / 2.0
        self.spring_cam_y.value = height / 2.0
        self.spring_cam_y.target = height / 2.0
        self.spring_zoom.value = self.base_zoom
        self.spring_zoom.target = self.base_zoom
        
        # 缩放状态
        click_timer = 0
        CLICK_DURATION_FRAMES = int(self.source_fps * self.click_duration) 
        last_click_focus_x = width / 2.0
        last_click_focus_y = height / 2.0
        
        frame_idx = 0
        mouse_idx = 0 # Current pointer in mouse_data for timestamp-based lookup
        last_click_state = False
        
        print(f"[VideoProcessor] Processing {total_frames} frames...")
        
        start_frame = int(self.start_time * self.source_fps)
        end_frame = int(self.end_time * self.source_fps) if self.end_time else total_frames
        
        # Optimization: Seek to start frame
        if start_frame > 0:
            print(f"[VideoProcessor] Seeking to frame {start_frame}...")
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            frame_idx = start_frame
            
            # Pre-warm springs to avoid jump at start if we seek
            # Need to get mouse position at start_frame? 
            # Ideally we'd simulate from 0, but that's slow. 
            # We'll just reset to center or first known mouse pos.
            if frame_idx < len(mouse_data):
                self.spring_cam_x.value = width / 2.0
                self.spring_cam_x.target = width / 2.0
                self.spring_cam_y.value = height / 2.0
                self.spring_cam_y.target = height / 2.0
        
        # Pre-allocate buffers
        print(f"[VideoProcessor] Allocating buffers: {out_w}x{out_h}")
        final_frame = np.zeros((out_h, out_w, 3), dtype=np.uint8)
        
        if self.rust_processor is None and self.gpu_processor is None:
            print("[VideoProcessor] rust_core not found, using Python fallback")
        
        # Pre-allocate resize buffer if needed (for standard non-zoom resize)
        # Only if inner dimensions differ from source and we aren't zooming constantly
        resize_buffer = None
        if inner_w != width or inner_h != height:
             resize_buffer = np.zeros((inner_h, inner_w, 3), dtype=np.uint8)
        
        # Optimization: Frame skipping logic
        write_interval = 1.0
        should_skip_frames = False
        next_write_frame = 0.0
        
        if self.source_fps > self.target_fps + 0.1:
            should_skip_frames = True
            write_interval = self.source_fps / self.target_fps
            # Reset next_write_frame relative to start of processing
            next_write_frame = float(frame_idx)
            print(f"[VideoProcessor] Downsampling optimization enabled: {self.source_fps} -> {self.target_fps} (Ratio: {write_interval:.2f})")
        
        had_write_error = False
        batch_frames = []
        batch_params = []
        batch_clicks = []
        # VIP Optimization: Balanced Batch Size (48) for throughput and keeping GPU in High P-State
        BATCH_SIZE = 48 if (self.rust_processor and self.use_gpu) else (16 if self.rust_processor else 1)
        
        # VIP Extreme Pipeline: 3-Stage Multi-threaded Architecture
        # Stage 1: Reader (CPU Decoding)
        # Stage 2: Processor (Physics + GPU Processing)
        # Stage 3: Writer (FFmpeg I/O)
        
        # Increase queue sizes to allow better buffering and mask IO latency
        raw_frames_queue = queue.Queue(maxsize=BATCH_SIZE * 3)
        write_queue = queue.Queue(maxsize=8)
        
        stop_pipeline = False
        
        def reader_worker():
            nonlocal frame_idx, stop_pipeline
            curr_idx = frame_idx
            curr_next_write = next_write_frame
            
            while not stop_pipeline:
                if not cap.isOpened():
                    break
                
                ret = cap.grab()
                if not ret:
                    break
                
                is_write_frame = True
                if should_skip_frames:
                    if curr_idx < int(curr_next_write):
                        is_write_frame = False
                    else:
                        curr_next_write += write_interval
                
                if is_write_frame:
                    ret_retrieve, frame = cap.retrieve()
                    if ret_retrieve and frame is not None:
                        # Put to queue. If queue is full, this blocks, providing backpressure.
                        raw_frames_queue.put((frame, curr_idx))
                    else:
                        break
                curr_idx += 1
            raw_frames_queue.put(None) # EOF signal

        def writer_worker():
            nonlocal had_write_error
            while True:
                item = write_queue.get()
                if item is None:
                    break
                try:
                    process.stdin.write(item)
                except Exception as e:
                    logger.error(f"FFmpeg write error: {e}")
                    had_write_error = True
                write_queue.task_done()

        # Start Reader and Writer threads
        reader_thread = threading.Thread(target=reader_worker, daemon=True)
        writer_thread = threading.Thread(target=writer_worker, daemon=True)
        reader_thread.start()
        writer_thread.start()

        print(f"[VideoProcessor] Pipeline started. Batch size: {BATCH_SIZE}")
        
        # Main Loop: Stage 2 (Processor)
        try:
            while True:
                item = raw_frames_queue.get()
                if item is None:
                    break
                
                frame, f_idx = item

                # Yield every 4 frames to keep system responsive without killing performance
                if f_idx % 4 == 0:
                    time.sleep(0.001)
                
                # 1. Physics & State Update
                dt = 1.0 / self.source_fps if self.source_fps > 0 else 0.033
                mx, my, click, current_zoom, cam_x, cam_y, current_frame_clicks, click_timer, last_click_focus_x, last_click_focus_y, mouse_idx = \
                    self._update_state(f_idx, mouse_data, mouse_idx, width, height, dt, last_click_state, click_timer, last_click_focus_x, last_click_focus_y)
                
                # DEBUG: Log Frame Data
                if debug_log_file:
                    try:
                        vw, vh = width / current_zoom, height / current_zoom
                        cx1, cy1 = max(0, int(cam_x - vw/2)), max(0, int(cam_y - vh/2))
                        cx2, cy2 = min(width, int(cx1 + vw)), min(height, int(cy1 + vh))
                        debug_log_file.write(f"{f_idx},{current_zoom:.6f},{cam_x:.2f},{cam_y:.2f},{mx:.2f},{my:.2f},{click},{vw:.2f},{vh:.2f},{cx1},{cy1},{cx2},{cy2}\n")
                        if f_idx % 100 == 0: debug_log_file.flush()
                    except: pass
                
                last_click_state = click
                
                # 2. Batching
                if self.gpu_processor:
                    batch_frames.append(frame)
                else:
                    batch_frames.append(frame.tobytes())
                
                batch_params.append((current_zoom, cam_x, cam_y, mx, my))
                batch_clicks.append(current_frame_clicks)
                
                if len(batch_frames) >= BATCH_SIZE:
                    if self.gpu_processor:
                        processed_batch = self.gpu_processor.process_batch(batch_frames, width, height, batch_params, batch_clicks)
                    elif self.rust_processor:
                        processed_batch = self.rust_processor.process_batch(batch_frames, width, height, batch_params, batch_clicks)
                    else:
                        # Python fallback (slow, but kept for robustness)
                        processed_frames = []
                        for i in range(len(batch_frames)):
                            f = np.frombuffer(batch_frames[i], dtype=np.uint8).reshape((height, width, 3))
                            zoom, cam_x, cam_y, mx, my = batch_params[i]
                            clicks = batch_clicks[i]
                            
                            # 1. Physics-based Crop & Resize
                            vw, vh = width / zoom, height / zoom
                            cx1, cy1 = max(0, int(cam_x - vw/2)), max(0, int(cam_y - vh/2))
                            # Ensure even dimensions for crop to prevent resize artifacts
                            cx2, cy2 = min(width, int(cx1 + vw)), min(height, int(cy1 + vh))
                            
                            # Ensure crop coordinates are valid and dimensions are even
                            if (cx2 - cx1) % 2 != 0: cx2 -= 1
                            if (cy2 - cy1) % 2 != 0: cy2 -= 1
                            
                            if cx2 <= cx1: cx2 = cx1 + 2
                            if cy2 <= cy1: cy2 = cy1 + 2
                            
                            crop = f[cy1:cy2, cx1:cx2]
                            
                            # Calculate inner dimensions (fit logic)
                            pad_px = int(out_w * self.bg_padding_ratio)
                            avail_w, avail_h = max(2, out_w - 2*pad_px), max(2, out_h - 2*pad_px)
                            
                            src_aspect = width / max(1, height)
                            tgt_aspect = avail_w / avail_h
                            
                            if src_aspect > tgt_aspect:
                                inner_w = avail_w
                                inner_h = int(avail_w / src_aspect)
                                off_x, off_y = pad_px, pad_px + (avail_h - inner_h) // 2
                            else:
                                inner_h = avail_h
                                inner_w = int(avail_h * src_aspect)
                                off_x, off_y = pad_px + (avail_w - inner_w) // 2, pad_px
                            
                            # Ensure even dimensions
                            inner_w = (inner_w // 2) * 2
                            inner_h = (inner_h // 2) * 2
                            inner_w = max(2, inner_w)
                            inner_h = max(2, inner_h)
                                
                            inner_video = cv2.resize(crop, (inner_w, inner_h), interpolation=cv2.INTER_AREA)
                            
                            # 2. Composite onto Background
                            frame_out = bg_image.copy() if bg_image is not None else np.zeros((out_h, out_w, 3), dtype=np.uint8)
                            
                            if self.video_corner_radius_ratio > 0:
                                # Apply Rounded Corners
                                mask = np.zeros((inner_h, inner_w), dtype=np.uint8)
                                r = int(self.video_corner_radius_ratio * out_w)
                                r = min(r, inner_w // 2, inner_h // 2)
                                if r > 0:
                                    cv2.rectangle(mask, (r, 0), (inner_w - r, inner_h), 255, -1)
                                    cv2.rectangle(mask, (0, r), (inner_w, inner_h - r), 255, -1)
                                    cv2.circle(mask, (r, r), r, 255, -1)
                                    cv2.circle(mask, (inner_w - r, r), r, 255, -1)
                                    cv2.circle(mask, (r, inner_h - r), r, 255, -1)
                                    cv2.circle(mask, (inner_w - r, inner_h - r), r, 255, -1)
                                else:
                                    mask[:] = 255
                                
                                # Blend using mask
                                mask_3ch = cv2.merge([mask, mask, mask]) / 255.0
                                roi = frame_out[off_y:off_y+inner_h, off_x:off_x+inner_w]
                                if roi.shape[:2] == inner_video.shape[:2]:
                                    frame_out[off_y:off_y+inner_h, off_x:off_x+inner_w] = (inner_video * mask_3ch + roi * (1 - mask_3ch)).astype(np.uint8)
                            else:
                                frame_out[off_y:off_y+inner_h, off_x:off_x+inner_w] = inner_video
                                
                            # 3. Overlays
                            # Scale cursor/clicks to inner_video coords then offset
                            scale_x, scale_y = inner_w / (cx2 - cx1), inner_h / (cy2 - cy1)
                            
                            for cx, cy, radius, alpha in clicks:
                                dcx = int((cx - cx1) * scale_x + off_x)
                                dcy = int((cy - cy1) * scale_y + off_y)
                                cv2.circle(frame_out, (dcx, dcy), int(radius), (0, 0, 255), 2) # Simple ripple
                                
                            if self.cursor_img is not None:
                                dcx = int((mx - cx1) * scale_x + off_x)
                                dcy = int((my - cy1) * scale_y + off_y)
                                self._overlay_cursor(frame_out, dcx, dcy)
                                
                            self._overlay_watermark(frame_out)
                            processed_frames.append(frame_out.tobytes())
                            
                        processed_batch = b"".join(processed_frames)                    
                    if processed_batch:
                        write_queue.put(processed_batch)
                    
                    batch_frames = []; batch_params = []; batch_clicks = []
                
                # Progress reporting
                if f_idx % 30 == 0:
                    print(f"[VideoProcessor] Processing frame {f_idx}/{total_frames}", end='\r')
                    if progress_callback and end_frame > start_frame:
                        progress_callback(max(0.0, min(1.0, (f_idx - start_frame) / (end_frame - start_frame))))

            # Final batch
            if batch_frames:
                if self.gpu_processor:
                    processed_batch = self.gpu_processor.process_batch(batch_frames, width, height, batch_params, batch_clicks)
                elif self.rust_processor:
                    processed_batch = self.rust_processor.process_batch(batch_frames, width, height, batch_params, batch_clicks)
                else:
                    processed_batch = None
                
                if processed_batch:
                    write_queue.put(processed_batch)

        except Exception as e:
            logger.error(f"Processing loop failed: {e}")
            import traceback
            traceback.print_exc()
            stop_pipeline = True
        
        # Shutdown
        if debug_log_file:
            try: debug_log_file.close()
            except: pass
        write_queue.put(None)
        writer_thread.join()
        reader_thread.join()
        process.stdin.close()
        process.wait()
        
        if process.returncode != 0:
            logger.error(f"[VideoProcessor] FFmpeg failed with code {process.returncode}")
            return False
        if had_write_error:
            return False
            
        # Prepare for audio merging
        import shutil
        temp_dir = os.path.join(os.path.dirname(self.output_path), "temp_video_proc_" + str(int(time.time())))
        os.makedirs(temp_dir, exist_ok=True)
        temp_video_path = os.path.join(temp_dir, "video_only.mp4")
        
        try:
            if os.path.exists(self.output_path):
                shutil.move(self.output_path, temp_video_path)
            else:
                return False
        except Exception as e:
            logger.error(f"Failed to move video: {e}")
            return False

        # Merge audio if present in original
        has_audio = False
        try:
             # Check for audio stream
             ffprobe = ffmpeg_exe.replace('ffmpeg.exe', 'ffprobe.exe')
             if os.path.exists(ffprobe):
                 cmd = [ffprobe, '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', self.input_path]
                 creationflags = subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
                 res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
                 if len(res.stdout) > 0:
                     has_audio = True
        except:
             pass
        
        if has_audio:
            # Extract audio first to avoid complex filter chains in one go
            temp_audio = os.path.join(temp_dir, "merged_audio.wav")
            try:
                creationflags = subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
                subprocess.run([ffmpeg_exe, '-y', '-i', self.input_path, '-vn', '-acodec', 'pcm_s16le', temp_audio], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=creationflags)
            except Exception as e:
                 print(f"[VideoProcessor] Audio extraction failed: {e}")
                 has_audio = False
            
            if has_audio and os.path.exists(temp_audio):
                final_cmd = [
                    ffmpeg_exe, '-y',
                    '-nostats', '-loglevel', 'error', 
                    '-progress', 'pipe:1',
                    '-i', temp_video_path,
                    '-i', temp_audio,
                    '-c:v', 'copy',
                    '-c:a', 'aac', '-b:a', '192k',
                    '-movflags', '+faststart',
                    '-map', '0:v', '-map', '1:a',
                    self.output_path
                ]
            else:
                # Fallback to video only copy
                final_cmd = [
                    ffmpeg_exe, '-y',
                    '-i', temp_video_path,
                    '-c', 'copy',
                    self.output_path
                ]
        else:
             final_cmd = [
                ffmpeg_exe, '-y',
                '-i', temp_video_path,
                '-c', 'copy',
                self.output_path
            ]
            
        print(f"[Export] Final CMD: {' '.join(final_cmd)}")
        
        try:
            # Use Popen to capture realtime progress if needed, but for now simple run
            startupinfo = None
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            ret = subprocess.run(
                final_cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
            )
            
            if ret.returncode != 0:
                print(f"[Export] Merge failed: {ret.stderr.decode(errors='ignore')}")
                if os.path.exists(temp_video_path) and not os.path.exists(self.output_path):
                     shutil.copy(temp_video_path, self.output_path)
                return False
        except Exception as e:
            print(f"[Export] Critical subprocess error: {e}")
            if os.path.exists(temp_video_path) and not os.path.exists(self.output_path):
                 shutil.copy(temp_video_path, self.output_path)
            return False
            
        # Cleanup
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except: pass
        
        acc_mode = "GPU (NVENC)" if self.use_gpu else "CPU (x264)"
        logger.info(f"[VideoProcessor] Done. Acceleration: {acc_mode}. Output: {self.output_path}")
        return True

    @staticmethod
    def _load_rust_core(required_attrs=("ParallelProcessor", "GpuProcessor"), context="video_processor"):
        required_attrs = tuple(required_attrs or ())
        details = []

        def _missing_attrs(mod):
            missing = []
            for attr in required_attrs:
                if not hasattr(mod, attr):
                    missing.append(attr)
            return missing

        try:
            m = importlib.import_module("rust_core")
            missing = _missing_attrs(m)
            if not missing:
                return m
            details.append(f"import_module缺少属性:{','.join(missing)}")
        except Exception as e:
            details.append(f"import_module失败:{type(e).__name__}:{e}")

        project_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        runtime_base = get_runtime_base_dir()
        exe_base = ""
        try:
            exe_base = os.path.dirname(sys.executable)
        except Exception:
            exe_base = ""

        base_dirs = [
            project_base,
            os.path.join(project_base, "rust_src", "target", "maturin"),
            os.path.join(project_base, "rust_src", "target", "release"),
            os.path.join(project_base, "rust_src", "target", "debug"),
        ]
        if runtime_base:
            base_dirs.extend([
                runtime_base,
                os.path.join(runtime_base, "rust_src", "target", "maturin"),
                os.path.join(runtime_base, "rust_src", "target", "release"),
                os.path.join(runtime_base, "rust_src", "target", "debug"),
            ])
        if exe_base:
            base_dirs.extend([
                exe_base,
                os.path.join(exe_base, "rust_src", "target", "maturin"),
                os.path.join(exe_base, "rust_src", "target", "release"),
                os.path.join(exe_base, "rust_src", "target", "debug"),
            ])

        unique_dirs = []
        seen_dirs = set()
        for d in base_dirs:
            if not d:
                continue
            n = os.path.normcase(os.path.abspath(d))
            if n in seen_dirs:
                continue
            seen_dirs.add(n)
            unique_dirs.append(d)

        suffixes = list(importlib.machinery.EXTENSION_SUFFIXES)
        for extra in [".pyd", ".dll"]:
            if extra not in suffixes:
                suffixes.append(extra)

        candidates = []
        seen_files = set()
        for d in unique_dirs:
            for suffix in suffixes:
                p = os.path.join(d, f"rust_core{suffix}")
                key = os.path.normcase(os.path.abspath(p))
                if key in seen_files:
                    continue
                seen_files.add(key)
                candidates.append(p)

        for p in candidates:
            if not os.path.exists(p):
                continue
            try:
                safe_add_dll_directory(os.path.dirname(os.path.abspath(p)))
            except Exception as e:
                details.append(f"dll目录失败:{p}:{type(e).__name__}:{e}")
            try:
                if "rust_core" in sys.modules:
                    del sys.modules["rust_core"]
                loader = importlib.machinery.ExtensionFileLoader("rust_core", p)
                spec = importlib.util.spec_from_file_location("rust_core", p, loader=loader)
                if spec is None:
                    details.append(f"spec为空:{p}")
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules["rust_core"] = mod
                loader.exec_module(mod)
                missing = _missing_attrs(mod)
                if not missing:
                    return mod
                details.append(f"文件加载缺少属性:{p}:{','.join(missing)}")
                try:
                    del sys.modules["rust_core"]
                except Exception:
                    pass
            except Exception as e:
                details.append(f"文件加载失败:{p}:{type(e).__name__}:{e}")
                try:
                    if "rust_core" in sys.modules:
                        del sys.modules["rust_core"]
                except Exception:
                    pass

        msg = " | ".join(details[-8:]) if details else "无可用候选文件"
        logger.error(f"[RustCore] 加载失败 context={context}: {msg}")
        raise ImportError(f"rust_core extension not loadable ({context})")

    def _prepare_watermark(self, w, h):
        use_image = bool(getattr(self, "watermark_use_image", False))
        image_path = getattr(self, "watermark_image_path", None)
        if use_image and image_path and os.path.exists(str(image_path)):
            try:
                base_scale = (h / 1080.0) * float(self.watermark_size or 1.0)
                margin = int(20 * base_scale)
                max_w = max(16, int(w * 0.35))
                max_h = max(16, int(h * 0.20))
                desired_h = max(16, int(h * 0.12 * float(self.watermark_size or 1.0)))

                img_pil = Image.open(str(image_path)).convert("RGBA")
                iw, ih = img_pil.size
                if iw > 0 and ih > 0:
                    new_h = min(max_h, desired_h)
                    new_w = int((float(iw) / float(ih)) * float(new_h))
                    if new_w > max_w:
                        new_w = max_w
                        new_h = max(16, int((float(ih) / float(iw)) * float(new_w)))
                    if new_w < 16 or new_h < 16:
                        new_w = max(16, new_w)
                        new_h = max(16, new_h)
                    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", getattr(Image, "LANCZOS", 1))
                    img_pil = img_pil.resize((int(new_w), int(new_h)), resample=resample)

                self.watermark_overlay = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGBA2BGRA)
                canvas_h, canvas_w = self.watermark_overlay.shape[:2]

                if self.watermark_pos == 'custom' and self.watermark_pos_x is not None and self.watermark_pos_y is not None:
                    try:
                        nx = float(self.watermark_pos_x)
                        ny = float(self.watermark_pos_y)
                    except Exception:
                        nx, ny = 0.0, 0.0
                    nx = max(0.0, min(1.0, nx))
                    ny = max(0.0, min(1.0, ny))
                    max_x = max(0, int(w - canvas_w))
                    max_y = max(0, int(h - canvas_h))
                    self.watermark_pos_xy = (int(nx * max_x), int(ny * max_y))
                elif self.watermark_pos == 'top-left':
                    self.watermark_pos_xy = (margin, margin)
                elif self.watermark_pos == 'top-right':
                    self.watermark_pos_xy = (w - canvas_w - margin, margin)
                elif self.watermark_pos == 'bottom-left':
                    self.watermark_pos_xy = (margin, h - canvas_h - margin)
                else:
                    self.watermark_pos_xy = (w - canvas_w - margin, h - canvas_h - margin)
                return
            except Exception:
                self.watermark_overlay = None

        if not self.watermark_text:
            self.watermark_overlay = None
            return

        base_scale = (h / 1080.0) * self.watermark_size
        font_size = max(12, int(40 * base_scale))
        margin = int(20 * base_scale)
        shadow_offset = max(1, int(2 * base_scale))

        font = None
        font_paths = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'JasonHandwriting1.ttf')
        ]
        if getattr(sys, 'frozen', False):
             font_paths.insert(0, os.path.join(os.path.dirname(sys.executable), 'assets', 'JasonHandwriting1.ttf'))

        for path in font_paths:
            if os.path.exists(path):
                try:
                    font = ImageFont.truetype(path, font_size)
                    break
                except:
                    continue
        if font is None:
            font = ImageFont.load_default()

        # Measure text size
        dummy_draw = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        bbox = dummy_draw.textbbox((0, 0), self.watermark_text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        # Create canvas for watermark
        canvas_w = text_w + shadow_offset + 10
        canvas_h = text_h + shadow_offset + 10

        img_pil = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img_pil)

        # Draw shadow and text
        draw.text((shadow_offset, shadow_offset), self.watermark_text, font=font, fill=(0, 0, 0, 255))
        draw.text((0, 0), self.watermark_text, font=font, fill=(255, 255, 255, 255))

        # Convert to OpenCV BGRA
        self.watermark_overlay = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGBA2BGRA)

        # Calculate position
        if self.watermark_pos == 'top-left':
            self.watermark_pos_xy = (margin, margin)
        elif self.watermark_pos == 'top-right':
            self.watermark_pos_xy = (w - canvas_w - margin, margin)
        elif self.watermark_pos == 'bottom-left':
            self.watermark_pos_xy = (margin, h - canvas_h - margin)
        else: # bottom-right
            self.watermark_pos_xy = (w - canvas_w - margin, h - canvas_h - margin)

    def _overlay_watermark(self, frame):
        if self.watermark_overlay is None: return
        
        overlay = self.watermark_overlay
        x, y = self.watermark_pos_xy
        x, y = int(x), int(y)
        
        h, w = frame.shape[:2]
        ch, cw = overlay.shape[:2]
        
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(w, x + cw)
        y2 = min(h, y + ch)
        
        cx1 = x1 - x
        cy1 = y1 - y
        cx2 = cx1 + (x2 - x1)
        cy2 = cy1 + (y2 - y1)
        
        if x2 > x1 and y2 > y1:
            c_slice = overlay[cy1:cy2, cx1:cx2]
            f_slice = frame[y1:y2, x1:x2]
            
            # Alpha blending
            alpha = c_slice[:, :, 3] / 255.0
            alpha = alpha[:, :, np.newaxis]
            
            f_slice[:] = (c_slice[:, :, :3] * alpha + f_slice * (1 - alpha)).astype(np.uint8)

    def _overlay_cursor(self, frame, x, y):
        cursor = self.cursor_img
        h, w = frame.shape[:2]
        ch, cw = cursor.shape[:2]
        
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(w, x + cw)
        y2 = min(h, y + ch)
        
        cx1 = x1 - x
        cy1 = y1 - y
        cx2 = cx1 + (x2 - x1)
        cy2 = cy1 + (y2 - y1)
        
        if x2 > x1 and y2 > y1:
            c_slice = cursor[cy1:cy2, cx1:cx2]
            f_slice = frame[y1:y2, x1:x2]
            
            alpha = c_slice[:, :, 3] / 255.0
            alpha = alpha[:, :, np.newaxis]
            
            f_slice[:] = (c_slice[:, :, :3] * alpha + f_slice * (1 - alpha)).astype(np.uint8)

    def _update_state(self, frame_idx, mouse_data, mouse_idx, width, height, dt, last_click_state, click_timer, last_click_focus_x, last_click_focus_y):
        """Helper to update physics and camera state for a frame"""
        mx, my = width/2, height/2
        click = False
        
        if len(mouse_data) > 0:
            current_time = frame_idx / self.source_fps
            
            # Smart Lookup: If metadata has timestamps 't', use them. 
            # Otherwise fallback to index (Python mode legacy or fixed FPS)
            has_timestamps = 't' in mouse_data[0]
            
            if has_timestamps:
                # Advance mouse_idx to match current_time
                while mouse_idx < len(mouse_data) - 1 and mouse_data[mouse_idx]['t'] < current_time:
                    mouse_idx += 1
                
                m = mouse_data[mouse_idx]
                mx = m['x'] * self.dpi_scale_x
                my = m['y'] * self.dpi_scale_y
                if 'region_x' in m:
                    mx -= m['region_x'] * self.dpi_scale_x
                    my -= m['region_y'] * self.dpi_scale_y
                click = m['click']
            else:
                # Legacy Index Lookup
                if frame_idx < len(mouse_data):
                    m = mouse_data[frame_idx]
                    mx = m['x'] * self.dpi_scale_x
                    my = m['y'] * self.dpi_scale_y
                    if 'region_x' in m:
                        mx -= m['region_x'] * self.dpi_scale_x
                        my -= m['region_y'] * self.dpi_scale_y
                    click = m['click']
                else:
                    m = mouse_data[-1]
                    mx = m['x'] * self.dpi_scale_x
                    my = m['y'] * self.dpi_scale_y
                    if 'region_x' in m:
                        mx -= m['region_x'] * self.dpi_scale_x
                        my -= m['region_y'] * self.dpi_scale_y
                    click = False
        
        new_click_started = False
        if click and not last_click_state:
            new_click_started = True
            click_timer = int(self.source_fps * self.click_duration)
            last_click_focus_x = mx
            last_click_focus_y = my
        
        if click_timer > 0:
            target_zoom = self.click_zoom
            click_timer -= 1
        else:
            target_zoom = self.base_zoom
            
        self.spring_zoom.set_target(target_zoom)
        current_zoom = self.spring_zoom.update(dt)
        
        snapped_to_one = False
        if target_zoom == self.base_zoom and abs(current_zoom - self.base_zoom) < 0.006:
            current_zoom = self.base_zoom
            self.spring_zoom.value = self.base_zoom
            self.spring_zoom.velocity = 0.0
            snapped_to_one = True
            
        vw = width / current_zoom
        vh = height / current_zoom

        if snapped_to_one:
            cam_x = width / 2.0
            cam_y = height / 2.0
            self.spring_cam_x.value = cam_x
            self.spring_cam_x.target = cam_x
            self.spring_cam_x.velocity = 0.0
            self.spring_cam_y.value = cam_y
            self.spring_cam_y.target = cam_y
            self.spring_cam_y.velocity = 0.0
            last_click_focus_x = cam_x
            last_click_focus_y = cam_y
        elif current_zoom > 1.01:
            focus_x, focus_y = last_click_focus_x, last_click_focus_y
            self.spring_cam_x.set_target(focus_x)
            self.spring_cam_y.set_target(focus_y)
            cam_x = self.spring_cam_x.update(dt)
            cam_y = self.spring_cam_y.update(dt)
            cam_x = max(vw/2, min(width - vw/2, cam_x))
            cam_y = max(vh/2, min(height - vh/2, cam_y))
            self.spring_cam_x.value = cam_x
            self.spring_cam_y.value = cam_y
        else:
            self.spring_cam_x.set_target(width / 2.0)
            self.spring_cam_y.set_target(height / 2.0)
            cam_x = self.spring_cam_x.update(dt)
            cam_y = self.spring_cam_y.update(dt)
            cam_x = max(vw/2, min(width - vw/2, cam_x))
            cam_y = max(vh/2, min(height - vh/2, cam_y))
            self.spring_cam_x.value = cam_x
            self.spring_cam_y.value = cam_y
        
        # Update clicks ripples
        if new_click_started:
            self.clicks.append({'x': mx, 'y': my, 'frame': frame_idx, 'life': 20})
            
        current_frame_clicks = []
        active_clicks = []
        for c in self.clicks:
            if c['life'] > 0:
                radius = (20 - c['life']) * 2
                alpha = c['life'] / 20.0
                current_frame_clicks.append((c['x'], c['y'], float(radius), float(alpha)))
                c['life'] -= 1
                active_clicks.append(c)
        self.clicks = active_clicks
        
        return mx, my, click, current_zoom, cam_x, cam_y, current_frame_clicks, click_timer, last_click_focus_x, last_click_focus_y, mouse_idx
