from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor, QPainter

class CountdownWidget(QWidget):
    finished = Signal()

    def __init__(self):
        super().__init__()
        # 全屏，无边框，置顶，背景透明
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 覆盖全屏
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        
        # 布局
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        
        self.label = QLabel("3")
        self.label.setAlignment(Qt.AlignCenter)
        # 增加文字阴影或轮廓以提高可见性
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                font-weight: bold;
                background-color: transparent;
            }
        """)
        
        # 设置巨大字体
        font = QFont("Arial", 150, QFont.Bold)
        self.label.setFont(font)
        
        layout.addWidget(self.label)
        
        self.count = 3
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_count)
        self.timer.start(1000)
        
    def update_count(self):
        self.count -= 1
        if self.count > 0:
            self.label.setText(str(self.count))
        elif self.count == 0:
            self.label.setText("GO!")
        else:
            self.timer.stop()
            self.close()
            self.finished.emit()
            
    def paintEvent(self, event):
        # 绘制半透明黑色背景
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))