from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QPushButton, QLabel, 
                               QFrame, QScrollArea, QHBoxLayout)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QCursor, QColor
import webbrowser

class AIToolButton(QPushButton):
    def __init__(self, name, url, color="#00afff", parent=None):
        super().__init__(parent)
        self.url = url
        self.setFixedSize(100, 100)
        self.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignCenter)
        
        # Icon (Character)
        self.icon_label = QLabel(name[0].upper())
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet(f"""
            QLabel {{
                color: white;
                background-color: {color};
                border-radius: 25px;
                font-size: 24px;
                font-weight: bold;
                min-width: 50px;
                min-height: 50px;
                max-width: 50px;
                max-height: 50px;
            }}
        """)
        
        # Text
        self.text_label = QLabel(name)
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setStyleSheet("color: #dddddd; font-size: 12px; background: transparent; border: none;")
        self.text_label.setWordWrap(True)
        
        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label)
        
        self.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                border: 1px solid #444444;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #444444;
                border: 1px solid #555555;
            }
            QPushButton:pressed {
                background-color: #222222;
            }
        """)
        
        self.clicked.connect(self.open_url)

    def open_url(self):
        webbrowser.open(self.url)

class AIToolsWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Use Tool flag to be independent but stay on top when active
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, False) # Don't delete on close, just hide
        self.setStyleSheet("background: transparent;")
        
        self.init_ui()
        
    def init_ui(self):
        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        self.container.setStyleSheet("""
            #MainContainer {
                background-color: #2b2b2b;
                border: 1px solid #555555;
                border-radius: 10px;
            }
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10) # Shadow margin placeholder
        main_layout.addWidget(self.container)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        title = QLabel("AI 工具箱")
        title.setStyleSheet("color: white; font-size: 16px; font-weight: bold; border: none; background: transparent;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        btn_close = QPushButton("×")
        btn_close.setFixedSize(24, 24)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                color: #888888;
                background: transparent;
                border: none;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: white;
            }
        """)
        btn_close.clicked.connect(self.hide)
        header_layout.addWidget(btn_close)
        
        layout.addLayout(header_layout)
        
        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #444444; border: none; max-height: 1px;")
        layout.addWidget(line)
        
        # Grid
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QWidget { background: transparent; }
            QScrollBar:vertical {
                border: none;
                background: #2b2b2b;
                width: 8px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #555555;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        
        scroll_content = QWidget()
        grid_layout = QGridLayout(scroll_content)
        grid_layout.setSpacing(10)
        
        tools = [
            ("Sora", "https://sora2.ironai.cn/pix/#/video-generator", "#000000"),
            ("Nano Banana", "https://sora2.ironai.cn/pix/#/image-generator", "#ffe135"),
            ("蝉镜数字人", "https://www.chanjing.cc/refc/?type=hzBuy&id=annnqdRM_gekt-fGKR-G9DDEPxmTXCuoZHhZ1CrBBXA", "#ff6b00"),
        ]
        
        row, col = 0, 0
        cols = 3
        
        for name, url, color in tools:
            # Special handling for white/light backgrounds if needed, but current impl uses white text.
            # If color is white, text won't show.
            # Let's use dark text for white bg? 
            # Simplified: just use darker bg for white icons or change text color logic.
            # For now, manually adjust white bg ones to #333 or keep white and hope contrast is ok (it won't be).
            # Fix: Midjourney uses white logo on black usually, or black on white. 
            # Let's set Midjourney to Black bg for icon.
            if name == "Midjourney": color = "#000000"
            if name == "Suno": color = "#000000"
            
            btn = AIToolButton(name, url, color)
            grid_layout.addWidget(btn, row, col)
            col += 1
            if col >= cols:
                col = 0
                row += 1
                
        # Add spacer to push content up
        grid_layout.setRowStretch(row + 1, 1)
                
        self.scroll.setWidget(scroll_content)
        layout.addWidget(self.scroll)
        
        # Resize
        self.resize(380, 500)
        
        # Drag support
        self.old_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.old_pos:
            delta = event.globalPos() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPos()

    def mouseReleaseEvent(self, event):
        self.old_pos = None