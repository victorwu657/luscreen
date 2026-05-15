import os
from datetime import datetime
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QFileDialog, QApplication, QInputDialog, QLineEdit,
                               QGraphicsDropShadowEffect, QLabel, QColorDialog, QFontDialog, QSlider, QStackedLayout, QSizePolicy, QComboBox, QPlainTextEdit, QButtonGroup,
                               QDialog, QListWidget, QListWidgetItem, QScrollArea, QFrame, QTabBar)
from PySide6.QtCore import Qt, QPoint, QRect, QSize, Signal, QTimer, QEvent, QPointF, QRectF, QLineF
from PySide6.QtGui import (QPainter, QPen, QColor, QBrush, QPixmap, QImage, 
                           QIcon, QPainterPath, QAction, QFont, QCursor, QGuiApplication, QFontMetrics,
                           QPainterPathStroker, QFontDatabase)
import pyperclip
import random
import math
import logging
from src.utils import open_folder_and_select_file

logger = logging.getLogger('ScreenshotEditor')

class FrameSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择画框背景")
        self.resize(600, 500)
        self.selected_bg = None
        self.margin_value = 30
        self.radius_value = 20
        
        layout = QVBoxLayout(self)
        
        # Help text
        layout.addWidget(QLabel("选择一个背景图片应用到画框:"))
        
        # List Widget for thumbnails
        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setIconSize(QSize(100, 100))
        self.list_widget.setGridSize(QSize(115, 115)) # Ensure 5 items fit in 600px width
        self.list_widget.setMovement(QListWidget.Static)
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setSpacing(5)
        # Single click to select, double click to accept
        self.list_widget.itemClicked.connect(self.on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        layout.addWidget(self.list_widget)
        
        # Settings Area
        settings_layout = QVBoxLayout()
        
        # Margin Slider
        margin_container = QHBoxLayout()
        margin_container.addWidget(QLabel("边距:"))
        self.margin_slider = QSlider(Qt.Horizontal)
        self.margin_slider.setRange(0, 100)
        self.margin_slider.setValue(30)
        self.margin_label = QLabel("30px")
        self.margin_slider.valueChanged.connect(lambda v: self.margin_label.setText(f"{v}px"))
        margin_container.addWidget(self.margin_slider)
        margin_container.addWidget(self.margin_label)
        settings_layout.addLayout(margin_container)
        
        # Radius Slider
        radius_container = QHBoxLayout()
        radius_container.addWidget(QLabel("圆角:"))
        self.radius_slider = QSlider(Qt.Horizontal)
        self.radius_slider.setRange(0, 100)
        self.radius_slider.setValue(20)
        self.radius_label = QLabel("20px") # Using px for radius usually, or is it degree? User said "10度" but radius is length. Assuming px.
        self.radius_slider.valueChanged.connect(lambda v: self.radius_label.setText(f"{v}px"))
        radius_container.addWidget(self.radius_slider)
        radius_container.addWidget(self.radius_label)
        settings_layout.addLayout(radius_container)
        
        layout.addLayout(settings_layout)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self.accept_selection)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        # Load backgrounds
        self.load_backgrounds()
        
    def load_backgrounds(self):
        assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'Backgroundpic')
        if not os.path.exists(assets_dir):
            return
            
        files = sorted([f for f in os.listdir(assets_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
        
        for f in files:
            path = os.path.join(assets_dir, f)
            icon = QIcon(path)
            item = QListWidgetItem(icon, "") # No text
            item.setToolTip(f) # Show filename on hover
            item.setData(Qt.UserRole, path)
            self.list_widget.addItem(item)
            
    def on_item_clicked(self, item):
        self.selected_bg = item.data(Qt.UserRole)
        
    def on_item_double_clicked(self, item):
        self.selected_bg = item.data(Qt.UserRole)
        self.accept_selection()
        
    def accept_selection(self):
        if not self.selected_bg:
            # If nothing selected but list has items, select first
            if self.list_widget.count() > 0:
                self.selected_bg = self.list_widget.item(0).data(Qt.UserRole)
            else:
                return
        
        self.margin_value = self.margin_slider.value()
        self.radius_value = self.radius_slider.value()
        self.accept()

class PropertiesPanel(QWidget):
    property_changed = Signal(str, object) # key, value
    action_triggered = Signal(str) # action_name
    size_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_editor = parent # Store reference to parent editor
        # Use Tool flag but keep it on top of parent
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.layout = QVBoxLayout(self)
        # Add margins to accommodate the shadow (blur radius 15 + offset 4 ~ 20px)
        # This prevents "UpdateLayeredWindowIndirect failed" warnings by ensuring the dirty rect fits in the window
        self.layout.setContentsMargins(20, 20, 20, 20)
        
        # Main Container
        self.container = QWidget()
        self.container.setStyleSheet("""
            QWidget#Container {
                background-color: #ffffff;
                border-radius: 8px;
                border: 1px solid #e0e0e0;
            }
            QLabel {
                font-size: 11px;
                color: #666;
                font-weight: bold;
                margin-top: 5px;
            }
            QPushButton {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px;
                min-width: 24px;
                min-height: 24px;
            }
            QPushButton:hover { background-color: #e8e8e8; }
            QPushButton:checked { background-color: #e3f2fd; border-color: #2196f3; }
            
            /* Color Button Style */
            QPushButton[colorBtn="true"] {
                border-radius: 4px;
                border: 1px solid #ccc;
                min-width: 20px;
                min-height: 20px;
            }
            QPushButton[colorBtn="true"]:checked {
                border: 2px solid #007aff;
            }
        """)
        self.container.setObjectName("Container")
        
        # Shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        self.container.setGraphicsEffect(shadow)
        
        # Increase width
        self.container.setFixedWidth(240)
        
        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setSpacing(12)
        
        self.layout.addWidget(self.container)
        
        self.current_mode = None

    def clear_ui(self):
        # Remove all items from layout
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                # Recursively delete layout items
                self._clear_layout(item.layout())
                item.layout().deleteLater()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def update_ui(self, item):
        self.clear_ui()
        if item is None:
            # Check if we are in "frame mode" (clicking on the background/frame)
            if hasattr(self.parent_editor, 'is_frame_mode') and self.parent_editor.is_frame_mode:
                 self.setup_for_frame()
                 # Force layout update and resize
                 self.container.adjustSize()
                 self.adjustSize()
                 self.repaint()
                 # Emit size change to re-center
                 self.size_changed.emit()
                 return
                 
            self.hide()
            return
            
        t = item.get('type')
        
        if t == 'image':
            self.setup_for_image(item)
        elif t in ['rect', 'circle']:
            self.setup_for_shape(item, has_fill=True)
        elif t in ['line', 'arrow']:
            self.setup_for_shape(item, has_fill=False)
        elif t in ['text', 'step_marker']:
            self.setup_for_text(item)
        elif t in ['pen', 'mosaic']:
            self.setup_for_pen(item)
        else:
            # Default minimal (Layers + Actions)
            self.setup_common_only(item)
            
        # Force layout update and resize
        self.container.adjustSize()
        self.adjustSize()
        self.repaint()
        # Emit size change to re-center
        self.size_changed.emit()
        
    def setup_for_frame(self):
        # 1. Title
        header = QHBoxLayout()
        header.addWidget(QLabel("🖼️ 画框设置"))
        self.content_layout.addLayout(header)
        
        # 2. Change Background Button
        btn_bg = QPushButton("更换背景")
        btn_bg.clicked.connect(lambda: self.action_triggered.emit('frame_change_bg'))
        self.content_layout.addWidget(btn_bg)
        
        # 3. Margin Slider
        self.add_section_label("边距")
        margin_layout = QHBoxLayout()
        slider_margin = QSlider(Qt.Horizontal)
        slider_margin.setRange(0, 100)
        current_margin = getattr(self.parent_editor, 'frame_margin', 20)
        slider_margin.setValue(current_margin)
        label_margin = QLabel(f"{current_margin}px")
        slider_margin.valueChanged.connect(lambda v: label_margin.setText(f"{v}px"))
        slider_margin.sliderReleased.connect(lambda: self.property_changed.emit('frame_margin', slider_margin.value()))
        margin_layout.addWidget(slider_margin)
        margin_layout.addWidget(label_margin)
        self.content_layout.addLayout(margin_layout)
        
        # 4. Radius Slider
        self.add_section_label("圆角")
        radius_layout = QHBoxLayout()
        slider_radius = QSlider(Qt.Horizontal)
        slider_radius.setRange(0, 100)
        current_radius = getattr(self.parent_editor, 'frame_radius', 20)
        slider_radius.setValue(current_radius)
        label_radius = QLabel(f"{current_radius}px")
        slider_radius.valueChanged.connect(lambda v: label_radius.setText(f"{v}px"))
        slider_radius.sliderReleased.connect(lambda: self.property_changed.emit('frame_radius', slider_radius.value()))
        radius_layout.addWidget(slider_radius)
        radius_layout.addWidget(label_radius)
        self.content_layout.addLayout(radius_layout)

    def add_section_label(self, text):
        self.content_layout.addWidget(QLabel(text))

    def add_color_picker(self, label, prop_key, current_color, include_transparent=False):
        self.add_section_label(label)
        layout = QHBoxLayout()
        layout.setSpacing(5)
        
        group = QButtonGroup(self)
        group.setExclusive(True)
        
        if include_transparent:
            colors = [
                QColor("#f8c3d1"),
                QColor("#b7e9b8"),
                QColor("#b7d9ff"),
                QColor("#ffe3a3")
            ]
            colors.insert(0, Qt.transparent)
        else:
            colors = [
                QColor("#1f1f1f"),
                QColor("#e53935"),
                QColor("#43a047"),
                QColor("#1e88e5"),
                QColor("#fb8c00")
            ]
            
        for c in colors:
            btn = QPushButton()
            btn.setProperty("colorBtn", True)
            if c == Qt.transparent:
                btn.setStyleSheet("background-color: transparent; border: 1px dashed #aaa;")
                btn.setToolTip("无填充")
            else:
                btn.setStyleSheet(f"background-color: {QColor(c).name()};")
            
            btn.setCheckable(True)
            group.addButton(btn)
            btn.setChecked(current_color == c)
            
            btn.clicked.connect(lambda _, col=c: self.emit_property(prop_key, col))
            layout.addWidget(btn)
            
        # Custom color
        btn_custom = QPushButton("...")
        btn_custom.setProperty("colorBtn", True)
        btn_custom.clicked.connect(lambda: self.pick_color(prop_key, current_color))
        layout.addWidget(btn_custom)
        
        layout.addStretch()
        self.content_layout.addLayout(layout)

    def pick_color(self, key, initial):
        c = QColorDialog.getColor(initial, self, "选择颜色")
        if c.isValid():
            self.emit_property(key, c)

    def pick_font(self, key, initial):
        ok, font = QFontDialog.getFont(initial, self, "选择字体")
        if ok:
            self.emit_property(key, font)

    def pick_font(self, key, initial, label=None):
        import time
        logger.info("=== DEBUG: pick_font triggered ===")
        
        # Check and release mouse grabber
        grabber = QWidget.mouseGrabber()
        logger.info(f"Current mouse grabber: {grabber}")
        if grabber:
            logger.info(f"Releasing mouse grabber from: {grabber}")
            grabber.releaseMouse()
            
        # Check and clear override cursors
        override_count = 0
        while QApplication.overrideCursor() is not None:
            override_count += 1
            QApplication.restoreOverrideCursor()
            
        if override_count > 0:
            logger.info(f"Restored {override_count} override cursors")
            
        logger.info(f"Current widget cursor shape: {self.cursor().shape()}")
        
        # Reset cursor to Arrow
        self.setCursor(Qt.ArrowCursor)
        # Ensure cursor update is processed
        QApplication.processEvents()
        
        logger.info("Opening QFontDialog...")
        start_t = time.time()
        ok, font = QFontDialog.getFont(initial, self, "选择字体")
        end_t = time.time()
        logger.info(f"QFontDialog closed. Duration: {end_t - start_t:.3f}s")
        
        if ok:
            logger.info(f"Font selected: {font.family()}")
            self.emit_property(key, font)
            if label:
                label.setText(font.family())
        else:
            logger.info("Font selection cancelled")
            
        logger.info("=== DEBUG: pick_font finished ===")

    def add_button_group(self, label, prop_key, options, current_val):
        # options: list of (label, value, tooltip)
        self.add_section_label(label)
        layout = QHBoxLayout()
        layout.setSpacing(5)
        
        # Use QButtonGroup for mutual exclusivity
        group = QButtonGroup(self)
        group.setExclusive(True)
        
        for text, val, tip in options:
            btn = QPushButton(text)
            btn.setCheckable(True)
            if tip: btn.setToolTip(tip)
            btn.setMinimumHeight(30)
            
            if current_val == val:
                btn.setChecked(True)
                
            btn.clicked.connect(lambda _, v=val: self.emit_property(prop_key, v))
            
            group.addButton(btn)
            layout.addWidget(btn)
            
        layout.addStretch()
        self.content_layout.addLayout(layout)

    def add_slider(self, label, prop_key, current_val, max_val=100, is_percentage=False):
        self.add_section_label(label)
        layout = QHBoxLayout()
        slider = QSlider(Qt.Horizontal)
        
        # Value Label
        val_label = QLabel()
        val_label.setFixedWidth(30)
        val_label.setAlignment(Qt.AlignCenter)
        val_label.setStyleSheet("color: #666; font-size: 10px;")

        if is_percentage:
            slider.setRange(0, 100)
            val = int(current_val * 100)
            slider.setValue(val)
            val_label.setText(f"{val}%")
            
            slider.valueChanged.connect(lambda v: self.emit_property(prop_key, v / 100.0))
            slider.valueChanged.connect(lambda v: val_label.setText(f"{v}%"))
        else:
            slider.setRange(1, max_val)
            val = int(current_val)
            slider.setValue(val)
            val_label.setText(str(val))
            
            slider.valueChanged.connect(lambda v: self.emit_property(prop_key, v))
            slider.valueChanged.connect(lambda v: val_label.setText(str(v)))
             
        layout.addWidget(slider)
        layout.addWidget(val_label)
        self.content_layout.addLayout(layout)

    def setup_common_actions(self):
        self.add_section_label("图层")
        layers_layout = QHBoxLayout()
        
        btns = [("⭱", "layer_top", "置顶"), ("↑", "layer_up", "上移"), 
                ("↓", "layer_down", "下移"), ("⭳", "layer_bottom", "置底")]
        
        for text, act, tip in btns:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setMinimumHeight(30)
            b.clicked.connect(lambda _, a=act: self.action_triggered.emit(a))
            layers_layout.addWidget(b)
        self.content_layout.addLayout(layers_layout)
        
        self.add_section_label("操作")
        act_layout = QHBoxLayout()
        
        b_copy = QPushButton("❐")
        b_copy.setToolTip("克隆")
        b_copy.setMinimumHeight(30)
        b_copy.clicked.connect(lambda: self.action_triggered.emit('copy'))
        
        b_del = QPushButton("🗑")
        b_del.setToolTip("删除")
        b_del.setMinimumHeight(30)
        b_del.setStyleSheet("QPushButton { color: red; } QPushButton:hover { background-color: #ffebee; }")
        b_del.clicked.connect(lambda: self.action_triggered.emit('delete'))
        
        act_layout.addWidget(b_copy)
        act_layout.addWidget(b_del)
        self.content_layout.addLayout(act_layout)

    def setup_for_image(self, item):
        self.add_button_group("边角", "radius", [("⎕", 0, "直角"), ("▢", 20, "圆角")], item.get('radius', 0))
        self.add_slider("透明度", "opacity", item.get('opacity', 1.0), is_percentage=True)
        self.setup_common_actions()

    def setup_for_shape(self, item, has_fill=True):
        # Stroke Color
        self.add_color_picker("描边", "color", item.get('color', Qt.black))
        
        # Fill Color
        if has_fill:
            self.add_color_picker("填充", "fill_color", item.get('fill_color', Qt.transparent), True)
            # self.add_button_group("填充样式", "fill_style", [("█", "solid", "纯色"), ("▒", "hatch", "网格"), ("☒", "cross", "交叉")], item.get('fill_style', 'solid'))
        
        # Stroke Width
        self.add_slider("描边宽度", "width", item.get('width', 3), max_val=20)
        
        # Stroke Style
        self.add_button_group("边框样式", "stroke_style", [("—", 1, "实线"), ("- -", 2, "虚线"), ("...", 3, "点线")], item.get('stroke_style', 1))
        
        # Sloppiness
        self.add_button_group("线条风格", "style", [("／", "normal", "平滑"), ("~", "hand_drawn", "手绘")], item.get('style', 'normal'))
        
        if item.get('type') == 'rect':
             self.add_button_group("边角", "radius", [("⎕", 0, "直角"), ("▢", 20, "圆角")], item.get('radius', 0))
             
        self.add_slider("透明度", "opacity", item.get('opacity', 1.0), is_percentage=True)
        self.setup_common_actions()

    def setup_for_pen(self, item):
        # Mosaic doesn't need color
        if item.get('type') != 'mosaic':
            self.add_color_picker("颜色", "color", item.get('color', Qt.black))
            
        self.add_slider("粗细", "width", item.get('width', 3), max_val=50) # Mosaic might need thicker stroke
        self.add_slider("透明度", "opacity", item.get('opacity', 1.0), is_percentage=True)
        self.setup_common_actions()

    def setup_for_text(self, item):
        self.add_color_picker("颜色", "color", item.get('color', Qt.black))
        
        if item.get('type') == 'text':
            self.add_section_label("字体")
            font_layout = QHBoxLayout()
            font_layout.setSpacing(5)
            
            # Standard Font Button
            btn_font = QPushButton("A")
            btn_font.setToolTip("选择字体")
            btn_font.setFixedSize(30, 30)
            btn_font.setStyleSheet("""
                QPushButton {
                    background-color: #f5f5f5;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    font-weight: bold;
                    font-family: serif; 
                    font-size: 16px;
                }
                QPushButton:hover { background-color: #e8e8e8; }
            """)
            current_font = item.get('font', QFont())
            if not isinstance(current_font, QFont):
                current_font = QFont()
            
            lbl_font_name = QLabel(current_font.family())
            lbl_font_name.setStyleSheet("color: #666; font-size: 10px; margin-left: 5px;")
            
            # Use item.get in lambda to ensure we pass the latest font as initial value next time
            btn_font.clicked.connect(lambda: self.pick_font('font', item.get('font', QFont()), lbl_font_name))
            
            font_layout.addWidget(btn_font)
            
            # Hand-drawn Font Button
            btn_hand = QPushButton("手")
            btn_hand.setToolTip("手绘字体")
            btn_hand.setFixedSize(30, 30)
            btn_hand.setStyleSheet("""
                QPushButton {
                    background-color: #f5f5f5;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 14px;
                }
                QPushButton:hover { background-color: #e8e8e8; }
            """)
            
            def apply_hand_font():
                parent = self.parent()
                if hasattr(parent, 'hand_drawn_font_family') and parent.hand_drawn_font_family:
                    # Create new font based on current but with new family
                    old_font = item.get('font', QFont())
                    if not isinstance(old_font, QFont): old_font = QFont()
                    
                    new_font = QFont(parent.hand_drawn_font_family)
                    size = old_font.pointSize()
                    new_font.setPointSize(size if size > 0 else 9)
                    new_font.setBold(old_font.bold())
                    new_font.setItalic(old_font.italic())
                    
                    self.emit_property('font', new_font)
                    lbl_font_name.setText(new_font.family())
            
            btn_hand.clicked.connect(apply_hand_font)
            font_layout.addWidget(btn_hand)
            
            font_layout.addWidget(lbl_font_name)
            font_layout.addStretch()
            self.content_layout.addLayout(font_layout)
        
        # Font size / Marker size
        size_key = 'font_size'
        current_size = item.get(size_key, 24)
        if 'font' in item:
            current_size = item['font'].pointSize()
        
        label = "字体大小" if item.get('type') == 'text' else "标记大小"
        self.add_slider(label, size_key, current_size, max_val=100)
        
        self.add_slider("透明度", "opacity", item.get('opacity', 1.0), is_percentage=True)
        self.setup_common_actions()

    def setup_common_only(self, item):
        self.add_slider("透明度", "opacity", item.get('opacity', 1.0), is_percentage=True)
        self.setup_common_actions()

    def emit_property(self, key, value):
        self.property_changed.emit(key, value)
        # Refresh UI to reflect changes (like exclusive check)
        # But for simplicity, we rely on user clicking. 
        # For programmatic updates, we might need full refresh.

    def resizeEvent(self, event):
        self.size_changed.emit()
        super().resizeEvent(event)


class EditToolBar(QWidget):
    # Signals for tools
    tool_selected = Signal(str) # 'rect', 'circle', 'arrow', 'line', 'pen', 'mosaic', 'text'
    action_triggered = Signal(str) # 'save', 'copy', 'close', 'undo'
    color_changed = Signal(QColor)
    width_changed = Signal(int)
    font_size_changed = Signal(int)
    style_changed = Signal(str) # 'normal', 'hand_drawn'
    crop_ratio_changed = Signal(str)
    rect_ratio_changed = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_editor = parent
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
        
        # --- New Canvas Button ---
        self.btn_new = QPushButton("🆕")
        self.btn_new.setFixedSize(30, 30)
        self.btn_new.setToolTip("新建画布")
        self.btn_new.clicked.connect(lambda: self.action_triggered.emit('new'))
        # Initially hidden, shown only in standalone mode
        self.btn_new.hide()
        container_layout.addWidget(self.btn_new)

        # --- Open Button (New) ---
        self.btn_open = QPushButton("🖼️")
        self.btn_open.setFixedSize(30, 30)
        self.btn_open.setToolTip("打开图片")
        self.btn_open.clicked.connect(lambda: self.action_triggered.emit('open'))
        # Initially hidden, shown only in standalone mode
        self.btn_open.hide() 
        container_layout.addWidget(self.btn_open)

        # --- Import Image Button ---
        self.btn_import_image = QPushButton("📂")
        self.btn_import_image.setFixedSize(30, 30)
        self.btn_import_image.setToolTip("导入图片到画布")
        self.btn_import_image.clicked.connect(lambda: self.action_triggered.emit('import_image'))
        self.btn_import_image.hide()
        container_layout.addWidget(self.btn_import_image)

        # --- Frame Button ---
        self.btn_frame = QPushButton()
        frame_icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets/frame.png')
        if os.path.exists(frame_icon_path):
            self.btn_frame.setIcon(QIcon(frame_icon_path))
            self.btn_frame.setIconSize(QSize(20, 20))
        else:
            self.btn_frame.setText("🔲")
        self.btn_frame.setFixedSize(30, 30)
        self.btn_frame.setToolTip("画框")
        self.btn_frame.clicked.connect(lambda: self.action_triggered.emit('frame'))
        container_layout.addWidget(self.btn_frame)
        
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
        sizes = [('小', 16), ('中', 24), ('大', 48)]
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
            if size == 24: btn.setChecked(True)
            
        self.settings_stack.addWidget(self.font_widget)

        # --- Rect Settings ---
        self.rect_widget = QWidget()
        rw_layout = QHBoxLayout(self.rect_widget)
        rw_layout.setContentsMargins(0, 0, 0, 0)
        rw_layout.setSpacing(5)
        
        self.rect_ratio_combo = QComboBox()
        self.rect_ratio_combo.addItems(["Free", "1:1", "3:4", "4:3", "2:3", "3:2", "9:16", "16:9"])
        self.rect_ratio_combo.setToolTip("矩形比例")
        self.rect_ratio_combo.setFixedWidth(60)
        self.rect_ratio_combo.setStyleSheet("""
            QComboBox { border: 1px solid #ccc; border-radius: 3px; font-size: 10px; padding: 1px; color: #333; }
            QComboBox::drop-down { border: none; }
        """)
        self.rect_ratio_combo.currentTextChanged.connect(lambda t: self.rect_ratio_changed.emit(t))
        
        rw_layout.addWidget(self.rect_ratio_combo)
        
        # Add slider for width as well
        self.rect_width_slider = QSlider(Qt.Horizontal)
        self.rect_width_slider.setRange(1, 20)
        self.rect_width_slider.setValue(3)
        self.rect_width_slider.setFixedWidth(40)
        self.rect_width_slider.setToolTip("线条粗细")
        self.rect_width_slider.valueChanged.connect(self.on_width_changed)
        
        self.rect_width_label = QLabel("3")
        self.rect_width_label.setStyleSheet("color: #333; font-size: 10px; margin-right: 5px;")
        self.rect_width_label.setFixedWidth(20)
        self.rect_width_label.setAlignment(Qt.AlignCenter)
        
        rw_layout.addWidget(self.rect_width_slider)
        rw_layout.addWidget(self.rect_width_label)
        
        self.settings_stack.addWidget(self.rect_widget)

        # --- Crop Settings ---
        self.crop_widget = QWidget()
        cw_layout = QHBoxLayout(self.crop_widget)
        cw_layout.setContentsMargins(0, 0, 0, 0)
        cw_layout.setSpacing(2)
        
        self.crop_ratio_combo = QComboBox()
        self.crop_ratio_combo.addItems(["Free", "1:1", "3:4", "4:3", "2:3", "3:2", "9:16", "16:9"])
        self.crop_ratio_combo.setToolTip("剪裁比例")
        self.crop_ratio_combo.setFixedWidth(60)
        self.crop_ratio_combo.setStyleSheet("""
            QComboBox { border: 1px solid #ccc; border-radius: 3px; font-size: 10px; padding: 1px; color: #333; }
            QComboBox::drop-down { border: none; }
        """)
        self.crop_ratio_combo.currentTextChanged.connect(lambda t: self.crop_ratio_changed.emit(t))
        
        btn_ok = QPushButton("✔")
        btn_ok.setFixedSize(20, 20)
        btn_ok.setStyleSheet("QPushButton { color: green; font-weight: bold; font-size: 14px; } QPushButton:hover { background-color: #e0e0e0; }")
        btn_ok.setToolTip("确认剪裁")
        btn_ok.clicked.connect(lambda: self.action_triggered.emit('crop_confirm'))

        btn_cancel = QPushButton("✘")
        btn_cancel.setFixedSize(20, 20)
        btn_cancel.setStyleSheet("QPushButton { color: red; font-weight: bold; font-size: 14px; } QPushButton:hover { background-color: #e0e0e0; }")
        btn_cancel.setToolTip("取消剪裁")
        btn_cancel.clicked.connect(lambda: self.action_triggered.emit('crop_cancel'))

        cw_layout.addWidget(self.crop_ratio_combo)
        cw_layout.addWidget(btn_ok)
        cw_layout.addWidget(btn_cancel)
        
        self.settings_stack.addWidget(self.crop_widget)
        
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
            ('select', None, '选择'),
            ('crop', '✂️', '剪裁'),
            ('rect', '⬜', '矩形'),
            ('circle', '⭕', '圆形'),
            ('step_marker', '①', '步骤标注'),
            ('arrow', '↗️', '箭头'),
            ('line', '📏', '直线'),
            ('pen', '✏️', '画笔'),
            ('laser', '🔦', '激光笔'),
            ('mosaic', '🏁', '马赛克'),
            ('text', 'T', '文字'),
        ]
        
        for key, icon, tooltip in tool_defs:
            if key == 'select':
                btn = QPushButton()
                btn.setIcon(self._create_dashed_rect_icon())
                btn.setIconSize(QSize(20, 20))
            else:
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
            if isinstance(icon_val, str) and icon_val.endswith('.png'):
                icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), icon_val)
                if os.path.exists(icon_path):
                    btn = QPushButton()
                    btn.setIcon(QIcon(icon_path))
                    btn.setIconSize(QSize(20, 20))
                else:
                    btn = QPushButton("?")
            else:
                btn = QPushButton(icon_val)
            btn.setToolTip(tooltip)
            btn.setFixedSize(30, 30)
            if key == 'minimize':
                self.btn_minimize = btn
            elif key == 'close':
                self.btn_close = btn
            if key == 'copy':
                # Use default arguments to capture current state
                def on_click(checked=False, cur_btn=btn):
                    self.action_triggered.emit('copy')
                    logger.info('Copy action button pressed, showing success feedback')
                    
                    # Capture original text and style immediately
                    original_text = '❐' # Hardcode original icon as btn.text() might be changed if clicked rapidly
                    original_style = cur_btn.styleSheet()
                    
                    cur_btn.setText("✔️")
                    cur_btn.setStyleSheet("QPushButton { color: #00ff00; font-weight: bold; }")
                    
                    # Force repaint to show change immediately
                    cur_btn.repaint()
                    
                    def restore_btn():
                        try:
                            if cur_btn and cur_btn.isVisible():
                                cur_btn.setText(original_text)
                                cur_btn.setStyleSheet(original_style)
                        except RuntimeError:
                            # Widget might be deleted
                            pass
                            
                    QTimer.singleShot(600, restore_btn)
                    
                    # Manually trigger hide check after a short delay to handle immediate app switch
                    # This helps in case FocusOut was missed or swallowed during button click processing
                    def check_hide():
                        try:
                            app = QApplication.instance()
                            # If app is not active, hide panel
                            if app.applicationState() != Qt.ApplicationActive:
                                if hasattr(self, 'parent_editor') and self.parent_editor:
                                    # We are in EditToolBar, parent is ScreenshotEditor
                                    if hasattr(self.parent_editor, '_hide_prop_panel_on_deactivate'):
                                        self.parent_editor._hide_prop_panel_on_deactivate("PostCopyCheck")
                        except:
                            pass
                            
                    QTimer.singleShot(500, check_hide)
                    
                btn.clicked.connect(on_click)
            else:
                btn.clicked.connect(lambda c, k=key: self.action_triggered.emit(k))
            container_layout.addWidget(btn)

        line2 = QLabel("|")
        line2.setStyleSheet("color: #bbb;")
        line2.setFixedWidth(10)
        line2.setAlignment(Qt.AlignCenter)
        line2.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        container_layout.addWidget(line2)

        self.canvas_size_label = QLabel("")
        self.canvas_size_label.setStyleSheet("color: #666; font-size: 10px; padding-left: 4px; padding-right: 4px;")
        self.canvas_size_label.setAlignment(Qt.AlignCenter)
        self.canvas_size_label.setFixedHeight(20)
        self.canvas_size_label.hide()
        container_layout.addWidget(self.canvas_size_label)
            
    def event(self, event):
        # Handle WindowDeactivate manually because changeEvent might not catch it for tool windows on some platforms
        if event.type() == QEvent.WindowDeactivate:
             if hasattr(self, 'parent_editor') and self.parent_editor:
                 if hasattr(self.parent_editor, '_hide_prop_panel_on_deactivate'):
                     self.parent_editor._hide_prop_panel_on_deactivate("ToolbarEventDeactivate")
        return super().event(event)

    def changeEvent(self, event):
        if event.type() == QEvent.WindowDeactivate:
            # When toolbar loses focus (e.g. switching apps), try to hide prop panel
            if hasattr(self, 'parent_editor') and self.parent_editor:
                if hasattr(self.parent_editor, '_hide_prop_panel_on_deactivate'):
                    self.parent_editor._hide_prop_panel_on_deactivate("ToolbarDeactivate")
        super().changeEvent(event)

    def set_canvas_size_text(self, text):
        self.canvas_size_label.setText(text)
        if text:
            self.canvas_size_label.show()
        else:
            self.canvas_size_label.hide()

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
        if hasattr(self, 'rect_width_label'):
             self.rect_width_label.setText(str(value))
        
        # Sync sliders
        if self.width_slider.value() != value:
            self.width_slider.blockSignals(True)
            self.width_slider.setValue(value)
            self.width_slider.blockSignals(False)
            
        if hasattr(self, 'rect_width_slider') and self.rect_width_slider.value() != value:
            self.rect_width_slider.blockSignals(True)
            self.rect_width_slider.setValue(value)
            self.rect_width_slider.blockSignals(False)

        self.width_changed.emit(value)

    def on_font_size_clicked(self, size, btn):
        for b in self.font_btns:
            if b != btn: b.setChecked(False)
        btn.setChecked(True)
        self.font_size_changed.emit(size)

    def _create_dashed_rect_icon(self):
        pm = QPixmap(20, 20)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(60, 60, 60), 2)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(3, 3, 14, 14)
        p.end()
        return QIcon(pm)

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
            elif key == 'crop':
                self.settings_stack.setCurrentWidget(self.crop_widget)
            elif key == 'rect':
                self.settings_stack.setCurrentWidget(self.rect_widget)
                # Sync slider
                self.rect_width_slider.setValue(self.width_slider.value())
            else:
                self.settings_stack.setCurrentWidget(self.width_widget)

import time

import copy
import uuid

class ScreenshotEditor(QWidget):
    def __init__(self, pixmap=None, global_rect=None, mode='screenshot'):
        super().__init__()
        
        self.mode = mode
        logger.info(f"Initializing ScreenshotEditor in mode: {mode}")
        
        if self.mode == 'screenshot':
            # Remove Qt.Tool to allow showing in taskbar for minimization
            # Remove Qt.WindowStaysOnTopHint so it doesn't block other windows
            self.setWindowFlags(Qt.FramelessWindowHint)
            self.setWindowTitle("截图")
            self.setAttribute(Qt.WA_DeleteOnClose)
            if global_rect:
                offset = 60
                target_rect = QRect(global_rect)
                target_rect.moveTo(global_rect.x() - offset, global_rect.y() - offset)
                screen = QGuiApplication.screenAt(global_rect.center()) or QGuiApplication.primaryScreen()
                if screen:
                    screen_geom = screen.geometry()
                    if target_rect.x() < screen_geom.left():
                        target_rect.moveLeft(screen_geom.left())
                    if target_rect.y() < screen_geom.top():
                        target_rect.moveTop(screen_geom.top())
                self.setGeometry(target_rect)
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
            # Create a default large canvas (Pseudo-infinite)
            # 4000x6000 as requested
            pixmap = QPixmap(4000, 6000)
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
        self.history = [([], self.original_pixmap)] # Undo stack: list of (items, pixmap) tuples

        self.tabbed_canvases_enabled = (self.mode == 'standalone')
        self.multi_page_enabled = False
        self.pages = []
        self.active_page_index = 0
        self._last_mapped_valid = False
        self._last_mapped_page_index = None
        if self.tabbed_canvases_enabled:
            self.pages.append(self._create_page(self.original_pixmap, self.mosaic_pixmap, self.items, self.history))
        
        self.pen_color = QColor(255, 0, 0)
        self.pen_width = 3
        self.font_size = 24
        
        # Selection / Moving
        self.selected_item_index = -1
        self.last_mouse_pos = QPoint()
        self.clipboard_item = None # For copying items
        self.region_select_rect = None
        self.region_select_start = QPointF()
        self.is_region_selecting = False
        
        # View Offset for Panning (Standalone mode)
        self.view_offset = QPoint(0, 0)
        self.alignment_guides = [] # For smart alignment in standalone mode
        
        # Path for free drawing
        self.current_path = None
        
        self.drawing_style = 'normal' # 'normal' or 'hand_drawn'
        self.rect_ratio = None
        
        # Crop State
        self.crop_rect = None # QRectF
        self.crop_ratio = None # Float or None
        self.crop_handle_index = -1
        self.is_moving_crop = False
        self.crop_start_pos = QPointF()
        self.crop_start_rect = QRectF()
        
        # Laser Pointer State
        self.laser_points = [] # List of {'pos': QPointF, 'time': float}
        self.laser_timer = QTimer(self)
        self.laser_timer.setInterval(30) # ~30 FPS
        self.laser_timer.timeout.connect(self.update_laser)
        
        # Toolbar
        # Pass self as parent so toolbar minimizes/restores with editor
        self.toolbar = EditToolBar(self)
        self.toolbar.tool_selected.connect(self.set_tool)
        self.toolbar.action_triggered.connect(self.handle_action)
        self.toolbar.color_changed.connect(self.set_color)
        self.toolbar.width_changed.connect(self.set_width)
        self.toolbar.font_size_changed.connect(self.set_font_size)
        self.toolbar.style_changed.connect(self.set_drawing_style)
        self.toolbar.crop_ratio_changed.connect(self.set_crop_ratio)
        self.toolbar.rect_ratio_changed.connect(self.set_rect_ratio)
        
        # Properties Panel
        self.prop_panel = PropertiesPanel(self)
        self.prop_panel.hide()
        self.prop_panel.property_changed.connect(self.on_prop_changed)
        self.prop_panel.action_triggered.connect(self.on_prop_action)
        self.prop_panel.size_changed.connect(self.update_toolbar_pos)
        if self.mode == 'standalone':
            try:
                self.prop_panel.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
                self.prop_panel.hide()
            except Exception:
                pass
        
        if self.mode == 'standalone':
            self.toolbar.setWindowFlags(Qt.Widget) # Ensure it behaves as a normal child widget
            self.toolbar.btn_open.show()
            self.toolbar.btn_new.show()
            self.toolbar.btn_import_image.show()
            if hasattr(self.toolbar, 'btn_minimize'):
                self.toolbar.btn_minimize.hide()
            if hasattr(self.toolbar, 'btn_close'):
                self.toolbar.btn_close.hide()
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

            self.page_tab_bar = QTabBar()
            self.page_tab_bar.setDocumentMode(True)
            self.page_tab_bar.setExpanding(False)
            self.page_tab_bar.setUsesScrollButtons(True)
            self.page_tab_bar.setMovable(False)
            self.page_tab_bar.setElideMode(Qt.ElideRight)
            self.page_tab_bar.setStyleSheet("""
                QTabBar::tab {
                    background: #f5f5f5;
                    border: 1px solid #e0e0e0;
                    border-bottom: none;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                    padding: 6px 12px;
                    margin-right: 4px;
                    min-width: 72px;
                }
                QTabBar::tab:selected {
                    background: #ffffff;
                    border-color: #cfd8dc;
                    color: #111111;
                }
                QTabBar::tab:!selected {
                    color: #666666;
                }
            """)
            self.page_tab_bar.currentChanged.connect(self._on_page_tab_changed)
            self.btn_canvas_clone = QPushButton("克隆")
            self.btn_canvas_delete = QPushButton("删除")
            self.btn_canvas_export_all = QPushButton("导出全部")
            self.btn_canvas_clone.setFixedHeight(28)
            self.btn_canvas_delete.setFixedHeight(28)
            self.btn_canvas_export_all.setFixedHeight(28)
            self.btn_canvas_clone.setMinimumWidth(72)
            self.btn_canvas_delete.setMinimumWidth(72)
            self.btn_canvas_export_all.setMinimumWidth(96)
            self.btn_canvas_clone.setCursor(Qt.PointingHandCursor)
            self.btn_canvas_delete.setCursor(Qt.PointingHandCursor)
            self.btn_canvas_export_all.setCursor(Qt.PointingHandCursor)
            self.btn_canvas_clone.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff;
                    border: 1px solid #d0d0d0;
                    border-radius: 6px;
                    padding: 4px 10px;
                }
                QPushButton:hover { background-color: #f4f4f4; }
            """)
            self.btn_canvas_delete.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff;
                    border: 1px solid #d0d0d0;
                    border-radius: 6px;
                    padding: 4px 10px;
                    color: #d32f2f;
                }
                QPushButton:hover { background-color: #ffebee; }
            """)
            self.btn_canvas_export_all.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff;
                    border: 1px solid #d0d0d0;
                    border-radius: 6px;
                    padding: 4px 10px;
                    color: #2e7d32;
                }
                QPushButton:hover { background-color: #e8f5e9; }
            """)
            self.btn_canvas_clone.clicked.connect(lambda: self.clone_canvas_page(self.active_page_index))
            self.btn_canvas_delete.clicked.connect(lambda: self.delete_canvas_page(self.active_page_index))
            self.btn_canvas_export_all.clicked.connect(self.export_all_canvases)

            self.page_tab_container = QWidget()
            tab_row = QHBoxLayout(self.page_tab_container)
            tab_row.setContentsMargins(8, 0, 8, 0)
            tab_row.setSpacing(8)
            tab_row.addWidget(self.page_tab_bar, 1)
            tab_row.addStretch(1)
            tab_row.addWidget(self.btn_canvas_clone)
            tab_row.addWidget(self.btn_canvas_delete)
            tab_row.addWidget(self.btn_canvas_export_all)
            self.main_layout.addWidget(self.page_tab_container)
            
            # Canvas area (spacer for now, painting happens on self)
            # Actually, if we use layout, the toolbar widget takes space at top.
            # We need to adjust paintEvent to respect the toolbar area if it's not transparent overlay.
            # But EditToolBar has translucent background.
            # To simplify, we'll let the toolbar be part of layout, and the rest is drawn below.
            # We need a dedicated CanvasWidget to draw on, otherwise self.paintEvent draws behind toolbar.
            
            self.scroll_area = QScrollArea()
            self.scroll_area.setFrameShape(QFrame.NoFrame)
            self.scroll_area.setWidgetResizable(True)
            self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

            self.canvas_widget = QWidget()
            # Remove stylesheet to avoid conflict with custom paintEvent in eventFilter
            # self.canvas_widget.setStyleSheet("background-color: #333;") 
            self.canvas_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.canvas_widget.setFocusPolicy(Qt.StrongFocus) # Allow canvas to receive key events
            self.canvas_widget.setMouseTracking(True) # Enable mouse tracking for hover effects
            self.canvas_widget.setAcceptDrops(True)
            self.scroll_area.setWidget(self.canvas_widget)
            self.main_layout.addWidget(self.scroll_area)
            
            # Re-route events from canvas_widget to self logic, OR better:
            # Install event filter on canvas_widget to capture mouse events
            self.canvas_widget.installEventFilter(self)
            if self.tabbed_canvases_enabled:
                self._sync_page_tabs()
            
        else:
            self.toolbar.show()
            self.update_toolbar_pos()

        self.update_canvas_size_label()
        self.setCursor(Qt.CrossCursor)

        # Load custom fonts
        self.hand_drawn_font_family = None
        self.load_fonts()

    def load_fonts(self):
        """Load custom fonts from assets directory"""
        try:
            assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets')
            if not os.path.exists(assets_dir):
                return
                
            font_files = [f for f in os.listdir(assets_dir) if f.lower().endswith('.ttf')]
            for f in font_files:
                font_path = os.path.join(assets_dir, f)
                font_id = QFontDatabase.addApplicationFont(font_path)
                if font_id != -1:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    # Filter out empty strings
                    families = [fam for fam in families if fam.strip()]
                    
                    logger.info(f"Loaded font {f}: {families}")
                    
                    if not families:
                        continue
                        
                    # Detect hand-drawn font (assuming it's the JasonHandwriting1 one or contains 'Hand')
                    # Prioritize JasonHandwriting1 as it is the primary hand-drawn font
                    is_jason = 'JasonHandwriting1' in f
                    is_hand = 'hand' in f.lower() or 'hand' in families[0].lower()
                    
                    if is_jason or is_hand:
                        # If we already have a hand-drawn font, only overwrite if this is the JasonHandwriting1 font (priority)
                        if self.hand_drawn_font_family:
                            if is_jason and 'JasonHandwriting1' not in self.hand_drawn_font_family:
                                self.hand_drawn_font_family = families[0]
                                logger.info(f"Identified hand-drawn font (Priority): {self.hand_drawn_font_family}")
                        else:
                            self.hand_drawn_font_family = families[0]
                            logger.info(f"Identified hand-drawn font: {self.hand_drawn_font_family}")
                            
        except Exception as e:
            logger.error(f"Failed to load fonts: {e}")

    def generate_mosaic(self, pixmap):
        # Scale down and up to create pixelation
        if pixmap.isNull(): return pixmap
        img = pixmap.toImage()
        w, h = img.width(), img.height()
        block_size = 10
        if w < block_size or h < block_size: return pixmap
        
        try:
            # Ensure target size is at least 1x1
            target_w = max(1, w // block_size)
            target_h = max(1, h // block_size)
            
            small = img.scaled(target_w, target_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            large = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            return QPixmap.fromImage(large)
        except Exception as e:
            logger.error(f"Error generating mosaic: {e}")
            return pixmap

    def update_laser(self):
        try:
            if not self.laser_points:
                self.laser_timer.stop()
                return
                
            current_time = time.time()
            # Remove expired points (older than 1.0s)
            self.laser_points = [p for p in self.laser_points if current_time - p['time'] < 1.0]
            
            if not self.laser_points:
                self.laser_timer.stop()
                logger.debug("Laser pointer trail cleared, timer stopped")
            
            self.refresh_canvas()
        except Exception as e:
            logger.error(f"Error in update_laser: {e}", exc_info=True)
            self.laser_timer.stop()

    def set_tool(self, tool):
        # Force commit if we are switching away from text or just changing tools
        if hasattr(self, 'active_text_editor') and self.active_text_editor:
            self.commit_text_editor()

        # Clear laser pointer data when switching tools
        if self.current_tool == 'laser' and tool != 'laser':
            self.laser_points = []
            self.laser_timer.stop()
            self.refresh_canvas()

        if tool != 'select':
            self.region_select_rect = None
            self.is_region_selecting = False

        self.current_tool = tool
        logger.info(f"Tool selected: {tool}")
        self.selected_item_index = -1 # Reset selection when changing tools
        self.prop_panel.hide() # Hide properties panel when tool is selected
        
        if tool == 'crop':
            self.init_crop()
            self.setCursor(Qt.CrossCursor)
        elif tool == 'select':
            self.setCursor(Qt.CrossCursor)
        elif tool == 'text':
            self.setCursor(Qt.IBeamCursor)
        elif tool == 'step_marker':
            self.setCursor(Qt.PointingHandCursor)
        elif tool == 'move':
            self.setCursor(Qt.OpenHandCursor)
        elif tool == 'laser':
            self.setCursor(Qt.CrossCursor)
        elif tool is None:
            self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.CrossCursor)
        
        self.refresh_canvas()

    def init_crop(self):
        # Initialize crop rect to None, waiting for user to drag anywhere
        self.crop_rect = None 
        self.crop_ratio = None
        self.toolbar.crop_ratio_combo.setCurrentText("Free")
        self.is_creating_crop = False # Flag to track if we are creating a new crop rect

    def set_crop_ratio(self, ratio_str):
        if ratio_str == "Free":
            self.crop_ratio = None
        else:
            try:
                w, h = map(int, ratio_str.split(':'))
                self.crop_ratio = w / h
                # Adjust current crop rect to match ratio
                if self.crop_rect:
                    current_center = self.crop_rect.center()
                    current_area = self.crop_rect.width() * self.crop_rect.height()
                    # Keep area roughly same, adjust w/h
                    # h * (ratio * h) = area => h^2 = area / ratio
                    if self.crop_ratio > 0:
                        new_h = math.sqrt(current_area / self.crop_ratio)
                        new_w = new_h * self.crop_ratio
                        
                        # Ensure it fits in image
                        img_w, img_h = self.original_pixmap.width(), self.original_pixmap.height()
                        if new_w > img_w:
                            new_w = img_w
                            new_h = new_w / self.crop_ratio
                        if new_h > img_h:
                            new_h = img_h
                            new_w = new_h * self.crop_ratio
                            
                        self.crop_rect = QRectF(0, 0, new_w, new_h)
                        self.crop_rect.moveCenter(current_center)
                        
                        # Constrain to image bounds
                        if self.crop_rect.left() < 0: self.crop_rect.moveLeft(0)
                        if self.crop_rect.top() < 0: self.crop_rect.moveTop(0)
                        if self.crop_rect.right() > img_w: self.crop_rect.moveRight(img_w)
                        if self.crop_rect.bottom() > img_h: self.crop_rect.moveBottom(img_h)
                        
                        self.refresh_canvas()
            except Exception as e:
                logger.error(f"Error setting crop ratio: {e}")
                self.crop_ratio = None

    def set_rect_ratio(self, ratio_str):
        if ratio_str == "Free":
            self.rect_ratio = None
        else:
            try:
                w, h = map(int, ratio_str.split(':'))
                self.rect_ratio = w / h
            except:
                self.rect_ratio = None

    def apply_crop(self):
        if not self.crop_rect: return
        
        logger.info(f"Applying crop: {self.crop_rect}")
        
        # 1. Flatten current drawing
        final_pixmap = self.get_final_image()
        
        # 2. Crop
        rect = self.crop_rect.toRect()
        # Ensure rect is within bounds
        img_rect = final_pixmap.rect()
        rect = rect.intersected(img_rect)
        
        cropped_pixmap = final_pixmap.copy(rect)
        
        # 3. Reset editor with new pixmap
        self._replace_active_page_pixmap(cropped_pixmap)
        self._replace_active_page_items([])
        self.update_canvas_size_label()
        
        self.save_state()
        
        self.toolbar.select_tool('move')
        self.current_tool = None
        self.setCursor(Qt.ArrowCursor)
        self.refresh_canvas()

    def cancel_crop(self):
        self.toolbar.select_tool('move')
        self.current_tool = None
        self.refresh_canvas()

    def handle_action(self, action):
        logger.info(f"Action triggered: {action}")
        if action == 'new':
            self.new_canvas_dialog()
        elif action == 'open':
            self.open_image()
        elif action == 'import_image':
            self.import_image_to_canvas()
        elif action == 'clear':
            self.clear_canvas()
        elif action == 'zoom_in':
            self.zoom_in()
        elif action == 'zoom_out':
            self.zoom_out()
        elif action == 'frame':
            self.show_frame_selection_dialog()
        elif action == 'save':
            self.save_image()
        elif action == 'copy':
            if not self.copy_region_selection_to_clipboard():
                self.copy_image()
        elif action == 'minimize':
            self.showMinimized()
        elif action == 'close':
            self.close()
        elif action == 'undo':
            self.undo()
        elif action == 'crop_confirm':
            self.apply_crop()
        elif action == 'crop_cancel':
            self.cancel_crop()

    def show_frame_selection_dialog(self):
        dialog = FrameSelectionDialog(self)
        
        if getattr(self, 'tabbed_canvases_enabled', False):
            page = self._get_active_page()
            fs = self._ensure_page_frame_state(page)
            if fs and fs.get("is_frame_mode"):
                dialog.margin_slider.setValue(int(fs.get("margin", 30)))
                dialog.radius_slider.setValue(int(fs.get("radius", 20)))
                bg = fs.get("bg_path")
                if bg:
                    for i in range(dialog.list_widget.count()):
                        item = dialog.list_widget.item(i)
                        if item.data(Qt.UserRole) == bg:
                            dialog.list_widget.setCurrentItem(item)
                            dialog.selected_bg = bg
                            break
        else:
            if hasattr(self, 'is_frame_mode') and self.is_frame_mode:
                dialog.margin_slider.setValue(self.frame_margin)
                dialog.radius_slider.setValue(self.frame_radius)
                if hasattr(self, 'frame_bg_path') and self.frame_bg_path:
                    for i in range(dialog.list_widget.count()):
                        item = dialog.list_widget.item(i)
                        if item.data(Qt.UserRole) == self.frame_bg_path:
                            dialog.list_widget.setCurrentItem(item)
                            dialog.selected_bg = self.frame_bg_path
                            break
        
        if dialog.exec() == QDialog.Accepted and dialog.selected_bg:
            self.apply_frame(dialog.selected_bg, dialog.margin_value, dialog.radius_value)
            
    def apply_frame(self, bg_path, margin=30, radius=20):
        if not os.path.exists(bg_path):
            return
            
        if not getattr(self, 'tabbed_canvases_enabled', False):
            if hasattr(self, 'is_frame_mode') and self.is_frame_mode and hasattr(self, 'raw_content_pixmap'):
                self.save_state()
                current_content = self.raw_content_pixmap
            else:
                self.save_state()
                current_content = self.get_final_image()
                self.raw_content_pixmap = current_content
                self.is_frame_mode = True

            if current_content.isNull():
                return

            self.frame_bg_path = bg_path
            self.frame_margin = margin
            self.frame_radius = radius

            w = current_content.width()
            h = current_content.height()
        else:
            page = self._get_active_page()
            fs = self._ensure_page_frame_state(page)
            if fs is None:
                return

            self.save_state()
            raw = fs.get("raw_content_pixmap")
            if fs.get("is_frame_mode") and isinstance(raw, QPixmap) and not raw.isNull():
                current_content = raw
            else:
                current_content = self.get_final_image()
                fs["raw_content_pixmap"] = current_content
                fs["is_frame_mode"] = True

            if current_content.isNull():
                return

            fs["bg_path"] = bg_path
            fs["margin"] = margin
            fs["radius"] = radius
            self.frame_bg_path = bg_path
            self.frame_margin = margin
            self.frame_radius = radius
            w = current_content.width()
            h = current_content.height()
        
        # 2. Prepare dimensions
        inner_w = w - 2 * margin
        inner_h = h - 2 * margin
        
        if inner_w <= 0 or inner_h <= 0:
            return
            
        # 3. Create new base
        new_pixmap = QPixmap(w, h)
        new_pixmap.fill(Qt.transparent)
        
        painter = QPainter(new_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # 4. Draw Background
        bg_img = QPixmap(bg_path)
        if not bg_img.isNull():
            # Scale background to fill
            bg_scaled = bg_img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(0, 0, bg_scaled)
        else:
            painter.fillRect(0, 0, w, h, Qt.white)
            
        # 5. Draw Content (Scaled down with rounded corners)
        content_scaled = current_content.scaled(inner_w, inner_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        
        if content_scaled.isNull():
             painter.end()
             return

        # Center the content
        cx = (w - content_scaled.width()) // 2
        cy = (h - content_scaled.height()) // 2
        
        # Create rounded rect path for clipping
        rounded_content = QPixmap(content_scaled.size())
        rounded_content.fill(Qt.transparent)
        
        content_painter = QPainter(rounded_content)
        content_painter.setRenderHint(QPainter.Antialiasing)
        content_painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        path = QPainterPath()
        path.addRoundedRect(0, 0, content_scaled.width(), content_scaled.height(), radius, radius)
        content_painter.setClipPath(path)
        content_painter.drawPixmap(0, 0, content_scaled)
        content_painter.end()
        
        painter.drawPixmap(cx, cy, rounded_content)
        painter.end()
        
        # 6. Update Editor
        self._replace_active_page_pixmap(new_pixmap)
        self._replace_active_page_items([]) # Content is flattened now
        self.history.append(([], self.original_pixmap))
        
        # Limit history again just in case
        if len(self.history) > 10:
            self.history.pop(0)
            
        self.refresh_canvas()
        logger.info(f"Applied frame: {bg_path}, margin={margin}, radius={radius}")

    def update_frame(self):
        if not getattr(self, 'tabbed_canvases_enabled', False):
            if hasattr(self, 'frame_bg_path') and self.frame_bg_path:
                self.apply_frame(self.frame_bg_path, self.frame_margin, self.frame_radius)
            return

        page = self._get_active_page()
        fs = self._ensure_page_frame_state(page)
        if not fs:
            return
        bg = fs.get("bg_path")
        if bg:
            self.apply_frame(bg, fs.get("margin", 30), fs.get("radius", 20))

    def open_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开图片", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            self.load_image(file_path)

    def import_image_to_canvas(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入图片", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            image = QImage(file_path)
            if image.isNull():
                return
            pixmap = QPixmap.fromImage(image)
            
            # Scale if too big (max 80% of canvas)
            canvas_w, canvas_h = self.original_pixmap.width(), self.original_pixmap.height()
            
            # If image is larger than canvas, scale it down
            if pixmap.width() > canvas_w * 0.8 or pixmap.height() > canvas_h * 0.8:
                pixmap = pixmap.scaled(QSize(int(canvas_w * 0.8), int(canvas_h * 0.8)), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
            # Center it
            x = (canvas_w - pixmap.width()) / 2
            y = (canvas_h - pixmap.height()) / 2
            
            item = {
                'type': 'image',
                'pixmap': pixmap,
                'rect': QRectF(x, y, pixmap.width(), pixmap.height()),
                'rotation': 0
            }
            self.items.append(item)
            self.save_state()
            self.refresh_canvas()

    def clear_canvas(self):
        # Clear all items but keep the original background
        self._replace_active_page_items([])
        self.selected_item_index = -1
        self.prop_panel.hide()
        
        # Reset history
        self._replace_active_page_history([([], self.original_pixmap)])
        self.refresh_canvas()

    def set_color(self, color):
        self.pen_color = color

    def set_drawing_style(self, style):
        self.drawing_style = style

    def set_width(self, width):
        self.pen_width = width

    def set_font_size(self, size):
        size = int(size) if int(size) > 0 else 9
        self.font_size = size
        if hasattr(self, 'active_text_editor') and self.active_text_editor:
             font = self.active_text_editor.font()
             font.setPointSize(size)
             self.active_text_editor.setFont(font)
             self.on_text_changed()

    def on_prop_changed(self, key, value):
        if self.selected_item_index == -1 or self.selected_item_index >= len(self.items):
            return
        item = self.items[self.selected_item_index]
        
        if key == 'font_size':
            size_val = int(value) if int(value) > 0 else 9
            if 'font' in item:
                font = QFont(item['font'])
                font.setPointSize(size_val)
                item['font'] = font
            else:
                item['font_size'] = size_val
        elif key == 'font':
            item['font'] = value
            if hasattr(value, 'pointSize'):
                item['font_size'] = value.pointSize()
        elif key == 'radius':
            item['radius'] = value
        elif key == 'opacity':
            item['opacity'] = value
        elif key == 'color':
            item['color'] = value
        elif key == 'fill_color':
            item['fill_color'] = value
        elif key == 'width':
            item['width'] = value
        elif key == 'stroke_style':
            item['stroke_style'] = value
        elif key == 'style':
            item['style'] = value
            
        self.refresh_canvas()
        # Save state for undo (debounce could be better for slider, but direct save is safer for now)
        self.save_state()
        
    def on_prop_action(self, action):
        if self.selected_item_index == -1 or self.selected_item_index >= len(self.items):
            return
        
        if action == 'copy':
            # Duplicate: Copy then Paste immediately
            self.copy_item()
            self.paste_item()
        elif action == 'delete':
            self.items.pop(self.selected_item_index)
            self.selected_item_index = -1
            self.prop_panel.hide()
            self.save_state()
            self.refresh_canvas()
        elif action == 'layer_top':
            item = self.items.pop(self.selected_item_index)
            self.items.append(item)
            self.selected_item_index = len(self.items) - 1
            self.refresh_canvas()
        elif action == 'layer_bottom':
            item = self.items.pop(self.selected_item_index)
            self.items.insert(0, item)
            self.selected_item_index = 0
            self.refresh_canvas()
        elif action == 'layer_up':
            idx = self.selected_item_index
            if idx < len(self.items) - 1:
                self.items[idx], self.items[idx+1] = self.items[idx+1], self.items[idx]
                self.selected_item_index = idx + 1
                self.refresh_canvas()
        elif action == 'layer_down':
            idx = self.selected_item_index
            if idx > 0:
                self.items[idx], self.items[idx-1] = self.items[idx-1], self.items[idx]
                self.selected_item_index = idx - 1
                self.refresh_canvas()

    def update_toolbar_pos(self):
        if not self.prop_panel.isHidden():
            panel_h = self.prop_panel.height()
            window_h = self.height()
            target_x = 20
            target_y = (window_h - panel_h) // 2
            if target_y < 20: target_y = 20
            p = self.mapToGlobal(QPoint(target_x, target_y))
            self.prop_panel.move(p)

        if self.mode == 'standalone':
            return
        
        screen = QGuiApplication.primaryScreen().geometry()
        tb_w = self.toolbar.sizeHint().width()
        tb_h = self.toolbar.sizeHint().height()
        
        x = self.x() + self.width() - tb_w
        if x < self.x(): x = self.x()
        
        gap = -25
        y = self.y() + self.height() + gap
        if y + tb_h > screen.bottom():
            y = self.y() + self.height() - tb_h - gap
        
        self.toolbar.move(x, y)
        new_pos = (x, y)
        if getattr(self, '_last_toolbar_pos', None) != new_pos:
            self._last_toolbar_pos = new_pos
            logger.info(f"Toolbar position updated: x={x}, y={y}, gap={gap}")

    def update_canvas_size_label(self):
        if not hasattr(self, 'toolbar') or not hasattr(self.toolbar, 'set_canvas_size_text'):
            return
        if self.mode != 'standalone':
            self.toolbar.set_canvas_size_text("")
            return
        if not hasattr(self, 'original_pixmap') or self.original_pixmap is None:
            self.toolbar.set_canvas_size_text("")
            return
        text = f"画布: {self.original_pixmap.width()} x {self.original_pixmap.height()}"
        if getattr(self, '_last_canvas_size_text', None) != text:
            self._last_canvas_size_text = text
            self.toolbar.set_canvas_size_text(text)
            logger.info(f"Canvas size updated: {text}")

    def resizeEvent(self, event):
        self.update_toolbar_pos()
        super().resizeEvent(event)

    def moveEvent(self, event):
        if self.mode == 'screenshot':
            self.update_toolbar_pos()
        super().moveEvent(event)

    def _hide_prop_panel_on_deactivate(self, reason):
        # Only hide if we are truly deactivating the application, 
        # NOT if we are just clicking on the property panel itself (which is a child/tool window).
        
        if getattr(self, '_is_checking_deactivate', False):
            return
        self._is_checking_deactivate = True
        
        try:
            if not (self.mode == 'standalone' and hasattr(self, 'prop_panel') and not self.prop_panel.isHidden()):
                return
    
            # If the active window is the property panel, DO NOT hide.
            app = QApplication.instance()
            active_window = app.activeWindow()
            
            logger.info(f"_hide_prop_panel_on_deactivate: reason={reason}, active={active_window}, appState={app.applicationState()}")
    
            if active_window == self.prop_panel:
                # logger.info("Active window is Prop Panel, ignoring deactivate hide")
                return
                
            # Also check if the active window is the editor itself (FocusOut might fire before activeWindow updates)
            if active_window == self:
                 return
                 
            # If we are here, it means focus went to some other window (e.g. another app, or desktop)
            # But verify again that active window is not one of ours
            if active_window in [self, self.prop_panel, self.toolbar]:
                 return
    
            # If we just copied, maybe give it a grace period or check if we are still active?
            # When user clicks Copy, activeWindow should be self (or toolbar).
            # If they switch app immediately, activeWindow becomes None (or invisible proxy).
            
            # Double check using win32 API if on Windows to be sure?
            # Or just trust Qt.
            
            # Fix: Check application state instead of just activeWindow
            if app.applicationState() == Qt.ApplicationActive:
                 # Application is still active, but maybe focus is transitioning
                 # Check if any of our widgets has focus
                 focus_widget = app.focusWidget()
                 logger.info(f"App Active, Focus Widget: {focus_widget}")
                 if focus_widget:
                     # If some widget in our app has focus, don't hide
                     return
            
            self.prop_panel.hide()
            logger.info(f"Properties panel hidden on {reason} (Active: {active_window})")
        except Exception as e:
            logger.error(f"Error in _hide_prop_panel_on_deactivate: {e}")
        finally:
            self._is_checking_deactivate = False

    def changeEvent(self, event):
        if event.type() == QEvent.WindowDeactivate:
            self._hide_prop_panel_on_deactivate("WindowDeactivate")
        super().changeEvent(event)

    def focusOutEvent(self, event):
        self._hide_prop_panel_on_deactivate("FocusOut")
        super().focusOutEvent(event)
        
    def closeEvent(self, event):
        # Stop timers
        if hasattr(self, 'laser_timer'):
            self.laser_timer.stop()
            
        # Auto-save before closing to prevent data loss
        self.auto_save()
        self.toolbar.close()
        super().closeEvent(event)

    def auto_save(self):
        try:
            # Check if essential attributes are initialized to prevent crash during init/test
            if not hasattr(self, 'original_pixmap'):
                return

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
            
            final_img = self.get_final_image()
            if final_img:
                final_img.save(file_path)
                logger.info(f"Auto-saved to: {file_path}")
        except Exception as e:
            logger.error(f"Auto-save failed: {e}")
            print(f"Auto-save failed: {e}")

    def refresh_canvas(self):
        if getattr(self, 'mode', None) == 'standalone' and hasattr(self, 'canvas_widget'):
            self.canvas_widget.update()
        else:
            self.update()

    def _create_page(self, pixmap, mosaic_pixmap, items, history):
        return {
            "id": uuid.uuid4().hex,
            "pixmap": pixmap,
            "mosaic_pixmap": mosaic_pixmap,
            "items": items,
            "history": history,
            "frame_state": {
                "is_frame_mode": False,
                "raw_content_pixmap": None,
                "bg_path": None,
                "margin": 30,
                "radius": 20
            }
        }

    def _get_active_page(self):
        if not getattr(self, 'tabbed_canvases_enabled', False):
            return None
        if not getattr(self, 'pages', None):
            return None
        if self.active_page_index < 0 or self.active_page_index >= len(self.pages):
            return None
        return self.pages[self.active_page_index]

    def _ensure_page_frame_state(self, page):
        if page is None:
            return None
        fs = page.get("frame_state")
        if not isinstance(fs, dict):
            fs = {}
        fs.setdefault("is_frame_mode", False)
        fs.setdefault("raw_content_pixmap", None)
        fs.setdefault("bg_path", None)
        fs.setdefault("margin", 30)
        fs.setdefault("radius", 20)
        page["frame_state"] = fs
        return fs

    def _deep_copy_item(self, item):
        new_item = {}
        for k, v in (item or {}).items():
            if k in ('pixmap', 'original_pixmap'):
                new_item[k] = v.copy()
            elif isinstance(v, QPixmap):
                new_item[k] = v.copy()
            elif k == 'path':
                new_item[k] = QPainterPath(v)
            elif isinstance(v, (QRectF, QPointF, QColor, QRect, QPoint)):
                new_item[k] = copy.copy(v)
            elif isinstance(v, QFont):
                new_item[k] = QFont(v)
            else:
                new_item[k] = copy.deepcopy(v)
        return new_item

    def _deep_copy_items(self, items):
        return [self._deep_copy_item(it) for it in (items or [])]

    def _set_active_page(self, page_index: int):
        if not getattr(self, 'tabbed_canvases_enabled', False):
            return
        if page_index < 0 or page_index >= len(self.pages):
            return
        if self.active_page_index == page_index:
            self._sync_page_tabs()
            return

        self.active_page_index = page_index
        page = self.pages[self.active_page_index]
        self.original_pixmap = page["pixmap"]
        self.mosaic_pixmap = page["mosaic_pixmap"]
        self.items = page["items"]
        self.history = page["history"]
        self.selected_item_index = -1
        self.crop_rect = None
        self.crop_handle_index = -1
        self.is_moving_crop = False
        try:
            self.prop_panel.hide()
        except Exception:
            pass
        self.update_canvas_size_label()
        self.refresh_canvas()
        self._sync_page_tabs()

    def _replace_active_page_pixmap(self, new_pixmap: QPixmap):
        self.original_pixmap = new_pixmap
        self.mosaic_pixmap = self.generate_mosaic(new_pixmap)
        if getattr(self, 'tabbed_canvases_enabled', False) and self.pages:
            page = self.pages[self.active_page_index]
            page["pixmap"] = self.original_pixmap
            page["mosaic_pixmap"] = self.mosaic_pixmap

    def _replace_active_page_items(self, new_items):
        self.items = new_items
        if getattr(self, 'tabbed_canvases_enabled', False) and self.pages:
            self.pages[self.active_page_index]["items"] = self.items

    def _replace_active_page_history(self, new_history):
        self.history = new_history
        if getattr(self, 'tabbed_canvases_enabled', False) and self.pages:
            self.pages[self.active_page_index]["history"] = self.history

    def _get_page_index_by_id(self, page_id: str) -> int:
        if not page_id:
            return -1
        for i, p in enumerate(self.pages):
            if p.get("id") == page_id:
                return i
        return -1

    def _sync_page_tabs(self):
        if not getattr(self, 'tabbed_canvases_enabled', False):
            return
        if not hasattr(self, 'page_tab_bar') or self.page_tab_bar is None:
            return

        tb = self.page_tab_bar
        tb.blockSignals(True)
        try:
            need = len(self.pages)
            while tb.count() > need:
                tb.removeTab(tb.count() - 1)
            while tb.count() < need:
                tb.addTab("")

            for i in range(need):
                tb.setTabText(i, f"画布{i + 1}")

            if 0 <= self.active_page_index < tb.count():
                tb.setCurrentIndex(self.active_page_index)
        finally:
            tb.blockSignals(False)

    def _on_page_tab_changed(self, index: int):
        if not getattr(self, 'tabbed_canvases_enabled', False):
            return
        if index < 0:
            return
        self._set_active_page(index)

    def _rebuild_page_controls(self):
        if not getattr(self, 'multi_page_enabled', False):
            return
        if not hasattr(self, 'canvas_widget'):
            return

        alive_ids = set()
        for idx, page in enumerate(self.pages):
            page_id = page["id"]
            alive_ids.add(page_id)
            if page_id in self._page_controls:
                continue

            btn_clone = QPushButton("克隆", self.canvas_widget)
            btn_delete = QPushButton("删除", self.canvas_widget)

            btn_clone.setCursor(Qt.PointingHandCursor)
            btn_delete.setCursor(Qt.PointingHandCursor)

            btn_clone.setFixedHeight(28)
            btn_delete.setFixedHeight(28)
            btn_clone.setMinimumWidth(72)
            btn_delete.setMinimumWidth(72)

            btn_clone.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff;
                    border: 1px solid #d0d0d0;
                    border-radius: 6px;
                    padding: 4px 10px;
                }
                QPushButton:hover { background-color: #f4f4f4; }
            """)
            btn_delete.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff;
                    border: 1px solid #d0d0d0;
                    border-radius: 6px;
                    padding: 4px 10px;
                    color: #d32f2f;
                }
                QPushButton:hover { background-color: #ffebee; }
            """)

            btn_clone.clicked.connect(lambda _=False, pid=page_id: self.clone_canvas_page(self._get_page_index_by_id(pid)))
            btn_delete.clicked.connect(lambda _=False, pid=page_id: self.delete_canvas_page(self._get_page_index_by_id(pid)))

            self._page_controls[page_id] = {"clone": btn_clone, "delete": btn_delete}

        for page_id in list(self._page_controls.keys()):
            if page_id in alive_ids:
                continue
            for b in self._page_controls[page_id].values():
                try:
                    b.deleteLater()
                except Exception:
                    pass
            self._page_controls.pop(page_id, None)

        self._update_canvas_widget_min_height()

    def _compute_pages_layout(self, canvas_width: int):
        layout = []
        y = int(self.page_margin)
        zoom = float(getattr(self, 'zoom_level', 1.0) or 1.0)

        for idx, page in enumerate(self.pages):
            pm = page.get("pixmap")
            if pm is None or pm.isNull():
                continue
            img_w, img_h = pm.width(), pm.height()
            scaled_w = max(1, int(img_w * zoom))
            scaled_h = max(1, int(img_h * zoom))

            x = (canvas_width - scaled_w) // 2
            if x < 0:
                x = 0

            rect = QRect(int(x), int(y), int(scaled_w), int(scaled_h))
            layout.append({"index": idx, "id": page["id"], "rect": rect, "img_w": img_w, "img_h": img_h})
            y += scaled_h + int(self.page_spacing)

        controls_h = 28 + 14
        total_h = y - int(self.page_spacing) + int(self.page_margin) + controls_h if layout else 0
        return layout, max(total_h, 0)

    def _update_canvas_widget_min_height(self):
        if not getattr(self, 'multi_page_enabled', False):
            return
        if not hasattr(self, 'canvas_widget'):
            return
        layout, total_h = self._compute_pages_layout(self.canvas_widget.width() if self.canvas_widget.width() > 0 else self.width())
        if total_h > 0 and self.canvas_widget.minimumHeight() != total_h:
            self.canvas_widget.setMinimumHeight(total_h)
        self._page_layout_cache = layout
        self._update_page_controls_geometry()

    def _update_page_controls_geometry(self):
        if not getattr(self, 'multi_page_enabled', False):
            return
        if not hasattr(self, 'canvas_widget'):
            return
        if not self._page_layout_cache:
            return

        btn_gap = 8
        btn_y_gap = 12
        for info in self._page_layout_cache:
            if info["index"] < 0 or info["index"] >= len(self.pages):
                continue
            page = self.pages[info["index"]]
            page_id = page["id"]
            rect = info["rect"]
            controls = self._page_controls.get(page_id)
            if not controls:
                continue

            btn_clone = controls["clone"]
            btn_delete = controls["delete"]

            btn_h = btn_delete.height()
            btn_w_del = btn_delete.sizeHint().width()
            btn_w_cl = btn_clone.sizeHint().width()

            right = rect.right()
            y = rect.bottom() + btn_y_gap
            x_del = right - btn_w_del + 1
            x_clone = x_del - btn_gap - btn_w_cl
            if x_clone < 0:
                x_clone = 0
                x_del = x_clone + btn_w_cl + btn_gap

            btn_clone.setGeometry(int(x_clone), int(y), int(btn_w_cl), int(btn_h))
            btn_delete.setGeometry(int(x_del), int(y), int(btn_w_del), int(btn_h))

    def clone_canvas_page(self, page_index: int):
        if not getattr(self, 'tabbed_canvases_enabled', False):
            return
        if page_index < 0 or page_index >= len(self.pages):
            return
        src = self.pages[page_index]
        src_pixmap = src.get("pixmap")
        if src_pixmap is None or src_pixmap.isNull():
            return

        new_pixmap = src_pixmap.copy()
        new_mosaic = self.generate_mosaic(new_pixmap)
        new_items = self._deep_copy_items(src.get("items", []))
        new_history = [(self._deep_copy_items(new_items), new_pixmap)]

        new_page = self._create_page(new_pixmap, new_mosaic, new_items, new_history)
        insert_at = page_index + 1
        self.pages.insert(insert_at, new_page)

        logger.info(f"Canvas page cloned: from={page_index} to={insert_at}, pages={len(self.pages)}")

        self._set_active_page(insert_at)
        self._sync_page_tabs()

    def delete_canvas_page(self, page_index: int):
        if not getattr(self, 'tabbed_canvases_enabled', False):
            return
        if page_index < 0 or page_index >= len(self.pages):
            return
        if len(self.pages) <= 1:
            logger.info("Delete last page requested -> clear current page instead")
            self.clear_canvas()
            return

        self.pages.pop(page_index)
        logger.info(f"Canvas page deleted: index={page_index}, pages={len(self.pages)}")

        new_active = self.active_page_index
        if page_index == self.active_page_index:
            new_active = min(page_index, len(self.pages) - 1)
        elif page_index < self.active_page_index:
            new_active = max(0, self.active_page_index - 1)

        self._set_active_page(new_active)
        self._sync_page_tabs()

    def _scroll_to_page(self, page_index: int):
        if not hasattr(self, 'scroll_area'):
            return
        if page_index < 0:
            return
        if not self._page_layout_cache:
            self._update_canvas_widget_min_height()
        for info in self._page_layout_cache:
            if info["index"] == page_index:
                y = max(0, info["rect"].top() - 20)
                try:
                    self.scroll_area.verticalScrollBar().setValue(int(y))
                except Exception:
                    pass
                return

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

    def _draw_hand_drawn_rect(self, painter, rect, seed=None, radius=0):
        rng = random.Random(seed) if seed is not None else random
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        
        # Handle small rectangles
        if w < 2 * radius: radius = w / 2
        if h < 2 * radius: radius = h / 2
        
        # If radius is 0, we draw a sharp hand-drawn rect (4 lines)
        if radius <= 0:
             # Top
             self._draw_hand_drawn_line(painter, QPointF(x, y), QPointF(x+w, y), rng.randint(0, 99999))
             # Right
             self._draw_hand_drawn_line(painter, QPointF(x+w, y), QPointF(x+w, y+h), rng.randint(0, 99999))
             # Bottom
             self._draw_hand_drawn_line(painter, QPointF(x+w, y+h), QPointF(x, y+h), rng.randint(0, 99999))
             # Left
             self._draw_hand_drawn_line(painter, QPointF(x, y+h), QPointF(x, y), rng.randint(0, 99999))
             return

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
        t = item.get('type')
        if not t: return

        painter.save()
        try:
            painter.setOpacity(item.get('opacity', 1.0))

            if t == 'pen':
                if 'path' not in item: return
                pen = QPen(item.get('color', Qt.black), item.get('width', 3), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(item['path'])
                
            elif t == 'mosaic':
                if 'path' not in item: return
                painter.setPen(Qt.NoPen)
                brush = QBrush(self.mosaic_pixmap)
                # Align brush pattern
                painter.setBrushOrigin(0, 0)
                painter.setBrush(brush)
                
                # Draw the path with a thick stroke turned into a fill
                path = item['path']
                stroker = QPainterPathStroker()
                stroker.setWidth(item.get('width', 15))
                stroker.setCapStyle(Qt.RoundCap)
                stroker.setJoinStyle(Qt.RoundJoin)
                fill_path = stroker.createStroke(path)
                
                painter.drawPath(fill_path)
                
            elif t == 'text':
                if 'text' not in item or 'pos' not in item: return
                font = item.get('font', QFont())
                color = item.get('color', Qt.black)
                
                painter.setFont(font)
                painter.setPen(color)
                
                lines = item['text'].split('\n')
                fm = QFontMetrics(font)
                line_height = fm.lineSpacing()
                
                y = item['pos'].y()
                x = item['pos'].x()
                
                for i, line in enumerate(lines):
                    painter.drawText(QPointF(x, y + i * line_height), line)
                    
            elif t == 'step_marker':
                if 'pos' not in item: return
                num = item.get('number', 1)
                center = item['pos']
                color = item.get('color', Qt.red)
                font_size = item.get('font_size', 24)
                width = item.get('width', 3)
                
                radius = max(15, font_size * 0.8)
                
                # Draw hollow circle
                pen = QPen(color, width)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush) # Transparent fill
                painter.drawEllipse(center, radius, radius)
                
                # Draw text in the same color as the circle
                painter.setPen(color)
                font = QFont()
                font.setBold(True)
                font.setPixelSize(int(radius * 1.2))
                painter.setFont(font)
                
                rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
                painter.drawText(rect, Qt.AlignCenter, str(num))

                
            elif t in ['rect', 'circle', 'line', 'arrow']:
                if 'start' not in item or 'end' not in item: return
                start_pos = item['start']
                end_pos = item['end']
                color = item.get('color', Qt.black)
                width = item.get('width', 3)
                style = item.get('style', 'normal')
                
                # Common pen setup
                pen = QPen(color, width)
                if item.get('stroke_style') == 2:
                    pen.setStyle(Qt.DashLine)
                elif item.get('stroke_style') == 3:
                    pen.setStyle(Qt.DotLine)
                else:
                    pen.setStyle(Qt.SolidLine)
                    
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                
                if t == 'line':
                    if style == 'hand_drawn':
                        self._draw_hand_drawn_line(painter, start_pos, end_pos, item.get('seed'))
                    else:
                        painter.drawLine(start_pos, end_pos)
                        
                elif t == 'arrow':
                    # Draw line
                    if style == 'hand_drawn':
                        self._draw_hand_drawn_line(painter, start_pos, end_pos, item.get('seed'))
                    else:
                        painter.drawLine(start_pos, end_pos)
                    
                    # Draw Arrow head
                    # Calculate angle
                    line = QLineF(start_pos, end_pos)
                    angle = math.radians(line.angle()) # QLineF.angle() returns degrees, math functions need radians
                    
                    head_size = width * 4 + 10
                    arrow_angle = math.radians(30) # 30 degrees
                    
                    # Arrow head calculation using scalar math to avoid QPoint operator issues
                    # QLineF angle is in degrees, 0 at 3 o'clock, CCW.
                    # Screen coordinates: Y is down.
                    # To convert math angle to screen vector: x = r*cos(a), y = -r*sin(a)
                    
                    # We want arrow wings pointing back from end_pos.
                    # Base angle is line angle. Backwards is +180 deg.
                    # Wings are +/- 30 deg from backwards.
                    
                    base_angle_rad = angle + math.pi # 180 degrees in radians
                    
                    # Wing 1
                    a1 = base_angle_rad + arrow_angle
                    dx1 = head_size * math.cos(a1)
                    dy1 = -head_size * math.sin(a1)
                    arrow_p1 = QPointF(end_pos.x() + dx1, end_pos.y() + dy1)
                    
                    # Wing 2
                    a2 = base_angle_rad - arrow_angle
                    dx2 = head_size * math.cos(a2)
                    dy2 = -head_size * math.sin(a2)
                    arrow_p2 = QPointF(end_pos.x() + dx2, end_pos.y() + dy2)

                                                
                    if style == 'hand_drawn':
                        self._draw_hand_drawn_line(painter, end_pos, arrow_p1, item.get('seed', 0) + 1)
                        self._draw_hand_drawn_line(painter, end_pos, arrow_p2, item.get('seed', 0) + 2)
                    else:
                        painter.drawLine(end_pos, arrow_p1)
                        painter.drawLine(end_pos, arrow_p2)
                        
                elif t in ['rect', 'circle']:
                    rect = QRectF(start_pos, end_pos).normalized()
                    
                    # Fill
                    fill_color = item.get('fill_color', Qt.transparent)
                    fill_style = item.get('fill_style', 'solid')
                    
                    brush = QBrush(Qt.NoBrush)
                    if fill_color != Qt.transparent:
                        if fill_style == 'solid':
                            brush = QBrush(fill_color)
                        elif fill_style == 'hatch':
                            brush = QBrush(fill_color, Qt.DiagCrossPattern)
                        elif fill_style == 'cross':
                            brush = QBrush(fill_color, Qt.CrossPattern)
                            
                    painter.setBrush(brush)
                    
                    if t == 'rect':
                        radius = item.get('radius', 0)
                        if style == 'hand_drawn':
                            # Hand drawn rect doesn't support fill perfectly yet, but we can try
                            # For now, if filled, draw normal filled rect behind, then hand drawn outline?
                            # Or just draw hand drawn outline.
                            # Existing implementation handles outline only.
                            if fill_color != Qt.transparent:
                                # Draw filled rect first without border
                                painter.setPen(Qt.NoPen)
                                if radius > 0:
                                    painter.drawRoundedRect(rect, radius, radius)
                                else:
                                    painter.drawRect(rect)
                                painter.setPen(pen)
                                
                            self._draw_hand_drawn_rect(painter, rect, item.get('seed'), radius)
                        else:
                            if radius > 0:
                                painter.drawRoundedRect(rect, radius, radius)
                            else:
                                painter.drawRect(rect)
                                
                    elif t == 'circle':
                        if style == 'hand_drawn':
                            if fill_color != Qt.transparent:
                                painter.setPen(Qt.NoPen)
                                painter.drawEllipse(rect)
                                painter.setPen(pen)
                            self._draw_hand_drawn_ellipse(painter, rect, item.get('seed'))
                        else:
                            painter.drawEllipse(rect)
                            
            elif t == 'image':
                if 'pixmap' not in item or 'rect' not in item: return
                
                rect = item['rect']
                pix = item['pixmap']
                
                # Apply radius if needed (complex for image, skip for now or use clip)
                radius = item.get('radius', 0)
                if radius > 0:
                    painter.save()
                    path = QPainterPath()
                    path.addRoundedRect(rect, radius, radius)
                    painter.setClipPath(path)
                    painter.drawPixmap(rect.toRect(), pix)
                    painter.restore()
                else:
                    painter.drawPixmap(rect.toRect(), pix)
                    
        except Exception as e:
            logger.error(f"Error drawing item {t}: {e}")
        finally:
            painter.restore()

    def draw_selection_overlay(self, painter):
        if self.selected_item_index == -1 or self.selected_item_index >= len(self.items):
            return
        
        item = self.items[self.selected_item_index]
        if item['type'] != 'image': return
        
        rect = item['rect']
        
        # Draw bounding box
        painter.setPen(QPen(Qt.blue, 1, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)
        
        # Draw handles
        handle_size = 10
        half = handle_size / 2
        
        handles = [
            rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight(),
            QPointF(rect.center().x(), rect.top()), # Top middle
            QPointF(rect.center().x(), rect.bottom()), # Bottom middle
            QPointF(rect.left(), rect.center().y()), # Left middle
            QPointF(rect.right(), rect.center().y()) # Right middle
        ]
        
        painter.setPen(QPen(Qt.blue, 1))
        painter.setBrush(Qt.white)
        
        for p in handles:
            painter.drawRect(QRectF(p.x() - half, p.y() - half, handle_size, handle_size))

    def draw_region_selection_overlay(self, painter):
        if not self.region_select_rect:
            return
        try:
            rect = self.region_select_rect.normalized()
            if rect.width() < 2 or rect.height() < 2:
                return
            painter.save()
            pen = QPen(QColor(0, 122, 255))
            pen.setStyle(Qt.DashLine)
            if getattr(self, "mode", None) == "standalone":
                zl = getattr(self, "zoom_level", 1.0) or 1.0
                pen.setWidthF(1.0 / max(0.1, float(zl)))
            else:
                pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            painter.restore()
        except Exception as e:
            logger.error(f"Error drawing region selection overlay: {e}", exc_info=True)
            try:
                painter.restore()
            except Exception:
                pass

    def hit_test_handles(self, pos):
        if self.selected_item_index == -1 or self.selected_item_index >= len(self.items):
            return -1
        
        item = self.items[self.selected_item_index]
        if item['type'] != 'image': return -1
        
        rect = item['rect']
        # Increase handle size to match the hover threshold (40)
        # However, drawing rect should be smaller. We only change hit test size.
        handle_size = 40 
        half = handle_size / 2
        
        handles = [
            rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight(),
            QPointF(rect.center().x(), rect.top()), 
            QPointF(rect.center().x(), rect.bottom()), 
            QPointF(rect.left(), rect.center().y()), 
            QPointF(rect.right(), rect.center().y()) 
        ]
        
        # 0: TL, 1: TR, 2: BL, 3: BR, 4: TM, 5: BM, 6: LM, 7: RM
        
        for i, p in enumerate(handles):
            r = QRectF(p.x() - half, p.y() - half, handle_size, handle_size)
            if r.contains(pos):
                return i
        return -1

    def resize_item(self, index, handle, pos, modifiers=None):
        if index < 0 or index >= len(self.items):
            return
        item = self.items[index]
        rect = item['rect']
        
        # Original aspect ratio
        orig_ratio = rect.width() / rect.height() if rect.height() > 0 else 1.0
        
        # 0: TL, 1: TR, 2: BL, 3: BR, 4: TM, 5: BM, 6: LM, 7: RM
        
        l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
        
        keep_aspect = modifiers and (modifiers & Qt.ShiftModifier)
        
        if keep_aspect and handle in [0, 1, 2, 3]:
            # Corner resizing with aspect ratio
            if handle == 0: # TL, anchor BR
                curr_w = r - pos.x()
                curr_h = b - pos.y()
                # Use max dimension to drive
                if curr_w / orig_ratio > curr_h:
                    height = curr_w / orig_ratio
                    t = b - height
                    l = pos.x()
                else:
                    width = curr_h * orig_ratio
                    l = r - width
                    t = pos.y()
                    
            elif handle == 1: # TR, anchor BL
                curr_w = pos.x() - l
                curr_h = b - pos.y()
                if curr_w / orig_ratio > curr_h:
                    height = curr_w / orig_ratio
                    t = b - height
                    r = pos.x()
                else:
                    width = curr_h * orig_ratio
                    r = l + width
                    t = pos.y()
                    
            elif handle == 2: # BL, anchor TR
                curr_w = r - pos.x()
                curr_h = pos.y() - t
                if curr_w / orig_ratio > curr_h:
                    height = curr_w / orig_ratio
                    b = t + height
                    l = pos.x()
                else:
                    width = curr_h * orig_ratio
                    l = r - width
                    b = pos.y()
                    
            elif handle == 3: # BR, anchor TL
                curr_w = pos.x() - l
                curr_h = pos.y() - t
                if curr_w / orig_ratio > curr_h:
                    height = curr_w / orig_ratio
                    b = t + height
                    r = pos.x()
                else:
                    width = curr_h * orig_ratio
                    r = l + width
                    b = pos.y()
                    
        else:
            # Normal resize
            if handle == 0: # TL
                l, t = pos.x(), pos.y()
            elif handle == 1: # TR
                r, t = pos.x(), pos.y()
            elif handle == 2: # BL
                l, b = pos.x(), pos.y()
            elif handle == 3: # BR
                r, b = pos.x(), pos.y()
            elif handle == 4: # TM
                t = pos.y()
            elif handle == 5: # BM
                b = pos.y()
            elif handle == 6: # LM
                l = pos.x()
            elif handle == 7: # RM
                r = pos.x()
            
        # Normalize and constraint
        new_rect = QRectF(QPointF(l, t), QPointF(r, b)).normalized()
        
        # Min size
        if new_rect.width() < 10: new_rect.setWidth(10)
        if new_rect.height() < 10: new_rect.setHeight(10)
        
        item['rect'] = new_rect

    def paintEvent(self, event):
        if self.mode == 'standalone':
            # We don't paint on self in standalone mode, we paint on canvas_widget via eventFilter
            return
            
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.original_pixmap)
        
        # Draw all committed items
        for item in self.items:
            self._draw_single_item(painter, item)
            
        # Draw Selection Overlay
        self.draw_selection_overlay(painter)
        self.draw_region_selection_overlay(painter)
            
        # Draw Crop Overlay
        if self.current_tool == 'crop' and self.crop_rect:
            self.draw_crop_overlay(painter)
            
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
        
        # Wing 1
        dx1 = arrow_len * math.cos(angle + arrow_angle)
        dy1 = arrow_len * math.sin(angle + arrow_angle)
        p1 = QPointF(end.x() + dx1, end.y() + dy1)
        
        # Wing 2
        dx2 = arrow_len * math.cos(angle - arrow_angle)
        dy2 = arrow_len * math.sin(angle - arrow_angle)
        p2 = QPointF(end.x() + dx2, end.y() + dy2)

        
        if hand_drawn:
            self._draw_hand_drawn_line(painter, end, p1, rng.randint(0, 99999))
            self._draw_hand_drawn_line(painter, end, p2, rng.randint(0, 99999))
        else:
            painter.drawLine(end, p1)
            painter.drawLine(end, p2)

    def hit_test(self, pos):
        # Reverse iterate to hit top-most items first
        for i in range(len(self.items) - 1, -1, -1):
            item = self.items[i]
            t = item['type']
            if t in ['rect', 'circle']:
                r = QRectF(item['start'], item['end']).normalized()
                if r.contains(pos): return i
            elif t == 'text':
                if 'font' not in item or 'text' not in item: continue
                fm = QFontMetrics(item['font'])
                lines = item['text'].split('\n')
                
                # Calculate bounding rect for multiline text
                max_w = 0
                for line in lines:
                    w = fm.horizontalAdvance(line)
                    if w > max_w: max_w = w
                
                line_height = fm.lineSpacing()
                total_h = len(lines) * line_height
                
                # Bounding rect starts at item['pos'] but adjusting for baseline
                # item['pos'] is roughly the baseline of the first line. 
                # QPainter.drawText(pos, text) draws text where pos is the baseline origin.
                # However, for boundingRect(text), it returns rect relative to (0,0) baseline.
                # We need to construct the full rect.
                
                # Top-left of the text block
                # ascent() is distance from baseline to top
                top_y = item['pos'].y() - fm.ascent()
                
                r = QRectF(item['pos'].x(), top_y, max_w, total_h)
                r.adjust(-5, -5, 5, 5) # Margin
                
                if r.contains(pos): return i
            elif t == 'step_marker':
                center = item['pos']
                font_size = item.get('font_size', 24)
                radius = max(15, font_size * 0.8)
                r = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
                if r.contains(pos): return i
            elif t in ['line', 'arrow']:
                # Simple bounding box for now
                p1 = item['start']
                p2 = item['end']
                r = QRectF(p1, p2).normalized().adjusted(-5,-5,5,5)
                if r.contains(pos): return i
            elif t in ['pen', 'mosaic']:
                path = item['path']
                stroker = QPainterPathStroker()
                stroker.setWidth(max(10, item.get('width', 10)))
                boundary = stroker.createStroke(path)
                if boundary.contains(pos): return i
            elif t == 'image':
                if item['rect'].contains(pos): return i
        return -1

    def calculate_snap_rect(self, index, target_rect):
        """
        Calculate snapped rect for the item at index based on target_rect.
        Returns (snapped_rect, guides)
        """
        if index < 0 or index >= len(self.items):
            return target_rect, []
        
        guides = []
        snap_threshold = 6 / self.zoom_level # Visual threshold
        
        # Edges of target
        t_left = target_rect.left()
        t_right = target_rect.right()
        t_top = target_rect.top()
        t_bottom = target_rect.bottom()
        t_cx = target_rect.center().x()
        t_cy = target_rect.center().y()
        
        snap_x = 0
        snap_y = 0
        min_dist_x = snap_threshold + 1
        min_dist_y = snap_threshold + 1
        
        # Iterate other items
        for i, other in enumerate(self.items):
            if i == index or other['type'] != 'image':
                continue
            
            o_rect = other['rect']
            o_left = o_rect.left()
            o_right = o_rect.right()
            o_top = o_rect.top()
            o_bottom = o_rect.bottom()
            o_cx = o_rect.center().x()
            o_cy = o_rect.center().y()
            
            # X Alignment Checks
            x_checks = [
                (t_left, o_left), (t_left, o_right), (t_left, o_cx),
                (t_right, o_left), (t_right, o_right), (t_right, o_cx),
                (t_cx, o_left), (t_cx, o_right), (t_cx, o_cx)
            ]
            
            for t_val, o_val in x_checks:
                dist = t_val - o_val
                if abs(dist) < min_dist_x:
                    min_dist_x = abs(dist)
                    snap_x = -dist
            
            # Y Alignment Checks
            y_checks = [
                (t_top, o_top), (t_top, o_bottom), (t_top, o_cy),
                (t_bottom, o_top), (t_bottom, o_bottom), (t_bottom, o_cy),
                (t_cy, o_top), (t_cy, o_bottom), (t_cy, o_cy)
            ]
            
            for t_val, o_val in y_checks:
                dist = t_val - o_val
                if abs(dist) < min_dist_y:
                    min_dist_y = abs(dist)
                    snap_y = -dist
        
        # Apply snap
        snapped_rect = QRectF(target_rect)
        
        if min_dist_x <= snap_threshold:
            snapped_rect.translate(snap_x, 0)
            
        if min_dist_y <= snap_threshold:
            snapped_rect.translate(0, snap_y)
            
        # Generate guides based on snapped rect
        f_left = snapped_rect.left()
        f_right = snapped_rect.right()
        f_top = snapped_rect.top()
        f_bottom = snapped_rect.bottom()
        f_cx = snapped_rect.center().x()
        f_cy = snapped_rect.center().y()
        
        epsilon = 0.5 
        
        for i, other in enumerate(self.items):
            if i == index or other['type'] != 'image':
                continue
            
            o_rect = other['rect']
            o_left = o_rect.left()
            o_right = o_rect.right()
            o_top = o_rect.top()
            o_bottom = o_rect.bottom()
            o_cx = o_rect.center().x()
            o_cy = o_rect.center().y()
            
            # Vertical Lines (X matches)
            if abs(f_left - o_left) < epsilon: guides.append(QLineF(f_left, min(f_top, o_top), f_left, max(f_bottom, o_bottom)))
            if abs(f_left - o_right) < epsilon: guides.append(QLineF(f_left, min(f_top, o_top), f_left, max(f_bottom, o_bottom)))
            if abs(f_left - o_cx) < epsilon: guides.append(QLineF(f_left, min(f_top, o_top), f_left, max(f_bottom, o_bottom)))
            
            if abs(f_right - o_left) < epsilon: guides.append(QLineF(f_right, min(f_top, o_top), f_right, max(f_bottom, o_bottom)))
            if abs(f_right - o_right) < epsilon: guides.append(QLineF(f_right, min(f_top, o_top), f_right, max(f_bottom, o_bottom)))
            if abs(f_right - o_cx) < epsilon: guides.append(QLineF(f_right, min(f_top, o_top), f_right, max(f_bottom, o_bottom)))
            
            if abs(f_cx - o_left) < epsilon: guides.append(QLineF(f_cx, min(f_top, o_top), f_cx, max(f_bottom, o_bottom)))
            if abs(f_cx - o_right) < epsilon: guides.append(QLineF(f_cx, min(f_top, o_top), f_cx, max(f_bottom, o_bottom)))
            if abs(f_cx - o_cx) < epsilon: guides.append(QLineF(f_cx, min(f_top, o_top), f_cx, max(f_bottom, o_bottom)))

            # Horizontal Lines (Y matches)
            if abs(f_top - o_top) < epsilon: guides.append(QLineF(min(f_left, o_left), f_top, max(f_right, o_right), f_top))
            if abs(f_top - o_bottom) < epsilon: guides.append(QLineF(min(f_left, o_left), f_top, max(f_right, o_right), f_top))
            if abs(f_top - o_cy) < epsilon: guides.append(QLineF(min(f_left, o_left), f_top, max(f_right, o_right), f_top))

            if abs(f_bottom - o_top) < epsilon: guides.append(QLineF(min(f_left, o_left), f_bottom, max(f_right, o_right), f_bottom))
            if abs(f_bottom - o_bottom) < epsilon: guides.append(QLineF(min(f_left, o_left), f_bottom, max(f_right, o_right), f_bottom))
            if abs(f_bottom - o_cy) < epsilon: guides.append(QLineF(min(f_left, o_left), f_bottom, max(f_right, o_right), f_bottom))
            
            if abs(f_cy - o_top) < epsilon: guides.append(QLineF(min(f_left, o_left), f_cy, max(f_right, o_right), f_cy))
            if abs(f_cy - o_bottom) < epsilon: guides.append(QLineF(min(f_left, o_left), f_cy, max(f_right, o_right), f_cy))
            if abs(f_cy - o_cy) < epsilon: guides.append(QLineF(min(f_left, o_left), f_cy, max(f_right, o_right), f_cy))

        return snapped_rect, guides

    def move_item(self, index, delta):
        if index < 0 or index >= len(self.items):
            return
        item = self.items[index]
        t = item['type']
        dx = delta.x()
        dy = delta.y()
        
        if t in ['rect', 'circle', 'line', 'arrow']:
            # Scalar addition for safety
            s = item['start']
            e = item['end']
            item['start'] = QPointF(s.x() + dx, s.y() + dy)
            item['end'] = QPointF(e.x() + dx, e.y() + dy)
        elif t == 'text':
            p = item['pos']
            item['pos'] = QPointF(p.x() + dx, p.y() + dy)
        elif t == 'step_marker':
            p = item['pos']
            item['pos'] = QPointF(p.x() + dx, p.y() + dy)
        elif t in ['pen', 'mosaic']:
            item['path'].translate(dx, dy)
        elif t == 'image':
            item['rect'].translate(dx, dy)


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
            delta = event.angleDelta().y()
            if delta == 0:
                return
            canvas = self.canvas_widget if hasattr(self, 'canvas_widget') else self
            img_h = self.original_pixmap.height()
            scaled_h = int(img_h * self.zoom_level)
            ch = canvas.height()
            if scaled_h <= ch:
                return
            center_y = (ch - scaled_h) // 2
            step = int((delta / 120) * 80)
            new_offset_y = self.view_offset.y() + step
            min_offset_y = (ch - scaled_h) - center_y
            max_offset_y = 0 - center_y
            if new_offset_y < min_offset_y:
                new_offset_y = min_offset_y
            if new_offset_y > max_offset_y:
                new_offset_y = max_offset_y
            if new_offset_y != self.view_offset.y():
                self.view_offset = QPoint(self.view_offset.x(), new_offset_y)
                logger.info(f"Canvas wheel scroll applied: offset_y={new_offset_y}, scaled_h={scaled_h}, canvas_h={ch}")
                self.refresh_canvas()
            return

    def map_pos(self, pos):
        self._last_mapped_valid = False
        self._last_mapped_page_index = None

        if getattr(self, 'mode', None) == 'standalone' and getattr(self, 'multi_page_enabled', False) and not getattr(self, 'tabbed_canvases_enabled', False):
            if not self._page_layout_cache:
                self._update_canvas_widget_min_height()
            for info in self._page_layout_cache:
                rect = info["rect"]
                if rect.contains(pos):
                    idx = info["index"]
                    self._last_mapped_valid = True
                    self._last_mapped_page_index = idx
                    if self.active_page_index != idx:
                        self._set_active_page(idx)
                    self.canvas_offset = rect.topLeft()
                    off_x = pos.x() - rect.x()
                    off_y = pos.y() - rect.y()
                    return QPointF(off_x / self.zoom_level, off_y / self.zoom_level)
            return QPointF(-1000000, -1000000)

        if getattr(self, 'mode', None) == 'standalone' and hasattr(self, 'canvas_offset'):
            off_x = pos.x() - self.canvas_offset.x()
            off_y = pos.y() - self.canvas_offset.y()
            return QPointF(off_x / self.zoom_level, off_y / self.zoom_level)
        return QPointF(pos)


    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
             local_pos = self.map_pos(event.pos())
             if getattr(self, 'multi_page_enabled', False) and not getattr(self, 'tabbed_canvases_enabled', False) and getattr(self, '_last_mapped_valid', False) is False:
                 return
             
             # Confirm crop on double click inside
             if self.current_tool == 'crop':
                 if self.crop_rect and self.crop_rect.contains(local_pos):
                     self.apply_crop()
                 return

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
        # Debug Logging for Properties Panel Logic
        if self.mode == 'standalone':
            global_pos = event.globalPos()
            local_in_editor = self.mapFromGlobal(global_pos)
            
            logger.info(f"MousePress: Global={global_pos}, LocalInEditor={local_in_editor}")
            
            if self.prop_panel.isVisible():
                # prop_panel is Qt.Tool, so geometry() is in global screen coordinates
                prop_rect = self.prop_panel.geometry()
                logger.info(f"Prop Panel Geometry: {prop_rect}")
                
                if prop_rect.contains(global_pos):
                    logger.info("Click inside Properties Panel -> Ignore")
                    return

            child = self.childAt(local_in_editor)
            logger.info(f"Child at {local_in_editor}: {child}")
            
            if child and hasattr(self, 'canvas_widget') and child != self.canvas_widget:
                logger.info("Click on UI element -> Ignore")
                # Also allow clicking on active text editor if it exists
                if not (hasattr(self, 'active_text_editor') and child == self.active_text_editor):
                    return

        try:
            self.setFocus() # Ensure widget gets key events
            if event.button() == Qt.LeftButton:
                self.last_mouse_pos = event.globalPos()
                local_pos = self.map_pos(event.pos())
                if getattr(self, 'multi_page_enabled', False) and not getattr(self, 'tabbed_canvases_enabled', False) and getattr(self, '_last_mapped_valid', False) is False:
                    return
                
                if self.current_tool == 'crop':
                    logger.info(f"Mouse Press in Crop Mode: local_pos={local_pos}")
                    try:
                        self.crop_handle_index = self.hit_test_crop(local_pos)
                    except Exception as e:
                        logger.error(f"Error in hit_test_crop: {e}", exc_info=True)
                        self.crop_handle_index = -1 # Fallback
                    
                    logger.info(f"Crop handle index: {self.crop_handle_index}")
                    
                    # Check current crop rect status
                    is_full_image = False
                    if self.crop_rect:
                        try:
                            w, h = self.original_pixmap.width(), self.original_pixmap.height()
                            # logger.info(f"Crop Rect: {self.crop_rect}, Image: {w}x{h}")
                            if self.crop_rect.width() * self.crop_rect.height() >= w * h * 0.95:
                                is_full_image = True
                                logger.info("Detected full image crop")
                        except Exception as e:
                            logger.error(f"Error checking full image: {e}")

                    if self.crop_handle_index != -1 and self.crop_handle_index != 8: # Resize handles
                        logger.info("Action: Resize Crop")
                        self.is_moving_crop = True
                        self.crop_start_pos = local_pos
                        self.crop_start_rect = QRectF(self.crop_rect)
                    elif self.crop_handle_index == 8 and not is_full_image: # Move body
                        logger.info("Action: Move Crop Body")
                        self.is_moving_crop = True
                        self.crop_start_pos = local_pos
                        self.crop_start_rect = QRectF(self.crop_rect)
                        # We treat body move as resize/move, handled in update_crop_rect
                    else:
                        logger.info("Action: Create New Crop")
                        # Clicked outside handles, or inside full image -> Start creating new crop rect
                        self.is_creating_crop = True
                        self.crop_start_pos = local_pos
                        self.crop_rect = QRectF(local_pos, QSizeF(0, 0))
                        self.refresh_canvas()
                    return

                if self.current_tool == 'select':
                    self.selected_item_index = -1
                    self.prop_panel.clear_ui()
                    self.prop_panel.hide()
                    self.is_region_selecting = True
                    self.region_select_start = QPointF(local_pos)
                    self.region_select_rect = QRectF(self.region_select_start, self.region_select_start)
                    logger.info(f"Region selection started: {self.region_select_start}")
                    self.refresh_canvas()
                    return

                if self.current_tool == 'move':
                    # Check for resize handles first
                    handle = self.hit_test_handles(local_pos)
                    if handle != -1:
                        self.resize_handle = handle
                        self.is_resizing_item = True
                        return

                    # 检查是否点击了已有的图形元素
                    idx = self.hit_test(local_pos)
                    if idx != -1:
                        self.selected_item_index = idx
                        
                        # Initialize drag start state for absolute snapping logic (Fixes sticky snap issue)
                        if self.mode == 'standalone':
                            item = self.items[idx]
                            if item['type'] == 'image':
                                self.drag_start_item_rect = QRectF(item['rect'])
                                self.drag_start_mouse_pos = event.globalPos()
                        
                        # Show prop panel only in standalone mode (Smart Board)
                        if self.mode == 'standalone':
                            item = self.items[idx]
                            self.prop_panel.update_ui(item)
                            self.prop_panel.show()
                            self.update_toolbar_pos()
                        else:
                            # In screenshot mode, hide it just in case
                            self.prop_panel.hide()
                            
                        self.setCursor(Qt.SizeAllCursor)
                        self.refresh_canvas()
                    else:
                        # Clicked on background
                        self.selected_item_index = -1
                        self.prop_panel.clear_ui() # Ensure cleared before hide
                        self.prop_panel.hide()
                            
                        self.refresh_canvas()
                        # 如果没点中元素，且不是独立模式，则拖动窗口
                        if self.mode != 'standalone':
                            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                        else:
                            # 独立模式下：空闲状态拖动也平移画布
                            # 我们不在这里移动，而是在 mouseMoveEvent 中处理
                            # 但是需要重置 last_mouse_pos，这已经在前面做了
                            pass
                
                elif self.current_tool:
                    # Ensure prop panel is hidden when starting to draw
                    self.prop_panel.clear_ui() # Ensure cleared before hide
                    self.prop_panel.hide()
                    
                    # 开始绘制新图形
                    self.is_drawing = True
                    
                    if self.current_tool == 'laser':
                        self.laser_points = [{'pos': local_pos, 'time': time.time()}]
                        self.laser_timer.start()
                        return
                    self.start_pos = local_pos
                    self.end_pos = local_pos
                    if self.current_tool in ['pen', 'mosaic']:
                        self.current_path = QPainterPath(self.start_pos)
                    elif self.current_tool == 'text':
                        self.add_text(local_pos)
                        self.is_drawing = False

                    elif self.current_tool == 'step_marker':
                        # Calculate next number
                        existing_numbers = [item['number'] for item in self.items if item.get('type') == 'step_marker']
                        next_num = 1
                        if existing_numbers:
                            next_num = max(existing_numbers) + 1
                        
                        item = {
                            'type': 'step_marker',
                            'pos': local_pos,
                            'number': next_num,
                            'color': self.pen_color,
                            'width': self.pen_width,
                            'style': self.drawing_style,
                            'font_size': self.font_size,
                            'seed': random.randint(0, 100000)
                        }
                        self.items.append(item)
                        self.save_state()
                        self.refresh_canvas()
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
        except Exception as e:
            logger.error(f"Error in mousePressEvent: {e}", exc_info=True)

    def get_constrained_pos(self, current_pos):
        if self.current_tool != 'rect' or self.rect_ratio is None:
            return current_pos
            
        dx = current_pos.x() - self.start_pos.x()
        dy = current_pos.y() - self.start_pos.y()
        
        if abs(dx) < 1: dx = 1 if dx >= 0 else -1
        if abs(dy) < 1: dy = 1 if dy >= 0 else -1
        
        current_ratio = abs(dx) / abs(dy)
        
        target_dx = dx
        target_dy = dy
        
        if current_ratio > self.rect_ratio:
            # Width dominant, adjust height
            target_dy = abs(dx) / self.rect_ratio * (1 if dy >= 0 else -1)
        else:
            # Height dominant, adjust width
            target_dx = abs(dy) * self.rect_ratio * (1 if dx >= 0 else -1)
            
        return QPointF(self.start_pos.x() + target_dx, self.start_pos.y() + target_dy)

    def mouseMoveEvent(self, event):
        # Enable mouse tracking is required for this to fire without buttons pressed,
        # but Qt widgets usually require setMouseTracking(True).
        # We ensure it's on in init.
        
        local_pos = self.map_pos(event.pos())
        if getattr(self, 'multi_page_enabled', False) and not getattr(self, 'tabbed_canvases_enabled', False) and getattr(self, '_last_mapped_valid', False) is False:
            return
        
        # logger.info(f"MouseMove: {local_pos}, Tool: {self.current_tool}, Selected: {self.selected_item_index}")
        
        if getattr(self, 'is_resizing_item', False):
            self.resize_item(self.selected_item_index, self.resize_handle, local_pos, event.modifiers())
            self.refresh_canvas()
            return

        if self.current_tool == 'crop':
            if self.is_moving_crop:
                self.update_crop_rect(local_pos)
            elif getattr(self, 'is_creating_crop', False):
                # Creating new crop rect
                
                # Apply ratio if needed
                if self.crop_ratio is not None:
                     dx = local_pos.x() - self.crop_start_pos.x()
                     dy = local_pos.y() - self.crop_start_pos.y()
                     
                     # Avoid division by zero
                     if abs(dx) < 1: dx = 1 if dx >= 0 else -1
                     if abs(dy) < 1: dy = 1 if dy >= 0 else -1
                     
                     current_ratio = abs(dx) / abs(dy)
                     if current_ratio > self.crop_ratio:
                         # Width dominant, adjust height
                         target_h = abs(dx) / self.crop_ratio
                         dy = target_h * (1 if dy >= 0 else -1)
                     else:
                         # Height dominant, adjust width
                         target_w = abs(dy) * self.crop_ratio
                         dx = target_w * (1 if dx >= 0 else -1)
                         
                     local_pos = QPointF(self.crop_start_pos.x() + dx, self.crop_start_pos.y() + dy)
                
                rect = QRectF(self.crop_start_pos, local_pos).normalized()
                # Constrain to image
                img_w, img_h = self.original_pixmap.width(), self.original_pixmap.height()
                rect = rect.intersected(QRectF(0, 0, img_w, img_h))
                self.crop_rect = rect
            else:
                # Update cursor based on hover
                handle = self.hit_test_crop(local_pos)
                
                is_full_image = False
                if self.crop_rect:
                    w, h = self.original_pixmap.width(), self.original_pixmap.height()
                    if self.crop_rect.width() >= w - 1 and self.crop_rect.height() >= h - 1:
                        is_full_image = True
                
                if handle in [0, 2]: self.setCursor(Qt.SizeFDiagCursor)
                elif handle in [1, 3]: self.setCursor(Qt.SizeBDiagCursor)
                elif handle in [4, 6]: self.setCursor(Qt.SizeVerCursor)
                elif handle in [5, 7]: self.setCursor(Qt.SizeHorCursor)
                elif handle == 8: 
                    if is_full_image:
                        self.setCursor(Qt.CrossCursor)
                    else:
                        self.setCursor(Qt.SizeAllCursor)
                else: self.setCursor(Qt.CrossCursor)
            
            self.refresh_canvas()
            return

        if self.current_tool == 'select' and getattr(self, 'is_region_selecting', False):
            try:
                img_w, img_h = self.original_pixmap.width(), self.original_pixmap.height()
                rect = QRectF(self.region_select_start, QPointF(local_pos)).normalized()
                rect = rect.intersected(QRectF(0, 0, img_w, img_h))
                self.region_select_rect = rect
                self.refresh_canvas()
            except Exception as e:
                logger.error(f"Error updating region selection rect: {e}", exc_info=True)
            return

        if self.selected_item_index != -1 and (self.current_tool == 'move' or not self.current_tool):
            # 移动选中的图形元素 - 仅当按下左键时
            if event.buttons() & Qt.LeftButton:
                # 区分模式：如果是独立模式，globalPos 移动量需要除以缩放比例
                delta = event.globalPos() - self.last_mouse_pos
                
                if self.mode == 'standalone':
                    # Use absolute drag logic if state is available (for image snapping)
                    # This prevents the "gravity well" issue where small movements snap back to the same spot.
                    if getattr(self, 'drag_start_item_rect', None) and getattr(self, 'drag_start_mouse_pos', None) and self.items[self.selected_item_index]['type'] == 'image':
                         
                         # Calculate total mouse delta since drag start
                         current_mouse_pos = event.globalPos()
                         total_mouse_delta = current_mouse_pos - self.drag_start_mouse_pos
                         
                         # Convert to logical delta
                         logical_dx = total_mouse_delta.x() / self.zoom_level
                         logical_dy = total_mouse_delta.y() / self.zoom_level
                         
                         # Theoretical Rect (where it would be without snapping)
                         theoretical_rect = self.drag_start_item_rect.translated(logical_dx, logical_dy)
                         
                         final_rect = theoretical_rect
                         self.alignment_guides = []
                         
                         # Apply snapping unless Alt is pressed
                         if not (event.modifiers() & Qt.AltModifier):
                             final_rect, guides = self.calculate_snap_rect(self.selected_item_index, theoretical_rect)
                             self.alignment_guides = guides
                             
                             # Log snap status if moving significantly
                             dist = (theoretical_rect.topLeft() - self.drag_start_item_rect.topLeft()).manhattanLength()
                             if dist > 5:
                                 is_snapped = final_rect != theoretical_rect
                                 # logger.info(f"Drag Dist: {dist:.1f}, Snapped: {is_snapped}")
                         
                         # Update item rect directly
                         self.items[self.selected_item_index]['rect'] = final_rect
                         
                    else:
                        # Fallback to incremental logic
                        dx = delta.x() / self.zoom_level
                        dy = delta.y() / self.zoom_level
                        logical_delta = QPointF(dx, dy)
                        self.move_item(self.selected_item_index, logical_delta)

                else:
                    self.move_item(self.selected_item_index, delta)
                
                self.last_mouse_pos = event.globalPos()
                self.refresh_canvas()
                return
            
        local_pos = self.map_pos(event.pos())
        if getattr(self, 'multi_page_enabled', False) and not getattr(self, 'tabbed_canvases_enabled', False) and getattr(self, '_last_mapped_valid', False) is False:
            return
        
        if self.current_tool == 'move':
            # Check handles for cursor update
            handle = self.hit_test_handles(local_pos)
            if handle != -1:
                # 0: TL, 1: TR, 2: BL, 3: BR
                if handle in [0, 3]: 
                    self.setCursor(Qt.SizeFDiagCursor)
                elif handle in [1, 2]: 
                    self.setCursor(Qt.SizeBDiagCursor)
                elif handle in [4, 5]: # Top/Bottom Middle
                    self.setCursor(Qt.SizeVerCursor)
                elif handle in [6, 7]: # Left/Right Middle
                    self.setCursor(Qt.SizeHorCursor)
                return
            
            # Check if hovering over corners (without clicking) to show resize cursor
            if self.selected_item_index != -1 and not (event.buttons() & Qt.LeftButton):
                item = self.items[self.selected_item_index]
                if item['type'] == 'image':
                    rect = item['rect']
                    # Define corners: TL, TR, BL, BR
                    # Use map_pos to get logical coordinates, but setCursor is screen-independent
                    # The issue is rect is in logical coords, local_pos is in logical coords.
                    # This calculation is correct.
                    # However, if handles are hit tested first, this block might be skipped or vice versa.
                    
                    # But hit_test_handles handles standard handles (blue boxes).
                    # If we are slightly outside the handle but near the corner, we still want the cursor.
                    # Or if hit_test_handles returns -1 (too far from exact handle center), we fallback here.
                    
                    corners = [
                        (rect.topLeft(), Qt.SizeFDiagCursor, "TL"),
                        (rect.topRight(), Qt.SizeBDiagCursor, "TR"),
                        (rect.bottomLeft(), Qt.SizeBDiagCursor, "BL"),
                        (rect.bottomRight(), Qt.SizeFDiagCursor, "BR")
                    ]
                    
                    # Increase threshold to be larger than handle size for better feel
                    hover_threshold = 40 # Increased to 40 for testing
                    
                    # Log rect and distances for debugging
                    # logger.info(f"Checking corners. Rect: {rect}, Mouse: {local_pos}")

                    for p, cursor, name in corners:
                        dist = (QPointF(local_pos) - p).manhattanLength()
                        # logger.info(f"Corner {name} dist: {dist:.2f}")
                        if dist < hover_threshold:
                            # logger.info(f"Setting cursor for corner {name} (dist={dist})")
                            self.setCursor(cursor)
                            return
            
            # Check for hovering over the image body itself
            if self.selected_item_index != -1 and not (event.buttons() & Qt.LeftButton):
                item = self.items[self.selected_item_index]
                if item['type'] == 'image':
                    # Add a small buffer around the rect to make it easier to grab
                    # But don't override corners if they were hit
                    if item['rect'].contains(local_pos):
                         # logger.info("Setting cursor for image body")
                         self.setCursor(Qt.SizeAllCursor)
                         return

            # 悬停效果：如果鼠标在元素上，显示移动光标
            idx = self.hit_test(local_pos)
            if idx != -1:
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.OpenHandCursor)
                
            if event.buttons() & Qt.LeftButton and self.selected_item_index == -1:
                # 拖动窗口（非独立模式下）
                if self.mode != 'standalone':
                    if hasattr(self, 'drag_pos'):
                        self.move(event.globalPos() - self.drag_pos)
                else:
                    # 独立模式下：拖动画布 (Pan)
                    # Use event.pos() diff because globalPos might jitter across widgets
                    # But we need delta. event.globalPos() - self.last_mouse_pos is reliable.
                    if not getattr(self, 'multi_page_enabled', False):
                        delta = event.globalPos() - self.last_mouse_pos
                        self.view_offset += delta
                        self.last_mouse_pos = event.globalPos() # Update last_mouse_pos for smooth panning
                        self.refresh_canvas()

        elif self.is_drawing:
            # 更新正在绘制的图形
            raw_pos = local_pos
            self.end_pos = self.get_constrained_pos(raw_pos)
            
            if self.current_tool in ['pen', 'mosaic']:
                self.current_path.lineTo(self.end_pos)
            elif self.current_tool == 'laser':
                self.laser_points.append({'pos': local_pos, 'time': time.time()})
                # Timer will handle refresh, but manual refresh makes it smoother
                self.refresh_canvas()
            
            self.refresh_canvas()
            
        elif not self.current_tool and event.buttons() & Qt.LeftButton:
            # 拖动窗口
            if self.mode != 'standalone':
                if hasattr(self, 'drag_pos'):
                     self.move(event.globalPos() - self.drag_pos)
            else:
                 # 独立模式下：空闲状态拖动也平移画布
                 if not getattr(self, 'multi_page_enabled', False):
                     delta = event.globalPos() - self.last_mouse_pos
                     self.view_offset += delta
                     self.refresh_canvas()
        
        self.last_mouse_pos = event.globalPos()

    def mouseReleaseEvent(self, event):
        if hasattr(self, 'alignment_guides') and self.alignment_guides:
            self.alignment_guides = []
            self.refresh_canvas()

        if getattr(self, 'is_resizing_item', False):
            self.is_resizing_item = False
            self.save_state()
            return

        if self.current_tool == 'crop':
            self.is_moving_crop = False
            self.is_creating_crop = False
            if self.crop_rect:
                self.crop_rect = self.crop_rect.normalized()
                if self.crop_rect.width() < 10 or self.crop_rect.height() < 10:
                     # Too small, invalid crop
                     self.crop_rect = None
            self.refresh_canvas()
            return

        if self.current_tool == 'select' and getattr(self, 'is_region_selecting', False):
            self.is_region_selecting = False
            try:
                if self.region_select_rect:
                    rect = self.region_select_rect.normalized()
                    if rect.width() < 2 or rect.height() < 2:
                        self.region_select_rect = None
                    else:
                        self.region_select_rect = rect
                logger.info(f"Region selection finalized: {self.region_select_rect}")
                self.refresh_canvas()
            except Exception as e:
                logger.error(f"Error finalizing region selection: {e}", exc_info=True)
                self.region_select_rect = None
                self.refresh_canvas()
            return

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
            raw_pos = self.map_pos(event.pos())
            if getattr(self, 'multi_page_enabled', False) and not getattr(self, 'tabbed_canvases_enabled', False) and getattr(self, '_last_mapped_valid', False) is False:
                return
            self.end_pos = self.get_constrained_pos(raw_pos)
            self.commit_drawing()
            self.refresh_canvas()

    def commit_drawing(self):
        if not self.current_tool: return
        # Text is handled by commit_text_editor, not here.
        if self.current_tool == 'text': return
        # Laser is temporary, never committed
        if self.current_tool == 'laser': return
        
        logger.debug(f"Committing drawing item: {self.current_tool}")
        
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
            # Explicitly copy the path to ensure it persists independently
            # This fixes issues where strokes might disappear under high load (e.g. during recording)
            item['path'] = QPainterPath(self.current_path)
        
        self.items.append(item)
        self.save_state()

    def copy_item(self):
        if self.copy_region_selection_to_clipboard():
            return
        if self.selected_item_index != -1:
            try:
                # Manual deep copy to handle QPixmap and QRectF safely
                item = self.items[self.selected_item_index]
                self.clipboard_item = {}
                for k, v in item.items():
                    if k == 'pixmap':
                        self.clipboard_item[k] = v.copy() # QPixmap.copy()
                    elif k == 'path':
                        self.clipboard_item[k] = QPainterPath(v) # Copy path
                    elif isinstance(v, (QRectF, QPointF, QColor, QRect, QPoint)):
                        # These are value types or copyable
                        import copy
                        self.clipboard_item[k] = copy.copy(v)
                    elif isinstance(v, QFont):
                        self.clipboard_item[k] = QFont(v) # Copy constructor
                    else:
                        import copy
                        self.clipboard_item[k] = copy.deepcopy(v)
                        
                logger.info("Item copied to internal clipboard")
            except Exception as e:
                logger.error(f"Copy failed: {e}")
        else:
            # Fallback to copy entire image to system clipboard
            self.copy_image()

    def copy_region_selection_to_clipboard(self) -> bool:
        try:
            if not self.region_select_rect:
                return False
            rectf = self.region_select_rect.normalized()
            if rectf.width() < 2 or rectf.height() < 2:
                return False
            src = self.get_final_image()
            if src.isNull():
                return False
            img_rectf = QRectF(src.rect())
            rectf = rectf.intersected(img_rectf)
            if rectf.width() < 2 or rectf.height() < 2:
                return False
            if hasattr(rectf, "toAlignedRect"):
                rect = rectf.toAlignedRect()
            else:
                rect = rectf.toRect()
            rect = rect.intersected(src.rect())
            if rect.isEmpty():
                return False
            cropped = src.copy(rect)
            if cropped.isNull():
                return False
            QApplication.clipboard().setPixmap(cropped)
            logger.info(f"Region copied to system clipboard: {rect.width()}x{rect.height()}")
            return True
        except Exception as e:
            logger.error(f"Failed to copy region selection to clipboard: {e}", exc_info=True)
            return False

    def paste_item(self):
        if not self.clipboard_item: return
        
        try:
            # Create new instance from clipboard
            new_item = {}
            for k, v in self.clipboard_item.items():
                if k == 'pixmap':
                    new_item[k] = v.copy()
                elif k == 'path':
                    new_item[k] = QPainterPath(v)
                elif isinstance(v, (QRectF, QPointF, QColor, QRect, QPoint)):
                    import copy
                    new_item[k] = copy.copy(v)
                elif isinstance(v, QFont):
                    new_item[k] = QFont(v)
                else:
                    import copy
                    new_item[k] = copy.deepcopy(v)
            
            # Offset position slightly (e.g. +20, +20) so it's visible
            offset = QPointF(20, 20)
            
            t = new_item['type']
            dx = offset.x()
            dy = offset.y()
            
            if t in ['rect', 'circle', 'line', 'arrow']:
                # Reconstruct points manually to avoid any operator overloading issues
                s = new_item['start']
                e = new_item['end']
                new_item['start'] = QPointF(s.x() + dx, s.y() + dy)
                new_item['end'] = QPointF(e.x() + dx, e.y() + dy)
            elif t in ['text', 'step_marker']:
                p = new_item['pos']
                new_item['pos'] = QPointF(p.x() + dx, p.y() + dy)
            elif t == 'image':
                # QRectF translate is usually safe, but let's be paranoid if needed
                # new_item['rect'].translate(dx, dy) is C++ call, should be fine.
                # If it fails, we can reconstruct QRectF too.
                r = new_item['rect']
                new_item['rect'] = QRectF(r.x() + dx, r.y() + dy, r.width(), r.height())
            elif t in ['pen', 'mosaic']:
                # QPainterPath translate is safe
                new_item['path'].translate(dx, dy)
                
            # Add to items
            self.items.append(new_item)
            
            # Select the new item
            self.selected_item_index = len(self.items) - 1
            
            # In smart board mode, pasted images should not immediately open the property panel.
            if self.mode == 'standalone' and new_item.get('type') == 'image':
                self.prop_panel.clear_ui()
                self.prop_panel.hide()
                logger.info("Image pasted from internal clipboard without opening property panel")
            else:
                self.prop_panel.update_ui(new_item)
                self.prop_panel.show()
                self.update_toolbar_pos()
            
            self.save_state()
            self.refresh_canvas()
            logger.info("Item pasted from internal clipboard")
        except Exception as e:
            logger.error(f"Paste failed: {e}")

    def paste_from_system_clipboard(self):
        try:
            clipboard = QApplication.clipboard()
            if clipboard is None:
                return False
            pixmap = clipboard.pixmap()
            if pixmap.isNull():
                image = clipboard.image()
                if not image.isNull():
                    pixmap = QPixmap.fromImage(image)
            if pixmap.isNull():
                logger.info("System clipboard has no image to paste")
                return False

            canvas_w, canvas_h = self.original_pixmap.width(), self.original_pixmap.height()
            if canvas_w <= 0 or canvas_h <= 0:
                return False

            if pixmap.width() > canvas_w * 0.8 or pixmap.height() > canvas_h * 0.8:
                pixmap = pixmap.scaled(QSize(int(canvas_w * 0.8), int(canvas_h * 0.8)), Qt.KeepAspectRatio, Qt.SmoothTransformation)

            x = (canvas_w - pixmap.width()) / 2
            y = (canvas_h - pixmap.height()) / 2

            item = {
                'type': 'image',
                'pixmap': pixmap,
                'rect': QRectF(x, y, pixmap.width(), pixmap.height()),
                'rotation': 0
            }
            self.items.append(item)
            self.selected_item_index = len(self.items) - 1
            self.prop_panel.clear_ui()
            self.prop_panel.hide()
            self.save_state()
            self.refresh_canvas()
            logger.info("Image pasted from system clipboard without opening property panel")
            return True
        except Exception as e:
            logger.error(f"Paste system clipboard image failed: {e}", exc_info=True)
            return False

    def keyPressEvent(self, event):
        try:
            if getattr(self, 'tabbed_canvases_enabled', False) and hasattr(self, 'page_tab_bar') and self.page_tab_bar is not None:
                if hasattr(self, 'active_text_editor') and self.active_text_editor and self.active_text_editor.hasFocus():
                    pass
                else:
                    if event.key() == Qt.Key_PageDown:
                        cur = self.page_tab_bar.currentIndex()
                        nxt = min(self.page_tab_bar.count() - 1, cur + 1)
                        if nxt != cur and nxt >= 0:
                            self.page_tab_bar.setCurrentIndex(nxt)
                        event.accept()
                        return
                    if event.key() == Qt.Key_PageUp:
                        cur = self.page_tab_bar.currentIndex()
                        nxt = max(0, cur - 1)
                        if nxt != cur:
                            self.page_tab_bar.setCurrentIndex(nxt)
                        event.accept()
                        return

            if event.key() == Qt.Key_Escape:
                if self.current_tool == 'select' and self.region_select_rect:
                    self.region_select_rect = None
                    self.is_region_selecting = False
                    self.refresh_canvas()
                elif self.current_tool == 'crop':
                    self.cancel_crop()
                elif hasattr(self, 'active_text_editor') and self.active_text_editor:
                    self.cancel_text_editor()
                else:
                    self.close()
            elif event.key() in [Qt.Key_Return, Qt.Key_Enter]:
                if self.current_tool == 'crop':
                    self.apply_crop()
            elif event.key() in [Qt.Key_Delete, Qt.Key_Backspace, 16777219, 16777223]:
                if self.selected_item_index != -1:
                    # Remove selected item
                    self.items.pop(self.selected_item_index)
                    self.selected_item_index = -1
                    self.prop_panel.hide()
                    self.save_state()
                    self.refresh_canvas()
            elif event.modifiers() & Qt.ControlModifier:
                if event.key() == Qt.Key_Z:
                    self.undo()
                elif event.key() == Qt.Key_S:
                    self.save_image()
                elif event.key() == Qt.Key_C:
                    self.copy_item()
                elif event.key() == Qt.Key_V:
                    if not self.paste_from_system_clipboard():
                        self.paste_item()
            super().keyPressEvent(event)
        except Exception as e:
            logger.error(f"Error in keyPressEvent: {e}", exc_info=True)
            print(f"Error in keyPressEvent: {e}")

    def eventFilter(self, obj, event):
        try:
            if self.mode == 'standalone' and hasattr(self, 'canvas_widget') and obj == self.canvas_widget:
                if event.type() == QEvent.Paint:
                    self.paint_canvas(obj)
                    return True
                elif event.type() in (QEvent.DragEnter, QEvent.DragMove):
                    md = event.mimeData()
                    if md and md.hasUrls():
                        for u in md.urls():
                            p = u.toLocalFile() if u.isLocalFile() else ""
                            if p and self._is_supported_image_file(p):
                                event.acceptProposedAction()
                                return True
                    event.ignore()
                    return True
                elif event.type() == QEvent.Drop:
                    md = event.mimeData()
                    if md and md.hasUrls():
                        paths = []
                        for u in md.urls():
                            p = u.toLocalFile() if u.isLocalFile() else ""
                            if p and self._is_supported_image_file(p):
                                paths.append(p)
                        if paths:
                            pos = self._event_pos(event)
                            center = self.map_pos(pos)
                            if getattr(self, "_last_mapped_valid", False) is False:
                                try:
                                    w = self.original_pixmap.width()
                                    h = self.original_pixmap.height()
                                    center = QPointF(w / 2.0, h / 2.0)
                                except Exception:
                                    center = QPointF(0, 0)
                            self._import_image_files_to_canvas(paths, center)
                            event.acceptProposedAction()
                            return True
                    event.ignore()
                    return True
                elif event.type() == QEvent.Wheel:
                    if event.modifiers() & Qt.ControlModifier:
                        self.wheelEvent(event)
                        return True
                    return False
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
                elif event.type() == QEvent.Resize:
                    if getattr(self, 'multi_page_enabled', False) and not getattr(self, 'tabbed_canvases_enabled', False):
                        self._update_canvas_widget_min_height()
                    return False
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
        except Exception as e:
            logger.error(f"Error in eventFilter: {e}", exc_info=True)
            print(f"Error in eventFilter: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _event_pos(self, event):
        try:
            if hasattr(event, "position"):
                return event.position().toPoint()
            if hasattr(event, "pos"):
                return event.pos()
        except Exception:
            return QPoint(0, 0)
        return QPoint(0, 0)

    def _is_supported_image_file(self, file_path: str) -> bool:
        ext = os.path.splitext(str(file_path or ""))[1].lower()
        return ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")

    def _import_image_files_to_canvas(self, file_paths, center_pos):
        added = 0
        base_center = QPointF(center_pos)
        cw = self.original_pixmap.width() if self.original_pixmap else 0
        ch = self.original_pixmap.height() if self.original_pixmap else 0
        max_w = cw * 0.8 if cw > 0 else 0
        max_h = ch * 0.8 if ch > 0 else 0

        for fp in file_paths:
            pixmap = QPixmap(fp)
            if pixmap.isNull():
                continue
            w, h = pixmap.width(), pixmap.height()
            if max_w > 0 and max_h > 0 and (w > max_w or h > max_h):
                pixmap = pixmap.scaled(QSize(int(max_w), int(max_h)), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                w, h = pixmap.width(), pixmap.height()

            off = QPointF(added * 16.0, added * 16.0)
            c = base_center + off
            x = c.x() - w / 2.0
            y = c.y() - h / 2.0

            item = {
                'type': 'image',
                'rect': QRectF(x, y, w, h),
                'pixmap': pixmap,
                'original_pixmap': pixmap,
                'seed': random.randint(0, 100000)
            }
            self.items.append(item)
            added += 1

        if added <= 0:
            return

        self.selected_item_index = len(self.items) - 1
        self.current_tool = 'move'
        self.setCursor(Qt.SizeAllCursor)
        self.save_state()
        self.refresh_canvas()

    def paint_canvas(self, canvas):
        try:
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.setRenderHint(QPainter.TextAntialiasing)
            
            # Fill background with a neutral color (e.g. gray) to distinguish image area
            painter.fillRect(canvas.rect(), QColor(240, 240, 240))

            if getattr(self, 'multi_page_enabled', False) and not getattr(self, 'tabbed_canvases_enabled', False):
                layout, total_h = self._compute_pages_layout(canvas.width())
                self._page_layout_cache = layout
                if total_h > 0 and canvas.minimumHeight() != total_h:
                    canvas.setMinimumHeight(total_h)
                self._rebuild_page_controls()

                shadow_color = QColor(0, 0, 0, 30)
                border_color = QColor(210, 210, 210)
                active_border = QColor(0, 122, 255)

                for info in layout:
                    idx = info["index"]
                    rect = info["rect"]
                    page = self.pages[idx]
                    pm = page.get("pixmap")
                    if pm is None or pm.isNull():
                        continue

                    painter.save()
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(shadow_color)
                    painter.drawRoundedRect(rect.adjusted(3, 3, 6, 6), 10, 10)
                    painter.restore()

                    painter.save()
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(Qt.white)
                    painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 10, 10)
                    painter.restore()

                    painter.save()
                    painter.translate(rect.x(), rect.y())
                    painter.scale(self.zoom_level, self.zoom_level)
                    painter.setClipRect(0, 0, pm.width(), pm.height())
                    painter.drawPixmap(0, 0, pm)
                    for it in page.get("items", []):
                        self._draw_single_item(painter, it)

                    if idx == self.active_page_index:
                        self.draw_selection_overlay(painter)
                        self.draw_region_selection_overlay(painter)
                        if self.current_tool == 'crop' and self.crop_rect:
                            self.draw_crop_overlay(painter)
                        if self.is_drawing and self.current_tool and self.current_tool != 'move':
                            temp_item = {
                                'type': self.current_tool,
                                'color': self.pen_color,
                                'width': self.pen_width,
                                'style': self.drawing_style,
                                'seed': 42
                            }
                            if self.current_tool in ['rect', 'circle', 'line', 'arrow']:
                                temp_item['start'] = self.start_pos
                                temp_item['end'] = self.end_pos
                            elif self.current_tool in ['pen', 'mosaic']:
                                temp_item['path'] = self.current_path
                            self._draw_single_item(painter, temp_item)

                        if self.laser_points:
                            self.draw_laser(painter)

                        if hasattr(self, 'alignment_guides') and self.alignment_guides:
                            pen = QPen(QColor(255, 0, 255), 1)
                            pen.setStyle(Qt.DashLine)
                            pen.setWidthF(1.0 / self.zoom_level)
                            painter.setPen(pen)
                            for line in self.alignment_guides:
                                painter.drawLine(line)

                    painter.restore()

                    painter.save()
                    pen = QPen(active_border if idx == self.active_page_index else border_color, 2 if idx == self.active_page_index else 1)
                    painter.setPen(pen)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRoundedRect(rect.adjusted(0, 0, 0, 0), 10, 10)
                    painter.restore()

                painter.end()
                return
            
            if not self.original_pixmap or self.original_pixmap.isNull():
                return
            
            # Center the image
            img_w, img_h = self.original_pixmap.width(), self.original_pixmap.height()
            
            # Apply zoom
            scaled_w = int(img_w * self.zoom_level)
            scaled_h = int(img_h * self.zoom_level)
            
            cw, ch = canvas.width(), canvas.height()
            
            # Base centering offset
            center_x = (cw - scaled_w) // 2
            center_y = (ch - scaled_h) // 2
            
            # Add manual panning offset
            x = center_x + self.view_offset.x()
            y = center_y + self.view_offset.y()
            
            # Store offset for mouse mapping
            self.canvas_offset = QPoint(x, y)
            
            painter.translate(x, y)
            painter.scale(self.zoom_level, self.zoom_level)
            
            # Clip drawing to image area
            painter.setClipRect(0, 0, img_w, img_h)
            
            # Draw the image
            painter.drawPixmap(0, 0, self.original_pixmap)
            
            # Draw all committed items
            for item in self.items:
                self._draw_single_item(painter, item)
                
            # Draw Selection Overlay
            self.draw_selection_overlay(painter)
            self.draw_region_selection_overlay(painter)
                
            # Draw Crop Overlay
            if self.current_tool == 'crop' and self.crop_rect:
                self.draw_crop_overlay(painter)
                
            # Draw in-progress shape
            if self.is_drawing and self.current_tool and self.current_tool != 'move':
                temp_item = {
                    'type': self.current_tool,
                    'color': self.pen_color,
                    'width': self.pen_width,
                    'style': self.drawing_style,
                    'seed': 42
                }
                if self.current_tool in ['rect', 'circle', 'line', 'arrow']:
                    temp_item['start'] = self.start_pos
                    temp_item['end'] = self.end_pos
                elif self.current_tool in ['pen', 'mosaic']:
                    temp_item['path'] = self.current_path
                
                self._draw_single_item(painter, temp_item)
                
            # Draw border
            # painter.setPen(QPen(Qt.black, 1))
            # painter.setBrush(Qt.NoBrush)
            # painter.drawRect(0, 0, img_w, img_h)
            
        except Exception as e:
            logger.error(f"Error in paint_canvas: {e}")
        
        # Helper to draw an item (Same as before but strictly using painter provided)
        for item in self.items:
            self._draw_single_item(painter, item)
            
        self.draw_selection_overlay(painter)
        self.draw_region_selection_overlay(painter)
            
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

        # Draw Crop Overlay (Standalone mode)
        if self.current_tool == 'crop' and self.crop_rect:
            self.draw_crop_overlay(painter)
            
        # Draw Laser Pointer Trail
        if self.laser_points:
            self.draw_laser(painter)

        # Draw Alignment Guides (Standalone Mode)
        if hasattr(self, 'alignment_guides') and self.alignment_guides:
            pen = QPen(QColor(255, 0, 255), 1) # Magenta
            pen.setStyle(Qt.DashLine)
            # Ensure width is at least 1px visual
            pen.setWidthF(1.0 / self.zoom_level)
            painter.setPen(pen)
            for line in self.alignment_guides:
                painter.drawLine(line)
            
        painter.end()

    def draw_laser(self, painter):
        if not self.laser_points: return
        
        try:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            
            current_time = time.time()
            
            # Draw segments
            # We draw line from i to i+1
            for i in range(len(self.laser_points) - 1):
                p1 = self.laser_points[i]
                p2 = self.laser_points[i+1]
                
                # Calculate properties based on age of p1
                age = current_time - p1['time']
                life = 1.0 - age # 1.0 to 0.0
                
                if life <= 0: continue
                
                # Fade out alpha
                alpha = max(0, min(255, int(255 * life)))
                # Thin out width
                width = max(0.5, 5 * life + 1)
                
                color = QColor(255, 0, 0, alpha)
                pen = QPen(color, width)
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                
                painter.drawLine(p1['pos'], p2['pos'])
                
            painter.restore()
        except Exception as e:
            logger.error(f"Error drawing laser: {e}")
            painter.restore() # Ensure restore is called

    def draw_crop_overlay(self, painter):
        if not self.crop_rect: return
        
        # 1. Dim outside area
        painter.save()
        img_rect = self.original_pixmap.rect()
        overlay_color = QColor(0, 0, 0, 150)
        
        # Draw 4 rects around the crop area
        r = self.crop_rect.toRect()
        # Top
        painter.fillRect(0, 0, img_rect.width(), r.top(), overlay_color)
        # Bottom
        painter.fillRect(0, r.bottom() + 1, img_rect.width(), img_rect.height() - r.bottom() - 1, overlay_color)
        # Left
        painter.fillRect(0, r.top(), r.left(), r.height(), overlay_color)
        # Right
        painter.fillRect(r.right() + 1, r.top(), img_rect.width() - r.right() - 1, r.height(), overlay_color)
        
        # 2. Draw Crop Rect Border
        pen = QPen(Qt.white, 2, Qt.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.crop_rect)
        
        # 3. Draw Grid (Rule of Thirds)
        pen.setColor(QColor(255, 255, 255, 100))
        pen.setWidth(1)
        painter.setPen(pen)
        
        x, y, w, h = self.crop_rect.x(), self.crop_rect.y(), self.crop_rect.width(), self.crop_rect.height()
        
        # Verticals
        painter.drawLine(x + w/3, y, x + w/3, y + h)
        painter.drawLine(x + 2*w/3, y, x + 2*w/3, y + h)
        # Horizontals
        painter.drawLine(x, y + h/3, x + w, y + h/3)
        painter.drawLine(x, y + 2*h/3, x + w, y + 2*h/3)
        
        # 4. Draw Handles
        painter.setPen(QPen(Qt.white, 1))
        painter.setBrush(Qt.white)
        handle_size = 8
        hs2 = handle_size / 2
        
        points = [
            self.crop_rect.topLeft(), self.crop_rect.topRight(),
            self.crop_rect.bottomRight(), self.crop_rect.bottomLeft(),
            QPointF(x + w/2, y), QPointF(x + w, y + h/2),
            QPointF(x + w/2, y + h), QPointF(x, y + h/2)
        ]
        
        # Only show side handles if ratio is Free
        limit = 8 if self.crop_ratio is None else 4
        
        for i in range(limit):
            p = points[i]
            painter.drawRect(p.x() - hs2, p.y() - hs2, handle_size, handle_size)
            
        # 5. Draw Size Label
        size_text = f"{int(w)} x {int(h)}"
        
        font = QFont()
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        
        fm = QFontMetrics(font)
        text_rect = fm.boundingRect(size_text)
        text_w = text_rect.width()
        text_h = text_rect.height()
        padding = 6
        
        # Calculate label position (centered above top edge)
        center_x = x + w / 2
        
        label_x = center_x - text_w / 2 - padding
        label_y = y - text_h - padding * 2 - 10 # 10px spacing above
        
        # Check if out of bounds (top)
        if label_y < 0:
            # Move inside
            label_y = y + 10
            
        label_rect = QRectF(label_x, label_y, text_w + padding * 2, text_h + padding * 2)
        
        # Draw label background
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.drawRoundedRect(label_rect, 4, 4)
        
        # Draw text
        painter.setPen(Qt.white)
        painter.drawText(label_rect, Qt.AlignCenter, size_text)
            
        painter.restore()

    def hit_test_crop(self, pos):
        if not self.crop_rect: return -1
        pos = QPointF(pos)
        
        handle_radius = 10
        x, y, w, h = self.crop_rect.x(), self.crop_rect.y(), self.crop_rect.width(), self.crop_rect.height()
        
        points = [
            self.crop_rect.topLeft(), self.crop_rect.topRight(),
            self.crop_rect.bottomRight(), self.crop_rect.bottomLeft(),
            QPointF(x + w/2, y), QPointF(x + w, y + h/2),
            QPointF(x + w/2, y + h), QPointF(x, y + h/2)
        ]
        
        limit = 8 if self.crop_ratio is None else 4
        
        for i in range(limit):
            if (pos - points[i]).manhattanLength() < handle_radius:
                logger.info(f"Hit handle {i}")
                return i
                
        if self.crop_rect.contains(pos):
            logger.info("Hit crop body (8)")
            return 8 # Move
            
        logger.info("Hit nothing (-1)")
        return -1

    def update_crop_rect(self, pos):
        if self.crop_handle_index == -1: return
        pos = QPointF(pos)
        
        rect = QRectF(self.crop_start_rect)
        # Use scalar delta
        dx = pos.x() - self.crop_start_pos.x()
        dy = pos.y() - self.crop_start_pos.y()
        
        img_w, img_h = self.original_pixmap.width(), self.original_pixmap.height()
        
        if self.crop_handle_index == 8: # Move
            rect.translate(dx, dy)
            # Constrain
            if rect.left() < 0: rect.moveLeft(0)
            if rect.top() < 0: rect.moveTop(0)
            if rect.right() > img_w: rect.moveRight(img_w)
            if rect.bottom() > img_h: rect.moveBottom(img_h)
            self.crop_rect = rect
            return

        # Resize
        # 0: TL, 1: TR, 2: BR, 3: BL
        # 4: T, 5: R, 6: B, 7: L
        
        idx = self.crop_handle_index
        # dx, dy is already calculated above
        
        # Apply aspect ratio constraints
        if self.crop_ratio is not None:
            # For corners, we project delta onto diagonal or just use X/Y dominant
            # Simple approach: preserve ratio based on X change (or Y if easier)
            
            # Recalculate rect based on new corner pos
            if idx == 0: # TL
                new_tl_x = rect.left() + dx
                new_w = rect.right() - new_tl_x
                new_h = new_w / self.crop_ratio
                new_y = rect.bottom() - new_h
                rect.setLeft(new_tl_x)
                rect.setTop(new_y)
            elif idx == 1: # TR
                new_tr_x = rect.right() + dx
                new_w = new_tr_x - rect.left()
                new_h = new_w / self.crop_ratio
                new_y = rect.bottom() - new_h
                rect.setRight(new_tr_x)
                rect.setTop(new_y)
            elif idx == 2: # BR
                new_br_x = rect.right() + dx
                new_w = new_br_x - rect.left()
                new_h = new_w / self.crop_ratio
                rect.setWidth(new_w)
                rect.setHeight(new_h)
            elif idx == 3: # BL
                new_bl_x = rect.left() + dx
                new_w = rect.right() - new_bl_x
                new_h = new_w / self.crop_ratio
                rect.setLeft(new_bl_x)
                rect.setTop(rect.bottom() - new_h) # Fix top based on new height
        else:
            # Free resize - Use scalar operations for robustness
            if idx == 0: # TL
                rect.setLeft(rect.left() + dx)
                rect.setTop(rect.top() + dy)
            elif idx == 1: # TR
                rect.setRight(rect.right() + dx)
                rect.setTop(rect.top() + dy)
            elif idx == 2: # BR
                rect.setRight(rect.right() + dx)
                rect.setBottom(rect.bottom() + dy)
            elif idx == 3: # BL
                rect.setLeft(rect.left() + dx)
                rect.setBottom(rect.bottom() + dy)
            elif idx == 4: # T
                rect.setTop(rect.top() + dy)
            elif idx == 5: # R
                rect.setRight(rect.right() + dx)
            elif idx == 6: # B
                rect.setBottom(rect.bottom() + dy)
            elif idx == 7: # L
                rect.setLeft(rect.left() + dx)
            
        # Normalize and constrain size
        rect = rect.normalized()
        if rect.width() < 10: rect.setWidth(10)
        if rect.height() < 10: rect.setHeight(10)
        
        # Constrain to image
        # Note: This simple constraint might break aspect ratio if hitting edge.
        # Ideally we clamp and recalculate, but for now just clamp corners if they go out.
        # But for valid crop, we should probably just stop growing if hitting edge.
        
        self.crop_rect = rect

    def new_canvas_dialog(self):
        from PySide6.QtWidgets import QDialog, QFormLayout, QComboBox, QSpinBox, QDialogButtonBox, QRadioButton, QButtonGroup, QHBoxLayout, QMessageBox
        
        # Check for existing content: items or history changes
        has_content = (not getattr(self, 'tabbed_canvases_enabled', False)) and (len(self.items) > 0 or len(self.history) > 1)
        
        if has_content:
             reply = QMessageBox.question(self, "保存画布", "当前画布已有内容，是否保存？", 
                                          QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
             if reply == QMessageBox.Yes:
                 if not self.save_image():
                     return # User cancelled save
             elif reply == QMessageBox.Cancel:
                 return

        dialog = QDialog(self)
        dialog.setWindowTitle("新建画布")
        dialog.setFixedWidth(350)
        
        layout = QFormLayout(dialog)
        
        # --- Orientation Selection ---
        orientation_layout = QHBoxLayout()
        rb_portrait = QRadioButton("竖屏")
        rb_landscape = QRadioButton("横屏")
        rb_square = QRadioButton("正方形")
        
        # Default to Portrait
        rb_portrait.setChecked(True)
        
        orientation_group = QButtonGroup(dialog)
        orientation_group.addButton(rb_portrait)
        orientation_group.addButton(rb_landscape)
        orientation_group.addButton(rb_square)
        
        orientation_layout.addWidget(rb_portrait)
        orientation_layout.addWidget(rb_landscape)
        orientation_layout.addWidget(rb_square)
        
        layout.addRow("方向:", orientation_layout)

        # --- Preset Sizes ---
        combo_preset = QComboBox()
        
        # Define presets for each type
        presets_portrait = [
            ("1080x1440 (3:4)(小红书)", 1080, 1440),
            ("1080x1920 (9:16)", 1080, 1920),
            ("2480x3508 (A4-300dpi)", 2480, 3508),
            ("1240x1754 (A4-150dpi)", 1240, 1754),
            ("720x1280 (9:16)", 720, 1280),
            ("800x1200 (2:3)", 800, 1200),
            ("600x800 (3:4)", 600, 800),
            ("自定义", 0, 0)
        ]
        
        presets_landscape = [
            ("1920x1080 (16:9)", 1920, 1080),
            ("3508x2480 (A4-300dpi)", 3508, 2480),
            ("1754x1240 (A4-150dpi)", 1754, 1240),
            ("1280x720 (16:9)", 1280, 720),
            ("1200x800 (3:2)", 1200, 800),
            ("1024x768 (4:3)", 1024, 768),
            ("800x600 (4:3)", 800, 600),
            ("自定义", 0, 0)
        ]
        
        presets_square = [
            ("1080x1080 (1:1)", 1080, 1080),
            ("800x800 (1:1)", 800, 800),
            ("500x500 (1:1)", 500, 500),
            ("自定义", 0, 0)
        ]

        layout.addRow("预设尺寸:", combo_preset)
        
        # Width/Height Spinboxes
        spin_w = QSpinBox()
        spin_w.setRange(10, 8000)
        
        spin_h = QSpinBox()
        spin_h.setRange(10, 8000)
        
        layout.addRow("宽度 (px):", spin_w)
        layout.addRow("高度 (px):", spin_h)
        
        # --- Logic ---
        def on_preset_changed(idx):
            data = combo_preset.currentData()
            if data:
                w, h = data
                if w > 0 and h > 0:
                    spin_w.setValue(w)
                    spin_h.setValue(h)
                
        combo_preset.currentIndexChanged.connect(on_preset_changed)

        def update_presets(btn=None):
            combo_preset.blockSignals(True)
            combo_preset.clear()
            current_presets = []
            
            if rb_portrait.isChecked():
                current_presets = presets_portrait
            elif rb_landscape.isChecked():
                current_presets = presets_landscape
            elif rb_square.isChecked():
                current_presets = presets_square
            
            for name, w, h in current_presets:
                combo_preset.addItem(name, (w, h))
            
            combo_preset.blockSignals(False)
            
            # Set default values based on first item
            if current_presets:
                 _, w, h = current_presets[0]
                 spin_w.setValue(w)
                 spin_h.setValue(h)

        orientation_group.buttonToggled.connect(update_presets)
        
        # Initialize
        update_presets()

        # Background Color
        bg_group = QButtonGroup(dialog)
        rb_white = QRadioButton("白色")
        rb_white.setChecked(True)
        rb_trans = QRadioButton("透明")
        rb_color = QRadioButton("颜色")
        
        bg_group.addButton(rb_white)
        bg_group.addButton(rb_trans)
        bg_group.addButton(rb_color)
        
        # Color button
        btn_bg_color = QPushButton()
        btn_bg_color.setFixedSize(20, 20)
        btn_bg_color.setStyleSheet("background-color: #cccccc; border: 1px solid #999;")
        btn_bg_color.setEnabled(False)
        self.selected_bg_color = QColor(Qt.white) # Default

        def choose_bg_color():
            c = QColorDialog.getColor(self.selected_bg_color, dialog, "选择背景色")
            if c.isValid():
                self.selected_bg_color = c
                btn_bg_color.setStyleSheet(f"background-color: {c.name()}; border: 1px solid #999;")

        btn_bg_color.clicked.connect(choose_bg_color)
        
        def on_bg_toggled(btn):
            if rb_color.isChecked():
                btn_bg_color.setEnabled(True)
            else:
                btn_bg_color.setEnabled(False)
        
        bg_group.buttonToggled.connect(on_bg_toggled)

        bg_layout = QHBoxLayout()
        bg_layout.addWidget(rb_white)
        bg_layout.addWidget(rb_trans)
        bg_layout.addWidget(rb_color)
        bg_layout.addWidget(btn_bg_color)
        layout.addRow("背景颜色:", bg_layout)
        
        # --- Zimeiti Button ---
        btn_zimeiti = QPushButton("自媒体常用图尺寸")
        def open_zimeiti():
            import sys
            from PySide6.QtWidgets import QMessageBox
            # Try to find the image
            possible_paths = [
                os.path.join("assets", "zimeiti.png"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "zimeiti.png"),
            ]
            
            # For frozen app
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
                possible_paths.insert(0, os.path.join(base_path, "assets", "zimeiti.png"))
            
            target_path = None
            for p in possible_paths:
                if os.path.exists(p):
                    target_path = os.path.abspath(p)
                    break
            
            if target_path:
                try:
                    os.startfile(target_path)
                except Exception as e:
                    logger.error(f"Failed to open image: {e}")
                    QMessageBox.warning(dialog, "错误", f"无法打开图片: {e}")
            else:
                QMessageBox.warning(dialog, "提示", "找不到参考图文件：zimeiti.png")
                
        btn_zimeiti.clicked.connect(open_zimeiti)
        layout.addRow(btn_zimeiti)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            w = spin_w.value()
            h = spin_h.value()
            
            bg_color = Qt.white
            is_transparent = False
            
            if rb_trans.isChecked():
                is_transparent = True
                bg_color = Qt.transparent
            elif rb_color.isChecked():
                bg_color = self.selected_bg_color
            
            self.create_new_canvas(w, h, bg_color, is_transparent)

    def create_new_canvas(self, w, h, bg_color=Qt.white, is_transparent=False):
        pixmap = QPixmap(w, h)
        pixmap.fill(bg_color)

        if getattr(self, 'tabbed_canvases_enabled', False):
            new_items = []
            new_history = [([], pixmap)]
            new_page = self._create_page(pixmap, self.generate_mosaic(pixmap), new_items, new_history)
            insert_at = min(self.active_page_index + 1, len(self.pages))
            self.pages.insert(insert_at, new_page)
            logger.info(f"New canvas page created: index={insert_at}, size={w}x{h}, pages={len(self.pages)}")
            self._set_active_page(insert_at)
            self._sync_page_tabs()
            return
            
        self._replace_active_page_pixmap(pixmap)
        self._replace_active_page_items([])
        self._replace_active_page_history([([], self.original_pixmap)])
        
        # Auto zoom to fit window
        view_w = self.width()
        view_h = self.height()
        
        if self.mode == 'standalone' and hasattr(self, 'canvas_widget'):
            view_w = self.canvas_widget.width()
            view_h = self.canvas_widget.height()
            
        # Reserve padding
        padding = 40
        view_w -= padding
        view_h -= padding
        
        if view_w > 0 and view_h > 0 and w > 0 and h > 0:
            scale_w = view_w / w
            scale_h = view_h / h
            # Fit to screen, but don't zoom in more than 100% initially to maintain clarity
            self.zoom_level = min(scale_w, scale_h, 1.0)
            # Ensure within bounds
            self.zoom_level = max(self.min_zoom, min(self.zoom_level, self.max_zoom))
        else:
            self.zoom_level = 1.0
            
        self.view_offset = QPoint(0, 0)
        self.update_canvas_size_label()
        self.refresh_canvas()
        
    def import_image_to_canvas(self):
        from src.config import ConfigManager
        config = ConfigManager()
        default_dir = config.get("save_path_capture", "")
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入图片", default_dir, "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            logger.info(f"Importing image: {file_path}")
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                w, h = pixmap.width(), pixmap.height()
                
                # Center the image on current canvas
                cw = self.original_pixmap.width()
                ch = self.original_pixmap.height()
                
                x = (cw - w) / 2
                y = (ch - h) / 2
                
                item = {
                    'type': 'image',
                    'rect': QRectF(x, y, w, h),
                    'pixmap': pixmap,
                    'original_pixmap': pixmap, # For quality resizing
                    'seed': random.randint(0, 100000)
                }
                
                self.items.append(item)
                
                # Select it automatically
                self.selected_item_index = len(self.items) - 1
                self.current_tool = 'move'
                self.setCursor(Qt.SizeAllCursor)
                
                self.save_state()
                self.refresh_canvas()
            else:
                logger.error(f"Failed to load image: {file_path}")

    def _open_pixmap_as_new_canvas_tab(self, pixmap: QPixmap):
        if pixmap is None or pixmap.isNull():
            return -1
        if not getattr(self, 'tabbed_canvases_enabled', False):
            return -1

        new_pixmap = pixmap.copy()
        new_mosaic = self.generate_mosaic(new_pixmap)
        new_items = []
        new_history = [([], new_pixmap)]

        new_page = self._create_page(new_pixmap, new_mosaic, new_items, new_history)
        insert_at = min(self.active_page_index + 1, len(self.pages))
        self.pages.insert(insert_at, new_page)
        logger.info(f"Image opened into new canvas tab: index={insert_at}, size={new_pixmap.width()}x{new_pixmap.height()}, pages={len(self.pages)}")

        self._set_active_page(insert_at)
        self._sync_page_tabs()
        return insert_at

    def open_image(self):
        from PySide6.QtWidgets import QMessageBox
        
        # Check for existing content
        has_content = len(self.items) > 0 or len(self.history) > 1
        
        if has_content and not getattr(self, 'tabbed_canvases_enabled', False):
             reply = QMessageBox.question(self, "保存画布", "当前画布已有内容，是否保存？", 
                                          QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
             if reply == QMessageBox.Yes:
                 if not self.save_image():
                     return # User cancelled save
             elif reply == QMessageBox.Cancel:
                 return

        from src.config import ConfigManager
        config = ConfigManager()
        default_dir = config.get("save_path_capture", "")
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开图片", default_dir, "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            logger.info(f"Opening image: {file_path}")
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                if getattr(self, 'tabbed_canvases_enabled', False):
                    self._open_pixmap_as_new_canvas_tab(pixmap)
                else:
                    self._replace_active_page_pixmap(pixmap)
                    self._replace_active_page_items([])
                    self._replace_active_page_history([([], self.original_pixmap)])
                    self.update_canvas_size_label()
                    self.refresh_canvas()
            else:
                logger.error(f"Failed to load image: {file_path}")

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
                 
        self.active_text_editor = QPlainTextEdit(parent)
        self.active_text_editor.setPlainText(initial_text)
        if not initial_text:
            self.active_text_editor.setPlaceholderText("输入文字")
            
        # Ensure move receives QPoint (int) not QPointF (float)
        self.active_text_editor.move(visual_pos.toPoint())

        
        if self.drawing_style == 'hand_drawn':
            font = self.get_hand_drawn_font()
        else:
            font = QFont("Arial", self.font_size, QFont.Bold)
            
        self.active_text_editor.setFont(font)
        self.active_text_editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # Style with dashed border to indicate edit mode
        self.active_text_editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: transparent;
                border: 1px dashed #007aff;
                color: {self.pen_color.name()};
            }}
        """)
        
        self.active_text_editor.setFocus()
        self.active_text_editor.show()
        
        # Initial resize
        self.on_text_changed()
             
        if self.active_text_editor:
            self.active_text_editor.textChanged.connect(self.on_text_changed)
            self.active_text_editor.installEventFilter(self)
        
        self.active_text_pos = pos

    def on_text_changed(self):
        if hasattr(self, 'active_text_editor') and self.active_text_editor:
            text = self.active_text_editor.toPlainText()
            fm = self.active_text_editor.fontMetrics()
            
            lines = text.split('\n')
            max_w = 0
            for line in lines:
                w = fm.horizontalAdvance(line)
                if w > max_w: max_w = w
            
            w = max_w + 50
            w = max(w, 200)
            
            line_height = fm.lineSpacing()
            num_lines = len(lines)
            h = num_lines * line_height + 15
            h = max(h, 40)
            
            self.active_text_editor.resize(w, h)

    def commit_text_editor(self):
        if not hasattr(self, 'active_text_editor') or not self.active_text_editor:
            return
            
        editor = self.active_text_editor
            
        text = editor.toPlainText()
        if text:
            font = editor.font()
            fm = QFontMetrics(font)
            # Adjust y to roughly match baseline visual
            baseline_y = self.active_text_pos.y() + fm.ascent() + 5
            
            # Explicitly create QPointF
            pos = QPointF(self.active_text_pos.x() + 5, baseline_y)
            item = {'type': 'text', 'text': text, 'pos': pos, 'color': self.pen_color, 'font': font}
            self.items.append(item)
            self.save_state()
            self.refresh_canvas()

            
        editor.deleteLater()
        self.active_text_editor = None

    def cancel_text_editor(self):
        if hasattr(self, 'active_text_editor') and self.active_text_editor:
            editor = self.active_text_editor
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
            
        self.history.append((new_items, self.original_pixmap))
        # Limit history to prevent OOM
        MAX_HISTORY = 10 
        if len(self.history) > MAX_HISTORY: 
            self.history.pop(0)

    def undo(self):
        if len(self.history) > 1:
            self.history.pop()
            state = self.history[-1]
            state_items = state[0]
            state_pixmap = state[1]
            
            # Restore pixmap (background)
            if self.original_pixmap != state_pixmap:
                self._replace_active_page_pixmap(state_pixmap)
                self.update_canvas_size_label()

            new_items = []
            for item in state_items:
                new_item = item.copy()
                if 'path' in item:
                    new_item['path'] = QPainterPath(item['path'])
                new_items.append(new_item)
            self._replace_active_page_items(new_items)
                
            self.selected_item_index = -1
            self.prop_panel.hide()
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

    def get_final_image_for_page_index(self, page_index: int):
        if page_index < 0 or page_index >= len(getattr(self, 'pages', []) or []):
            return None
        page = self.pages[page_index]
        pm = page.get("pixmap")
        if pm is None or pm.isNull():
            return None
        final = pm.copy()
        painter = QPainter(final)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.TextAntialiasing)
        for item in page.get("items", []) or []:
            self._draw_single_item(painter, item)
        painter.end()
        return final

    def _get_captures_dir(self):
        override = getattr(self, "_captures_dir_override", None)
        if override:
            os.makedirs(override, exist_ok=True)
            return override
        base_dir = os.path.dirname(os.path.dirname(__file__))
        captures_dir = os.path.join(base_dir, "captures")
        os.makedirs(captures_dir, exist_ok=True)
        return captures_dir

    def _export_all_canvases_to_dir(self, out_dir: str):
        if not out_dir:
            return []
        os.makedirs(out_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        written = []

        if getattr(self, 'tabbed_canvases_enabled', False) and getattr(self, 'pages', None):
            total = len(self.pages)
            for i in range(total):
                pm = self.get_final_image_for_page_index(i)
                if pm is None:
                    continue
                file_path = os.path.join(out_dir, f"Canvas_{timestamp}_{i+1}.png")
                n = 1
                while os.path.exists(file_path):
                    n += 1
                    file_path = os.path.join(out_dir, f"Canvas_{timestamp}_{i+1}_{n}.png")
                if pm.save(file_path):
                    written.append(file_path)
        else:
            pm = self.get_final_image()
            file_path = os.path.join(out_dir, f"Canvas_{timestamp}_1.png")
            n = 1
            while os.path.exists(file_path):
                n += 1
                file_path = os.path.join(out_dir, f"Canvas_{timestamp}_1_{n}.png")
            if pm and pm.save(file_path):
                written.append(file_path)

        return written

    def export_all_canvases(self):
        from PySide6.QtWidgets import QMessageBox
        out_dir = self._get_captures_dir()
        files = self._export_all_canvases_to_dir(out_dir)
        logger.info(f"Export all canvases: count={len(files)}, dir={out_dir}")
        QMessageBox.information(self, "导出完成", f"已导出 {len(files)} 张到：\n{out_dir}")

    def save_image(self):
        from src.config import ConfigManager
        config = ConfigManager()
        save_path = config.get("save_path_capture", os.getcwd())
        
        # Ensure the directory exists
        if save_path and not os.path.exists(save_path):
            try:
                os.makedirs(save_path, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create directory {save_path}: {e}")
                print(f"Failed to create directory {save_path}: {e}")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = os.path.join(save_path, f"Screenshot_{timestamp}.png")
        
        file_path, _ = QFileDialog.getSaveFileName(self, "保存截图", default_name, "Images (*.png *.jpg *.bmp)")
        if file_path:
            try:
                self.get_final_image().save(file_path)
                logger.info(f"Image saved to: {file_path}")
                # Open folder and select file
                if os.name == 'nt':
                    if not open_folder_and_select_file(file_path):
                         # Fallback if utility fails
                         import subprocess
                         subprocess.run(['explorer', '/select,', os.path.normpath(file_path)])
                return True
            except Exception as e:
                logger.error(f"Failed to save image or open folder: {e}")
                print(f"Failed to save image: {e}")
        return False
            # self.close() # Keep window open after save

    def copy_image(self):
        try:
            clipboard = QApplication.clipboard()
            clipboard.setPixmap(self.get_final_image())
            logger.info("Final image copied to system clipboard")
        except Exception as e:
            logger.error(f"Failed to copy image to clipboard: {e}")
        # self.close()
