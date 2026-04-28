import os
import sys
from datetime import datetime
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
                               QListWidget, QListWidgetItem, QTabWidget, QLineEdit, 
                               QMenu, QFrame, QMessageBox, QScrollArea, QAbstractItemView,
                               QInputDialog, QDialog, QSpinBox)
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QPoint, QPoint  # Added QPoint
from PySide6.QtGui import QIcon, QPixmap, QCursor, QAction

class ClipboardItemWidget(QWidget):
    copy_requested = Signal(int)
    delete_requested = Signal(int)
    favorite_toggled = Signal(int, bool)
    
    def __init__(self, item_data, parent=None):
        super().__init__(parent)
        self.item_data = item_data
        self.item_id = item_data['id']
        self.is_fav = bool(item_data['is_favorite'])
        
        self.init_ui()
        
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 1. Content Preview
        self.content_lbl = QLabel()
        self.content_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        if self.item_data['type'] == 'text':
            # Text Preview
            text = self.item_data['preview']
            if not text: text = self.item_data['content'][:100]
            self.content_lbl.setText(text)
            self.content_lbl.setWordWrap(True)
            self.content_lbl.setStyleSheet("color: #ddd; font-size: 13px;")
            self.content_lbl.setFixedHeight(40) # Limit height
        else:
            # Image Preview
            thumb_path = self.item_data.get('preview_path')
            if thumb_path and os.path.exists(thumb_path):
                pixmap = QPixmap(thumb_path)
                # Scale to fixed height
                pixmap = pixmap.scaledToHeight(60, Qt.SmoothTransformation)
                self.content_lbl.setPixmap(pixmap)
            else:
                self.content_lbl.setText("[图片丢失]")
                
        layout.addWidget(self.content_lbl, stretch=1)
        
        # 2. Meta Info (Time)
        time_str = self.format_time(self.item_data['created_at'])
        self.time_lbl = QLabel(time_str)
        self.time_lbl.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.time_lbl)
        
        # 3. Actions (Hidden by default, shown on hover? Or just always visible for simplicity first)
        # Let's make them visible but small icons
        
        # Copy Button
        self.btn_copy = QPushButton("📋")
        self.btn_copy.setFixedSize(24, 24)
        self.btn_copy.setToolTip("复制")
        self.btn_copy.clicked.connect(self.animate_copy)
        self.btn_copy.setStyleSheet("QPushButton { border: none; background: transparent; color: #888; } QPushButton:hover { color: #00afff; }")
        layout.addWidget(self.btn_copy)
        
        # Favorite Button
        self.btn_fav = QPushButton("★" if self.is_fav else "☆")
        self.btn_fav.setFixedSize(24, 24)
        self.btn_fav.setToolTip("收藏")
        self.btn_fav.clicked.connect(self.toggle_fav)
        color = "#ffaa00" if self.is_fav else "#666"
        self.btn_fav.setStyleSheet(f"QPushButton {{ border: none; background: transparent; color: {color}; }} QPushButton:hover {{ color: #ffaa00; }}")
        layout.addWidget(self.btn_fav)
        
        # Delete Button
        self.btn_del = QPushButton("×")
        self.btn_del.setFixedSize(24, 24)
        self.btn_del.setToolTip("删除")
        self.btn_del.clicked.connect(lambda: self.delete_requested.emit(self.item_id))
        self.btn_del.setStyleSheet("QPushButton { border: none; background: transparent; color: #888; } QPushButton:hover { color: #ff4444; }")
        layout.addWidget(self.btn_del)

        # Style
        self.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)
        
    def animate_copy(self):
        # Trigger actual copy
        self.copy_requested.emit(self.item_id)
        
        # Visual feedback
        original_text = "📋"
        original_style = self.btn_copy.styleSheet()
        
        self.btn_copy.setText("✔️")
        self.btn_copy.setStyleSheet("QPushButton { border: none; background: transparent; color: #00ff00; font-weight: bold; }")
        
        # Revert after 600ms
        QTimer.singleShot(600, lambda: self._reset_copy_btn(original_text, original_style))
        
    def _reset_copy_btn(self, text, style):
        try:
            self.btn_copy.setText(text)
            self.btn_copy.setStyleSheet(style)
        except:
            # Widget might be destroyed
            pass
        
    def toggle_fav(self):
        self.is_fav = not self.is_fav
        self.btn_fav.setText("★" if self.is_fav else "☆")
        color = "#ffaa00" if self.is_fav else "#666"
        self.btn_fav.setStyleSheet(f"QPushButton {{ border: none; background: transparent; color: {color}; }} QPushButton:hover {{ color: #ffaa00; }}")
        self.favorite_toggled.emit(self.item_id, self.is_fav)

    def format_time(self, timestamp):
        dt = datetime.fromtimestamp(timestamp)
        now = datetime.now()
        diff = now - dt
        
        if diff.days == 0:
            if diff.seconds < 60:
                return "刚刚"
            elif diff.seconds < 3600:
                return f"{diff.seconds // 60}分钟前"
            else:
                return f"{diff.seconds // 3600}小时前"
        elif diff.days == 1:
            return "昨天"
        elif diff.days < 10:
            return f"{diff.days}天前"
        else:
            return dt.strftime("%m-%d")


class ClipboardSettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("剪贴板设置")
        # Ensure it stays on top and has a proper window frame
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(320, 220)
        self.setup_ui()
        self.setup_style()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Retention Days
        days_layout = QVBoxLayout()
        lbl_days = QLabel("历史记录保留天数 (1-30):")
        self.spin_days = QSpinBox()
        self.spin_days.setRange(1, 30)
        self.spin_days.setValue(int(self.config.get("clipboard_retention_days", 10)))
        days_layout.addWidget(lbl_days)
        days_layout.addWidget(self.spin_days)
        layout.addLayout(days_layout)
        
        # Max Items
        limit_layout = QVBoxLayout()
        lbl_limit = QLabel("最大记录条数 (1-1000):")
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(1, 1000)
        self.spin_limit.setValue(int(self.config.get("clipboard_max_items", 200)))
        limit_layout.addWidget(lbl_limit)
        limit_layout.addWidget(self.spin_limit)
        layout.addLayout(limit_layout)
        
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("保存")
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.clicked.connect(self.save_settings)
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("cancel")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def setup_style(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: white;
            }
            QLabel {
                color: #ddd;
                font-size: 13px;
                font-weight: bold;
            }
            QSpinBox {
                background-color: #1a1a1a;
                color: white;
                border: 1px solid #444;
                padding: 5px 8px;
                border-radius: 6px;
                font-size: 14px;
                min-height: 30px;
            }
            QSpinBox:focus {
                border: 1px solid #00afff;
            }
            QPushButton {
                background-color: #00afff;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0099dd;
            }
            QPushButton#cancel {
                background-color: #444;
                color: #ccc;
            }
            QPushButton#cancel:hover {
                background-color: #555;
                color: white;
            }
        """)
        
    def save_settings(self):
        self.config.set("clipboard_retention_days", self.spin_days.value())
        self.config.set("clipboard_max_items", self.spin_limit.value())
        self.config.save()
        self.accept()


class ClipboardWindow(QWidget):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        
        # Window setup
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(400, 600)
        
        self.init_ui()
        self.setup_connections()
        
        self.current_filter = None # None=All, 'text', 'image'
        self.show_favorites = False
        
        # Load initial data
        self.refresh_list()
        
        # Dragging
        self.old_pos = None

    def init_ui(self):
        # Main Container
        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 10px;
            }
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # 1. Header
        header_layout = QHBoxLayout()
        
        title_lbl = QLabel("📋 剪贴板")
        title_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 16px; border: none;")
        header_layout.addWidget(title_lbl)
        
        header_layout.addStretch()
        
        btn_close = QPushButton("×")
        btn_close.setFixedSize(24, 24)
        btn_close.clicked.connect(self.hide)
        btn_close.setStyleSheet("""
            QPushButton { color: #888; border: none; font-size: 18px; background: transparent; }
            QPushButton:hover { color: white; }
        """)
        header_layout.addWidget(btn_close)
        
        layout.addLayout(header_layout)
        
        # 2. Search Box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索...")
        self.search_box.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 15px;
                padding: 5px 10px;
                color: white;
            }
            QLineEdit:focus { border: 1px solid #00afff; }
        """)
        self.search_box.textChanged.connect(self.filter_list)
        layout.addWidget(self.search_box)
        
        # 3. Tabs (Custom style buttons)
        tabs_layout = QHBoxLayout()
        tabs_layout.setSpacing(5)
        
        self.btn_all = self.create_tab_btn("全部", True)
        self.btn_text = self.create_tab_btn("文本")
        self.btn_image = self.create_tab_btn("图片")
        self.btn_fav = self.create_tab_btn("收藏")
        
        self.btn_all.clicked.connect(lambda: self.switch_tab(None, False, self.btn_all))
        self.btn_text.clicked.connect(lambda: self.switch_tab('text', False, self.btn_text))
        self.btn_image.clicked.connect(lambda: self.switch_tab('image', False, self.btn_image))
        self.btn_fav.clicked.connect(lambda: self.switch_tab(None, True, self.btn_fav))
        
        tabs_layout.addWidget(self.btn_all)
        tabs_layout.addWidget(self.btn_text)
        tabs_layout.addWidget(self.btn_image)
        tabs_layout.addWidget(self.btn_fav)
        tabs_layout.addStretch()
        
        layout.addLayout(tabs_layout)
        
        # 4. List
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                border-bottom: 1px solid #333;
                padding: 5px;
            }
            QListWidget::item:selected {
                background-color: #333;
                border-radius: 5px;
            }
        """)
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_widget.itemDoubleClicked.connect(self.on_item_dbl_click)
        layout.addWidget(self.list_widget)
        
        # 5. Footer
        footer_layout = QHBoxLayout()
        
        btn_clear = QPushButton("清除所有")
        btn_clear.clicked.connect(self.clear_all_items)
        btn_clear.setStyleSheet("color: #888; border: none; background: transparent; font-size: 12px;")
        btn_clear.setCursor(Qt.PointingHandCursor)
        
        btn_settings = QPushButton("⚙️")
        btn_settings.setStyleSheet("color: #888; border: none; background: transparent; font-size: 16px;")
        btn_settings.setCursor(Qt.PointingHandCursor)
        btn_settings.clicked.connect(self.show_settings_menu)
        
        footer_layout.addWidget(btn_clear)
        footer_layout.addStretch()
        footer_layout.addWidget(btn_settings)
        
        layout.addLayout(footer_layout)
        
        # Store tab buttons
        self.tab_buttons = [self.btn_all, self.btn_text, self.btn_image, self.btn_fav]

    def create_tab_btn(self, text, active=False):
        btn = QPushButton(text)
        btn.setFixedSize(60, 30)
        btn.setCursor(Qt.PointingHandCursor)
        self.update_tab_style(btn, active)
        return btn
        
    def update_tab_style(self, btn, active):
        if active:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #00afff;
                    color: white;
                    border: none;
                    border-radius: 15px;
                    font-weight: bold;
                }
            """)
        else:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #888;
                    border: none;
                }
                QPushButton:hover { color: #ccc; }
            """)

    def setup_connections(self):
        self.manager.item_added.connect(self.on_item_added)
        self.manager.item_removed.connect(self.on_item_removed)
        self.manager.data_cleared.connect(self.refresh_list)

    def switch_tab(self, filter_type, is_fav, btn_sender):
        self.current_filter = filter_type
        self.show_favorites = is_fav
        
        for btn in self.tab_buttons:
            self.update_tab_style(btn, btn == btn_sender)
            
        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        
        # Get data
        items = self.manager.get_history(limit=50, filter_type=self.current_filter, only_favorites=self.show_favorites)
        
        search_text = self.search_box.text().lower()
        
        for item in items:
            # Client-side search filtering (simple)
            if search_text:
                content_preview = item.get('preview', '').lower()
                if search_text not in content_preview:
                    continue
                    
            self.add_list_item(item)

    def add_list_item(self, item_data):
        item = QListWidgetItem(self.list_widget)
        # Height calculation: Text ~60, Image ~80
        height = 80 if item_data['type'] == 'image' else 60
        item.setSizeHint(QSize(300, height))
        
        widget = ClipboardItemWidget(item_data)
        widget.copy_requested.connect(self.on_copy)
        widget.delete_requested.connect(self.on_delete)
        widget.favorite_toggled.connect(self.on_fav_toggle)
        
        self.list_widget.setItemWidget(item, widget)

    def on_item_added(self, item_id):
        # For simplicity, just refresh. Optimized way: fetch single item and insertTop.
        # But we need to respect filters.
        # Let's just refresh for V1.
        self.refresh_list()

    def on_item_removed(self, item_id):
        self.refresh_list()

    def filter_list(self, text):
        self.refresh_list()

    def on_copy(self, item_id):
        self.manager.copy_to_clipboard(item_id)
        # Maybe show a toast?
        
    def on_delete(self, item_id):
        self.manager.delete_item(item_id)
        
    def on_fav_toggle(self, item_id, is_fav):
        self.manager.set_favorite(item_id, is_fav)
        # If in Favorites tab and unfavorited, refresh
        if self.show_favorites and not is_fav:
            self.refresh_list()

    def clear_all_items(self):
        reply = QMessageBox.question(self, "确认清除", "确定要清除所有历史记录吗？\n(收藏的项目不会被删除)", 
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.manager.clear_all()
            
    def on_item_dbl_click(self, item):
        widget = self.list_widget.itemWidget(item)
        if widget:
            self.on_copy(widget.item_id)

    def show_settings_menu(self):
        # Use the new Dialog instead of Menu
        dialog = ClipboardSettingsDialog(self.manager.config_manager, self)
        # Move dialog to center of this window
        dialog.move(
            self.geometry().center().x() - dialog.width() // 2,
            self.geometry().center().y() - dialog.height() // 2
        )
        
        if dialog.exec() == QDialog.Accepted:
            # Refresh list and trigger cleanup if settings changed
            self.manager.cleanup()
            self.refresh_list()

    # --- Window Dragging ---
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