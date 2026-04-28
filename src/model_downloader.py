import os
import json
import hashlib
import requests
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QHBoxLayout
import logging

logger = logging.getLogger("ModelDownloader")

class DownloadThread(QThread):
    progress = Signal(int, int, int)  # downloaded, total, speed
    finished = Signal(bool, str)  # success, message

    def __init__(self, url, save_path, md5_hash=None):
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.md5_hash = md5_hash
        self.is_cancelled = False

    def run(self):
        try:
            response = requests.get(self.url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            os.makedirs(os.path.dirname(self.save_path), exist_ok=True)

            with open(self.save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self.is_cancelled:
                        f.close()
                        os.remove(self.save_path)
                        self.finished.emit(False, "下载已取消")
                        return

                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total_size, 0)

            # 验证 MD5
            if self.md5_hash:
                if not self.verify_md5(self.save_path, self.md5_hash):
                    os.remove(self.save_path)
                    self.finished.emit(False, "文件校验失败")
                    return

            self.finished.emit(True, "下载完成")

        except Exception as e:
            logger.error(f"下载失败: {e}")
            self.finished.emit(False, f"下载失败: {str(e)}")

    def verify_md5(self, file_path, expected_md5):
        md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                md5.update(chunk)
        return md5.hexdigest() == expected_md5

    def cancel(self):
        self.is_cancelled = True


class ModelDownloadDialog(QDialog):
    def __init__(self, model_name, model_info, parent=None):
        super().__init__(parent)
        self.model_name = model_name
        self.model_info = model_info
        self.download_thread = None

        self.setWindowTitle("下载模型")
        self.setFixedSize(400, 180)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel(f"🎙️ 正在下载 {self.model_name}")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        # 信息
        size_mb = self.model_info.get('size_mb', 0)
        info = QLabel(f"大小: {size_mb} MB\n来源: luscreen.com")
        layout.addWidget(info)

        # 进度条
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        # 状态标签
        self.status_label = QLabel("准备下载...")
        layout.addWidget(self.status_label)

        # 按钮
        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.cancel_download)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def start_download(self):
        url = self.model_info['url']
        save_path = self.get_model_path()
        md5_hash = self.model_info.get('md5')

        self.download_thread = DownloadThread(url, save_path, md5_hash)
        self.download_thread.progress.connect(self.update_progress)
        self.download_thread.finished.connect(self.download_finished)
        self.download_thread.start()

    def get_model_path(self):
        app_data = os.getenv('APPDATA')
        models_dir = os.path.join(app_data, 'LuScreen', 'models', 'whisperx')
        return os.path.join(models_dir, f"{self.model_name}.pt")

    def update_progress(self, downloaded, total, speed):
        if total > 0:
            percent = int(downloaded * 100 / total)
            self.progress_bar.setValue(percent)

            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self.status_label.setText(f"已下载: {downloaded_mb:.1f} MB / {total_mb:.1f} MB")

    def download_finished(self, success, message):
        if success:
            self.status_label.setText("✅ " + message)
            self.btn_cancel.setText("完成")
            self.btn_cancel.clicked.disconnect()
            self.btn_cancel.clicked.connect(self.accept)
        else:
            self.status_label.setText("❌ " + message)
            self.btn_cancel.setText("关闭")

    def cancel_download(self):
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.cancel()
        self.reject()


class ModelManager:
    MANIFEST_URL = "https://luscreen.com/downloads/models/manifest.json"

    @staticmethod
    def get_models_dir():
        app_data = os.getenv('APPDATA')
        return os.path.join(app_data, 'LuScreen', 'models', 'whisperx')

    @staticmethod
    def is_model_installed(model_name):
        models_dir = ModelManager.get_models_dir()
        model_path = os.path.join(models_dir, f"{model_name}.pt")
        return os.path.exists(model_path)

    @staticmethod
    def fetch_manifest():
        try:
            response = requests.get(ModelManager.MANIFEST_URL, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return None

    @staticmethod
    def prompt_download(model_name="whisperx-base", parent=None):
        from PySide6.QtWidgets import QMessageBox

        # 检查是否已安装
        if ModelManager.is_model_installed(model_name):
            return True

        # 获取模型信息
        manifest = ModelManager.fetch_manifest()
        if not manifest:
            QMessageBox.warning(parent, "错误", "无法连接到服务器获取模型信息")
            return False

        model_info = manifest.get('models', {}).get(model_name)
        if not model_info:
            QMessageBox.warning(parent, "错误", f"未找到模型: {model_name}")
            return False

        # 询问用户
        size_mb = model_info.get('size_mb', 0)
        reply = QMessageBox.question(
            parent,
            "下载 AI 模型",
            f"字幕生成功能需要下载 AI 模型\n\n"
            f"模型: {model_info.get('display_name', model_name)}\n"
            f"大小: {size_mb} MB\n"
            f"来源: luscreen.com\n\n"
            f"是否立即下载？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            dialog = ModelDownloadDialog(model_name, model_info, parent)
            dialog.start_download()
            return dialog.exec() == QDialog.Accepted

        return False
