from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QApplication
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon
import ctypes
from ctypes import wintypes
import os
import logging

logger = logging.getLogger("ControlBar")

class ControlBar(QWidget):
    stop_clicked = Signal()
    pause_clicked = Signal()

    def __init__(self, recording_region=None):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.recording_region = recording_region
        self.setStyleSheet("""
            QWidget {
                background-color: #333333;
                border-radius: 20px;
                color: white;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 15px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
            QPushButton#stopBtn {
                background-color: #ff4444;
            }
            QPushButton#stopBtn:hover {
                background-color: #ff6666;
            }
            QPushButton#pauseBtn {
                background-color: #4444ff;
                font-size: 14px;
            }
            QPushButton#pauseBtn:hover {
                background-color: #6666ff;
            }
            QLabel {
                padding: 0 10px;
                font-family: monospace;
                font-weight: bold;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        # 计时器标签
        self.time_label = QLabel("00:00")
        layout.addWidget(self.time_label)

        # 暂停/继续按钮
        self.pause_btn = QPushButton("⏸")
        self.pause_btn.setObjectName("pauseBtn")
        self.pause_btn.setFixedSize(30, 30)
        self.pause_btn.setToolTip("暂停/继续")
        self.pause_btn.clicked.connect(self.on_pause_clicked)
        layout.addWidget(self.pause_btn)

        # 停止按钮
        self.stop_btn = QPushButton()
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setFixedSize(30, 30)
        # 这里可以用图标，暂时用方形方块代替停止图标
        self.stop_btn.setText("■") 
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        layout.addWidget(self.stop_btn)

        # 录制计时逻辑
        self.seconds = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        self.timer.start(1000)
        
        # 初始位置
        self.adjustSize() # 确保尺寸计算正确
        if self.recording_region:
            self.move_out_of_region()
        else:
            self.center_on_screen()
        
        # 拖拽相关
        self.old_pos = None
        
        # 尝试将窗口从截图中排除 (Windows 10 2004+)
        self.exclude_from_capture()

    def exclude_from_capture(self):
        if os.name != 'nt':
            return
            
        try:
            # WDA_EXCLUDEFROMCAPTURE = 0x00000011
            # 即使在录制时，用户肉眼能看到窗口，但截图 API 会忽略它
            
            user32 = ctypes.windll.user32
            # 定义函数原型
            user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
            
            # 获取窗口句柄
            hwnd = int(self.winId())
            
            result = user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
            if not result:
                print(f"Failed to exclude ControlBar from capture. Error code: {ctypes.get_last_error()}")
            else:
                print("ControlBar excluded from capture successfully.")
        except Exception as e:
            print(f"Error excluding window from capture: {e}")

    def move_out_of_region(self):
        # 用户要求：
        # 1. 默认放在最下面中间，贴近任务栏
        # 2. 如果跟录制区域冲突，则放在右下角
        
        screen = QApplication.primaryScreen().geometry()
        bar_w = self.width()
        bar_h = self.height()
        
        # 默认位置：屏幕底部居中，预留一点任务栏空间 (例如 60px)
        # 通常任务栏高度在 40-60px 之间
        taskbar_height = 60 
        default_x = screen.width() // 2 - bar_w // 2
        default_y = screen.height() - bar_h - taskbar_height
        
        # 检查是否与录制区域冲突
        # 定义控制条的矩形
        from PySide6.QtCore import QRect
        bar_rect = QRect(default_x, default_y, bar_w, bar_h)
        
        # 获取录制区域矩形
        region_rect = QRect(
            self.recording_region.get('left'),
            self.recording_region.get('top'),
            self.recording_region.get('width'),
            self.recording_region.get('height')
        )
        
        final_x, final_y = default_x, default_y
        
        # 如果冲突（有交集）
        if bar_rect.intersects(region_rect):
            # 尝试方案2：右下角
            # 同样预留任务栏高度
            alt_x = screen.width() - bar_w - 20 # 右边留 20px 边距
            alt_y = screen.height() - bar_h - taskbar_height
            
            # 再次检查右下角是否也冲突？
            # 用户只说了“第二选择放在右边最下角”，没说如果还冲突怎么办。
            # 通常右下角冲突意味着全屏录制或者大区域录制。
            # 如果是全屏录制，放哪都会遮挡，除非放外面。
            # 我们就按用户说的，冲突就去右下角。
            final_x = alt_x
            final_y = alt_y
            
        # 确保坐标在屏幕内
        if final_x < 0: final_x = 0
        if final_x + bar_w > screen.width(): final_x = screen.width() - bar_w
        if final_y < 0: final_y = 0
        if final_y + bar_h > screen.height(): final_y = screen.height() - bar_h
            
        self.move(final_x, final_y)

    def on_pause_clicked(self):
        logger.info("ControlBar pause button clicked seconds=%s", self.seconds)
        self.pause_clicked.emit()

    def on_stop_clicked(self):
        logger.info("ControlBar stop button clicked seconds=%s", self.seconds)
        self.stop_clicked.emit()

    def update_timer(self):
        self.seconds += 1
        mins = self.seconds // 60
        secs = self.seconds % 60
        self.time_label.setText(f"{mins:02d}:{secs:02d}")

    def pause_timer(self):
        if self.timer.isActive():
            self.timer.stop()
            self.pause_btn.setText("▶") # 变为播放图标，提示点击继续
            self.pause_btn.setToolTip("继续录制")

    def resume_timer(self):
        if not self.timer.isActive():
            self.timer.start(1000)
            self.pause_btn.setText("⏸") # 变为暂停图标
            self.pause_btn.setToolTip("暂停录制")

    def center_on_screen(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.width() // 2 - self.width() // 2,
            screen.height() - 100
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.old_pos = None
