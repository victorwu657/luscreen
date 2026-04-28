
import sys
import ctypes
from ctypes import wintypes
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, 
                               QPushButton, QSlider, QLabel, QFrame, QApplication, QGraphicsOpacityEffect, QSizeGrip, QColorDialog)
from PySide6.QtCore import Qt, QTimer, QPoint, QSize, Signal
from PySide6.QtGui import QColor, QPalette, QFont, QIcon, QPainter, QPen, QTextCursor

import json

class TeleprompterWindow(QWidget):
    closed = Signal()
    CONFIG_FILE = "teleprompter_config.json"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Default settings
        self.scroll_speed_level = 1 # 1, 2, 3, 4
        self.font_size = 24
        self.text_color = "#FFFFFF" # Default text color
        self.is_playing = False
        self.old_pos = None
        
        # Load saved settings and text
        self.load_settings()
        
        # Setup UI
        self.init_ui()
        self.resize(500, 400)
        
        # Add resize grip to the bottom-right corner
        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("""
            QSizeGrip {
                background-color: transparent;
                width: 20px;
                height: 20px;
            }
        """)
        
        # Timer for scrolling
        self.scroll_timer = QTimer(self)
        self.scroll_timer.timeout.connect(self.scroll_text)
        
        # Center on screen
        if QApplication.primaryScreen():
            screen_geo = QApplication.primaryScreen().availableGeometry()
            self.move(
                screen_geo.center().x() - self.width() // 2,
                screen_geo.center().y() - self.height() // 2
            )
            
        # Exclude from capture (Windows only)
        self.exclude_from_capture()

    def exclude_from_capture(self):
        if os.name != 'nt':
            return
            
        try:
            # WDA_EXCLUDEFROMCAPTURE = 0x00000011
            user32 = ctypes.windll.user32
            user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
            
            hwnd = int(self.winId())
            result = user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
            if not result:
                print(f"Failed to exclude Teleprompter from capture. Error code: {ctypes.get_last_error()}")
        except Exception as e:
            print(f"Error excluding Teleprompter from capture: {e}")

    def resizeEvent(self, event):
        # Keep size grip at bottom right
        if hasattr(self, 'size_grip'):
            rect = self.rect()
            self.size_grip.move(rect.right() - self.size_grip.width(), rect.bottom() - self.size_grip.height())
        super().resizeEvent(event)

    def closeEvent(self, event):
        self.save_settings()
        self.closed.emit()
        super().closeEvent(event)

    def load_settings(self):
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.saved_text = data.get('text', "")
                    self.scroll_speed_level = data.get('speed', 1)
                    self.font_size = data.get('font_size', 24)
                    self.text_color = data.get('text_color', "#FFFFFF")
            except Exception as e:
                print(f"Error loading teleprompter settings: {e}")
                self.saved_text = ""
        else:
            self.saved_text = ""

    def save_settings(self):
        try:
            # Save raw text without the added padding
            text = self.text_edit.toPlainText()
            # We might want to strip the massive padding we added
            # Heuristic: if it ends with many newlines, strip them.
            # But user might have intended some newlines.
            # Let's just strip trailing whitespace for storage to be safe and clean.
            text = text.rstrip()
            
            data = {
                'text': text,
                'speed': self.scroll_speed_level,
                'font_size': self.font_size,
                'text_color': self.text_color
            }
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving teleprompter settings: {e}")

    def init_ui(self):
        # Main Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Container Frame (for rounded corners and background)
        self.container = QFrame()
        self.container.setObjectName("Container")
        self.container.setStyleSheet("""
            QFrame#Container {
                background-color: rgba(30, 30, 30, 240);
                border-radius: 10px;
                border: 1px solid #444;
            }
        """)
        
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(10, 10, 10, 10)
        
        # --- Top Bar (Title + Close) ---
        top_bar = QHBoxLayout()
        
        title_label = QLabel("提词器")
        title_label.setStyleSheet("color: #ccc; font-weight: bold;")
        top_bar.addWidget(title_label)
        
        top_bar.addStretch()
        
        btn_minimize = QPushButton("－")
        btn_minimize.setFixedSize(24, 24)
        btn_minimize.setCursor(Qt.PointingHandCursor)
        btn_minimize.clicked.connect(self.showMinimized)
        btn_minimize.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #888;
                border: none;
                font-size: 18px;
                font-weight: bold;
                padding-bottom: 5px;
            }
            QPushButton:hover {
                color: white;
            }
        """)
        top_bar.addWidget(btn_minimize)

        btn_close = QPushButton("×")
        btn_close.setFixedSize(24, 24)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.close)
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
        top_bar.addWidget(btn_close)
        
        container_layout.addLayout(top_bar)
        
        # --- Text Area ---
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("在此粘贴或输入台词...")
        if hasattr(self, 'saved_text') and self.saved_text:
            self.text_edit.setPlainText(self.saved_text)
            
        # Force pasted text color to white using CSS
        self.update_text_style()
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Override paste to force plain text (optional, but style sheet handles color)
        # We can also connect textChanged to re-apply color if needed, but CSS usually handles it.
        # Ensure scroll logic works by adding extra newlines to the end of content
        self.text_edit.textChanged.connect(self.ensure_padding)
        
        # Customize scrollbar
        self.text_edit.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                border: none;
                background: rgba(0,0,0,0.1);
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.3);
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        container_layout.addWidget(self.text_edit)
        
        # --- Bottom Toolbar ---
        toolbar = QFrame()
        toolbar.setStyleSheet("""
            QFrame {
                background-color: rgba(50, 50, 50, 150);
                border-radius: 20px;
                padding: 4px;
            }
            QLabel {
                color: #ccc;
                font-size: 12px;
                margin-left: 5px;
            }
        """)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 2, 10, 2)
        toolbar_layout.setSpacing(10)
        
        # 1. Play/Pause
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(32, 32)
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.setToolTip("播放/暂停 (Space)")
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_play.setStyleSheet("""
            QPushButton {
                background-color: #007aff;
                color: white;
                border-radius: 16px;
                font-size: 14px;
                padding-bottom: 2px;
            }
            QPushButton:hover {
                background-color: #0099ff;
            }
        """)
        toolbar_layout.addWidget(self.btn_play)
        
        # 2. Font Size
        toolbar_layout.addWidget(QLabel("A"))
        
        self.slider_font = QSlider(Qt.Horizontal)
        self.slider_font.setRange(12, 72)
        self.slider_font.setValue(self.font_size)
        self.slider_font.setFixedWidth(60) # Reduced width
        self.slider_font.setToolTip("字体大小")
        self.slider_font.valueChanged.connect(self.change_font_size)
        toolbar_layout.addWidget(self.slider_font)
        
        # 3. Speed (Slider + Label)
        toolbar_layout.addWidget(QLabel("🚀"))
        
        self.slider_speed = QSlider(Qt.Horizontal)
        self.slider_speed.setRange(1, 4) # 1x to 4x
        self.slider_speed.setValue(self.scroll_speed_level)
        self.slider_speed.setFixedWidth(40) # Shortened slider
        self.slider_speed.setToolTip("滚动速度")
        self.slider_speed.valueChanged.connect(self.change_speed_level)
        toolbar_layout.addWidget(self.slider_speed)
        
        self.lbl_speed = QLabel(f"{self.scroll_speed_level}x")
        self.lbl_speed.setFixedWidth(30) # Widened label
        self.lbl_speed.setStyleSheet("color: white; font-weight: bold;")
        toolbar_layout.addWidget(self.lbl_speed)
        
        # 4. Text Color
        self.btn_color = QPushButton("🎨")
        self.btn_color.setFixedSize(24, 24)
        self.btn_color.setCursor(Qt.PointingHandCursor)
        self.btn_color.setToolTip("文字颜色")
        self.btn_color.clicked.connect(self.pick_color)
        self.btn_color.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.2);
                border-radius: 12px;
            }
        """)
        toolbar_layout.addWidget(self.btn_color)

        # 5. Opacity
        toolbar_layout.addWidget(QLabel("👁"))
        
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(20, 100) # 20% to 100%
        self.slider_opacity.setValue(100)
        self.slider_opacity.setFixedWidth(60) # Reduced width
        self.slider_opacity.setToolTip("窗口透明度")
        self.slider_opacity.valueChanged.connect(self.change_opacity)
        toolbar_layout.addWidget(self.slider_opacity)
        
        # 6. Reset
        btn_reset = QPushButton("↺")
        btn_reset.setFixedSize(24, 24)
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.setToolTip("重置滚动")
        btn_reset.clicked.connect(self.reset_scroll)
        btn_reset.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #ccc;
                border: none;
                font-size: 16px;
            }
            QPushButton:hover {
                color: white;
            }
        """)
        toolbar_layout.addWidget(btn_reset)
        
        container_layout.addWidget(toolbar)
        
        layout.addWidget(self.container)

    def toggle_play(self):
        if self.is_playing:
            self.stop_scroll()
        else:
            self.start_scroll()

    def start_scroll(self):
        self.is_playing = True
        self.btn_play.setText("⏸")
        self.btn_play.setStyleSheet("""
            QPushButton {
                background-color: #ff9500;
                color: white;
                border-radius: 16px;
                font-size: 14px;
                padding-bottom: 2px;
            }
            QPushButton:hover {
                background-color: #ffaa33;
            }
        """)
        # Calculate interval based on speed level (1x, 2x, 3x, 4x)
        # 1x: 250ms (Very Slow), 2x: 200ms, 3x: 100ms, 4x: 80ms
        intervals = {1: 250, 2: 200, 3: 100, 4: 80}
        interval = intervals.get(self.scroll_speed_level, 250)
        self.scroll_timer.start(interval)

    def stop_scroll(self):
        self.is_playing = False
        self.btn_play.setText("▶")
        self.btn_play.setStyleSheet("""
            QPushButton {
                background-color: #007aff;
                color: white;
                border-radius: 16px;
                font-size: 14px;
                padding-bottom: 2px;
            }
            QPushButton:hover {
                background-color: #0099ff;
            }
        """)
        self.scroll_timer.stop()

    def reset_scroll(self):
        self.stop_scroll()
        self.text_edit.verticalScrollBar().setValue(0)

    def scroll_text(self):
        scrollbar = self.text_edit.verticalScrollBar()
        current_val = scrollbar.value()
        max_val = scrollbar.maximum()
        
        # print(f"DEBUG: scroll_text val={current_val} max={max_val}")
        
        if current_val >= max_val:
            # Check if we really reached the visual end or if we need more padding?
            # If we added padding correctly, max_val should allow scrolling to top.
            self.stop_scroll()
            return
            
        scrollbar.setValue(current_val + 1)

    def ensure_padding(self):
        # We only use this to prevent auto-scroll interference during typing if needed
        # For now, pass
        pass

    def toggle_play(self):
        if self.is_playing:
            self.stop_scroll()
        else:
            # Before starting, ensure we have enough padding at the bottom
            self.add_bottom_padding()
            self.start_scroll()

    def add_bottom_padding(self):
        # Temporarily block signals to prevent recursive calls or weird updates
        old_state = self.text_edit.blockSignals(True)
        
        # Calculate lines needed to push last line to top
        # height / line_height
        # Use a safe default for line height if calculation is tricky
        line_height = max(20, self.font_size * 1.5) 
        viewport_height = self.text_edit.viewport().height()
        lines_needed = int(viewport_height / line_height) + 2 # Add a bit extra buffer
        
        padding = "\n" * lines_needed
        
        doc = self.text_edit.document()
        text = doc.toPlainText()
        
        # Check if we already have a big block of newlines at the end
        # We check for a subset of the needed padding to avoid constant addition
        if not text.endswith("\n" * (lines_needed // 2)): 
             cursor = self.text_edit.textCursor()
             cursor.movePosition(QTextCursor.End)
             cursor.insertText(padding)
        
        self.text_edit.blockSignals(old_state)

    def pick_color(self):
        color = QColorDialog.getColor(QColor(self.text_color), self, "选择文字颜色")
        if color.isValid():
            self.text_color = color.name()
            self.update_text_style()

    def update_text_style(self):
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                color: {self.text_color};
                border: none;
                font-family: "Microsoft YaHei", sans-serif;
                font-size: {self.font_size}px;
                line-height: 1.5;
            }}
        """)
        
    def change_speed_level(self, value):
        self.scroll_speed_level = value
        self.lbl_speed.setText(f"{value}x")
        
        if self.is_playing:
            # Restart timer with new interval
            self.stop_scroll()
            self.start_scroll()

    def change_opacity(self, value):
        opacity = value / 100.0
        self.setWindowOpacity(opacity)

    def change_font_size(self, value):
        self.font_size = value
        self.update_text_style()

    # --- Dragging Logic ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Don't start drag if clicking on slider or button (handled by widgets)
            # But since they are children, they should accept event first.
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.old_pos = None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TeleprompterWindow()
    window.show()
    sys.exit(app.exec())
