from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QPen, QColor
import ctypes
from ctypes import wintypes
import os

class RecordingFrame(QWidget):
    def __init__(self, rect):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        
        # 设置几何位置
        # 注意：rect 是全局坐标
        self.setGeometry(rect)
        
        # 为了不影响录制画面，我们可以把框画在区域外部，或者画在边缘上
        # 但由于这是一个独立的窗口，它的 geometry 就是录制区域
        # 如果我们在里面画框，会遮挡一部分录制内容
        # 更好的做法是让这个窗口比录制区域稍大一点，或者就在边缘画细线
        # 这里我们简单处理：就在边缘画红线，可能会被录进去一点点，但这是提示框的代价
        # 或者我们可以调整窗口大小比 rect 大一点
        
        padding = 2
        self.setGeometry(rect.adjusted(-padding, -padding, padding, padding))
        self.border_rect = QRect(padding, padding, rect.width(), rect.height())
        
        self.is_paused = False
        self.exclude_from_capture()

    def set_paused(self, paused):
        self.is_paused = paused
        self.update() # Trigger repaint

    def exclude_from_capture(self):
        if os.name != 'nt':
            return
            
        try:
            user32 = ctypes.windll.user32
            user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
            
            hwnd = int(self.winId())
            # WDA_EXCLUDEFROMCAPTURE = 0x00000011
            result = user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
            if not result:
                print(f"Failed to exclude RecordingFrame from capture: {ctypes.get_last_error()}")
        except Exception as e:
            print(f"Error excluding RecordingFrame: {e}")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        color = Qt.yellow if self.is_paused else Qt.red
        pen = QPen(color, 1, Qt.DashLine) # 1像素虚线
        
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        
        painter.drawRect(self.border_rect)