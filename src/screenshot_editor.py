import os
from datetime import datetime
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QFileDialog, QApplication, QInputDialog, QLineEdit,
                               QGraphicsDropShadowEffect, QLabel, QColorDialog, QSlider, QStackedLayout, QSizePolicy)
from PySide6.QtCore import Qt, QPoint, QRect, QSize, Signal, QTimer, QEvent, QPointF
from PySide6.QtGui import (QPainter, QPen, QColor, QBrush, QPixmap, QImage, 
                           QIcon, QPainterPath, QAction, QFont, QCursor, QGuiApplication, QFontMetrics,
                           QPainterPathStroker, QFontDatabase)
import pyperclip
import random
import math

class EditToolBar(QWidget):
    # Signals for tools
    tool_selected = Signal(str) # 'rect', 'circle', 'arrow', 'line', 'pen', 'mosaic', 'text'
    action_triggered = Signal(str) # 'save', 'copy', 'close', 'undo'
    color_changed = Signal(QColor)
    width_changed = Signal(int)
    font_size_changed = Signal(int)
    style_changed = Signal(str) # 'normal', 'hand_drawn'
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Background container
        self.container = QWidget()
        self.container.setStyleSheet("""
            QWidget {
                background-color: #f5f5f5;
                border-radius: 4px;
                border: 1px solid #dcdcdc;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 3px;
                padding: 1px;
                font-size: 16px;
                color: #333;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:checked {
                background-color: #d0d0d0;
                color: #007aff;
            }
        """)
        
        # Add shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 50))
        shadow.setOffset(0, 2)
        self.container.setGraphicsEffect(shadow)
        
        # Force compact height
        self.container.setFixedHeight(34) # 30px buttons + 2px top/bottom padding
        
        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(2, 2, 2, 2)
        container_layout.setSpacing(2)
        
        self.layout.addWidget(self.container)
        
        # --- Open Button (New) ---
        self.btn_open = QPushButton("📂")
        self.btn_open.setFixedSize(30, 30)
        self.btn_open.setToolTip("打开图片")
        self.btn_open.clicked.connect(lambda: self.action_triggered.emit('open'))
        # Initially hidden, shown only in standalone mode
        self.btn_open.hide() 
        container_layout.addWidget(self.btn_open)
        
        # --- Style Toggle ---
        self.btn_style = QPushButton("🎨")
        self.btn_style.setFixedSize(30, 30)
        self.btn_style.setCheckable(True)
        self.btn_style.setToolTip("切换手绘风格")
        self.btn_style.clicked.connect(self.toggle_style)
        container_layout.addWidget(self.btn_style)

        # --- Color Picker ---
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(24, 24)
        self.btn_color.setStyleSheet("background-color: red; border: 2px solid #ccc; border-radius: 12px;")
        self.btn_color.setToolTip("选择颜色")
        self.btn_color.clicked.connect(self.choose_color)
        container_layout.addWidget(self.btn_color)
        
        # --- Settings Container (Stacked) ---
        # Use a stacked layout to switch between width slider and font size buttons
        # This prevents layout jumping as the container size is fixed.
        self.settings_container = QWidget()
        self.settings_container.setFixedWidth(110) # Fixed width for the settings area
        self.settings_stack = QStackedLayout(self.settings_container)
        self.settings_stack.setContentsMargins(0, 0, 0, 0)
        
        # --- Width Selector (Slider) ---
        self.width_widget = QWidget()
        ww_layout = QHBoxLayout(self.width_widget)
        ww_layout.setContentsMargins(0, 0, 0, 0)
        ww_layout.setSpacing(5)

        self.width_slider = QSlider(Qt.Horizontal)
        self.width_slider.setRange(1, 20)
        self.width_slider.setValue(3)
        self.width_slider.setFixedWidth(60)
        self.width_slider.setToolTip("线条粗细")
        self.width_slider.valueChanged.connect(self.on_width_changed)
        
        self.width_label = QLabel("3")
        self.width_label.setStyleSheet("color: #333; font-size: 10px; margin-right: 5px;")
        self.width_label.setFixedWidth(20)
        self.width_label.setAlignment(Qt.AlignCenter)
        
        ww_layout.addWidget(self.width_slider)
        ww_layout.addWidget(self.width_label)
        
        self.settings_stack.addWidget(self.width_widget)
        
        # --- Font Size Selector ---
        self.font_widget = QWidget()
        fw_layout = QHBoxLayout(self.font_widget)
        fw_layout.setContentsMargins(0, 0, 0, 0)
        fw_layout.setSpacing(2)

        self.font_btns = []
        sizes = [('小', 12), ('中', 16), ('大', 24)]
        for label, size in sizes:
            btn = QPushButton(label)
            btn.setFixedSize(24, 24)
            btn.setCheckable(True)
            btn.setStyleSheet("""
                QPushButton { border: 1px solid #ccc; border-radius: 3px; font-size: 12px; color: #333; }
                QPushButton:checked { background-color: #007aff; color: white; border: 1px solid #005bb5; }
                QPushButton:hover { background-color: #e0e0e0; }
            """)
            btn.clicked.connect(lambda c, s=size, b=btn: self.on_font_size_clicked(s, b))
            fw_layout.addWidget(btn)
            self.font_btns.append(btn)
            if size == 16: btn.setChecked(True)
            
        self.settings_stack.addWidget(self.font_widget)
        
        container_layout.addWidget(self.settings_container)
        
        # Separator
        line1 = QLabel("|")
        line1.setStyleSheet("color: #bbb;")
        line1.setFixedWidth(10)
        line1.setAlignment(Qt.AlignCenter)
        from PySide6.QtWidgets import QSizePolicy
        line1.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        container_layout.addWidget(line1)
        
        # Tools
        self.tools = {}
        # Symbols: 
        # Move: ✋ (Move elements)
        # Rect: ⬜ (using unicode square)
        # Circle: ⭕
        # Arrow: ↗️
        # Line: 📏
        # Pen: ✏️
        # Mosaic: ▒
        # Text: T
        # Undo: ↩️
        # Save: 💾
        # Copy: 📋
        # Close: ❌
        
        tool_defs = [
            ('move', '✋', '移动元素'),
            ('rect', '⬜', '矩形'),
            ('circle', '⭕', '圆形'),
            ('arrow', '↗️', '箭头'),
            ('line', '📏', '直线'),
            ('pen', '✏️', '画笔'),
            ('mosaic', '🏁', '马赛克'),
            ('text', 'T', '文字'),
        ]
        
        for key, icon, tooltip in tool_defs:
            btn = QPushButton(icon)
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setFixedSize(30, 30)
            btn.clicked.connect(lambda c, k=key: self.select_tool(k))
            container_layout.addWidget(btn)
            self.tools[key] = btn
            
        # Separator
        line = QLabel("|")
        line.setStyleSheet("color: #bbb;")
        line.setFixedWidth(10)
        line.setAlignment(Qt.AlignCenter)
        line.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        container_layout.addWidget(line)
        
        # Actions
        action_defs = [
            ('undo', '↩️', '撤销 (Ctrl+Z)'),
            ('zoom_in', 'assets/big.png', '放大'),
            ('zoom_out', 'assets/small.png', '缩小'),
            ('clear', '🗑️', '清空'),
            ('save', '💾', '保存 (Ctrl+S)'),
            ('copy', '❐', '复制 (Ctrl+C)'),
            ('minimize', '➖', '最小化'),
            ('close', '❌', '关闭'),
        ]
        
        for key, icon_val, tooltip in action_defs:
            if icon_val.endswith('.png'):
                # Load icon from file
                icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), icon_val)
                if os.path.exists(icon_path):
                     btn = QPushButton()
                     btn.setIcon(QIcon(icon_path))
                     btn.setIconSize(QSize(20, 20))
                else:
                     btn = QPushButton("?") # Fallback
            else:
                btn = QPushButton(icon_val)
                
            btn.setToolTip(tooltip)
            btn.setFixedSize(30, 30)
            btn.clicked.connect(lambda c, k=key: self.action_triggered.emit(k))
            container_layout.addWidget(btn)
            
    def toggle_style(self, checked):
        style = 'hand_drawn' if checked else 'normal'
        self.style_changed.emit(style)

    def choose_color(self):
        color = QColorDialog.getColor(Qt.red, self, "选择颜色")
        if color.isValid():
            self.btn_color.setStyleSheet(f"background-color: {color.name()}; border: 2px solid #ccc; border-radius: 12px;")
            self.color_changed.emit(color)

    def on_width_changed(self, value):
        self.width_label.setText(str(value))
        self.width_changed.emit(value)

    def on_font_size_clicked(self, size, btn):
        for b in self.font_btns:
            if b != btn: b.setChecked(False)
        btn.setChecked(True)
        self.font_size_changed.emit(size)

    def select_tool(self, key):
        # Uncheck others
        for k, btn in self.tools.items():
            if k != key:
                btn.setChecked(False)
        
        if not self.tools[key].isChecked():
            # Was checked, now unchecked
             self.tool_selected.emit(None)
             self.settings_stack.setCurrentWidget(self.width_widget)
        else:
            self.tool_selected.emit(key)
            if key == 'text':
                self.settings_stack.setCurrentWidget(self.font_widget)
            else:
                self.settings_stack.setCurrentWidget(self.width_widget)

class ScreenshotEditor(QWidget):
    def __init__(self, pixmap=None, global_rect=None, mode='screenshot'):
        super().__init__()
        
        self.mode = mode
        
        if self.mode == 'screenshot':
            # Remove Qt.Tool to allow showing in taskbar for minimization
            # Remove Qt.WindowStaysOnTopHint so it doesn't block other windows
            self.setWindowFlags(Qt.FramelessWindowHint)
            self.setAttribute(Qt.WA_DeleteOnClose)
            if global_rect:
                self.setGeometry(global_rect)
        else:
            # Standalone mode
            self.setWindowTitle("LuScreen 智能画板")
            self.resize(1200, 800)
            self.setAttribute(Qt.WA_DeleteOnClose)
            self.zoom_level = 1.0
            self.min_zoom = 0.1
            self.max_zoom = 5.0
        
        # Set Application Icon
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        if pixmap is None:
            # Create a default white canvas
            pixmap = QPixmap(1920, 1080)
            pixmap.fill(Qt.white)
            
        self.original_pixmap = pixmap
        # Mosaic preparation
        self.mosaic_pixmap = self.generate_mosaic(pixmap)
        
        self.global_rect = global_rect
        
        # State
        self.current_tool = None
        self.is_drawing = False
        self.start_pos = QPoint()
        self.end_pos = QPoint()
        
        self.items = [] # List of all drawn items
        self.history = [[]] # Undo stack: list of lists of items
        
        self.pen_color = QColor(255, 0, 0)
        self.pen_width = 3
        self.font_size = 16
        
        # Selection / Moving
        self.selected_item_index = -1
        self.last_mouse_pos = QPoint()
        
        # Path for free drawing
        self.current_path = None
        
        self.drawing_style = 'normal' # 'normal' or 'hand_drawn'
        
        # Toolbar
        # Pass self as parent so toolbar minimizes/restores with editor
        self.toolbar = EditToolBar(self)
        self.toolbar.tool_selected.connect(self.set_tool)
        self.toolbar.action_triggered.connect(self.handle_action)
        self.toolbar.color_changed.connect(self.set_color)
        self.toolbar.width_changed.connect(self.set_width)
        self.toolbar.font_size_changed.connect(self.set_font_size)
        self.toolbar.style_changed.connect(self.set_drawing_style)
        
        if self.mode == 'standalone':
            self.toolbar.setWindowFlags(Qt.Widget) # Ensure it behaves as a normal child widget
            self.toolbar.btn_open.show()
            # In standalone mode, use layout
            self.main_layout = QVBoxLayout(self)
            self.main_layout.setContentsMargins(0, 0, 0, 0)
            self.main_layout.setSpacing(0)
            
            # Toolbar container to control height/alignment
            tb_container = QWidget()
            tb_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed) # Prevent vertical stretching
            tb_layout = QHBoxLayout(tb_container)
            tb_layout.setContentsMargins(5, 5, 5, 5) # Minimal vertical margins
            tb_layout.addStretch() # Center toolbar
            tb_layout.addWidget(self.toolbar)
            tb_layout.addStretch() # Center toolbar
            
            self.main_layout.addWidget(tb_container)
            
            # Canvas area (spacer for now, painting happens on self)
            # Actually, if we use layout, the toolbar widget takes space at top.
            # We need to adjust paintEvent to respect the toolbar area if it's not transparent overlay.
            # But EditToolBar has translucent background.
            # To simplify, we'll let the toolbar be part of layout, and the rest is drawn below.
            # We need a dedicated CanvasWidget to draw on, otherwise self.paintEvent draws behind toolbar.
            
            self.canvas_widget = QWidget()
            # Remove stylesheet to avoid conflict with custom paintEvent in eventFilter
            # self.canvas_widget.setStyleSheet("background-color: #333;") 
            self.canvas_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.canvas_widget.setFocusPolicy(Qt.StrongFocus) # Allow canvas to receive key events
            self.main_layout.addWidget(self.canvas_widget)
            
            # Re-route events from canvas_widget to self logic, OR better:
            # Install event filter on canvas_widget to capture mouse events
            self.canvas_widget.installEventFilter(self)
            
        else:
            self.toolbar.show()
            self.update_toolbar_pos()
        
        self.setCursor(Qt.CrossCursor)

        # Load custom fonts
        self.hand_drawn_font_family = None
        self.load_custom_fonts()

    def load_custom_fonts(self):
        # Only load 851hand font
        font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'qingsong8.ttf')
        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    self.hand_drawn_font_family = families[0]

    def generate_mosaic(self, pixmap):
        # Scale down and up to create pixelation
        img = pixmap.toImage()
        w, h = img.width(), img.height()
        block_size = 10
        if w < block_size or h < block_size: return pixmap
        
        small = img.scaled(w // block_size, h // block_size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        large = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        return QPixmap.fromImage(large)

    def set_tool(self, tool):
        # Force commit if we are switching away from text or just changing tools
        if hasattr(self, 'active_text_editor') and self.active_text_editor:
            self.commit_text_editor()

        self.current_tool = tool
        if tool == 'text':
            self.setCursor(Qt.IBeamCursor)
        elif tool == 'move':
            self.setCursor(Qt.OpenHandCursor)
        elif tool is None:
            self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.CrossCursor)

    def handle_action(self, action):
        if action == 'open':
            self.open_image()
        elif action == 'clear':
            self.clear_canvas()
        elif action == 'zoom_in':
            self.zoom_in()
        elif action == 'zoom_out':
            self.zoom_out()
        elif action == 'save':
            self.save_image()
        elif action == 'copy':
            self.copy_image()
        elif action == 'minimize':
            self.showMinimized()
        elif action == 'close':
            self.close()
        elif action == 'undo':
            self.undo()

    def clear_canvas(self):
        # Clear all items and reset background to white
        self.items = []
        self.history = [[]]
        
        # Reset background to white if in standalone mode or just want to clear
        # But user said "restore all white floor", implying a white canvas.
        # If it was a screenshot, maybe they want to clear annotations?
        # "restore all white floor" usually means clear everything and set bg to white.
        
        # Create a default white canvas
        self.original_pixmap = QPixmap(1920, 1080)
        self.original_pixmap.fill(Qt.white)
        self.mosaic_pixmap = self.generate_mosaic(self.original_pixmap)
        
        self.refresh_canvas()

    def set_color(self, color):
        self.pen_color = color

    def set_drawing_style(self, style):
        self.drawing_style = style

    def set_width(self, width):
        self.pen_width = width

    def set_font_size(self, size):
        self.font_size = size
        if hasattr(self, 'active_text_editor') and self.active_text_editor:
             font = self.active_text_editor.font()
             font.setPointSize(size)
             self.active_text_editor.setFont(font)
             self.on_text_changed(self.active_text_editor.text())

    def update_toolbar_pos(self):
        if self.mode == 'standalone': return
        
        # Position toolbar below the editor
        # If not enough space, put it inside at bottom
        screen = QGuiApplication.primaryScreen().geometry()
        tb_w = self.toolbar.sizeHint().width()
        tb_h = self.toolbar.sizeHint().height()
        
        x = self.x() + self.width() - tb_w
        if x < self.x(): x = self.x() # Align left if too narrow
        
        y = self.y() + self.height() + 5
        if y + tb_h > screen.bottom():
            # Put inside
            y = self.y() + self.height() - tb_h - 10
        
        self.toolbar.move(x, y)

    def moveEvent(self, event):
        if self.mode == 'screenshot':
            self.update_toolbar_pos()
        super().moveEvent(event)
        
    def closeEvent(self, event):
        # Auto-save before closing to prevent data loss
        self.auto_save()
        self.toolbar.close()
        super().closeEvent(event)

    def auto_save(self):
        try:
            from src.config import ConfigManager
            config = ConfigManager()
            save_path = config.get("save_path_capture", os.getcwd())
            if not os.path.exists(save_path):
                os.makedirs(save_path)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Use a distinct prefix or suffix if needed, but timestamp is usually enough
            # Maybe add "_autosave" to distinguish? Or just save normally.
            # User request implies "found later", so normal save structure is good.
            file_path = os.path.join(save_path, f"Screenshot_{timestamp}_autosave.png")
            
            self.get_final_image().save(file_path)
        except Exception as e:
            print(f"Auto-save failed: {e}")

    def refresh_canvas(self):
        if getattr(self, 'mode', None) == 'standalone' and hasattr(self, 'canvas_widget'):
            self.canvas_widget.update()
        else:
            self.update()

    def _draw_hand_drawn_line(self, painter, p1, p2, seed=None):
        # Excalidraw style: Double stroke with Bezier curves and slight overshoot/roughness
        rng = random.Random(seed) if seed is not None else random
        
        x1, y1 = p1.x(), p1.y()
        x2, y2 = p2.x(), p2.y()
        
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 2:
            painter.drawLine(p1, p2)
            return

        roughness = 2.0
        
        def draw_stroke():
            path = QPainterPath()
            
            # Start jitter
            r1 = rng.uniform(-roughness, roughness)
            r2 = rng.uniform(-roughness, roughness)
            path.moveTo(x1 + r1, y1 + r2)
            
            # Curve control point
            mid_x = (x1 + x2) / 2
            mid_y = (y1 + y2) / 2
            
            # Random offset for curve (bowing)
            # Use a smaller factor for straighter look but still hand-drawn
            bow_factor = max(length * 0.01, 0.5)
            off_x = rng.uniform(-bow_factor, bow_factor)
            off_y = rng.uniform(-bow_factor, bow_factor)
            
            # End jitter
            r3 = rng.uniform(-roughness, roughness)
            r4 = rng.uniform(-roughness, roughness)
            
            path.quadTo(mid_x + off_x, mid_y + off_y, x2 + r3, y2 + r4)
            painter.drawPath(path)

        # Draw two strokes for the sketchy look
        draw_stroke()
        draw_stroke()

    def _draw_hand_drawn_rect(self, painter, rect, seed=None):
        rng = random.Random(seed) if seed is not None else random
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        radius = 15
        
        # Handle small rectangles
        if w < 2 * radius: radius = w / 2
        if h < 2 * radius: radius = h / 2
        
        # Define segments
        # Top Edge
        t_start = QPointF(x + radius, y)
        t_end = QPointF(x + w - radius, y)
        
        # Right Edge
        r_start = QPointF(x + w, y + radius)
        r_end = QPointF(x + w, y + h - radius)
        
        # Bottom Edge
        b_start = QPointF(x + w - radius, y + h)
        b_end = QPointF(x + radius, y + h)
        
        # Left Edge
        l_start = QPointF(x, y + h - radius)
        l_end = QPointF(x, y + radius)

        # Draw straight edges
        self._draw_hand_drawn_line(painter, t_start, t_end, rng.randint(0, 99999))
        self._draw_hand_drawn_line(painter, r_start, r_end, rng.randint(0, 99999))
        self._draw_hand_drawn_line(painter, b_start, b_end, rng.randint(0, 99999))
        self._draw_hand_drawn_line(painter, l_start, l_end, rng.randint(0, 99999))
        
        # Helper for corners
        def draw_corner(p1, corner, p2, seed_val):
             rng_c = random.Random(seed_val)
             roughness = 1.0
             for _ in range(2):
                 path = QPainterPath()
                 # Jitter start
                 r1 = rng_c.uniform(-roughness, roughness)
                 r2 = rng_c.uniform(-roughness, roughness)
                 path.moveTo(p1.x() + r1, p1.y() + r2)
                 
                 # Jitter end
                 r3 = rng_c.uniform(-roughness, roughness)
                 r4 = rng_c.uniform(-roughness, roughness)
                 
                 # Jitter control point
                 rc1 = rng_c.uniform(-roughness, roughness)
                 rc2 = rng_c.uniform(-roughness, roughness)
                 
                 path.quadTo(corner.x() + rc1, corner.y() + rc2, p2.x() + r3, p2.y() + r4)
                 painter.drawPath(path)

        # Draw corners
        # Top-Left: l_end -> t_start via (x, y)
        draw_corner(l_end, QPointF(x, y), t_start, rng.randint(0, 99999))
        
        # Top-Right: t_end -> r_start via (x+w, y)
        draw_corner(t_end, QPointF(x + w, y), r_start, rng.randint(0, 99999))
        
        # Bottom-Right: r_end -> b_start via (x+w, y+h)
        draw_corner(r_end, QPointF(x + w, y + h), b_start, rng.randint(0, 99999))
        
        # Bottom-Left: b_end -> l_start via (x, y+h)
        draw_corner(b_end, QPointF(x, y + h), l_start, rng.randint(0, 99999))

    def _draw_hand_drawn_ellipse(self, painter, rect, seed=None):
        rng = random.Random(seed) if seed is not None else random
        
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        rx, ry = w / 2, h / 2
        cx, cy = x + rx, y + ry
        
        roughness = 1.5 # Slightly rougher
        k = 0.55228 
        
        def np(px, py):
            return QPointF(px + rng.uniform(-roughness, roughness), 
                           py + rng.uniform(-roughness, roughness))
        
        # Draw 2 rough ellipses
        for _ in range(2):
            path = QPainterPath()
            
            # 4 Anchor points with jitter
            p0 = np(cx + rx, cy) 
            p1 = np(cx, cy + ry) 
            p2 = np(cx - rx, cy) 
            p3 = np(cx, cy - ry) 
            
            path.moveTo(p0)
            
            # Control points also jittered
            # Curve 1: East to South
            cp1 = np(cx + rx, cy + k * ry)
            cp2 = np(cx + k * rx, cy + ry)
            path.cubicTo(cp1, cp2, p1)
            
            # Curve 2: South to West
            cp3 = np(cx - k * rx, cy + ry)
            cp4 = np(cx - rx, cy + k * ry)
            path.cubicTo(cp3, cp4, p2)
            
            # Curve 3: West to North
            cp5 = np(cx - rx, cy - k * ry)
            cp6 = np(cx - k * rx, cy - ry)
            path.cubicTo(cp5, cp6, p3)
            
            # Curve 4: North to East
            cp7 = np(cx + k * rx, cy - ry)
            cp8 = np(cx + rx, cy - k * ry)
            path.cubicTo(cp7, cp8, p0)
            
            painter.drawPath(path)

    def _draw_single_item(self, painter, item):
        if item['type'] == 'mosaic':
            painter.save()
            stroker = QPainterPathStroker()
            stroker.setWidth(item['width'])
            stroker.setCapStyle(Qt.RoundCap)
            stroker.setJoinStyle(Qt.RoundJoin)
            stroke_path = stroker.createStroke(item['path'])
            painter.setClipPath(stroke_path)
            painter.drawPixmap(0, 0, self.mosaic_pixmap)
            painter.restore()
            return

        painter.setPen(QPen(item['color'], item.get('width', 3)))
        
        is_hand_drawn = item.get('style') == 'hand_drawn'
        seed = item.get('seed')
        
        if item['type'] == 'rect':
            rect = QRect(item['start'], item['end']).normalized()
            if is_hand_drawn:
                self._draw_hand_drawn_rect(painter, rect, seed)
            else:
                painter.drawRoundedRect(rect, 15, 15)
        elif item['type'] == 'circle':
            rect = QRect(item['start'], item['end']).normalized()
            if is_hand_drawn:
                self._draw_hand_drawn_ellipse(painter, rect, seed)
            else:
                painter.drawEllipse(rect)
        elif item['type'] == 'line':
            if is_hand_drawn:
                self._draw_hand_drawn_line(painter, item['start'], item['end'], seed)
            else:
                painter.drawLine(item['start'], item['end'])
        elif item['type'] == 'arrow':
            if is_hand_drawn:
                self.draw_arrow(painter, item['start'], item['end'], hand_drawn=True, seed=seed)
            else:
                self.draw_arrow(painter, item['start'], item['end'])
        elif item['type'] == 'pen':
            painter.drawPath(item['path']) # Pen is already hand drawn
        elif item['type'] == 'text':
            if 'font' in item and 'text' in item:
                painter.setFont(item['font'])
                painter.drawText(item['pos'], item['text'])

    def paintEvent(self, event):
        if self.mode == 'standalone':
            # We don't paint on self in standalone mode, we paint on canvas_widget via eventFilter
            return
            
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.original_pixmap)
        
        # Draw all committed items
        for item in self.items:
            self._draw_single_item(painter, item)
            
        # Draw in-progress shape
        if self.is_drawing and self.current_tool and self.current_tool != 'move':
            temp_item = {
                'type': self.current_tool,
                'color': self.pen_color,
                'width': self.pen_width,
                'style': self.drawing_style,
                'seed': 42 # Constant seed for preview to prevent vibration
            }
            if self.current_tool in ['rect', 'circle', 'line', 'arrow']:
                temp_item['start'] = self.start_pos
                temp_item['end'] = self.end_pos
            elif self.current_tool in ['pen', 'mosaic']:
                temp_item['path'] = self.current_path
            
            self._draw_single_item(painter, temp_item)

        # Draw border
        pen = QPen(QColor(0, 175, 255), 2)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))

    def draw_arrow(self, painter, start, end, hand_drawn=False, seed=None):
        rng = random.Random(seed) if seed is not None else random
        
        if hand_drawn:
            self._draw_hand_drawn_line(painter, start, end, rng.randint(0, 99999))
        else:
            painter.drawLine(start, end)
        
        # Arrow head
        angle = math.atan2(start.y() - end.y(), start.x() - end.x())
        arrow_len = 15
        arrow_angle = math.pi / 6
        
        p1 = end + QPoint(int(arrow_len * math.cos(angle + arrow_angle)), 
                          int(arrow_len * math.sin(angle + arrow_angle)))
        p2 = end + QPoint(int(arrow_len * math.cos(angle - arrow_angle)), 
                          int(arrow_len * math.sin(angle - arrow_angle)))
        
        if hand_drawn:
            self._draw_hand_drawn_line(painter, end, p1, rng.randint(0, 99999))
            self._draw_hand_drawn_line(painter, end, p2, rng.randint(0, 99999))
        else:
            painter.drawLine(end, p1)
            painter.drawLine(end, p2)

    def hit_test(self, pos):
        for i in range(len(self.items) - 1, -1, -1):
            item = self.items[i]
            t = item['type']
            if t in ['rect', 'circle']:
                r = QRect(item['start'], item['end']).normalized()
                if r.contains(pos): return i
            elif t == 'text':
                if 'font' not in item or 'text' not in item: continue
                fm = QFontMetrics(item['font'])
                r = fm.boundingRect(item['text'])
                r.translate(item['pos'])
                r.adjust(-5, -5, 5, 5)
                if r.contains(pos): return i
            elif t in ['line', 'arrow']:
                # Simple bounding box for now
                p1 = item['start']
                p2 = item['end']
                r = QRect(p1, p2).normalized().adjusted(-5,-5,5,5)
                if r.contains(pos): return i
            elif t in ['pen', 'mosaic']:
                path = item['path']
                stroker = QPainterPathStroker()
                stroker.setWidth(max(10, item.get('width', 10)))
                boundary = stroker.createStroke(path)
                if boundary.contains(pos): return i
        return -1

    def move_item(self, index, delta):
        item = self.items[index]
        t = item['type']
        if t in ['rect', 'circle', 'line', 'arrow']:
            item['start'] += delta
            item['end'] += delta
        elif t == 'text':
            item['pos'] += delta
        elif t in ['pen', 'mosaic']:
            item['path'].translate(delta.x(), delta.y())

    def zoom_in(self):
        if self.mode == 'standalone':
            self.zoom_level = min(self.zoom_level * 1.1, self.max_zoom)
            self.refresh_canvas()

    def zoom_out(self):
        if self.mode == 'standalone':
            self.zoom_level = max(self.zoom_level / 1.1, self.min_zoom)
            self.refresh_canvas()

    def wheelEvent(self, event):
        if self.mode == 'standalone':
            if event.modifiers() & Qt.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.zoom_level = min(self.zoom_level * 1.1, self.max_zoom)
                else:
                    self.zoom_level = max(self.zoom_level / 1.1, self.min_zoom)
                self.refresh_canvas()
                return

    def map_pos(self, pos):
        # 如果是独立编辑模式，需要减去画布的偏移量，将鼠标坐标转换为相对于图片的坐标
        if getattr(self, 'mode', None) == 'standalone' and hasattr(self, 'canvas_offset'):
            # Inverse zoom and translate
            return (pos - self.canvas_offset) / self.zoom_level
        return pos

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
             local_pos = self.map_pos(event.pos())
             idx = self.hit_test(local_pos)
             if idx != -1:
                 item = self.items[idx]
                 if item['type'] == 'text':
                     # Edit text
                     self.items.pop(idx) # Remove old item
                     self.selected_item_index = -1
                     
                     self.add_text(item['pos'], initial_text=item['text'])
                     self.refresh_canvas()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_mouse_pos = event.globalPos()
            # 获取相对于图片的局部坐标
            local_pos = self.map_pos(event.pos())
            
            if self.current_tool == 'move':
                # 检查是否点击了已有的图形元素
                idx = self.hit_test(local_pos)
                if idx != -1:
                    self.selected_item_index = idx
                    self.setCursor(Qt.SizeAllCursor)
                else:
                    self.selected_item_index = -1
                    # 如果没点中元素，且不是独立模式，则拖动窗口
                    self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            
            elif self.current_tool:
                # 开始绘制新图形
                self.is_drawing = True
                self.start_pos = local_pos
                self.end_pos = local_pos
                if self.current_tool in ['pen', 'mosaic']:
                    self.current_path = QPainterPath(self.start_pos)
                elif self.current_tool == 'text':
                    self.add_text(local_pos)
                    self.is_drawing = False
            
            else:
                # 没有选择工具时的默认行为
                idx = self.hit_test(local_pos)
                if idx != -1:
                    self.selected_item_index = idx
                    self.current_tool = 'move' # 临时切换到移动工具
                    self.setCursor(Qt.SizeAllCursor)
                else:
                    # 拖动窗口
                    self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.selected_item_index != -1 and (self.current_tool == 'move' or not self.current_tool):
            # 移动选中的图形元素
            delta = event.globalPos() - self.last_mouse_pos
            self.move_item(self.selected_item_index, delta)
            self.last_mouse_pos = event.globalPos()
            self.refresh_canvas()
            return
            
        local_pos = self.map_pos(event.pos())
        
        if self.current_tool == 'move':
            # 悬停效果：如果鼠标在元素上，显示移动光标
            idx = self.hit_test(local_pos)
            if idx != -1:
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.OpenHandCursor)
                
            if event.buttons() & Qt.LeftButton and self.selected_item_index == -1:
                # 拖动窗口（非独立模式下）
                if hasattr(self, 'drag_pos'):
                    self.move(event.globalPos() - self.drag_pos)

        elif self.is_drawing:
            # 更新正在绘制的图形
            self.end_pos = local_pos
            if self.current_tool in ['pen', 'mosaic']:
                self.current_path.lineTo(self.end_pos)
            
            self.refresh_canvas()
            
        elif not self.current_tool and event.buttons() & Qt.LeftButton:
            # 拖动窗口
            if hasattr(self, 'drag_pos'):
                 self.move(event.globalPos() - self.drag_pos)
        
        self.last_mouse_pos = event.globalPos()

    def mouseReleaseEvent(self, event):
        if self.selected_item_index != -1:
            # Keep selected item index for further actions (like delete)
            # Only reset if we clicked outside (handled in mousePress)
            self.save_state()
            if self.current_tool == 'move' and not self.toolbar.tools['move'].isChecked():
                # 恢复之前的工具状态
                self.current_tool = None
            return

        if self.is_drawing and event.button() == Qt.LeftButton:
            # 完成绘制操作
            self.is_drawing = False
            self.end_pos = self.map_pos(event.pos())
            self.commit_drawing()
            self.refresh_canvas()

    def commit_drawing(self):
        if not self.current_tool: return
        # Text is handled by commit_text_editor, not here.
        if self.current_tool == 'text': return
        
        item = {
            'type': self.current_tool,
            'color': self.pen_color,
            'width': self.pen_width,
            'style': self.drawing_style,
            'seed': random.randint(0, 100000) # Persist random look
        }
        
        if self.current_tool in ['rect', 'circle', 'line', 'arrow']:
            item['start'] = self.start_pos
            item['end'] = self.end_pos
        elif self.current_tool in ['pen', 'mosaic']:
            item['path'] = self.current_path
        
        self.items.append(item)
        self.save_state()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if hasattr(self, 'active_text_editor') and self.active_text_editor:
                self.cancel_text_editor()
            else:
                self.close()
        elif event.key() in [Qt.Key_Delete, Qt.Key_Backspace, 16777219, 16777223]:
            if self.selected_item_index != -1:
                # Remove selected item
                self.items.pop(self.selected_item_index)
                self.selected_item_index = -1
                self.save_state()
                self.refresh_canvas()
        elif event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_Z:
                self.undo()
            elif event.key() == Qt.Key_S:
                self.save_image()
            elif event.key() == Qt.Key_C:
                self.copy_image()
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if self.mode == 'standalone' and hasattr(self, 'canvas_widget') and obj == self.canvas_widget:
            if event.type() == QEvent.Paint:
                self.paint_canvas(obj)
                return True
            elif event.type() == QEvent.Wheel:
                self.wheelEvent(event)
                return True
            elif event.type() == QEvent.MouseButtonDblClick:
                self.mouseDoubleClickEvent(event)
                return True
            elif event.type() in [QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseMove]:
                # Focus canvas on click to receive key events
                if event.type() == QEvent.MouseButtonPress:
                    self.canvas_widget.setFocus()
                    self.mousePressEvent(event)
                elif event.type() == QEvent.MouseButtonRelease:
                    self.mouseReleaseEvent(event)
                elif event.type() == QEvent.MouseMove:
                    self.mouseMoveEvent(event)
                return True
            elif event.type() == QEvent.KeyPress:
                # Manually call keyPressEvent with the event
                # Simply returning True might block default processing but we want to execute logic
                # However, keyPressEvent is on `self`, not `obj`.
                # If we just call self.keyPressEvent(event), we are good.
                self.keyPressEvent(event)
                return True
                
        if hasattr(self, 'active_text_editor') and obj == self.active_text_editor:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.cancel_text_editor()
                return True
        return super().eventFilter(obj, event)

    def paint_canvas(self, canvas):
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.TextAntialiasing)
        
        # Fill background with a neutral color (e.g. gray) to distinguish image area
        painter.fillRect(canvas.rect(), QColor(240, 240, 240))
        
        # Center the image
        img_w, img_h = self.original_pixmap.width(), self.original_pixmap.height()
        
        # Apply zoom
        scaled_w = int(img_w * self.zoom_level)
        scaled_h = int(img_h * self.zoom_level)
        
        cw, ch = canvas.width(), canvas.height()
        
        x = (cw - scaled_w) // 2
        y = (ch - scaled_h) // 2
        
        # Store offset for mouse mapping
        self.canvas_offset = QPoint(x, y)
        
        painter.translate(x, y)
        painter.scale(self.zoom_level, self.zoom_level)
        
        # Clip drawing to image area
        painter.setClipRect(0, 0, img_w, img_h)
        
        # Draw the image
        painter.drawPixmap(0, 0, self.original_pixmap)
        
        # Helper to draw an item (Same as before but strictly using painter provided)
        for item in self.items:
            self._draw_single_item(painter, item)
            
        if self.is_drawing and self.current_tool and self.current_tool != 'move':
            temp_item = {
                'type': self.current_tool,
                'color': self.pen_color,
                'width': self.pen_width,
                'style': self.drawing_style,
                'seed': 42 # Constant seed for preview
            }
            if self.current_tool in ['rect', 'circle', 'line', 'arrow']:
                temp_item['start'] = self.start_pos
                temp_item['end'] = self.end_pos
            elif self.current_tool in ['pen', 'mosaic']:
                temp_item['path'] = self.current_path
            
            self._draw_single_item(painter, temp_item)
        
        # Draw subtle border around image
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(0, 0, img_w, img_h)

    def open_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开图片", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                self.original_pixmap = pixmap
                self.mosaic_pixmap = self.generate_mosaic(pixmap)
                self.items = []
                self.history = [[]]
                self.refresh_canvas()

    def get_hand_drawn_font(self):
        if self.hand_drawn_font_family:
            return QFont(self.hand_drawn_font_family, self.font_size)
        
        # Fallback to system handwritten fonts
        # Try Segoe Print (Windows), then Comic Sans MS
        db = QFontDatabase()
        families = db.families()
        if "Segoe Print" in families:
            return QFont("Segoe Print", self.font_size)
        elif "Comic Sans MS" in families:
            return QFont("Comic Sans MS", self.font_size)
        else:
            return QFont("Arial", self.font_size, QFont.Bold)

    def add_text(self, pos, initial_text=""):
        if hasattr(self, 'active_text_editor') and self.active_text_editor:
            self.commit_text_editor()
            
        parent = self
        visual_pos = pos # Default for screenshot mode
        
        if getattr(self, 'mode', None) == 'standalone':
             if hasattr(self, 'canvas_widget'):
                 parent = self.canvas_widget
             if hasattr(self, 'canvas_offset'):
                 # Convert logical image pos back to visual widget pos
                 visual_pos = (pos * self.zoom_level) + self.canvas_offset
                 
        self.active_text_editor = QLineEdit(parent)
        self.active_text_editor.setText(initial_text)
        if not initial_text:
            self.active_text_editor.setPlaceholderText("输入文字")
            
        self.active_text_editor.move(visual_pos)
        self.active_text_editor.resize(200, 40)
        
        if self.drawing_style == 'hand_drawn':
            font = self.get_hand_drawn_font()
        else:
            font = QFont("Arial", self.font_size, QFont.Bold)
            
        self.active_text_editor.setFont(font)
        
        # Style with dashed border to indicate edit mode
        self.active_text_editor.setStyleSheet(f"""
            QLineEdit {{
                background-color: transparent;
                border: 1px dashed #007aff;
                color: {self.pen_color.name()};
            }}
        """)
        
        self.active_text_editor.setFocus()
        self.active_text_editor.show()
        
        if initial_text:
             self.on_text_changed(initial_text)
             
        if self.active_text_editor:
            self.active_text_editor.editingFinished.connect(self.commit_text_editor)
            self.active_text_editor.textChanged.connect(self.on_text_changed)
            self.active_text_editor.installEventFilter(self)
        
        self.active_text_pos = pos

    def on_text_changed(self, text):
        if hasattr(self, 'active_text_editor') and self.active_text_editor:
            fm = self.active_text_editor.fontMetrics()
            w = fm.horizontalAdvance(text) + 50
            w = max(w, 200)
            self.active_text_editor.resize(w, self.active_text_editor.height())

    def commit_text_editor(self):
        if not hasattr(self, 'active_text_editor') or not self.active_text_editor:
            return
            
        editor = self.active_text_editor
        # Disconnect signal to prevent re-entry if focus changes during deletion
        try:
            editor.editingFinished.disconnect(self.commit_text_editor)
        except Exception:
            pass
            
        text = editor.text()
        if text:
            font = editor.font()
            fm = QFontMetrics(font)
            # Adjust y to roughly match baseline visual
            baseline_y = self.active_text_pos.y() + fm.ascent() + 5
            
            item = {'type': 'text', 'text': text, 'pos': QPoint(self.active_text_pos.x() + 5, baseline_y), 'color': self.pen_color, 'font': font}
            self.items.append(item)
            self.save_state()
            self.refresh_canvas()
            
        editor.deleteLater()
        self.active_text_editor = None

    def cancel_text_editor(self):
        if hasattr(self, 'active_text_editor') and self.active_text_editor:
            editor = self.active_text_editor
            try:
                editor.editingFinished.disconnect(self.commit_text_editor)
            except Exception:
                pass
            editor.deleteLater()
            self.active_text_editor = None

    def save_state(self):
        import copy
        new_items = []
        for item in self.items:
            new_item = item.copy()
            if 'path' in item:
                new_item['path'] = QPainterPath(item['path'])
            new_items.append(new_item)
            
        self.history.append(new_items)
        if len(self.history) > 20: # Limit history
            self.history.pop(0)

    def undo(self):
        if len(self.history) > 1:
            self.history.pop()
            state_items = self.history[-1]
            
            # Restore items
            self.items = []
            for item in state_items:
                new_item = item.copy()
                if 'path' in item:
                    new_item['path'] = QPainterPath(item['path'])
                self.items.append(new_item)
            self.refresh_canvas()

    def clear_canvas(self):
        # Clear all items but keep the original background
        self.items = []
        self.history = [[]]
        self.refresh_canvas()

    def clear_canvas(self):
        # Clear all items but keep the original background
        self.items = []
        self.history = [[]]
        self.refresh_canvas()

    def get_final_image(self):
        final = self.original_pixmap.copy()
        painter = QPainter(final)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.TextAntialiasing)
        
        for item in self.items:
            self._draw_single_item(painter, item)
                
        painter.end()
        return final

    def save_image(self):
        from src.config import ConfigManager
        config = ConfigManager()
        save_path = config.get("save_path_capture", os.getcwd())
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = os.path.join(save_path, f"Screenshot_{timestamp}.png")
        
        file_path, _ = QFileDialog.getSaveFileName(self, "保存截图", default_name, "Images (*.png *.jpg *.bmp)")
        if file_path:
            self.get_final_image().save(file_path)
            # self.close() # Keep window open after save

    def copy_image(self):
        clipboard = QApplication.clipboard()
        clipboard.setPixmap(self.get_final_image())
        # self.close()