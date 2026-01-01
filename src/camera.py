import sys
import cv2
import numpy as np
import logging
import os
from PySide6.QtCore import Qt, QTimer, QPoint, QSize
from PySide6.QtGui import QImage, QPixmap, QPainter, QPainterPath, QRegion, QMouseEvent, QAction
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QVBoxLayout, QLabel
from PySide6.QtMultimedia import QMediaDevices

def setup_logger():
    """Setup a logger for camera debugging."""
    logger = logging.getLogger('CameraWidget')
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        log_file = os.path.join(base_path, 'camera_debug.log')
        fh = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    return logger

class CameraWidget(QWidget):
    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self.logger = setup_logger()
        self.logger.info(f"Initializing CameraWidget with index: {camera_index}")
        
        self.camera_index = camera_index
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground) # 优化录制捕获
        self.setAutoFillBackground(False)
        
        # 默认尺寸
        self.default_size = 200
        self.resize(self.default_size, self.default_size)
        
        # 摄像头设置
        self.cap = None
        self.start_camera(self.camera_index)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30) # 30 FPS
        
        # 样式设置
        self.shape_mode = 'circle' # 'circle', 'square', '4:3', '3:4'
        self.border_color = Qt.white
        self.border_width = 4
        
        # 拖拽相关
        self.old_pos = None

        # 初始化UI
        self.init_ui()
        self.move_to_bottom_right()

    def move_to_bottom_right(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.width() - self.width() - 50
        y = screen.height() - self.height() - 50
        self.move(x, y)

    @staticmethod
    def get_available_cameras():
        """返回可用摄像头的列表 [{'name': 'Camera Name', 'index': 0}, ...]"""
        cameras = []
        devices = QMediaDevices.videoInputs()
        for i, device in enumerate(devices):
            cameras.append({
                'name': device.description(),
                'index': i
            })
        # 如果找不到（某些环境），回退到默认
        if not cameras:
            cameras.append({'name': 'Default Camera', 'index': 0})
        return cameras

    def start_camera(self, index):
        self.logger.info(f"Attempting to start camera index: {index}")
        if self.cap:
            self.cap.release()
            self.logger.info("Released previous camera")
        
        # Log available devices for debugging
        try:
            devices = QMediaDevices.videoInputs()
            self.logger.info(f"Available QMediaDevices: {[d.description() for d in devices]}")
        except Exception as e:
            self.logger.error(f"Failed to list QMediaDevices: {e}")

        # 尝试打开指定索引的摄像头
        # 注意：QMediaDevices 的索引顺序通常与 OpenCV 的索引顺序一致，但不保证 100%
        # 在 Windows 上通常是匹配的
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) # 使用 DirectShow 提高兼容性
        if not self.cap.isOpened():
            self.logger.warning(f"Failed to open camera {index} with CAP_DSHOW. Retrying with default backend...")
            # 如果失败，尝试不带 API 后端参数
            self.cap = cv2.VideoCapture(index)
            
        if self.cap.isOpened():
            self.logger.info(f"Camera {index} opened successfully.")
            # Log camera properties
            w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            self.logger.info(f"Camera Properties - Width: {w}, Height: {h}, FPS: {fps}")
        else:
            self.logger.error(f"Failed to open camera {index} with any backend.")
            
        self.camera_index = index
        self.frame_count = 0 # for logging throttle

    def change_camera(self, index):
        self.start_camera(index)

    def init_ui(self):
        # 右键菜单
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def set_shape(self, shape):
        current_width = self.width()
        self.shape_mode = shape
        
        # 根据形状调整窗口比例，保持当前宽度
        if shape == '4:3':
            new_height = int(current_width * 3 / 4)
            self.resize(current_width, new_height)
        elif shape == '3:4':
            # 3:4 模式下，如果保持宽度，高度会变大
            new_height = int(current_width * 4 / 3)
            self.resize(current_width, new_height)
        else:
            # Circle / Square
            self.resize(current_width, current_width)
            
        self.update()

    def set_border_visible(self, visible):
        self.border_width = 4 if visible else 0
        self.update()

    def update_frame(self):
        if not self.cap or not self.cap.isOpened():
            if self.frame_count % 300 == 0: # Log every ~10 seconds
                self.logger.warning("Camera capture is not opened.")
            self.frame_count += 1
            return

        ret, frame = self.cap.read()
        
        if self.frame_count < 5: # Log first 5 frames details
            self.logger.debug(f"Frame {self.frame_count}: read success={ret}, shape={frame.shape if ret else 'None'}")
        
        self.frame_count += 1
        
        if ret:
            # OpenCV BGR -> RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.flip(frame, 1)
            
            h, w, ch = frame.shape
            
            # 根据目标形状计算裁剪区域
            target_ratio = 1.0
            if self.shape_mode == '4:3':
                target_ratio = 4/3
            elif self.shape_mode == '3:4':
                target_ratio = 3/4
            
            # 计算裁剪
            current_ratio = w / h
            if current_ratio > target_ratio:
                # 画面太宽，裁剪两边
                new_w = int(h * target_ratio)
                start_x = (w - new_w) // 2
                frame = frame[:, start_x:start_x+new_w]
            else:
                # 画面太高，裁剪上下
                new_h = int(w / target_ratio)
                start_y = (h - new_h) // 2
                frame = frame[start_y:start_y+new_h, :]
            
            # 缩放以适应窗口
            frame = cv2.resize(frame, (self.width(), self.height()))
            
            # 转换为QImage
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            
            self.current_pixmap = QPixmap.fromImage(q_img)
            self.update() # 触发 paintEvent

    def paintEvent(self, event):
        if not hasattr(self, 'current_pixmap'):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制路径
        path = QPainterPath()
        rect = self.rect().adjusted(self.border_width, self.border_width, -self.border_width, -self.border_width)
        
        if self.shape_mode == 'circle':
            path.addEllipse(rect)
        else:
            # 所有矩形模式都使用圆角
            path.addRoundedRect(rect, 20, 20)

        # 设置裁剪区域，只显示摄像头内容在路径内
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, self.width(), self.height(), self.current_pixmap)
        
        # 绘制边框
        painter.setClipping(False)
        pen = painter.pen()
        pen.setWidth(self.border_width)
        pen.setColor(self.border_color)
        painter.setPen(pen)
        painter.drawPath(path)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.old_pos = None

    def wheelEvent(self, event):
        """鼠标滚轮调整大小"""
        delta = event.angleDelta().y()
        step = 20 # 每次调整的像素值
        
        current_width = self.width()
        
        if delta > 0:
            new_width = min(current_width + step, 800) # 最大 800
        else:
            new_width = max(current_width - step, 100) # 最小 100
            
        if new_width != current_width:
            self.set_shape(self.shape_mode) # 重新计算高度
            # 实际上 set_shape 使用了 self.width()，所以我们需要先 resize 宽度，或者传递宽度给 set_size
            self.resize_to_width(new_width)

    def resize_to_width(self, width):
        if self.shape_mode == '4:3':
            height = int(width * 3 / 4)
        elif self.shape_mode == '3:4':
            height = int(width * 4 / 3)
        else:
            height = width
        self.resize(width, height)
        self.update()

    def show_context_menu(self, pos):
        menu = QMenu(self)
        
        # 尺寸子菜单
        size_menu = QMenu("尺寸", self)
        sizes = [
            ('小 (150px)', 150),
            ('中 (250px)', 250),
            ('大 (350px)', 350),
            ('特大 (500px)', 500)
        ]
        for name, width in sizes:
            action = QAction(name, self)
            action.triggered.connect(lambda c=False, w=width: self.resize_to_width(w))
            size_menu.addAction(action)
        menu.addMenu(size_menu)

        # 形状子菜单
        shape_menu = QMenu("形状", self)
        shapes = [
            ('圆形', 'circle'),
            ('圆角正方形', 'square'),
            ('横向 4:3', '4:3'),
            ('竖向 3:4', '3:4')
        ]
        for name, mode in shapes:
            action = QAction(name, self)
            if self.shape_mode == mode:
                action.setCheckable(True)
                action.setChecked(True)
            action.triggered.connect(lambda c=False, m=mode: self.set_shape(m))
            shape_menu.addAction(action)
        
        menu.addMenu(shape_menu)
        menu.addSeparator()
        
        close_action = QAction("关闭摄像头", self)
        close_action.triggered.connect(self.close)
        menu.addAction(close_action)
        
        menu.exec(self.mapToGlobal(pos))

    def toggle_shape(self):
        # 废弃，改用 set_shape
        pass

    def closeEvent(self, event):
        self.cap.release()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    camera = CameraWidget()
    camera.show()
    sys.exit(app.exec())