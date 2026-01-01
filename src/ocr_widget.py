import sys
import time
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, 
                               QPushButton, QLabel, QSplitter, QApplication, QMessageBox, QProgressBar)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QPixmap, QImage, QIcon
import pyperclip
import cv2
import numpy as np

class OCRWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, image_np):
        super().__init__()
        self.image_np = image_np

    def run(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
            engine = RapidOCR()
            result, elapse = engine(self.image_np)
            
            if result:
                # result is a list of [box, text, score]
                text = "\n".join([line[1] for line in result])
                self.finished.emit(text)
            else:
                self.finished.emit("未识别到文字")
        except ImportError:
            self.error.emit("错误：未安装 rapidocr_onnxruntime 库。\n请运行: pip install rapidocr_onnxruntime")
        except Exception as e:
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