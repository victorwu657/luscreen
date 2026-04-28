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
        
        logs_dir = os.path.join(base_path, 'logs')
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
            
        log_file = os.path.join(logs_dir, 'camera_debug.log')
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
        self.shape_mode = 'circle' # 'circle', 'square', 'custom'
        self.aspect_ratio = 1.0 # default square/circle
        self.border_color = Qt.white
        self.border_width = 4
        
        # 拖拽相关
        self.old_pos = None
        
        # 全屏模式
        self.is_fullscreen_mode = False
        self.pre_fullscreen_geometry = None
        self.pre_fullscreen_shape = None

        # 初始化UI
        self.init_ui()
        # 默认位置逻辑在 init 后根据场景调用，但作为通用组件，我们先设为右下角（兼容全屏录制场景）
        # 外部（如 ControlPanel 或 MainWindow）可以在创建后根据需要调用 move_to_center
        self.move_to_bottom_right()

    def move_to_bottom_right(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.width() - self.width() - 50
        y = screen.height() - self.height() - 50
        self.move(x, y)

    def move_to_center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
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
        
        # 尝试设置高清分辨率 (1920x1080)
        # 很多摄像头默认以 640x480 启动，需要手动请求更高分辨率
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            
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
            print(f"[DEBUG] Camera Opened: {w}x{h} @ {fps}fps") # Console output for user visibility
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
        
        # 根据形状调整窗口比例，保持当前宽度
        if shape == '4:3':
            self.shape_mode = 'custom'
            self.set_aspect_ratio(4/3)
        elif shape == '3:4':
            self.shape_mode = 'custom'
            self.set_aspect_ratio(3/4)
        elif shape == 'circle':
            self.shape_mode = 'circle'
            self.set_aspect_ratio(1.0)
        elif shape == 'square':
            self.shape_mode = 'square'
            self.set_aspect_ratio(1.0)
        elif shape == '3:2':
            self.shape_mode = 'custom'
            self.set_aspect_ratio(3/2)
        elif shape == '2:3':
            self.shape_mode = 'custom'
            self.set_aspect_ratio(2/3)
        elif shape == '16:9':
            self.shape_mode = 'custom'
            self.set_aspect_ratio(16/9)
        elif shape == '9:16':
            self.shape_mode = 'custom'
            self.set_aspect_ratio(9/16)
        else:
            # Try to parse "W:H"
            try:
                parts = shape.split(':')
                if len(parts) == 2:
                    w = float(parts[0])
                    h = float(parts[1])
                    self.shape_mode = 'custom'
                    self.set_aspect_ratio(w/h)
            except:
                pass
            
        self.update()

    def set_aspect_ratio(self, ratio):
        self.aspect_ratio = ratio
        current_width = self.width()
        new_height = int(current_width / ratio)
        self.resize(current_width, new_height)
        self.update()

    def set_border_visible(self, visible):
        self.border_width = 4 if visible else 0
        self.update()

    def set_fullscreen(self, enabled):
        if enabled:
            if not self.is_fullscreen_mode:
                self.is_fullscreen_mode = True
                self.pre_fullscreen_geometry = self.geometry()
                self.pre_fullscreen_shape = self.shape_mode
                self.pre_fullscreen_ratio = self.aspect_ratio
                
                # 获取屏幕尺寸
                screen = QApplication.primaryScreen().geometry()
                self.setGeometry(screen)
                self.shape_mode = 'fullscreen'
                self.aspect_ratio = screen.width() / screen.height()
                self.border_width = 0
                self.update()
        else:
            if self.is_fullscreen_mode:
                self.is_fullscreen_mode = False
                if self.pre_fullscreen_geometry:
                    self.setGeometry(self.pre_fullscreen_geometry)
                if self.pre_fullscreen_shape:
                    self.shape_mode = self.pre_fullscreen_shape
                if self.pre_fullscreen_ratio:
                    self.aspect_ratio = self.pre_fullscreen_ratio
                self.border_width = 4 # Restore border
                self.update()

    def update_frame(self):
        if not self.cap or not self.cap.isOpened():
            if self.frame_count % 300 == 0: # Log every ~10 seconds
                self.logger.warning("Camera capture is not opened.")
            self.frame_count += 1
            return

        try:
            ret, frame = self.cap.read()
            
            if self.frame_count < 5: # Log first 5 frames details
                self.logger.debug(f"Frame {self.frame_count}: read success={ret}, shape={frame.shape if ret else 'None'}")
            
            self.frame_count += 1
            
            if ret:
                h, w, ch = frame.shape
                
                # 根据目标形状计算裁剪区域
                target_ratio = self.aspect_ratio
                
                # 1. 计算理论上的目标尺寸
                current_ratio = w / h
                if current_ratio > target_ratio:
                    # 画面太宽，以高度为基准
                    new_w = int(h * target_ratio)
                    new_h = int(h)
                else:
                    # 画面太高，以宽度为基准
                    new_h = int(w / target_ratio)
                    new_w = int(w)
                
                # 2. 强制对齐到 32 像素 (与 get_recording_size 保持一致)
                final_w = (new_w // 32) * 32
                final_h = (new_h // 32) * 32
                
                # 3. 执行中心裁剪
                if final_w > 0 and final_h > 0:
                    start_x = (w - final_w) // 2
                    start_y = (h - final_h) // 2
                    frame = frame[start_y:start_y+final_h, start_x:start_x+final_w]
                
                # Store full resolution frame for recording (BGRA for compatibility)
                # OpenCV default is BGR. We convert to BGRA for recorder (matches MSS format)
                # 使用临时变量处理，最后一次性赋值给 self.last_frame_full_res，避免竞态条件
                processed_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
                
                # 镜像处理 (如果需要，通常摄像头是镜像的)
                # 统一：先处理成 BGRA，最后做 flip。
                processed_frame = cv2.flip(processed_frame, 1)
                
                # 原子性更新共享变量
                self.last_frame_full_res = processed_frame

                # 缩放以适应窗口显示
                display_frame = cv2.resize(self.last_frame_full_res, (self.width(), self.height()))
                
                # Store processed frame for recorder (Legacy)
                # self.last_frame_rgb = ... (No longer needed if we use full_res)
                
                # 转换为QImage (BGRA -> Format_ARGB32)
                h, w, ch = display_frame.shape
                bytes_per_line = ch * w
                # 内存中是 B G R A，对应 Little Endian 的 ARGB32
                q_img = QImage(display_frame.data, w, h, bytes_per_line, QImage.Format_ARGB32)
                
                self.current_pixmap = QPixmap.fromImage(q_img)
                self.update() # 触发 paintEvent

        except cv2.error as e:
            if e.code == cv2.Error.StsNoMem: # OOM
                self.logger.error("OpenCV OOM detected during frame processing. Triggering GC and skipping frame.")
                import gc
                gc.collect()
            else:
                self.logger.error(f"OpenCV error in update_frame: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in update_frame: {e}")

    def get_current_frame(self):
        """Return the latest processed frame in RGB format."""
        if hasattr(self, 'last_frame_full_res'):
            return self.last_frame_full_res
        elif hasattr(self, 'last_frame_rgb'):
            return self.last_frame_rgb
        return None

    def get_recording_size(self):
        """Calculate the optimal recording size based on camera native resolution and aspect ratio."""
        if self.cap and self.cap.isOpened():
            w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            
            if w > 0 and h > 0:
                target_ratio = self.aspect_ratio
                current_ratio = w / h
                
                if current_ratio > target_ratio:
                    # Too wide, crop width
                    new_w = int(h * target_ratio)
                    new_h = int(h)
                else:
                    # Too tall, crop height
                    new_h = int(w / target_ratio)
                    new_w = int(w)
                
                # Ensure dimensions are multiples of 32 for best compatibility (H.264/HEVC/WMF)
                new_w = (new_w // 32) * 32
                new_h = (new_h // 32) * 32
                return new_w, new_h
                
        # Fallback to current widget size
        return self.width(), self.height()

    def paintEvent(self, event):
        if not hasattr(self, 'current_pixmap'):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 全屏模式直接绘制，不使用路径裁剪
        if self.is_fullscreen_mode:
            painter.drawPixmap(0, 0, self.width(), self.height(), self.current_pixmap)
            return

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
        height = int(width / self.aspect_ratio)
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
            ('竖向 3:4', '3:4'),
            ('横向 3:2', '3:2'),
            ('竖向 2:3', '2:3'),
            ('横向 16:9', '16:9'),
            ('竖向 9:16', '9:16')
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
        if hasattr(self, 'timer') and self.timer.isActive():
            self.timer.stop()
        
        if self.cap:
            self.cap.release()
            self.cap = None
            
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    camera = CameraWidget()
    camera.show()
    sys.exit(app.exec())