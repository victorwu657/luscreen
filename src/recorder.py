import threading
import time
import cv2
import numpy as np
import mss
import os
import subprocess
import imageio_ffmpeg
import sys
from datetime import datetime
from src.audio_recorder import AudioRecorder
# from src.system_audio_recorder import SystemAudioRecorder # 延迟导入以避免COM冲突
import ctypes

import logging

def setup_logger():
    """Setup a logger that writes to a file in the executable's directory."""
    logger = logging.getLogger('ScreenRecorder')
    logger.setLevel(logging.DEBUG)
    
    if not logger.handlers:
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
        log_file = os.path.join(base_path, 'recorder_debug.log')
        
        fh = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        
    return logger

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

def open_folder_and_select_file(file_path):
    """
    使用 PowerShell 脚本查找已打开的资源管理器窗口并选中文件。
    如果未找到，则打开新窗口。
    """
    if os.name != 'nt':
        return False
        
    try:
        file_path = os.path.abspath(file_path)
        folder_path = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)
        
        # PowerShell 脚本：遍历窗口，如果找到匹配路径，则选中文件；否则调用 explorer /select
        # 注意：需要处理路径中的单引号
        ps_file_path = file_path.replace("'", "''")
        ps_folder_path = folder_path.replace("'", "''")
        ps_file_name = file_name.replace("'", "''")
        
        ps_script = f"""
        $filePath = '{ps_file_path}';
        $folderPath = '{ps_folder_path}'.TrimEnd('\\');
        $fileName = '{ps_file_name}';
        $shell = New-Object -ComObject Shell.Application;
        
        function Activate-Window {{
            param($targetPath)
            foreach ($window in $shell.Windows()) {{
                try {{
                    if ($window.Document -and $window.Document.Folder) {{
                        $winPath = $window.Document.Folder.Self.Path;
                        if ($winPath) {{
                            $winPath = $winPath.TrimEnd('\\');
                            if ($winPath -eq $targetPath) {{
                                $window.Visible = $true;
                                if ($window.WindowState -eq 1) {{ $window.WindowState = 0; }}
                                
                                $wshell = New-Object -ComObject WScript.Shell;
                                if ($window.LocationName) {{
                                    $wshell.AppActivate($window.LocationName);
                                }}
                                
                                $folder = $window.Document.Folder;
                                $item = $folder.ParseName($fileName);
                                if ($item) {{
                                    $window.Document.SelectItem($item, 29);
                                }}
                                return $true;
                            }}
                        }}
                    }}
                }} catch {{ }}
            }}
            return $false;
        }}
        
        # 第一次尝试查找
        $found = Activate-Window -targetPath $folderPath;
        
        if (-not $found) {{
            # 没找到，打开新窗口
            # 使用 Start-Process 并加上引号，确保路径被正确解析
            Start-Process explorer.exe -ArgumentList "/select, `"$filePath`""
        }}
        """
        
        # 使用 subprocess 运行 PowerShell，隐藏窗口
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], startupinfo=startupinfo)
        return True
    except Exception as e:
        print(f"PowerShell select failed: {e}")
        return False

from ctypes import windll, Structure, c_long, byref

class POINT(Structure):
    _fields_ = [("x", c_long), ("y", c_long)]

def get_mouse_pos():
    pt = POINT()
    windll.user32.GetCursorPos(byref(pt))
    return pt.x, pt.y

class ScreenRecorder(threading.Thread):
    def __init__(self, region=None, output_filename=None, record_audio=True, audio_device_index=None, record_system_audio=False, output_dir=None, video_quality="1080p", use_gpu=False):
        super().__init__()
        self.cursor_img = self.create_cursor_image()
        self.region = region 
        self.is_recording = False
        self.is_paused = False
        self.pause_event = threading.Event()
        self.pause_event.set() # Set means NOT paused (running)
        self.stop_event = threading.Event()
        self.record_audio = record_audio
        self.audio_device_index = audio_device_index
        self.record_system_audio = record_system_audio
        self.video_quality = video_quality
        self.use_gpu = use_gpu
        
        # 确保输出目录存在
        if output_dir:
            self.output_dir = output_dir
        else:
            self.output_dir = os.path.join(os.getcwd(), "recordings")

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # 文件名生成
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if output_filename is None:
            self.final_output = os.path.join(self.output_dir, f"LuScreen_{timestamp}.mp4")
        else:
            self.final_output = output_filename
            
        # 临时文件
        self.temp_video = os.path.join(self.output_dir, f"temp_video_{timestamp}.mp4")
        self.temp_audio_mic = os.path.join(self.output_dir, f"temp_audio_mic_{timestamp}.wav")
        self.temp_audio_sys = os.path.join(self.output_dir, f"temp_audio_sys_{timestamp}.wav")
        
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
            
        # 音频录制器
        self.mic_recorder = None
        self.sys_recorder = None
        self.last_pause_start = 0
        self.ffmpeg_process = None
        self.logger = setup_logger()

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

    def run(self):
        self.logger.info("Starting ScreenRecorder thread")
        self.is_recording = True
        
        # 初始化 MSS
        self.sct = mss.mss()
        
        if self.region is None:
            monitor = self.sct.monitors[1]
            self.region = {'top': monitor['top'], 'left': monitor['left'], 'width': monitor['width'], 'height': monitor['height']}
            
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
        
        if self.video_quality.startswith('4k'):
            crf = '17'
            # 4K resolution
            scale_filter = ['-vf', "scale='min(3840,iw)':-2"]
        elif self.video_quality.startswith('2k'):
            crf = '20'
            # 2K resolution
            scale_filter = ['-vf', "scale='min(2560,iw)':-2"]
        else: # 1080p
            crf = '23'
            scale_filter = ['-vf', "scale='min(1920,iw)':-2"]

        # 尝试检测 NVIDIA GPU (如果用户开启了GPU加速)
        has_nvidia_gpu = False
        if self.use_gpu:
            try:
                # 简单的检测方法：尝试运行 ffmpeg 查看支持的编码器
                result = subprocess.run([ffmpeg_exe, '-encoders'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if 'h264_nvenc' in result.stdout:
                    has_nvidia_gpu = True
                    print("NVIDIA GPU detected. Using NVENC for hardware acceleration.")
                else:
                    print("GPU acceleration enabled but no supported NVIDIA GPU found. Falling back to CPU.")
            except:
                pass
        else:
            print("GPU acceleration disabled by user.")

        # 构建 FFmpeg 命令: 输入 Raw BGRA -> 输出 H.264 MP4
        # 使用 -pix_fmt bgra 匹配 MSS 在 Windows 上的默认输出
        cmd = [
            ffmpeg_exe, '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-pix_fmt', 'bgra',
            '-s', f"{self.region['width']}x{self.region['height']}",
            '-r', str(self.fps),
            '-i', '-'
        ]
        
        if has_nvidia_gpu:
            # NVENC 编码
            cq = '26'
            if self.video_quality.startswith('4k'): cq = '19'
            elif self.video_quality.startswith('2k'): cq = '23'
            
            cmd.extend([
                '-c:v', 'h264_nvenc',
                '-preset', 'p4',
                '-cq', cq,
                '-pix_fmt', 'yuv420p'
            ])
        else:
            # CPU libx264 编码
            cmd.extend([
                '-c:v', 'libx264',
                '-preset', 'veryfast', # 保证实时编码性能
                '-crf', crf,
                '-pix_fmt', 'yuv420p'
            ])
            
        cmd.extend(scale_filter)
        cmd.append(self.temp_video)

        # 启动 FFmpeg 进程
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        try:
            self.ffmpeg_process = subprocess.Popen(cmd, stdin=subprocess.PIPE, startupinfo=startupinfo)
        except Exception as e:
            print(f"Failed to start FFmpeg process: {e}")
            self.is_recording = False
            return
        
        # 启动麦克风录制
        if self.record_audio:
            self.mic_recorder = AudioRecorder(self.temp_audio_mic, device_index=self.audio_device_index)
            self.mic_recorder.start()

        # 启动系统声音录制
        if self.record_system_audio:
            self.logger.info("Initializing SystemAudioRecorder...")
            # 延迟导入，避免主线程 COM 冲突
            try:
                from src.system_audio_recorder import SystemAudioRecorder
                self.sys_recorder = SystemAudioRecorder(self.temp_audio_sys)
                self.sys_recorder.start()
                self.logger.info("SystemAudioRecorder started")
            except Exception as e:
                self.logger.error(f"Failed to start SystemAudioRecorder: {e}")
                self.sys_recorder = None
        
        frame_duration = 1.0 / self.fps
        print(f"Started recording region: {self.region}")
        
        start_time = time.time()
        next_frame_time = start_time
        
        while not self.stop_event.is_set():
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
            
            try:
                img = self.sct.grab(self.region)
                frame = np.array(img)
                self.draw_cursor(frame)
                
                if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                    # 直接写入原始 BGRA 字节到 FFmpeg 管道
                    self.ffmpeg_process.stdin.write(frame.tobytes())
                    
                    # 补帧逻辑
                    current_time = time.time()
                    if current_time > next_frame_time + frame_duration:
                        missed_frames = int((current_time - next_frame_time) / frame_duration) - 1
                        missed_frames = min(missed_frames, 5) 
                        
                        if missed_frames > 0:
                            for _ in range(missed_frames):
                                self.ffmpeg_process.stdin.write(frame.tobytes())
                            next_frame_time += missed_frames * frame_duration
                            
            except (BrokenPipeError, IOError):
                print("FFmpeg process pipe broken, stopping recording.")
                break
            except Exception as e:
                print(f"Error during recording: {e}")
            
            # 更新下一帧理论时间
            next_frame_time += frame_duration
            
            # 精确睡眠
            delay = max(0, next_frame_time - time.time())
            time.sleep(delay)
            
        # 停止视频写入
        if self.ffmpeg_process:
            if self.ffmpeg_process.poll() is None:
                self.ffmpeg_process.stdin.close()
            self.ffmpeg_process.wait()
            
        # 停止音频录制
        if self.mic_recorder:
            self.mic_recorder.stop()
        if self.sys_recorder:
            self.sys_recorder.stop()
            
        self.is_recording = False
        print("Recording stopped. Merging files...")
        
        # 合并音视频
        self.merge_av()

    def merge_av(self):
        self.logger.info("Starting merge_av")
        ffmpeg_exe = get_ffmpeg_path()
        self.logger.info(f"FFmpeg path: {ffmpeg_exe}")
        
        has_mic = self.record_audio and os.path.exists(self.temp_audio_mic)
        has_sys = self.record_system_audio and os.path.exists(self.temp_audio_sys)
        
        self.logger.info(f"Has Mic: {has_mic} (Path: {self.temp_audio_mic})")
        self.logger.info(f"Has Sys: {has_sys} (Path: {self.temp_audio_sys})")

        if self.record_system_audio and not has_sys:
            self.logger.warning(f"System audio recording enabled but file not found: {self.temp_audio_sys}")
            
        cmd = [ffmpeg_exe, '-y', '-i', self.temp_video]
        
        # 添加音频输入
        if has_mic:
            cmd.extend(['-i', self.temp_audio_mic])
        if has_sys:
            cmd.extend(['-i', self.temp_audio_sys])
            
        # 视频参数: 使用流复制 (Stream Copy) 以极大减少合并时间
        video_args = ['-c:v', 'copy']
        
        # 构建映射和过滤器
        if has_mic and has_sys:
            # 混合两个音频流
            cmd.extend([
                '-filter_complex', '[1:a]volume=1.5[a1];[2:a]volume=1.5[a2];[a1][a2]amix=inputs=2:duration=longest:dropout_transition=0[aout]',
                '-map', '0:v',
                '-map', '[aout]',
            ])
        elif has_mic or has_sys:
            # 只有一个音频流 (索引1)
            cmd.extend(['-map', '0:v', '-map', '1:a'])
        else:
            # 无音频，只处理视频
            cmd.extend(['-map', '0:v'])

        # 应用视频参数
        cmd.extend(video_args)
        
        # 应用音频参数 (如果有)
        if has_mic or has_sys:
            cmd.extend(['-c:a', 'aac'])
            
        cmd.append(self.final_output)

        try:
            # 创建启动信息以隐藏控制台窗口
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
            print(f"Merged successfully (Fast Mode): {self.final_output}")
            
            # 清理临时文件
            if os.path.exists(self.temp_video):
                os.remove(self.temp_video)
            if os.path.exists(self.temp_audio_mic):
                os.remove(self.temp_audio_mic)
            if os.path.exists(self.temp_audio_sys):
                os.remove(self.temp_audio_sys)
            
            # 打开输出文件夹并选中文件
            try:
                if os.name == 'nt':
                    if not open_folder_and_select_file(self.final_output):
                        subprocess.run(['explorer', '/select,', os.path.normpath(self.final_output)])
                else:
                    os.startfile(self.output_dir)
            except Exception as e:
                print(f"Failed to open output folder: {e}")
                
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg merge failed: {e}")

    def stop(self):
        self.pause_event.set() # Ensure we are not paused when stopping
        self.stop_event.set()
        self.join()

    def pause(self):
        self.is_paused = True
        self.pause_event.clear()
        print("Recording paused")

    def resume(self):
        self.is_paused = False
        self.pause_event.set()
        print("Recording resumed")