import sys
import time
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, 
                               QPushButton, QLabel, QSplitter, QApplication, QMessageBox, QProgressBar)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QPixmap, QImage, QIcon
import pyperclip
import cv2
import numpy as np
import traceback

import logging

logger = logging.getLogger("OCRWidget")

try:
    from rapidocr_onnxruntime import RapidOCR
    RapidOCR_Error = None
except ImportError as e:
    RapidOCR = None
    import traceback
    RapidOCR_Error = f"{e}\n{traceback.format_exc()}"
except Exception as e:
    RapidOCR = None
    import traceback
    RapidOCR_Error = f"{e}\n{traceback.format_exc()}"

class OCRWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, image_np):
        super().__init__()
        self.image_np = image_np

    def run(self):
        logger.info("OCRWorker started")
        try:
            if RapidOCR is None:
                logger.error(f"RapidOCR import failed previously: {RapidOCR_Error}")
                raise ImportError(f"rapidocr_onnxruntime import failed.\nDetails: {RapidOCR_Error}")
            
            import sys
            import os
            
            kwargs = {}
            # Handle PyInstaller frozen environment
            if getattr(sys, 'frozen', False):
                logger.info(f"Running in frozen environment. sys.executable: {sys.executable}")
                # Try to locate config.yaml in standard PyInstaller locations
                base_paths = []
                if hasattr(sys, '_MEIPASS'):
                    base_paths.append(sys._MEIPASS)
                    logger.info(f"Added _MEIPASS: {sys._MEIPASS}")
                
                # For onedir mode
                exe_dir = os.path.dirname(sys.executable)
                base_paths.append(exe_dir)
                base_paths.append(os.path.join(exe_dir, '_internal'))
                
                for base in base_paths:
                    config_path = os.path.join(base, 'rapidocr_onnxruntime', 'config.yaml')
                    logger.debug(f"Checking config path: {config_path}")
                    if os.path.exists(config_path):
                        kwargs['config_path'] = config_path
                        logger.info(f"Found config.yaml at: {config_path}")
                        break
            
            logger.info("Initializing RapidOCR engine...")
            engine = RapidOCR(**kwargs)
            logger.info("RapidOCR engine initialized successfully")
            
            # 1. 尝试原始图片
            logger.info("Starting inference on original image")
            result, elapse = engine(self.image_np)
            
            # 2. 如果未识别到，尝试添加白边 (解决文字贴边问题)
            if not result:
                logger.info("No result, trying padding...")
                h, w, c = self.image_np.shape
                pad = 50
                img_padded = np.full((h + 2*pad, w + 2*pad, c), 255, dtype=np.uint8)
                img_padded[pad:pad+h, pad:pad+w] = self.image_np
                result, elapse = engine(img_padded)
            
            # 3. 如果还是未识别到，尝试放大图片 (解决小字问题)
            if not result:
                logger.info("No result, trying scaling...")
                img_scaled = cv2.resize(self.image_np, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                result, elapse = engine(img_scaled)
                
            # 4. 尝试灰度化 + 二值化
            if not result:
                logger.info("No result, trying binarization...")
                gray = cv2.cvtColor(self.image_np, cv2.COLOR_BGR2GRAY)
                _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                # 转回3通道以适配接口
                binary_color = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
                result, elapse = engine(binary_color)
            
            if result:
                logger.info(f"OCR success. Found {len(result)} lines.")
                # result is a list of [box, text, score]
                text = "\n".join([line[1] for line in result])
                self.finished.emit(text)
            else:
                logger.warning("OCR failed to find any text.")
                self.finished.emit("未识别到文字")
        except ImportError as e:
            logger.error(f"ImportError in OCRWorker: {e}", exc_info=True)
            self.error.emit(f"OCR 库加载失败: {str(e)}")
        except Exception as e:
            logger.error(f"Exception in OCRWorker: {e}", exc_info=True)
            self.error.emit(f"OCR 识别出错: {str(e)}")

class OCRWidget(QWidget):
    def __init__(self, image_np, parent=None):
        super().__init__(parent)
        self.image_np = image_np
        self.setWindowTitle("OCR 文字提取")
        self.resize(800, 500)
        
        # 居中显示
        if parent is None:
            screen = QApplication.primaryScreen().geometry()
            self.move((screen.width() - self.width()) // 2, 
                      (screen.height() - self.height()) // 2)
        
        self.init_ui()
        self.start_ocr()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # 分割器：左边图片，右边文字
        splitter = QSplitter(Qt.Horizontal)
        
        # 左侧：图片预览
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #2b2b2b; border: 1px solid #444;")
        self.show_image(self.image_np)
        
        # 右侧：文本区域
        self.right_widget = QWidget()
        right_layout = QVBoxLayout(self.right_widget)
        right_layout.setContentsMargins(0,0,0,0)
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("正在提取文字...")
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #2b2b2b;
                color: #dddddd;
                border: 1px solid #444;
                font-size: 14px;
                padding: 10px;
            }
        """)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # Infinite loop
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar { height: 4px; border: none; background: #333; } QProgressBar::chunk { background: #007aff; }")
        
        right_layout.addWidget(self.text_edit)
        right_layout.addWidget(self.progress_bar)
        
        splitter.addWidget(self.image_label)
        splitter.addWidget(self.right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)
        
        # 底部按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_copy = QPushButton("复制文字")
        self.btn_copy.setFixedSize(100, 35)
        self.btn_copy.clicked.connect(self.copy_text)
        self.btn_copy.setEnabled(False) # Wait for result
        self.btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #007aff;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0069d9;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        
        self.btn_close = QPushButton("关闭")
        self.btn_close.setFixedSize(80, 35)
        self.btn_close.clicked.connect(self.close)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        
        btn_layout.addWidget(self.btn_copy)
        btn_layout.addWidget(self.btn_close)
        
        layout.addLayout(btn_layout)

    def show_image(self, image_np):
        height, width, channel = image_np.shape
        bytes_per_line = 3 * width
        q_img = QImage(image_np.data, width, height, bytes_per_line, QImage.Format_BGR888)
        pixmap = QPixmap.fromImage(q_img)
        
        w = 400
        h = 400
        scaled_pixmap = pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled_pixmap)
        self.image_label.setScaledContents(True)

    def start_ocr(self):
        self.worker = OCRWorker(self.image_np)
        self.worker.finished.connect(self.on_ocr_finished)
        self.worker.error.connect(self.on_ocr_error)
        self.worker.start()

    def on_ocr_finished(self, text):
        self.progress_bar.hide()
        self.text_edit.setText(text)
        self.btn_copy.setEnabled(True)

    def on_ocr_error(self, error_msg):
        self.progress_bar.hide()
        self.text_edit.setText(error_msg)
        self.btn_copy.setEnabled(False)

    def copy_text(self):
        text = self.text_edit.toPlainText()
        if text:
            pyperclip.copy(text)
            self.btn_copy.setText("已复制!")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1000, lambda: self.btn_copy.setText("复制文字"))