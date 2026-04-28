from PySide6.QtWidgets import QWidget, QRubberBand, QPushButton, QHBoxLayout, QVBoxLayout, QFrame, QApplication, QMenu, QMessageBox
from PySide6.QtCore import Qt, QRect, QPoint, QSize, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QCursor, QAction
from src.control_panel import ControlPanel
import logging
import os

logger = logging.getLogger("SelectionWidget")

class SelectionWidget(QWidget):
    # 定义信号
    area_selected = Signal(QRect, str) # 包含最终选区和模式
    scroll_area_selected = Signal(QRect) # 新增信号
    camera_ratio_changed = Signal(float) # 相机比例变更
    mode_changed = Signal(str) # 模式变更信号
    cancelled = Signal()
    
    # 转发控制面板的信号
    settings_changed = Signal(dict) # {type: 'mic'/'cam', value: ...}

    def __init__(self, control_panel, mode='record'):
        logger.info(f"Initializing SelectionWidget mode={mode}")
        super().__init__()
        self.mode = mode # 'record', 'capture' or 'ocr'
        self.control_panel = control_panel

        if os.name == "nt":
            try:
                import ctypes
                title = "截图" if mode == "capture" else "LuScreen"
                ctypes.windll.kernel32.SetConsoleTitleW(str(title))
            except Exception:
                pass
        
        # 全屏无边框，置顶
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        
        # 获取屏幕几何信息
        screen = QApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        
        # 状态
        self.start_point = None
        self.end_point = None
        self.is_selecting = False
        self.is_resizing = False
        self.resize_edge = None # 'top', 'bottom', 'left', 'right', 'top-left', ...
        self.selection_rect = screen.geometry() # 默认全屏
        self.aspect_ratio = None
        
        # 边缘检测阈值
        self.handle_size = 10
        
        # 连接控制面板信号
        self.control_panel.mode_changed.connect(self.on_mode_changed)
        self.control_panel.size_changed.connect(self.update_selection_from_panel)
        self.control_panel.ratio_changed.connect(self.set_aspect_ratio)
        self.control_panel.record_clicked.connect(self.confirm_selection)
        self.control_panel.ocr_clicked.connect(self.confirm_selection) # OCR 也是确认选区
        self.control_panel.scroll_capture_clicked.connect(self.confirm_scroll_selection)
        self.control_panel.cancel_clicked.connect(self.cancel_selection)
        
        # 转发设置信号
        self.control_panel.mic_toggled.connect(lambda v: self.settings_changed.emit({'type': 'mic_toggle', 'value': v}))
        self.control_panel.mic_changed.connect(lambda v: self.settings_changed.emit({'type': 'mic_idx', 'value': v}))
        self.control_panel.sys_audio_toggled.connect(lambda v: self.settings_changed.emit({'type': 'sys_toggle', 'value': v}))
        self.control_panel.camera_toggled.connect(lambda v: self.settings_changed.emit({'type': 'cam_toggle', 'value': v}))
        self.control_panel.camera_changed.connect(lambda v: self.settings_changed.emit({'type': 'cam_idx', 'value': v}))
        self.control_panel.camera_size_changed.connect(lambda v: self.settings_changed.emit({'type': 'cam_size', 'value': v}))
        self.control_panel.camera_shape_changed.connect(lambda v: self.settings_changed.emit({'type': 'cam_shape', 'value': v}))
        self.control_panel.mouse_style_changed.connect(lambda v: self.settings_changed.emit({'type': 'mouse_style', 'value': v}))
        
        # 如果是截图或OCR模式，面板可以简化
        if self.mode == 'capture':
            self.control_panel.set_capture_mode()
        elif self.mode == 'ocr':
            self.control_panel.set_ocr_mode()
            
        # 初始模式
        if self.mode in ['capture', 'ocr']:
            self.current_mode = 'area'
            self.control_panel.set_mode('area')
            # 清空初始选区，等待用户拖拽
            self.selection_rect = QRect()
        else:
            # 录屏模式默认空闲
            self.current_mode = None
            self.control_panel.set_mode(None)
            self.selection_rect = QRect()
        
    def on_mode_changed(self, mode):
        logger.info(f"Mode changed to: {mode}")
        self.current_mode = mode
        self.mode_changed.emit(mode)
        if mode == 'fullscreen':
            self.selection_rect = self.rect()
            logger.info("Showing fullscreen selection")
            self.show() # 显示全屏遮罩
            self.raise_() # 确保在最上层
            self.control_panel.raise_() # 面板必须在遮罩之上
            self.update()
            # 全屏时更新面板数字
            self.control_panel.update_size_display(self.rect().width(), self.rect().height())
        elif mode == 'area':
            # 切换到区域模式，默认无选区，等待用户拖拽
            self.selection_rect = QRect()
            logger.info("Showing area selection (empty)")
            self.show() # 显示全屏遮罩以捕获鼠标
            self.raise_()
            self.control_panel.raise_()
            self.update()
            # 显示面板（在底部），允许用户取消
            self.show_panel()
        elif mode == 'camera_only' or mode == 'audio_only':
            self.selection_rect = QRect()
            # Hide mask for camera/audio only modes to avoid black screen
            self.hide() 
            self.control_panel.show()
            self.control_panel.raise_()
            self.show_panel()
            
            # Special handling for camera_only: show camera if hidden
            if mode == 'camera_only':
                # We can't directly access camera_widget here easily, 
                # but the mode_changed signal will trigger logic in main.py
                pass
        elif mode is None or mode == "":
            logger.info("Mode changed to None (Reset)")
            self.selection_rect = QRect()
            self.hide() # 隐藏全屏遮罩，恢复桌面交互
            self.update() # 触发重绘以清除任何残留的绘制（如全屏边框）

    def set_aspect_ratio(self, ratio):
        if self.current_mode == 'camera_only':
            if ratio is not None:
                self.camera_ratio_changed.emit(ratio)
            return

        self.aspect_ratio = ratio
        if not self.selection_rect.isNull() and ratio is not None:
            # 立即调整当前选区符合比例
            # 保持当前宽度，调整高度
            w = self.selection_rect.width()
            h = int(w / ratio)
            
            # 如果高度超出屏幕，则反过来调整宽度
            if self.selection_rect.top() + h > self.height():
                 h = self.selection_rect.height()
                 w = int(h * ratio)
            
            center = self.selection_rect.center()
            self.selection_rect.setSize(QSize(w, h))
            self.selection_rect.moveCenter(center)
            self.update()
            self.show_panel()
            
    def paintEvent(self, event):
        # logger.debug("paintEvent") # Reduce spam
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制半透明遮罩
        painter.setBrush(QColor(0, 0, 0, 100)) # 黑色，透明度100/255
        painter.setPen(Qt.NoPen)
        painter.drawRect(self.rect())
        
        # 如果有选区，清除选区内的遮罩（使其透明）并绘制边框
        if not self.selection_rect.isNull():
            # 使用 CompositionMode_Clear 挖空选区
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.setBrush(Qt.transparent)
            painter.drawRect(self.selection_rect)
            
            # 恢复正常模式
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            
            # 填充一层极低不透明度的颜色以捕获鼠标
            painter.setBrush(QColor(255, 255, 255, 1))
            painter.setPen(Qt.NoPen)
            painter.drawRect(self.selection_rect)
            
            # 绘制红色细虚线边框
            pen = QPen(Qt.red, 1, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.selection_rect)
            
            # 绘制拖拽手柄
            self.draw_handles(painter)
            
            # 显示尺寸文字
            text = f"{self.selection_rect.width()} x {self.selection_rect.height()}"
            painter.setPen(Qt.white)
            tl = self.selection_rect.topLeft()
            painter.drawText(QPoint(tl.x(), tl.y() - 5), text)


    def draw_handles(self, painter):
        if self.selection_rect.isNull(): return
        
        r = self.selection_rect
        radius = 5
        
        painter.setBrush(Qt.white)
        painter.setPen(QPen(Qt.black, 1)) # 给手柄加个黑色边框，增强对比度
        
        # 8个控制点
        points = [
            r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight(),
            QPoint(r.center().x(), r.top()),
            QPoint(r.center().x(), r.bottom()),
            QPoint(r.left(), r.center().y()),
            QPoint(r.right(), r.center().y())
        ]
        
        for p in points:
            painter.drawEllipse(p, radius, radius)

    def get_resize_edge(self, pos):
        if self.selection_rect.isNull(): return None
        
        r = self.selection_rect
        x, y = pos.x(), pos.y()
        hs = self.handle_size
        
        # 检查角落
        if abs(r.top() - y) < hs and abs(r.left() - x) < hs: return 'top-left'
        if abs(r.top() - y) < hs and abs(r.right() - x) < hs: return 'top-right'
        if abs(r.bottom() - y) < hs and abs(r.left() - x) < hs: return 'bottom-left'
        if abs(r.bottom() - y) < hs and abs(r.right() - x) < hs: return 'bottom-right'
        
        # 检查边缘
        if abs(r.top() - y) < hs and r.left() < x < r.right(): return 'top'
        if abs(r.bottom() - y) < hs and r.left() < x < r.right(): return 'bottom'
        if abs(r.left() - x) < hs and r.top() < y < r.bottom(): return 'left'
        if abs(r.right() - x) < hs and r.top() < y < r.bottom(): return 'right'
        
        # 检查内部 (移动)
        if r.contains(pos): return 'inside'
        
        return None

    def set_cursor_for_edge(self, edge):
        if edge in ['top', 'bottom']: self.setCursor(Qt.SizeVerCursor)
        elif edge in ['left', 'right']: self.setCursor(Qt.SizeHorCursor)
        elif edge in ['top-left', 'bottom-right']: self.setCursor(Qt.SizeFDiagCursor)
        elif edge in ['top-right', 'bottom-left']: self.setCursor(Qt.SizeBDiagCursor)
        elif edge == 'inside': self.setCursor(Qt.SizeAllCursor)
        else: self.setCursor(Qt.CrossCursor)

    def mousePressEvent(self, event):
        if self.current_mode == 'area' and event.button() == Qt.LeftButton:
            edge = self.get_resize_edge(event.pos())
            
            if edge:
                # 调整现有选区
                self.is_resizing = True
                self.resize_edge = edge
                self.start_point = event.pos()
                self.original_rect = QRect(self.selection_rect)
                self.control_panel.hide() # 仅在开始调整时隐藏
            elif not self.selection_rect.contains(event.pos()):
                # 点击选区外部，开始创建新选区
                self.start_point = event.pos()
                self.is_selecting = True
                self.selection_rect = QRect()
                self.control_panel.hide() # 仅在开始创建时隐藏
            
            # 如果点击的是选区内部但没有命中边缘（移动模式），我们在 move 时再隐藏
            # 或者干脆不隐藏，因为移动时通常希望看到实时效果
            
            self.update()

    def mouseMoveEvent(self, event):
        # 1. 如果正在选择（创建新选区）
        if self.is_selecting and self.start_point:
            self.end_point = event.pos()
            # ... (保持原逻辑)
            rect = QRect(self.start_point, self.end_point).normalized()
            if self.aspect_ratio is not None:
                w = rect.width()
                h = int(w / self.aspect_ratio)
                if rect.height() < h: h = rect.height(); w = int(h * self.aspect_ratio)
                rect.setSize(QSize(w, h))
            self.selection_rect = rect
            self.update()
            return

        # 2. 如果正在调整大小/移动
        if self.is_resizing and self.resize_edge:
            self.control_panel.hide() # 确保拖拽过程中隐藏
            curr_pos = event.pos()
            
            # 移动模式 (Inside) 不受比例影响
            if self.resize_edge == 'inside':
                dx = curr_pos.x() - self.start_point.x()
                dy = curr_pos.y() - self.start_point.y()
                rect = QRect(self.original_rect)
                rect.translate(dx, dy)
                self.selection_rect = rect.normalized()
                self.update()
                return

            # 调整大小模式
            rect = QRect(self.original_rect)
            
            if self.aspect_ratio is not None:
                # --- 比例锁定模式 ---
                edge = self.resize_edge
                ratio = self.aspect_ratio
                orig = self.original_rect
                dx = curr_pos.x() - self.start_point.x()
                dy = curr_pos.y() - self.start_point.y()
                
                # 1. 拖拽角：基于宽计算高 (或反之)，固定对角
                if edge in ['top-left', 'top-right', 'bottom-left', 'bottom-right']:
                    # 确定锚点 (Anchor)
                    if edge == 'bottom-right': anchor = orig.topLeft()
                    elif edge == 'top-left': anchor = orig.bottomRight()
                    elif edge == 'top-right': anchor = orig.bottomLeft()
                    elif edge == 'bottom-left': anchor = orig.topRight()
                    
                    # 简单策略：以宽度变化为驱动
                    if 'right' in edge: new_w = curr_pos.x() - anchor.x()
                    else: new_w = anchor.x() - curr_pos.x()
                    
                    # 避免翻转或过小
                    if new_w < 10: new_w = 10
                    
                    new_h = int(new_w / ratio)
                    
                    # 重建 rect
                    new_rect = QRect(0, 0, new_w, new_h)
                    
                    # 重新定位到锚点
                    if 'right' in edge: new_rect.moveLeft(anchor.x())
                    else: new_rect.moveRight(anchor.x())
                    
                    if 'bottom' in edge: new_rect.moveTop(anchor.y())
                    else: new_rect.moveBottom(anchor.y())
                    
                    rect = new_rect

                # 2. 拖拽边：以边为驱动，中心扩散
                else:
                    if edge == 'right':
                        new_w = max(10, orig.width() + dx)
                        new_h = int(new_w / ratio)
                        rect.setWidth(new_w)
                        rect.setHeight(new_h)
                        rect.moveTop(orig.center().y() - new_h // 2)
                        
                    elif edge == 'left':
                        new_w = max(10, orig.width() - dx)
                        new_h = int(new_w / ratio)
                        rect.setLeft(orig.right() - new_w)
                        rect.setHeight(new_h)
                        rect.moveTop(orig.center().y() - new_h // 2)
                        
                    elif edge == 'bottom':
                        new_h = max(10, orig.height() + dy)
                        new_w = int(new_h * ratio)
                        rect.setHeight(new_h)
                        rect.setWidth(new_w)
                        rect.moveLeft(orig.center().x() - new_w // 2)
                        
                    elif edge == 'top':
                        new_h = max(10, orig.height() - dy)
                        new_w = int(new_h * ratio)
                        rect.setTop(orig.bottom() - new_h)
                        rect.setWidth(new_w)
                        rect.moveLeft(orig.center().x() - new_w // 2)

            else:
                # --- 自由模式 (原逻辑) ---
                dx = curr_pos.x() - self.start_point.x()
                dy = curr_pos.y() - self.start_point.y()
                if 'left' in self.resize_edge: rect.setLeft(rect.left() + dx)
                if 'right' in self.resize_edge: rect.setRight(rect.right() + dx)
                if 'top' in self.resize_edge: rect.setTop(rect.top() + dy)
                if 'bottom' in self.resize_edge: rect.setBottom(rect.bottom() + dy)
            
            self.selection_rect = rect.normalized()
            self.update()
            return

        # 3. 仅仅是移动鼠标
        if self.current_mode == 'area' and not self.selection_rect.isNull():
            edge = self.get_resize_edge(event.pos())
            self.set_cursor_for_edge(edge)
        else:
            self.setCursor(Qt.CrossCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_selecting = False
            self.is_resizing = False
            self.resize_edge = None
            
            # 无论刚才做了什么，只要现在有有效的选区，就显示面板
            if not self.selection_rect.isNull() and self.selection_rect.width() > 10 and self.selection_rect.height() > 10:
                self.show_panel()
            else:
                # 如果选区无效（太小），如果是全屏模式则不管，如果是区域模式且之前没选区则不显示
                if self.current_mode == 'fullscreen':
                    self.show_panel()
            
            self.update()

    def show_panel(self):
        # 更新面板上的数字
        self.control_panel.update_size_display(self.selection_rect.width(), self.selection_rect.height())
        
        # 计算位置
        self.control_panel.adjustSize()
        panel_w = self.control_panel.width()
        panel_h = self.control_panel.height()
        
        # 水平居中于选区
        if self.selection_rect.isNull():
            center_x = self.rect().center().x()
        else:
            center_x = self.selection_rect.center().x()
            
        x = center_x - panel_w // 2
        
        # 垂直位置：默认在选区下方
        if self.selection_rect.isNull():
            # 无选区（初始状态），放在屏幕底部上方
            y = self.rect().bottom() - panel_h - 50
        else:
            y = self.selection_rect.bottom() + 15
            
            # 如果下方空间不足（例如全屏或接近底部），则放在选区内部底部，或者上方
            screen_bottom = self.rect().bottom()
            if y + panel_h > screen_bottom:
                # 尝试放在上方
                y = self.selection_rect.top() - panel_h - 15
                
                # 如果上方也空间不足（例如全屏），则放在屏幕底部上方（悬浮在画面上）
                if y < 0:
                     y = screen_bottom - panel_h - 50

        # 最后的屏幕边界检查 (Clamping to SelectionWidget bounds)
        # 注意：SelectionWidget 通常只覆盖主屏幕，但在多屏下可能需要覆盖所有屏幕
        # 这里保留基本的 Clamping 防止超出 SelectionWidget
        # if x < 0: x = 0
        # if x + panel_w > self.width(): x = self.width() - panel_w
        # if y < 0: y = 0
        # if y + panel_h > self.height(): y = self.height() - panel_h
        
        # --- 鲁棒性增强：屏幕可见性检查 ---
        # 防止面板因断开显示器等原因出现在不可见区域
        is_visible = False
        panel_rect = QRect(x, y, panel_w, panel_h)
        
        for screen in QApplication.screens():
            if screen.geometry().intersects(panel_rect):
                is_visible = True
                break
        
        if not is_visible:
            logger.warning(f"ControlPanel position {x},{y} is off-screen. Resetting to primary screen center.")
            primary = QApplication.primaryScreen().geometry()
            x = primary.left() + primary.width() // 2 - panel_w // 2
            y = primary.top() + primary.height() // 2 - panel_h // 2
            
        self.control_panel.move(x, y)
        self.control_panel.show()
        self.control_panel.raise_() # 确保在最顶层

    def update_selection_from_panel(self, w, h):
        if self.current_mode == 'area':
            if self.selection_rect.isNull():
                center = self.rect().center()
                self.selection_rect = QRect(0, 0, w, h)
                self.selection_rect.moveCenter(center)
            else:
                center = self.selection_rect.center()
                self.selection_rect.setSize(QSize(w, h))
                self.selection_rect.moveCenter(center)
            self.update()
            self.show_panel()
        elif self.current_mode == 'fullscreen':
            # 修改尺寸意味着切换到区域模式
            self.control_panel.set_mode('area')
            self.update_selection_from_panel(w, h)

    def confirm_selection(self):
        # 如果是纯摄像头模式或纯音频模式，不需要选区
        if self.current_mode != 'camera_only' and self.current_mode != 'audio_only':
            if self.selection_rect.isNull() or self.selection_rect.width() <= 0 or self.selection_rect.height() <= 0:
                QMessageBox.warning(self, "提示", "请先用鼠标框选区域")
                return

        self.hide() # 先隐藏自己
        self.control_panel.hide() # 隐藏面板
        QApplication.processEvents() # 让系统处理隐藏事件
        self.close()
        self.control_panel.close()
        self.area_selected.emit(self.selection_rect, self.current_mode)

    def confirm_scroll_selection(self):
        if self.selection_rect.isNull() or self.selection_rect.width() <= 0 or self.selection_rect.height() <= 0:
            QMessageBox.warning(self, "提示", "请先用鼠标框选区域")
            return

        self.hide() 
        self.control_panel.hide()
        QApplication.processEvents()
        self.close()
        self.control_panel.close()
        self.scroll_area_selected.emit(self.selection_rect)

    def cancel_selection(self):
        self.close()
        self.control_panel.close()
        self.cancelled.emit()
        
    def select_fullscreen(self):
        # 废弃
        pass
        
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancel_selection()
