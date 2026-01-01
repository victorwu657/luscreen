from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
                               QLineEdit, QFrame, QMenu, QToolTip)
from PySide6.QtCore import Qt, Signal, QSize, QPoint
from PySide6.QtGui import QAction, QIntValidator
from src.camera import CameraWidget
from src.audio_recorder import AudioRecorder

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

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 当前选中的设备索引
        self.current_mic_index = None
        self.current_cam_index = 0
        self.current_ratio = None  # None means free selection
        self.current_mouse_style = 'both'
        self.old_pos = None # 用于拖拽
        
        # 移除 ControlPanel 自身的背景样式，改为在 paintEvent 中绘制
        # 保留 color: white 以便继承
        self.setStyleSheet("""
            ControlPanel {
                color: white;
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
            }
            QPushButton#ModeBtn:hover {
                background-color: #444;
                color: white;
                border-radius: 4px;
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
        layout.setContentsMargins(15, 15, 15, 15)
        
        # --- 第一行：模式与尺寸 ---
        row1 = QHBoxLayout()
        
        # 模式按钮
        self.btn_fullscreen = QPushButton("全屏")
        self.btn_fullscreen.setObjectName("ModeBtn")
        self.btn_fullscreen.setCheckable(True)
        self.btn_fullscreen.clicked.connect(lambda: self.set_mode('fullscreen'))
        
        self.btn_area = QPushButton("区域")
        self.btn_area.setObjectName("ModeBtn")
        self.btn_area.setCheckable(True)
        self.btn_area.clicked.connect(lambda: self.set_mode('area'))
        
        row1.addWidget(self.btn_fullscreen)
        row1.addWidget(self.btn_area)
        
        # 尺寸输入
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
        
        row1.addWidget(QLabel("W:"))
        row1.addWidget(self.width_input)
        row1.addWidget(QLabel("x"))
        row1.addWidget(QLabel("H:"))
        row1.addWidget(self.height_input)
        
        # 比例菜单按钮
        self.btn_ratio = QPushButton("⚙️") # 比例/设置
        self.btn_ratio.setFixedSize(30, 30)
        self.btn_ratio.setStyleSheet("background: transparent; border: none; color: #aaa;")
        self.btn_ratio.setMenu(self.create_ratio_menu())
        row1.addWidget(self.btn_ratio)
        
        row1.addStretch()
        
        # 取消按钮
        btn_cancel = QPushButton("❌")
        btn_cancel.setFixedSize(30, 30)
        btn_cancel.setToolTip("取消")
        btn_cancel.setStyleSheet("background: transparent; border: none; color: #aaa; font-size: 14px;")
        btn_cancel.clicked.connect(self.cancel_clicked.emit)
        row1.addWidget(btn_cancel)
        
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
        self.set_mode(None)

    def set_capture_mode(self):
        """切换到截图模式的简化界面"""
        # 隐藏第二行（设备开关）
        self.btn_mic.hide()
        self.btn_sys.hide()
        self.btn_cam.hide()
        self.btn_mouse.hide()
        
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
        # 隐藏第二行（设备开关）
        self.btn_mic.hide()
        self.btn_sys.hide()
        self.btn_cam.hide()
        self.btn_mouse.hide()
        
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
        self.btn_fullscreen.setChecked(mode == 'fullscreen')
        self.btn_area.setChecked(mode == 'area')
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
            ("1:1 (正方形)", 1.0)
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
        # 如果是固定比例，我们需要通知外部（Selector）去调整选区
        # 这里有点复杂，因为 ControlPanel 之前只发 size_changed (w, h)
        # 我们需要一个新的信号 ratio_changed
        
        # 为了兼容现有逻辑，我们可以根据当前的宽度，计算出新的高度，然后发射 size_changed
        # 或者增加一个 ratio_changed 信号
        
        # 让我们添加 ratio_changed 信号到类定义中
        self.ratio_changed.emit(ratio)

    def update_size_display(self, w, h):
        self.width_input.setText(str(w))
        self.height_input.setText(str(h))

    def on_size_input(self):
        try:
            w = int(self.width_input.text())
            h = int(self.height_input.text())
            self.size_changed.emit(w, h)
        except:
            pass

    def on_mic_click(self, checked):
        self.mic_toggled.emit(checked)
        
    def show_mic_menu(self, pos):
        menu = QMenu(self)
        try:
            devices = AudioRecorder.get_input_devices()
            for dev in devices:
                action = QAction(dev['name'], self)
                action.setCheckable(True)
                # 如果当前索引匹配，或者 (当前为None且是默认设备通常是0)
                # 这里简单起见，如果 self.current_mic_index 是 None，我们假设它是默认设备
                # 但为了准确，我们只在匹配时打钩
                if self.current_mic_index == dev['index']:
                    action.setChecked(True)
                
                action.triggered.connect(lambda c=False, idx=dev['index']: self.on_mic_selected(idx))
                menu.addAction(action)
        except:
            menu.addAction("无法获取设备")
        menu.exec(self.btn_mic.mapToGlobal(pos))

    def on_mic_selected(self, index):
        print(f"DEBUG: ControlPanel on_mic_selected index={index}")
        self.current_mic_index = index
        self.mic_changed.emit(index)

    def on_cam_click(self, checked):
        self.camera_toggled.emit(checked)
        
    def show_cam_menu(self, pos):
        menu = QMenu(self)
        
        # 形状子菜单
        shape_menu = QMenu("形状", self)
        shapes = [
            ('圆形', 'circle'),
            ('圆角正方形', 'square'),
            ('横向 4:3', '4:3'),
            ('竖向 3:4', '3:4')
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