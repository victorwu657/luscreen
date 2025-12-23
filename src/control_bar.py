from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QApplication
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon
import ctypes
from ctypes import wintypes
import os

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
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
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
        # 尝试将控制条放在录制区域下方
        screen = QApplication.primaryScreen().geometry()
        
        # 区域底部坐标
        region_bottom = self.recording_region.get('top') + self.recording_region.get('height')
        region_top = self.recording_region.get('top')
        region_center_x = self.recording_region.get('left') + self.recording_region.get('width') // 2
        
        bar_w = self.width()
        bar_h = self.height()
        
        # 计算水平位置：居中于录制区域
        x = region_center_x - bar_w // 2
        
        # 垂直位置策略：
        # 1. 优先放在区域下方 (加一点间距 20px)
        y = region_bottom + 20
        
        # 2. 如果下方超出屏幕，放在区域上方
        if y + bar_h > screen.height():
            y = region_top - bar_h - 20
            
        # 3. 如果上方也超出屏幕（全屏录制），或者就在区域内部底部
        #    注意：如果全屏录制，确实很难不遮挡。
        #    作为妥协，放在屏幕右下角，或者顶部中间，但用户要求“不要录进去”
        #    这对于全屏录制几乎是不可能的，除非最小化到托盘。
        #    这里我们尽可能放在角落，或者提示用户。
        
        if y < 0: 
            # 全屏情况，放在顶部，但可能会被录进去。
            # 唯一的办法是让 mss 忽略这个窗口，但这很复杂。
            # 或者我们将控制条放在屏幕边缘之外？不行，那样用户点不到停止。
            # 妥协方案：放在屏幕右下角，尽量减少干扰
            y = screen.height() - bar_h - 50
            x = screen.width() - bar_w - 50
            
        # 确保 x 在屏幕内
        if x < 0: x = 10
        if x + bar_w > screen.width(): x = screen.width() - bar_w - 10
            
        self.move(x, y)

    def on_pause_clicked(self):
        self.pause_clicked.emit()

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