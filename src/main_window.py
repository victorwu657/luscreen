from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
                               QFrame)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFont

class MainMenuButton(QPushButton):
    def __init__(self, text, icon_text, parent=None):
        super().__init__(parent)
        self.setFixedSize(200, 45)
        self.setCursor(Qt.PointingHandCursor)
        
        # Use a horizontal layout for icon and text
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 0, 0)
        layout.setSpacing(15)
        layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        self.icon_label = QLabel(icon_text)
        self.icon_label.setStyleSheet("color: #00afff; font-size: 18px; border: none; background: transparent;")
        
        self.text_label = QLabel(text)
        self.text_label.setStyleSheet("color: #dddddd; font-size: 14px; border: none; background: transparent;")
        
        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label)
        
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 6px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #444444;
            }
            QPushButton:pressed {
                background-color: #555555;
            }
        """)

class MainWindow(QWidget):
    # Signals to communicate with the main controller
    action_triggered = Signal(str) # 'capture_area', 'capture_full', 'record', 'settings', 'quit'

    def __init__(self):
        super().__init__()
        
        # 使用 Qt.Popup 属性：
        # 1. 它是模态的，会捕获鼠标输入
        # 2. 点击窗口外部区域时，它会自动关闭（隐藏）
        # 3. 它默认置顶
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Popup)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.init_ui()
        
        # For dragging
        self.old_pos = None

    def init_ui(self):
        # Main container with rounded corners and border
        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame {
                background-color: #2b2b2b;
                border: 1px solid #555555;
                border-radius: 10px;
            }
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)
        
        # Content layout
        layout = QVBoxLayout(self.container)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 15, 10, 15)
        
        # Title / Drag Handle
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(5, 0, 5, 5)
        
        self.title_label = QLabel("LuScreen")
        self.title_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.title_label.setStyleSheet("color: #888888; border: none;")
        
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        
        # Close button (small 'x')
        self.btn_close = QPushButton("×")
        self.btn_close.setFixedSize(20, 20)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet("""
            QPushButton {
                color: #888888;
                background: transparent;
                border: none;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: white;
            }
        """)
        self.btn_close.clicked.connect(self.hide)
        title_layout.addWidget(self.btn_close)
        
        layout.addLayout(title_layout)
        
        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("background-color: #444444; border: none; max-height: 1px;")
        layout.addWidget(line)
        layout.addSpacing(5)
        
        # Buttons
        self.btn_area = MainMenuButton("区域截图", "⛶")
        self.btn_area.clicked.connect(lambda: self.trigger_action('capture_area'))
        layout.addWidget(self.btn_area)
        
        self.btn_full = MainMenuButton("全屏截图", "🖥️")
        self.btn_full.clicked.connect(lambda: self.trigger_action('capture_full'))
        layout.addWidget(self.btn_full)
        
        self.btn_record = MainMenuButton("录制屏幕", "🔴")
        self.btn_record.clicked.connect(lambda: self.trigger_action('record'))
        layout.addWidget(self.btn_record)
        
        layout.addSpacing(5)
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet("background-color: #444444; border: none; max-height: 1px;")
        layout.addWidget(line2)
        layout.addSpacing(5)
        
        self.btn_settings = MainMenuButton("设置", "⚙️")
        self.btn_settings.clicked.connect(lambda: self.trigger_action('settings'))
        layout.addWidget(self.btn_settings)
        
        self.btn_quit = MainMenuButton("退出程序", "🚪")
        self.btn_quit.clicked.connect(lambda: self.trigger_action('quit'))
        layout.addWidget(self.btn_quit)

    def trigger_action(self, action):
        self.hide()
        # 强制刷新UI循环并稍作等待，确保窗口在截屏前完全从屏幕上消失
        from PySide6.QtWidgets import QApplication
        import time
        QApplication.processEvents()
        time.sleep(0.2)
        
        self.action_triggered.emit(action)

    def show_at_cursor(self):
        pos = QCursor.pos()
        
        # 先显示以获取正确尺寸
        self.show()
        
        screen = self.screen().geometry()
        w = self.width()
        h = self.height()
        
        # 策略调整：将窗口显示在鼠标的【左上方】，以避开通常向右下展开的系统右键菜单
        # 这样即使系统菜单没关掉，我们的窗口也不会被遮挡
        x = pos.x() - w + 15 
        y = pos.y() - 15
        
        # 边界检查 (防止跑出屏幕左上)
        if x < screen.left():
            x = screen.left() + 10
        if y < screen.top():
            y = screen.top() + 10
            
        # 右下边界检查
        if x + w > screen.right():
            x = screen.right() - w - 10
        if y + h > screen.bottom():
            y = screen.bottom() - h - 10
            
        self.move(x, y)
        
        # 强制置顶 (Windows API)
        # 这有助于覆盖系统右键菜单
        import os
        if os.name == 'nt':
            try:
                import ctypes
                HWND_TOPMOST = -1
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_SHOWWINDOW = 0x0040
                hwnd = int(self.winId())
                ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, 
                                                  SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            except Exception as e:
                print(f"Force topmost failed: {e}")
                
        self.raise_()
        self.activateWindow() # 关键：获取焦点以便检测 focusOut

    def show_centered(self):
        screen = self.screen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        self.show()
        self.activateWindow()

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

    def focusOutEvent(self, event):
        # 失去焦点时（点击外部）自动隐藏
        self.hide()
        super().focusOutEvent(event)