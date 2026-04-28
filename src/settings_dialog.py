import subprocess
import imageio_ffmpeg
import sys
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QLineEdit, QPushButton, QFileDialog, QGroupBox,
                               QListWidget, QStackedWidget, QWidget, QComboBox, 
                               QCheckBox, QFormLayout, QFrame, QKeySequenceEdit,
                               QScrollArea, QMessageBox, QApplication, QInputDialog)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QFont, QKeySequence, QPixmap
import os
from datetime import datetime
from src.audio_recorder import AudioRecorder
from src.camera import CameraWidget
from src.startup_manager import StartupManager
from src.license_manager import LicenseManager
from src.version import APP_VERSION
from src.updater import UpdateWorker, install_update

class SettingsDialog(QDialog):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.startup_manager = StartupManager()
        self.license_manager = LicenseManager()
        self.setWindowTitle("LuScreen 设置中心")
        self.setFixedSize(800, 600)
        self.setStyleSheet("""
            QDialog { background-color: #2b2b2b; color: white; }
            QLabel { color: #ddd; font-size: 14px; }
            QLineEdit { 
                padding: 6px; 
                border-radius: 4px; 
                border: 1px solid #555;
                background-color: #1a1a1a;
                color: white;
            }
            QPushButton {
                background-color: #444;
                color: white;
                border: none;
                padding: 6px 15px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #555; }
            QListWidget {
                background-color: #222;
                border: none;
                outline: none;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 12px 20px;
                color: #aaa;
            }
            QListWidget::item:selected {
                background-color: #333;
                color: white;
                border-left: 3px solid #007aff;
            }
            QGroupBox {
                border: 1px solid #444;
                border-radius: 6px;
                margin-top: 20px;
                padding-top: 10px;
                font-weight: bold;
                color: #00afff;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QComboBox {
                padding: 5px;
                background-color: #1a1a1a;
                border: 1px solid #555;
                border-radius: 4px;
                color: white;
            }
            QCheckBox { color: #ddd; spacing: 8px; }
        """)
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # --- 左侧导航栏 ---
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(200)
        
        nav_items = [
            "⚙️ 系统设置",
            "⛶ 截图设置",
            "🔴 录屏设置",
            "🎙️ 麦克风设置",
            "📹 摄像头设置",
            "🖱️ 鼠标设置",
            "ℹ️ 软件更新",
            "📞 合作联系"
        ]
        
        for item in nav_items:
            self.nav_list.addItem(item)
            
        self.nav_list.currentRowChanged.connect(self.change_page)
        main_layout.addWidget(self.nav_list)
        
        # --- 右侧内容区 ---
        self.pages = QStackedWidget()
        self.pages.setStyleSheet("QStackedWidget { background-color: #2b2b2b; padding: 20px; }")
        
        # 1. 系统设置
        self.pages.addWidget(self.create_system_page())
        # 2. 截图设置
        self.pages.addWidget(self.create_capture_page())
        # 3. 录屏设置
        self.pages.addWidget(self.create_record_page())
        # 4. 麦克风设置
        self.pages.addWidget(self.create_mic_page())
        # 5. 摄像头设置
        self.pages.addWidget(self.create_camera_page())
        # 6. 鼠标设置
        self.pages.addWidget(self.create_mouse_page())
        # 7. 软件版本
        self.pages.addWidget(self.create_about_page())
        # 8. 合作联系
        self.pages.addWidget(self.create_contact_page())
        
        main_layout.addWidget(self.pages)
        
        # 默认选中第一项
        self.nav_list.setCurrentRow(0)

    def change_page(self, index):
        self.pages.setCurrentIndex(index)

    def create_page_container(self, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # 自定义滚动条样式
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                border: none;
                background: #2b2b2b;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #555;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        
        page = QWidget()
        page.setObjectName("scrollContent")
        page.setStyleSheet("#scrollContent { background: transparent; }")
        
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        scroll.setWidget(page)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: white; margin-bottom: 20px;")
        layout.addWidget(title_label)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #444;")
        layout.addWidget(line)
        
        return scroll, layout

    def create_system_page(self):
        page, layout = self.create_page_container("系统设置")
        
        # 快捷键设置
        layout.addWidget(QLabel("全局快捷键 (弹出托盘菜单):"))
        self.key_editor = QKeySequenceEdit()
        current_hotkey = self.config_manager.get("global_hotkey", "ctrl+l")
        self.key_editor.setKeySequence(QKeySequence(current_hotkey))
        self.key_editor.keySequenceChanged.connect(lambda k: self.on_hotkey_changed("global_hotkey", k))
        layout.addWidget(self.key_editor)
        
        layout.addWidget(QLabel("开始录制 (Start Recording):"))
        self.key_start = QKeySequenceEdit()
        self.key_start.setKeySequence(QKeySequence(self.config_manager.get("hotkey_record_start", "ctrl+f1")))
        self.key_start.keySequenceChanged.connect(lambda k: self.on_hotkey_changed("hotkey_record_start", k))
        layout.addWidget(self.key_start)
        
        layout.addWidget(QLabel("暂停/继续录制 (Pause/Resume):"))
        self.key_pause = QKeySequenceEdit()
        self.key_pause.setKeySequence(QKeySequence(self.config_manager.get("hotkey_record_pause", "f2")))
        self.key_pause.keySequenceChanged.connect(lambda k: self.on_hotkey_changed("hotkey_record_pause", k))
        layout.addWidget(self.key_pause)
        
        layout.addWidget(QLabel("停止录制 (Stop Recording):"))
        self.key_stop = QKeySequenceEdit()
        self.key_stop.setKeySequence(QKeySequence(self.config_manager.get("hotkey_record_stop", "ctrl+f3")))
        self.key_stop.keySequenceChanged.connect(lambda k: self.on_hotkey_changed("hotkey_record_stop", k))
        layout.addWidget(self.key_stop)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #444; margin: 10px 0;")
        layout.addWidget(line)
        
        # 视频质量设置
        layout.addWidget(QLabel("录制视频质量 (Recording Quality):"))
        self.combo_quality = QComboBox()
        # 1080p/2k 30FPS; 4k 60FPS
        self.combo_quality.addItem("1080p, 30FPS", "1080p_30")
        self.combo_quality.addItem("2K, 30FPS", "2k_30")
        self.combo_quality.addItem("4K, 60FPS", "4k_60")
        
        current_quality = self.config_manager.get("video_quality", "1080p_30")
        # 兼容旧配置
        if current_quality == "1080p": current_quality = "1080p_30"
        elif current_quality == "2k": current_quality = "2k_30"
        elif current_quality == "4k": current_quality = "4k_60"
        
        # Set index based on data
        index = self.combo_quality.findData(current_quality)
        if index >= 0:
            self.combo_quality.setCurrentIndex(index)
            
        self.combo_quality.currentIndexChanged.connect(self.on_quality_changed)
        layout.addWidget(self.combo_quality)
        
        # GPU 加速设置
        self.license_manager = LicenseManager()
        gpu_text = "启用 NVIDIA GPU 硬件加速 (NVENC) [Pro版功能]"
        self.cb_gpu = QCheckBox(gpu_text)
        self.cb_gpu.setChecked(self.config_manager.get("gpu_acceleration", False))
        self.cb_gpu.toggled.connect(self.on_gpu_changed)
        
        # License check for GPU
        if not self.license_manager.can_use_gpu():
            self.cb_gpu.setEnabled(False)
            self.cb_gpu.setToolTip("GPU 加速仅限 Pro 版用户使用")
            if self.cb_gpu.isChecked():
                self.cb_gpu.setChecked(False) # 强制关闭
        
        layout.addWidget(self.cb_gpu)

        # 检测并显示 GPU 信息
        gpu_info = "未检测到支持的 NVIDIA GPU"
        self.has_nvidia_gpu = False
        try:
            # 使用 nvidia-smi 获取 GPU 名称
            # 格式: Name
            result = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], 
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode == 0:
                gpu_model = result.stdout.strip()
                if gpu_model:
                    gpu_info = f"已检测到 GPU: {gpu_model}"
                    # 检查 ffmpeg 是否支持 nvenc
                    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                    enc_result = subprocess.run([ffmpeg_exe, '-encoders'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if 'h264_nvenc' in enc_result.stdout:
                        gpu_info += " (支持 NVENC)"
                        self.has_nvidia_gpu = True
                    else:
                        gpu_info += " (FFmpeg 未检测到 NVENC)"
        except FileNotFoundError:
             # 系统没有 nvidia-smi
             pass
        except Exception as e:
            print(f"GPU detection error: {e}")
            
        lbl_gpu_info = QLabel(gpu_info)
        lbl_gpu_info.setStyleSheet("color: #888; font-size: 12px; margin-left: 20px;")
        layout.addWidget(lbl_gpu_info)

        self.cb_startup = QCheckBox("开机自动启动 LuScreen")
        # 从注册表读取实际状态
        is_enabled = self.startup_manager.is_enabled()
        self.cb_startup.setChecked(is_enabled)
        self.cb_startup.toggled.connect(self.on_startup_changed)
        layout.addWidget(self.cb_startup)
        
        cb_close = QCheckBox("点击关闭按钮时最小化到托盘")
        cb_close.setChecked(True)
        cb_close.setEnabled(False) # 强制开启
        layout.addWidget(cb_close)
        
        layout.addStretch()
        return page

    def create_capture_page(self):
        page, layout = self.create_page_container("截图设置")
        
        group = QGroupBox("保存位置")
        vbox = QVBoxLayout()
        
        self.edit_capture = QLineEdit(self.config_manager.get("save_path_capture"))
        self.edit_capture.setReadOnly(True)
        btn_browse = QPushButton("浏览文件夹...")
        btn_browse.clicked.connect(self.browse_capture)
        
        vbox.addWidget(self.edit_capture)
        vbox.addWidget(btn_browse)
        group.setLayout(vbox)
        layout.addWidget(group)
        
        layout.addStretch()
        return page

    def create_record_page(self):
        page, layout = self.create_page_container("录屏设置")
        
        group = QGroupBox("保存位置")
        vbox = QVBoxLayout()
        
        self.edit_record = QLineEdit(self.config_manager.get("save_path_record"))
        self.edit_record.setReadOnly(True)
        btn_browse = QPushButton("浏览文件夹...")
        btn_browse.clicked.connect(self.browse_record)
        
        vbox.addWidget(self.edit_record)
        vbox.addWidget(btn_browse)
        group.setLayout(vbox)
        layout.addWidget(group)
        
        layout.addStretch()
        return page

    def create_mic_page(self):
        page, layout = self.create_page_container("麦克风设置")
        
        layout.addWidget(QLabel("默认输入设备:"))
        self.combo_mic = QComboBox()
        self.mic_devices = []
        try:
            self.mic_devices = AudioRecorder.get_input_devices()
            current_idx = self.config_manager.get("mic_index")
            
            self.combo_mic.addItem("系统默认设备", None)
            for i, dev in enumerate(self.mic_devices):
                self.combo_mic.addItem(dev['name'], dev['index'])
                if current_idx == dev['index']:
                    self.combo_mic.setCurrentIndex(i + 1)
        except:
            self.combo_mic.addItem("无法获取设备")
            
        self.combo_mic.currentIndexChanged.connect(self.on_mic_changed)
        layout.addWidget(self.combo_mic)
        
        layout.addStretch()
        return page

    def create_camera_page(self):
        page, layout = self.create_page_container("摄像头设置")
        self.cb_border = QCheckBox("显示摄像头边框 (Show Border)")
        self.cb_border.setChecked(self.config_manager.get("cam_border_enabled", True))
        self.cb_border.toggled.connect(self.on_border_changed)
        layout.addWidget(self.cb_border)
        
        layout.addWidget(QLabel("默认摄像头:"))
        self.combo_cam = QComboBox()
        self.cam_devices = []
        try:
            self.cam_devices = CameraWidget.get_available_cameras()
            current_idx = self.config_manager.get("cam_index", 0)
            
            for i, cam in enumerate(self.cam_devices):
                self.combo_cam.addItem(cam['name'], cam['index'])
                if current_idx == cam['index']:
                    self.combo_cam.setCurrentIndex(i)
        except:
            self.combo_cam.addItem("无法获取设备")
            
        self.combo_cam.currentIndexChanged.connect(self.on_cam_changed)
        layout.addWidget(self.combo_cam)
        
        layout.addWidget(QLabel("默认形状:"))
        self.combo_shape = QComboBox()
        shapes = [
            ('圆形', 'circle'),
            ('圆角正方形', 'square'),
            ('横向 4:3', '4:3'),
            ('竖向 3:4', '3:4')
        ]
        current_shape = self.config_manager.get("cam_shape", "circle")
        for i, (name, mode) in enumerate(shapes):
            self.combo_shape.addItem(name, mode)
            if current_shape == mode:
                self.combo_shape.setCurrentIndex(i)
        
        self.combo_shape.currentIndexChanged.connect(self.on_shape_changed)
        layout.addWidget(self.combo_shape)
        
        layout.addStretch()
        return page

    def create_mouse_page(self):
        page, layout = self.create_page_container("鼠标设置")
        
        self.cb_mouse = QCheckBox("录制时捕获鼠标光标")
        self.cb_mouse.setChecked(self.config_manager.get("mouse_enabled", True))
        self.cb_mouse.toggled.connect(self.on_mouse_changed)
        layout.addWidget(self.cb_mouse)
        
        layout.addWidget(QLabel("鼠标特效样式:"))
        self.combo_mouse_style = QComboBox()
        styles = [
            ('无特效', 'none'),
            ('高亮光标 (黄色光环)', 'highlight'),
            ('点击波纹', 'ring'),
            ('高亮 + 波纹', 'both')
        ]
        current_style = self.config_manager.get("mouse_style", "both")
        for name, style in styles:
            self.combo_mouse_style.addItem(name, style)
            if style == current_style:
                self.combo_mouse_style.setCurrentIndex(self.combo_mouse_style.count() - 1)
        
        self.combo_mouse_style.currentIndexChanged.connect(self.on_mouse_style_changed)
        layout.addWidget(self.combo_mouse_style)
        
        layout.addStretch()
        return page

    def create_about_page(self):
        page, layout = self.create_page_container("软件版本")
        
        # 顶部容器
        header_layout = QHBoxLayout()
        header_layout.setAlignment(Qt.AlignCenter)
        
        # 图标
        icon_label = QLabel()
        
        # 处理资源路径
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.getcwd()
            
        icon_path = os.path.join(base_path, "assets", "icon.png")
        
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            # 缩放图片到合适大小，例如 64x64
            pixmap = pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(pixmap)
        header_layout.addWidget(icon_label)
        
        # Logo 文字
        logo_label = QLabel("LuScreen")
        logo_label.setStyleSheet("font-size: 48px; font-weight: bold; color: #00afff; margin-left: 10px;")
        logo_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.addWidget(logo_label)
        
        layout.addLayout(header_layout)
        
        # Version & License Info
        version_text = f"版本: v{APP_VERSION}\n构建日期: {datetime.now().strftime('%Y-%m-%d')}"
        if self.license_manager.is_pro:
            version_text += "\n\n👑 Pro 专业版 (已激活)"
        else:
            version_text += "\n\n(免费版)"
            
        info_label = QLabel(version_text)
        info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(info_label)
        
        # 按钮容器
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        # 激活 Pro 按钮
        if not self.license_manager.is_pro:
            btn_activate = QPushButton("激活 Pro 版")
            btn_activate.setFixedWidth(120)
            btn_activate.setStyleSheet("background-color: #007aff; color: white; font-weight: bold;")
            btn_activate.setCursor(Qt.PointingHandCursor)
            btn_activate.clicked.connect(self.activate_pro_dialog)
            btn_layout.addWidget(btn_activate)
            btn_layout.addSpacing(20)
        else:
            # 注销按钮 (用于测试)
            btn_deactivate = QPushButton("注销激活")
            btn_deactivate.setFixedWidth(120)
            btn_deactivate.setStyleSheet("background-color: #d9534f; color: white;")
            btn_deactivate.setCursor(Qt.PointingHandCursor)
            btn_deactivate.setToolTip("移除当前激活码，恢复为免费版")
            btn_deactivate.clicked.connect(self.deactivate_pro)
            btn_layout.addWidget(btn_deactivate)
            btn_layout.addSpacing(20)
        
        # 检查更新按钮
        btn_check = QPushButton("检查更新")
        btn_check.setFixedWidth(120)
        btn_check.setCursor(Qt.PointingHandCursor)
        btn_check.clicked.connect(self.check_for_updates)
        btn_layout.addWidget(btn_check)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        update_label = QLabel("软件更新: Luscreen.com")
        update_label.setAlignment(Qt.AlignCenter)
        update_label.setStyleSheet("color: #aaa; margin-top: 10px;")
        layout.addWidget(update_label)
        
        layout.addStretch()
        return page

    def activate_pro_dialog(self):
        text, ok = QInputDialog.getText(self, "激活 Pro 版", "请输入激活码 (License Key):")
        if ok and text:
            if self.license_manager.activate_pro(text):
                QMessageBox.information(self, "激活成功", "恭喜！您已成功激活 Pro 专业版。\n请重启软件以解锁所有功能。")
                # Reload current page to update UI
                self.pages.removeWidget(self.pages.currentWidget())
                self.pages.insertWidget(6, self.create_about_page())
                self.pages.setCurrentIndex(6)
            else:
                reason = getattr(self.license_manager, "last_error", "") or "无效的激活码，请检查后重试。"
                QMessageBox.warning(self, "激活失败", reason)

    def deactivate_pro(self):
        reply = QMessageBox.question(self, "注销激活", "确定要注销当前的 Pro 版激活吗？\n软件将恢复为免费版限制。", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.license_manager.deactivate()
            QMessageBox.information(self, "已注销", "激活已移除。")
            # Reload UI
            self.pages.removeWidget(self.pages.currentWidget())
            self.pages.insertWidget(6, self.create_about_page())
            self.pages.setCurrentIndex(6)

    def check_for_updates(self):
        self.update_worker = UpdateWorker(mode='check')
        self.update_worker.check_finished.connect(self.on_check_finished)
        self.update_worker.error.connect(lambda e: QMessageBox.warning(self, "更新检查失败", e))
        self.update_worker.start()
        
    def on_check_finished(self, has_update, version, url):
        if has_update:
            reply = QMessageBox.question(
                self, "发现新版本", 
                f"发现新版本 {version}！\n当前版本: {APP_VERSION}\n\n是否立即更新？",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.start_download(url)
        else:
            QMessageBox.information(self, "检查更新", f"当前已是最新版本 ({APP_VERSION})")

    def start_download(self, url):
        from PySide6.QtWidgets import QProgressDialog
        self.progress_dialog = QProgressDialog("正在下载更新...", "取消", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()
        
        self.update_worker = UpdateWorker(mode='download', download_url=url)
        self.update_worker.download_progress.connect(self.progress_dialog.setValue)
        self.update_worker.download_finished.connect(self.on_download_finished)
        self.update_worker.error.connect(self.on_download_error)
        self.update_worker.start()
        
        self.progress_dialog.canceled.connect(self.update_worker.terminate)

    def on_download_error(self, error_msg):
        self.progress_dialog.close()
        QMessageBox.warning(self, "下载失败", f"无法下载更新包：\n{error_msg}")

    def on_download_finished(self):
        # 硬编码路径，避免信号传参风险
        base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
        file_path = os.path.join(base_dir, "update.zip")
        
        from src.updater import log
        log(f"Signal received: on_download_finished. Using fixed path: {file_path}")
        self.progress_dialog.close()
        # 增加延时到 500ms，并强制 GC，防止 Nuitka 环境下的资源释放崩溃
        import gc
        gc.collect()
        from PySide6.QtCore import QTimer
        log("Scheduling prompt_install...")
        QTimer.singleShot(500, lambda: self.prompt_install(file_path))

    def prompt_install(self, file_path):
        from src.updater import log
        log("Executing prompt_install...")
        reply = QMessageBox.question(
            self, "下载完成", 
            "更新包已下载完成。\n\n程序将重启以完成更新。\n是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if install_update(file_path):
                # 成功启动更新脚本后，主动退出程序
                QApplication.quit()
            else:
                QMessageBox.critical(self, "更新失败", "安装更新失败，请查看 logs/update_log.txt 获取详情。")

    def create_contact_page(self):
        page, layout = self.create_page_container("合作联系")
        
        contact_info = QLabel(
            "如果您有任何问题或合作意向，请联系我们：\n\n"
            "📧 邮箱: 76697742@qq.com\n"
            "🌐 官网: www.luscreen.com\n"
            "💬 微信: wuhui8118（加入交流群）"
        )
        contact_info.setStyleSheet("font-size: 16px; line-height: 150%;")
        contact_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(contact_info)
        
        # 二维码
        qr_label = QLabel()
        qr_label.setAlignment(Qt.AlignCenter)
        
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.getcwd()
            
        qr_path = os.path.join(base_path, "assets", "qrcode.png")
        
        if os.path.exists(qr_path):
            pixmap = QPixmap(qr_path)
            # 缩放图片到合适大小，例如 200x200
            pixmap = pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            qr_label.setPixmap(pixmap)
            layout.addWidget(qr_label)
            
            qr_desc = QLabel("扫码加入交流群")
            qr_desc.setAlignment(Qt.AlignCenter)
            qr_desc.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
            layout.addWidget(qr_desc)
        
        layout.addStretch()
        return page

    # --- 事件处理 ---
    def browse_capture(self):
        path = QFileDialog.getExistingDirectory(self, "选择截图保存文件夹", self.edit_capture.text())
        if path:
            path = os.path.normpath(path)
            self.edit_capture.setText(path)
            self.config_manager.set("save_path_capture", path)
            self.config_manager.save()

    def browse_record(self):
        path = QFileDialog.getExistingDirectory(self, "选择录屏保存文件夹", self.edit_record.text())
        if path:
            path = os.path.normpath(path)
            self.edit_record.setText(path)
            self.config_manager.set("save_path_record", path)
            self.config_manager.save()

    def on_mic_changed(self, index):
        data = self.combo_mic.currentData()
        self.config_manager.set("mic_index", data)
        self.config_manager.save()

    def on_cam_changed(self, index):
        data = self.combo_cam.currentData()
        self.config_manager.set("cam_index", data)
        self.config_manager.save()

    def on_shape_changed(self, index):
        data = self.combo_shape.currentData()
        self.config_manager.set("cam_shape", data)
        self.config_manager.save()

    def on_mouse_changed(self, checked):
        self.config_manager.set("mouse_enabled", checked)
        self.config_manager.save()

    def on_mouse_style_changed(self, index):
        data = self.combo_mouse_style.currentData()
        self.config_manager.set("mouse_style", data)
        self.config_manager.save()

    def on_hotkey_changed(self, key_name, key_sequence):
        # 将 QKeySequence 转换为字符串
        hotkey_str = key_sequence.toString(QKeySequence.NativeText)
        # 转换为 keyboard 库友好的格式 (例如 Ctrl+L -> ctrl+l)
        hotkey_str = hotkey_str.lower()
        self.config_manager.set(key_name, hotkey_str)
        self.config_manager.save()

    def on_quality_changed(self, index):
        quality = self.combo_quality.currentData()
        
        # License Check
        target_res = "1080p"
        target_fps = 30
        
        if "4k" in quality: target_res = "4k"
        elif "2k" in quality: target_res = "2k"
        
        if "60" in quality: target_fps = 60
        
        if not self.license_manager.can_use_resolution(target_res) or not self.license_manager.can_use_fps(target_fps):
            QMessageBox.information(self, "Pro 版功能", 
                f"您当前使用的是免费版。\n\n"
                f"2K/4K 分辨率和 60FPS 高帧率是 Pro 版专属功能。\n"
                f"免费版最高支持 1080p @ 30fps。")
            
            # Reset to 1080p
            idx_1080 = self.combo_quality.findData("1080p_30")
            if idx_1080 >= 0:
                self.combo_quality.setCurrentIndex(idx_1080)
            return

        if quality == "4k_60":
            # 4K 60FPS 优化逻辑
            if self.has_nvidia_gpu:
                if not self.cb_gpu.isChecked():
                    if self.license_manager.can_use_gpu():
                        self.cb_gpu.setChecked(True)
                        QMessageBox.information(self, "性能优化", "已为您自动开启 GPU 硬件加速，以确保 4K 60FPS 录制流畅。")
            else:
                QMessageBox.warning(self, "性能警告", 
                                    "您的电脑未检测到支持 NVENC 的 NVIDIA 显卡。\n\n"
                                    "使用 CPU 录制 4K 60FPS 可能会导致严重卡顿或音画不同步。\n"
                                    "建议降低画质或帧率。")

        self.config_manager.set("video_quality", quality)
        self.config_manager.save()

    def on_gpu_changed(self, checked):
        self.config_manager.set("gpu_acceleration", checked)
        self.config_manager.save()

    def on_startup_changed(self, checked):
        success = self.startup_manager.set_enabled(checked)
        if not success:
            # 如果失败（例如权限不足），恢复复选框状态
            # 使用 blockSignals 防止递归触发
            self.cb_startup.blockSignals(True)
            self.cb_startup.setChecked(not checked)
            self.cb_startup.blockSignals(False)
            # 可以在这里添加一个弹窗提示用户失败原因

    def on_border_changed(self, checked):
        self.config_manager.set("cam_border_enabled", checked)
        self.config_manager.save()
