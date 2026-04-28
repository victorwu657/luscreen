from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
                               QLineEdit, QFrame, QMenu, QToolTip, QProgressBar)
from PySide6.QtCore import Qt, Signal, QSize, QPoint, QTimer, QThread, QEvent
from PySide6.QtGui import QAction, QIntValidator
from PySide6.QtMultimedia import QMediaDevices
from src.camera import CameraWidget
from src.audio_recorder import AudioRecorder
from src.teleprompter import TeleprompterWindow
import pyaudio
import numpy as np
import logging

logger = logging.getLogger("ControlPanel")

class AudioMonitor(QThread):
    level_changed = Signal(int)
    error_occurred = Signal() # Signal for circuit breaker

    def __init__(self, device_index=None):
        super().__init__()
        self.device_index = device_index
        self.is_running = True
        self.p = pyaudio.PyAudio()

    def run(self):
        error_count = 0
        MAX_ERRORS = 5
        
        try:
            stream = self.p.open(format=pyaudio.paInt16,
                                 channels=1,
                                 rate=44100,
                                 input=True,
                                 input_device_index=self.device_index,
                                 frames_per_buffer=1024)
            
            while self.is_running:
                try:
                    data = stream.read(1024, exception_on_overflow=False)
                    # Convert bytes to numpy array
                    audio_data = np.frombuffer(data, dtype=np.int16)
                    # Calculate RMS
                    rms = np.sqrt(np.mean(audio_data.astype(np.float64)**2))
                    
                    # Normalize to 0-100 (adjust divisor based on sensitivity)
                    # 2000 is a reasonable divisor for 16-bit audio (max 32768) to show visible movement
                    level = min(100, int(rms / 20)) 
                    self.level_changed.emit(level)
                    
                    # Reset error count on success
                    error_count = 0
                    
                except Exception as e:
                    error_count += 1
                    if error_count >= MAX_ERRORS:
                        logger.error(f"AudioMonitor circuit breaker triggered after {error_count} consecutive errors.")
                        self.error_occurred.emit()
                        break
                    # Short sleep before retry
                    self.msleep(50)
                    continue

                self.msleep(50)
            
            # Ensure stream is stopped/closed if we break out of loop
            if stream.is_active():
                stream.stop_stream()
            stream.close()
            
        except Exception as e:
            print(f"Audio monitor error: {e}")
        finally:
            pass # Don't terminate PyAudio here as it might be used elsewhere

    def stop(self):
        self.is_running = False
        self.wait()

    def enterEvent(self, event):
        if self.text() and self.toolTip():
             QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())), self.toolTip())
        super().enterEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

class IconButton(QPushButton):
    def __init__(self, text, tooltip, parent=None):
        super().__init__(text, parent)
        self.setToolTip(tooltip)
        self.setCheckable(True)
        self.setFixedSize(40, 40)
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 5px;
                color: #888888;
                font-size: 20px;
            }
            QPushButton:hover {
                background-color: #444444;
                color: white;
            }
            QPushButton:checked {
                background-color: #555555;
                color: #00afff; /* 激活色 */
                border: 1px solid #00afff;
            }
        """)
        
    def enterEvent(self, event):
        if self.toolTip():
             QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())), self.toolTip())
        super().enterEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)


class ControlPanel(QFrame):
    record_clicked = Signal()
    ocr_clicked = Signal() # 新增信号
    scroll_capture_clicked = Signal() # 新增信号
    cancel_clicked = Signal()
    size_changed = Signal(int, int) # width, height
    mode_changed = Signal(str) # 'fullscreen', 'area', 'ratio'
    ratio_changed = Signal(object) # float or None
    
    # 设置变更信号
    mic_toggled = Signal(bool)
    mic_changed = Signal(int)
    sys_audio_toggled = Signal(bool)
    camera_toggled = Signal(bool)
    camera_changed = Signal(int)
    camera_size_changed = Signal(int) # width
    camera_shape_changed = Signal(str) # 'circle', 'square', '4:3', '3:4'
    mouse_toggled = Signal(bool)
    mouse_style_changed = Signal(str) # 'highlight', 'ring', 'both', 'none'

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter:
            if isinstance(obj, QPushButton) and obj.toolTip():
                QToolTip.showText(obj.mapToGlobal(QPoint(0, obj.height())), obj.toolTip())
        elif event.type() == QEvent.Leave:
             QToolTip.hideText()
        return super().eventFilter(obj, event)

    def __init__(self, parent=None):
        logger.info("Initializing ControlPanel")
        super().__init__(parent)
        
        # 当前选中的设备索引
        self.current_mic_index = None
        self.current_mic_name = None # Track name for UI check state
        self.current_cam_index = 0
        self.current_ratio = None  # None means free selection
        self.current_mouse_style = 'both'
        self.old_pos = None # 用于拖拽
        self.is_capture_mode = False # 标记是否为截图/OCR模式
        
        # 移除 ControlPanel 自身的背景样式，改为在 paintEvent 中绘制
        # 保留 color: white 以便继承
        self.setStyleSheet("""
            ControlPanel {
                color: white;
            }
            QToolTip {
                color: #ffffff;
                background-color: #2a2a2a;
                border: 1px solid #444;
                border-radius: 2px;
                padding: 4px;
            }
            QLabel { color: #ccc; }
            QLineEdit {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
                color: white;
                padding: 2px;
                selection-background-color: #007aff;
            }
            QPushButton#ModeBtn {
                background-color: transparent;
                border: none;
                color: #aaa;
                padding: 5px;
                font-size: 24px; /* 增大字体/图标 */
            }
            QPushButton#ModeBtn:hover {
                background-color: #444;
                color: white;
                border-radius: 8px; /* 加大圆角 */
            }
            QPushButton#ModeBtn:checked {
                color: #00afff;
                font-weight: bold;
            }
        """)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground) # 开启透明背景，消除圆角黑边
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 10, 15, 15) # 顶部间距稍微减小，给Logo留位置

        # --- Logo 栏 ---
        logo_layout = QHBoxLayout()
        logo_layout.setContentsMargins(5, 0, 0, 0)
        self.lbl_logo = QLabel("LuScreen")
        self.lbl_logo.setStyleSheet("color: #00afff; font-weight: bold; font-family: 'Segoe UI', sans-serif; font-size: 14px;")
        logo_layout.addWidget(self.lbl_logo)
        
        logo_layout.addStretch()
        
        # 最小化按钮
        btn_minimize = QPushButton("－")
        btn_minimize.setFixedSize(24, 24)
        btn_minimize.setCursor(Qt.PointingHandCursor)
        btn_minimize.setToolTip("最小化")
        btn_minimize.clicked.connect(self.showMinimized)
        btn_minimize.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #888;
                border: none;
                font-size: 14px;
                font-weight: bold;
                padding-bottom: 2px;
            }
            QPushButton:hover {
                color: white;
            }
        """)
        logo_layout.addWidget(btn_minimize)

        # 关闭按钮
        btn_close = QPushButton("×")
        btn_close.setFixedSize(24, 24)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setToolTip("关闭")
        btn_close.clicked.connect(self.cancel_clicked.emit)
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #888;
                border: none;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #ff4444;
            }
        """)
        logo_layout.addWidget(btn_close)
        
        layout.addLayout(logo_layout)
        
        # --- 第一行：模式与尺寸 ---
        row1 = QHBoxLayout()
        
        # 模式按钮
        self.btn_fullscreen = QPushButton("🖥️")
        self.btn_fullscreen.setToolTip("全屏")
        self.btn_fullscreen.setObjectName("ModeBtn")
        self.btn_fullscreen.setCheckable(True)
        self.btn_fullscreen.setFixedSize(80, 60) # 增大2倍
        self.btn_fullscreen.installEventFilter(self) # Install event filter
        self.btn_fullscreen.clicked.connect(lambda: self.set_mode('fullscreen'))
        
        self.btn_area = QPushButton("⛶")
        self.btn_area.setToolTip("区域")
        self.btn_area.setObjectName("ModeBtn")
        self.btn_area.setCheckable(True)
        self.btn_area.setFixedSize(80, 60) # 增大2倍
        self.btn_area.installEventFilter(self) # Install event filter
        self.btn_area.clicked.connect(lambda: self.set_mode('area'))

        self.btn_camera_only = QPushButton("📷")
        self.btn_camera_only.setToolTip("只录摄像头")
        self.btn_camera_only.setObjectName("ModeBtn")
        self.btn_camera_only.setCheckable(True)
        self.btn_camera_only.setFixedSize(80, 60) # 增大2倍
        self.btn_camera_only.installEventFilter(self) # Install event filter
        self.btn_camera_only.clicked.connect(lambda: self.set_mode('camera_only'))
        
        self.btn_audio_only = QPushButton("🎙️")
        self.btn_audio_only.setToolTip("只录音")
        self.btn_audio_only.setObjectName("ModeBtn")
        self.btn_audio_only.setCheckable(True)
        self.btn_audio_only.setFixedSize(80, 60) # 增大2倍
        self.btn_audio_only.installEventFilter(self) # Install event filter
        self.btn_audio_only.clicked.connect(lambda: self.set_mode('audio_only'))
        
        row1.addWidget(self.btn_fullscreen)
        row1.addWidget(self.btn_area)
        row1.addWidget(self.btn_camera_only)
        row1.addWidget(self.btn_audio_only)
        
        # 尺寸输入 (W/H labels and inputs)
        self.size_widgets = QWidget()
        size_layout = QHBoxLayout(self.size_widgets)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(5)
        
        self.width_input = QLineEdit()
        self.width_input.setFixedWidth(50)
        self.width_input.setValidator(QIntValidator(1, 10000))
        self.width_input.setAlignment(Qt.AlignCenter)
        self.width_input.editingFinished.connect(self.on_size_input)
        
        self.height_input = QLineEdit()
        self.height_input.setFixedWidth(50)
        self.height_input.setValidator(QIntValidator(1, 10000))
        self.height_input.setAlignment(Qt.AlignCenter)
        self.height_input.editingFinished.connect(self.on_size_input)
        
        size_layout.addWidget(QLabel("W:"))
        size_layout.addWidget(self.width_input)
        size_layout.addWidget(QLabel("x"))
        size_layout.addWidget(QLabel("H:"))
        size_layout.addWidget(self.height_input)
        
        row1.addWidget(self.size_widgets)
        
        # 比例菜单按钮
        self.btn_ratio = QPushButton("⚙️") # 比例/设置
        self.btn_ratio.setToolTip("设置/比例")
        self.btn_ratio.setFixedSize(30, 30)
        self.btn_ratio.setStyleSheet("background: transparent; border: none; color: #aaa;")
        self.btn_ratio.setMenu(self.create_ratio_menu())
        row1.addWidget(self.btn_ratio)
        
        row1.addStretch()
        
        layout.addLayout(row1)
        
        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #444;")
        layout.addWidget(line)
        
        # --- 第二行：设备开关 ---
        row2 = QHBoxLayout()
        row2.setSpacing(15)
        
        # 麦克风
        self.btn_mic = IconButton("🎙️", "麦克风 (左键开关/右键选择)")
        self.btn_mic.clicked.connect(self.on_mic_click)
        self.btn_mic.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_mic.customContextMenuRequested.connect(self.show_mic_menu)
        self.btn_mic.setChecked(True)
        row2.addWidget(self.btn_mic)
        
        # 麦克风音量条
        self.mic_level_bar = QProgressBar()
        self.mic_level_bar.setOrientation(Qt.Vertical)
        self.mic_level_bar.setFixedSize(6, 40)
        self.mic_level_bar.setTextVisible(False)
        self.mic_level_bar.setRange(0, 100)
        self.mic_level_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444;
                border-radius: 3px;
                background-color: #222;
            }
            QProgressBar::chunk {
                background-color: #00afff;
                border-radius: 2px;
            }
        """)
        row2.addWidget(self.mic_level_bar)
        
        # 启动音频监听
        self.audio_monitor = None
        self.start_audio_monitor()
        
        # 系统声音
        self.btn_sys = IconButton("🔈", "系统声音")
        self.btn_sys.clicked.connect(lambda c: self.sys_audio_toggled.emit(c))
        self.btn_sys.setChecked(True)
        row2.addWidget(self.btn_sys)
        
        # 摄像头
        self.btn_cam = IconButton("📹", "摄像头 (左键开关/右键选择)")
        self.btn_cam.clicked.connect(self.on_cam_click)
        self.btn_cam.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_cam.customContextMenuRequested.connect(self.show_cam_menu)
        row2.addWidget(self.btn_cam)
        
        # 鼠标选项
        self.btn_mouse = IconButton("🖱️", "显示鼠标光标 (左键开关/右键样式)")
        self.btn_mouse.clicked.connect(lambda c: self.mouse_toggled.emit(c))
        self.btn_mouse.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_mouse.customContextMenuRequested.connect(self.show_mouse_menu)
        self.btn_mouse.setChecked(True)
        row2.addWidget(self.btn_mouse)
        
        # 提词器按钮
        self.btn_teleprompter = IconButton("📄", "提词器")
        self.btn_teleprompter.clicked.connect(self.toggle_teleprompter)
        self.btn_teleprompter.setCheckable(False) # 不是开关状态，而是触发
        row2.addWidget(self.btn_teleprompter)
        
        row2.addStretch()
        
        # 开始录制按钮
        self.btn_record = QPushButton("🔴")
        self.btn_record.setFixedSize(40, 40)
        self.btn_record.setToolTip("开始录制")
        self.btn_record.setStyleSheet("""
            QPushButton {
                background-color: #ff4444;
                border-radius: 20px;
                color: white;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #ff6666;
            }
        """)
        self.btn_record.clicked.connect(self.record_clicked.emit)
        row2.addWidget(self.btn_record)
        
        # 滚动截图按钮 (默认隐藏)
        self.btn_scroll = QPushButton("📜")
        self.btn_scroll.setFixedSize(40, 40)
        self.btn_scroll.setToolTip("滚动截图 (Scroll Capture)")
        self.btn_scroll.setStyleSheet("""
            QPushButton {
                background-color: #ff9500;
                border-radius: 20px;
                color: white;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #ffaa33;
            }
        """)
        self.btn_scroll.clicked.connect(self.scroll_capture_clicked.emit)
        self.btn_scroll.hide()
        row2.addWidget(self.btn_scroll)
        
        layout.addLayout(row2)
        
        # 默认不选中任何模式
        self.current_mode = None # Initialize current_mode before calling set_mode
        self.set_mode(None)

    def set_capture_mode(self):
        """切换到截图模式的简化界面"""
        self.is_capture_mode = True
        # 隐藏第二行（设备开关）
        if hasattr(self, 'btn_mic'): self.btn_mic.hide()
        if hasattr(self, 'mic_level_bar'): self.mic_level_bar.hide()
        if hasattr(self, 'btn_sys'): self.btn_sys.hide()
        if hasattr(self, 'btn_cam'): self.btn_cam.hide()
        if hasattr(self, 'btn_mouse'): self.btn_mouse.hide()
        
        # 隐藏录摄像头/录音按钮 (截图模式不需要)
        if hasattr(self, 'btn_camera_only'):
            self.btn_camera_only.hide()
        if hasattr(self, 'btn_audio_only'):
            self.btn_audio_only.hide()
        
        # 显示滚动截图按钮
        self.btn_scroll.show()
        
        # 更改主按钮样式
        self.btn_record.setText("📷")
        self.btn_record.setToolTip("截图 (Enter)")
        self.btn_record.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #00afff;
                border-radius: 20px;
                color: #00afff;
                font-size: 20px;
            }
            QPushButton:hover {
                background-color: rgba(0, 175, 255, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(0, 175, 255, 0.3);
            }
        """)
        
        # 断开旧连接，连接新信号
        try: self.btn_record.clicked.disconnect()
        except: pass
        self.btn_record.clicked.connect(self.record_clicked.emit)

    def set_ocr_mode(self):
        """切换到OCR模式的简化界面"""
        self.is_capture_mode = True
        # 隐藏第二行（设备开关）
        if hasattr(self, 'btn_mic'): self.btn_mic.hide()
        if hasattr(self, 'mic_level_bar'): self.mic_level_bar.hide()
        if hasattr(self, 'btn_sys'): self.btn_sys.hide()
        if hasattr(self, 'btn_cam'): self.btn_cam.hide()
        if hasattr(self, 'btn_mouse'): self.btn_mouse.hide()
        
        # 隐藏录摄像头/录音按钮
        if hasattr(self, 'btn_camera_only'):
            self.btn_camera_only.hide()
        if hasattr(self, 'btn_audio_only'):
            self.btn_audio_only.hide()
        
        # 隐藏滚动截图按钮
        self.btn_scroll.hide()
        
        # 更改主按钮样式
        self.btn_record.setText("📝")
        self.btn_record.setToolTip("OCR取字 (Enter)")
        self.btn_record.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #00afff;
                border-radius: 20px;
                color: #00afff;
                font-size: 20px;
            }
            QPushButton:hover {
                background-color: rgba(0, 175, 255, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(0, 175, 255, 0.3);
            }
        """)
        
        # 断开旧连接，连接新信号
        try: self.btn_record.clicked.disconnect()
        except: pass
        self.btn_record.clicked.connect(self.ocr_clicked.emit)

    def set_mode(self, mode):
        logger.info(f"ControlPanel switching mode to: {mode}")
        
        # 如果点击的是当前已经激活的模式，则视为取消选中（Toggle off）
        # 但如果是从 None 切换到某个模式，则正常切换
        # 特殊情况：全屏和区域模式通常互斥，但也允许都不选（此时隐藏遮罩）
        # 用户反馈：再次点击“全屏”恢复初始状态（即 None），蓝色边框消失。
        
        if self.current_mode == mode and mode is not None:
            # Toggle off
            mode = None
            
        self.current_mode = mode
        
        # Reset all buttons to default style
        default_style = """
            QPushButton#ModeBtn {
                background-color: transparent;
                border: none;
                color: #aaa;
                padding: 5px;
                font-size: 24px;
            }
            QPushButton#ModeBtn:hover {
                background-color: #444;
                color: white;
                border-radius: 8px;
            }
        """
        
        active_style = """
            QPushButton#ModeBtn {
                background-color: #444;
                border: 1px solid #00afff;
                color: #00afff;
                border-radius: 8px;
                padding: 5px;
                font-weight: bold;
                font-size: 24px;
            }
        """
        
        # Apply styles
        self.btn_fullscreen.setStyleSheet(active_style if mode == 'fullscreen' else default_style)
        self.btn_area.setStyleSheet(active_style if mode == 'area' else default_style)
        if hasattr(self, 'btn_camera_only'):
            self.btn_camera_only.setStyleSheet(active_style if mode == 'camera_only' else default_style)
        if hasattr(self, 'btn_audio_only'):
            self.btn_audio_only.setStyleSheet(active_style if mode == 'audio_only' else default_style)

        self.btn_fullscreen.setChecked(mode == 'fullscreen')
        self.btn_area.setChecked(mode == 'area')
        if hasattr(self, 'btn_camera_only'):
            self.btn_camera_only.setChecked(mode == 'camera_only')
        if hasattr(self, 'btn_audio_only'):
            self.btn_audio_only.setChecked(mode == 'audio_only')

        # 动态 UI 更新
        is_audio = (mode == 'audio_only')
        is_camera = (mode == 'camera_only')
        is_area = (mode == 'area') # 只有区域模式才显示尺寸和比例
        is_screen = (mode in ['fullscreen', 'area'])
        
        # 1. 尺寸输入框 (仅区域模式显示)
        if hasattr(self, 'size_widgets'):
            self.size_widgets.setVisible(is_area)
        self.btn_ratio.setVisible(is_area)
        
        # 2. 设备开关
        if self.is_capture_mode:
            self.btn_cam.hide()
            self.btn_mouse.hide()
            self.btn_mic.hide()
            self.btn_sys.hide()
        else:
            self.btn_cam.setVisible(not is_audio)
            self.btn_mouse.setVisible(not is_audio)
        
        # 3. 录制按钮样式
        if is_audio:
            self.btn_record.setText("🎙️") # 录音图标
        elif is_camera:
             self.btn_record.setText("🔴") # 录制
        else:
             self.btn_record.setText("🔴")
             
        # 4. 调整窗口大小
        self.adjustSize()
        
        self.mode_changed.emit(mode)

    def create_ratio_menu(self):
        menu = QMenu(self)
        self.ratio_menu = menu # Keep reference
        menu.aboutToShow.connect(self.update_ratio_menu_checks)
        
        # 自由选择
        action_free = menu.addAction("自由选择")
        action_free.setCheckable(True)
        action_free.setData("free") # Use "free" string to identify
        action_free.triggered.connect(lambda: self.on_ratio_selected(None))
        menu.addSeparator()
        
        # 常用比例
        ratios = [
            ("16:9 (标准横屏)", 16/9),
            ("9:16 (标准竖屏)", 9/16),
            ("4:3 (传统横屏)", 4/3),
            ("3:4 (传统竖屏)", 3/4),
            ("1:1 (正方形)", 1.0),
            ("2:3 (35mm)", 2/3),
            ("3:2 (35mm)", 3/2)
        ]
        
        for name, ratio in ratios:
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setData(ratio)
            # 注意：triggered 发射一个 checked 参数，必须显式接收它(c)，否则它会覆盖 r
            action.triggered.connect(lambda c=False, r=ratio: self.on_ratio_selected(r))
            
        return menu

    def update_ratio_menu_checks(self):
        for action in self.ratio_menu.actions():
            if action.isSeparator():
                continue
            
            data = action.data()
            if data == "free":
                action.setChecked(self.current_ratio is None)
            elif isinstance(data, float) and self.current_ratio is not None:
                # Float comparison with tolerance
                action.setChecked(abs(data - self.current_ratio) < 0.001)
            else:
                action.setChecked(False)

    def on_ratio_selected(self, ratio):
        self.current_ratio = ratio
        # 发射信号
        self.ratio_changed.emit(ratio)

    def update_size_display(self, w, h):
        self.width_input.setText(str(w))
        self.height_input.setText(str(h))

    def on_size_input(self):
        try:
            w = int(self.width_input.text())
            h = int(self.height_input.text())
            
            # Check size and clamp to available screen geometry
            screen = self.screen()
            if screen:
                avail = screen.availableGeometry()
                max_w = avail.width()
                max_h = avail.height()
                
                clamped_w = min(w, max_w)
                clamped_h = min(h, max_h)
                
                if clamped_w != w:
                    w = clamped_w
                    self.width_input.setText(str(w))
                    
                if clamped_h != h:
                    h = clamped_h
                    self.height_input.setText(str(h))
            
            self.size_changed.emit(w, h)
        except:
            pass

    def start_audio_monitor(self):
        if self.audio_monitor:
            self.audio_monitor.stop()
        
        # Only start if mic is enabled
        if self.btn_mic.isChecked():
            # Restore default style (in case it was in error state)
            self.btn_mic.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 5px;
                    color: #888888;
                    font-size: 20px;
                }
                QPushButton:hover {
                    background-color: #444444;
                    color: white;
                }
                QPushButton:checked {
                    background-color: #555555;
                    color: #00afff; /* 激活色 */
                    border: 1px solid #00afff;
                }
            """)
            self.btn_mic.setToolTip("麦克风 (左键开关/右键选择)")
            
            self.audio_monitor = AudioMonitor(self.current_mic_index)
            self.audio_monitor.level_changed.connect(self.mic_level_bar.setValue)
            self.audio_monitor.error_occurred.connect(self.on_audio_error)
            self.audio_monitor.start()
        else:
            self.mic_level_bar.setValue(0)

    def on_audio_error(self):
        """Handle audio monitor circuit breaker trip"""
        logger.error("Audio monitor circuit breaker triggered. Disabling microphone.")
        
        # Stop monitor (cleanup)
        self.stop_audio_monitor()
        
        # Update UI to error state
        self.btn_mic.setChecked(False)
        self.btn_mic.setToolTip("麦克风不可用 (设备故障或已移除)")
        
        # Set Error Style (Red border/text)
        self.btn_mic.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #ff4444;
                border-radius: 5px;
                color: #ff4444;
                font-size: 20px;
            }
            QPushButton:hover {
                background-color: rgba(255, 68, 68, 0.1);
                color: #ff4444;
            }
        """)
        
        # Notify app that mic is off
        self.mic_toggled.emit(False)

    def stop_audio_monitor(self):
        if self.audio_monitor:
            self.audio_monitor.stop()
            self.audio_monitor = None
            self.mic_level_bar.setValue(0)

    def on_mic_click(self, checked):
        self.mic_toggled.emit(checked)
        if checked:
            self.start_audio_monitor()
        else:
            self.stop_audio_monitor()
        
    def show_mic_menu(self, pos):
        menu = QMenu(self)
        try:
            # Use Qt QMediaDevices for the UI list because it handles hotplug events much better
            # and is always up-to-date compared to PyAudio which might cache or lag
            qt_devices = QMediaDevices.audioInputs()
            
            # Also get PyAudio devices to verify availability (optional, but good for debugging)
            # pa_devices = AudioRecorder.get_input_devices() 
            
            found_current = False
            
            for dev in qt_devices:
                name = dev.description()
                action = QAction(name, self)
                action.setCheckable(True)
                
                # Check if this is the currently selected device
                # We match by name because index might have shifted
                # Get current device name from PyAudio index if possible, or use saved name
                is_selected = False
                
                # Priority 1: Check against stored name (most reliable for UI)
                if self.current_mic_name and name == self.current_mic_name:
                    action.setChecked(True)
                    found_current = True
                
                # Priority 2: Fallback to index check if name match failed (legacy/first run)
                elif not found_current and self.current_mic_index is not None:
                    pa_index = AudioRecorder.get_device_index_by_name(name)
                    if pa_index is not None and pa_index == self.current_mic_index:
                        action.setChecked(True)
                        found_current = True
                        # Auto-update name for future consistency
                        self.current_mic_name = name
                
                action.triggered.connect(lambda c=False, n=name: self.on_mic_name_selected(n))
                menu.addAction(action)
                
            if not qt_devices:
                 menu.addAction("未检测到麦克风")
                 
        except Exception as e:
            logger.error(f"Error showing mic menu: {e}")
            menu.addAction("无法获取设备")
            
        menu.exec(self.btn_mic.mapToGlobal(pos))

    def on_mic_name_selected(self, name):
        """Handle selection by name (from Qt list) -> convert to PyAudio index"""
        print(f"DEBUG: ControlPanel on_mic_name_selected name='{name}'")
        idx = AudioRecorder.get_device_index_by_name(name)
        if idx is not None:
            self.current_mic_name = name # Update stored name
            self.on_mic_selected(idx)
        else:
            # Should not happen if lists are consistent, but if it does:
            print(f"Error: Could not find PyAudio index for device '{name}'")
            # Fallback or alert user? For now just log.

    def on_mic_selected(self, index):
        print(f"DEBUG: ControlPanel on_mic_selected index={index}")
        self.current_mic_index = index
        self.mic_changed.emit(index)
        # Restart monitor with new device
        self.start_audio_monitor()

    def closeEvent(self, event):
        self.stop_audio_monitor()
        super().closeEvent(event)

    def on_cam_click(self, checked):
        self.camera_toggled.emit(checked)
        # 如果是全屏模式下手动开启摄像头，我们不强制居中，让其保持右下角默认
        pass
        
    def show_cam_menu(self, pos):
        menu = QMenu(self)
        
        # 形状子菜单
        shape_menu = QMenu("形状", self)
        shapes = [
            ('圆形', 'circle'),
            ('圆角正方形', 'square'),
            ('横向 4:3', '4:3'),
            ('竖向 3:4', '3:4'),
            ('横向 3:2', '3:2'),
            ('竖向 2:3', '2:3'),
            ('横向 16:9', '16:9'),
            ('竖向 9:16', '9:16')
        ]
        for name, mode in shapes:
            action = QAction(name, self)
            action.triggered.connect(lambda c=False, m=mode: self.camera_shape_changed.emit(m))
            shape_menu.addAction(action)
        menu.addMenu(shape_menu)

        # 尺寸子菜单
        size_menu = QMenu("尺寸", self)
        sizes = [
            ('小 (150px)', 150),
            ('中 (250px)', 250),
            ('大 (350px)', 350),
            ('特大 (500px)', 500)
        ]
        for name, width in sizes:
            action = QAction(name, self)
            action.triggered.connect(lambda c=False, w=width: self.camera_size_changed.emit(w))
            size_menu.addAction(action)
        menu.addMenu(size_menu)
        
        menu.addSeparator()
        
        try:
            cameras = CameraWidget.get_available_cameras()
            for cam in cameras:
                action = QAction(cam['name'], self)
                action.setCheckable(True)
                if self.current_cam_index == cam['index']:
                    action.setChecked(True)
                    
                action.triggered.connect(lambda c=False, idx=cam['index']: self.on_cam_selected(idx))
                menu.addAction(action)
        except:
            menu.addAction("无法获取设备")
        menu.exec(self.btn_cam.mapToGlobal(pos))

    def on_cam_selected(self, index):
        print(f"DEBUG: ControlPanel on_cam_selected index={index}")
        self.current_cam_index = index
        self.camera_changed.emit(index)

    def show_mouse_menu(self, pos):
        menu = QMenu(self)
        
        styles = [
            ('无特效', 'none'),
            ('高亮光标 (黄色光环)', 'highlight'),
            ('点击波纹', 'ring'),
            ('高亮 + 波纹', 'both')
        ]
        
        for name, style in styles:
            action = QAction(name, self)
            action.setCheckable(True)
            if self.current_mouse_style == style:
                action.setChecked(True)
            action.triggered.connect(lambda c=False, s=style: self.on_mouse_style_selected(s))
            menu.addAction(action)
            
        menu.exec(self.btn_mouse.mapToGlobal(pos))

    def on_mouse_style_selected(self, style):
        self.current_mouse_style = style
        self.mouse_style_changed.emit(style)

    def toggle_teleprompter(self):
        if not hasattr(self, 'teleprompter') or self.teleprompter is None:
            self.teleprompter = TeleprompterWindow()
            self.teleprompter.show()
            self.update_teleprompter_button_style(True)
            
            # Connect closed signal to handle cleanup/UI update
            self.teleprompter.closed.connect(self.on_teleprompter_closed)
            
        else:
            if self.teleprompter.isVisible():
                # If already visible, just activate it (User requirement: "only open existing")
                # Wait, usually toggle means hide if visible. 
                # User said: "if already has one... click... only open existing"
                # This implies: If hidden/minimized -> Open/Restore. If Visible -> Focus.
                # BUT user also said "only open existing", maybe contrasting with creating NEW one.
                # Let's assume toggle behavior is still desired for UX, but if "only open existing" means
                # "don't create new one", we are safe.
                # However, if user means "Clicking button should NOT close it if open", then I should just activate.
                # Let's interpret "only open existing" as "Show/Focus" if it exists.
                # But standard behavior for such panel buttons is Toggle.
                # Let's try Toggle behavior first as it's standard.
                # Re-reading: "如果已经有一个提词器，点击控制面板上按钮只能打开已有的提词器" -> "If there is already a teleprompter, clicking the button on the control panel can ONLY open the existing teleprompter."
                # This sounds like: 1. Don't create new. 2. "Open" it.
                # It doesn't explicitly say "Close it if open".
                # But if I can't close it via button, I can only close via 'X'.
                # Let's stick to Toggle for now, but ensure Singleton (which we have).
                # Actually, if I just Activate, how does user hide it without closing? Minimize button we just added.
                # So maybe button should just be "Show/Focus".
                # Let's make it: If hidden/minimized -> Show. If visible -> Focus.
                # If user wants to close, they use X. If they want to minimize, they use -.
                # This fits "Only open existing" literally.
                
                # Check if minimized
                if self.teleprompter.isMinimized():
                    self.teleprompter.showNormal()
                
                self.teleprompter.show()
                self.teleprompter.activateWindow()
                self.update_teleprompter_button_style(True)
            else:
                self.teleprompter.show()
                self.teleprompter.activateWindow()
                self.update_teleprompter_button_style(True)

    def on_teleprompter_closed(self):
        self.update_teleprompter_button_style(False)
        # We don't necessarily need to set to None if we want to preserve state (text), 
        # but if the window is truly closed (destroyed), we must.
        # TeleprompterWindow calls close(), which usually hides if WA_DeleteOnClose is not set.
        # But for top level widgets, close() usually hides.
        # However, we emitted 'closed' signal.
        # Let's assume we keep the instance to save text.
        # But wait, if user clicks X, they might expect reset.
        # Let's keep it simple: Hide on close, keep instance.
        # But we need to know if we should re-show.
        pass

    def update_teleprompter_button_style(self, active):
        if active:
            self.btn_teleprompter.setStyleSheet("""
                QPushButton {
                    background-color: #555555;
                    border: 2px solid #00afff; /* Blue border */
                    border-radius: 5px;
                    color: #00afff;
                    font-size: 20px;
                }
                QPushButton:hover {
                    background-color: #666666;
                }
            """)
        else:
            # Revert to default IconButton style
            self.btn_teleprompter.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 5px;
                    color: #888888;
                    font-size: 20px;
                }
                QPushButton:hover {
                    background-color: #444444;
                    color: white;
                }
                QPushButton:checked {
                    background-color: #555555;
                    color: #00afff;
                    border: 1px solid #00afff;
                }
            """)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QPen
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制背景
        painter.setBrush(QColor("#2b2b2b"))
        
        # 绘制边框
        pen = QPen(QColor("#555555"))
        pen.setWidth(1)
        painter.setPen(pen)
        
        # 绘制圆角矩形
        rect = self.rect().adjusted(0, 0, -1, -1) 
        painter.drawRoundedRect(rect, 10, 10)

    # --- 拖拽逻辑 ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.old_pos = None