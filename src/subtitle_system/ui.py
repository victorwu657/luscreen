import os
import importlib
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QRadioButton, QLineEdit, QFileDialog,
                               QProgressBar, QMessageBox, QGroupBox, QComboBox, QCheckBox, QButtonGroup)
from PySide6.QtCore import Qt, QSettings
from src.subtitle_system.device_policy import choose_default_asr_device, is_cuda_available, log_cuda_status
from src.subtitle_system.model_registry import list_available_local_models, get_default_whisperx_model_id
from src.subtitle_system.runtime_installer import ensure_subtitle_runtime_on_path, is_subtitle_runtime_installed, SubtitleRuntimeDownloadWorker

class SubtitleGenerationDialog(QDialog):
    def __init__(self, parent=None, video_path=None, mic_path=None):
        super().__init__(parent)
        self.setWindowTitle("生成字幕")
        self.resize(500, 400)
        
        self.video_path = video_path
        self.mic_path = mic_path
        self.settings = QSettings("LuScreen", "Subtitle")
        
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        layout = QVBoxLayout()
        
        # 1. Engine Selection
        gb_engine = QGroupBox("选择识别引擎")
        vbox_engine = QVBoxLayout()
        
        self._rb_local_label = "本地模型 (WhisperX) - 推荐"
        self._rb_api_label = "云端 API (OpenAI Whisper)"

        self.rb_local = QRadioButton(self._rb_local_label)
        self.rb_local.setChecked(True)
        self.rb_local.toggled.connect(self.update_ui_state)
        
        self.rb_api = QRadioButton(self._rb_api_label)
        self.rb_api.toggled.connect(self.update_ui_state)
        
        vbox_engine.addWidget(self.rb_local)
        vbox_engine.addWidget(self.rb_api)
        gb_engine.setLayout(vbox_engine)
        layout.addWidget(gb_engine)
        
        # 2. Local Settings
        self.gb_local_settings = QGroupBox("本地模型设置")
        vbox_local = QVBoxLayout()
        
        hbox_model = QHBoxLayout()
        self.cmb_local_model = QComboBox()
        self.btn_refresh_models = QPushButton("刷新")
        self.btn_refresh_models.clicked.connect(self.refresh_local_models)
        self.btn_custom_model = QPushButton("自定义...")
        self.btn_custom_model.clicked.connect(self.choose_custom_model_dir)
        hbox_model.addWidget(QLabel("模型:"))
        hbox_model.addWidget(self.cmb_local_model, 1)
        hbox_model.addWidget(self.btn_refresh_models)
        hbox_model.addWidget(self.btn_custom_model)

        hbox_device = QHBoxLayout()
        self.chk_cpu = QCheckBox("CPU")
        self.chk_gpu = QCheckBox("GPU（需要CUDA环境）")
        self._device_group = QButtonGroup(self)
        self._device_group.setExclusive(True)
        self._device_group.addButton(self.chk_cpu)
        self._device_group.addButton(self.chk_gpu)
        self.chk_cpu.setChecked(True)
        cuda_ok = bool(is_cuda_available())
        if not cuda_ok:
            try:
                self.chk_gpu.setText("GPU（未检测到CUDA）")
                self.chk_gpu.setEnabled(False)
                self.chk_cpu.setChecked(True)
            except Exception:
                pass
        hbox_device.addWidget(QLabel("运行设备:"))
        hbox_device.addWidget(self.chk_cpu)
        hbox_device.addWidget(self.chk_gpu)
        hbox_device.addStretch(1)
        try:
            log_cuda_status(context="subtitle_dialog_init")
        except Exception:
            pass
        
        self.lbl_download_hint = QLabel(
            '提示：本地字幕使用 WhisperX（Whisper + 对齐）生成逐词时间戳。<br>'
            '模型会优先从根目录 <code>models</code> 下加载/缓存：<br>'
            '<code style="background-color: #333; color: #eee; padding: 2px;">models/manifest.json</code>（模型清单）<br>'
            '<code style="background-color: #333; color: #eee; padding: 2px;">models/whisperx/whisper</code>（本地模型目录）<br>'
        )
        self.lbl_download_hint.setOpenExternalLinks(True)
        self.lbl_download_hint.setWordWrap(True)
        self.lbl_download_hint.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        
        vbox_local.addLayout(hbox_model)
        vbox_local.addLayout(hbox_device)
        vbox_local.addWidget(self.lbl_download_hint)
        self.gb_local_settings.setLayout(vbox_local)
        layout.addWidget(self.gb_local_settings)
        
        # 3. API Settings
        self.gb_api_settings = QGroupBox("API 设置")
        vbox_api = QVBoxLayout()
        
        hbox_key = QHBoxLayout()
        self.line_api_key = QLineEdit()
        self.line_api_key.setEchoMode(QLineEdit.Password)
        self.line_api_key.setPlaceholderText("sk-...")
        hbox_key.addWidget(QLabel("API Key:"))
        hbox_key.addWidget(self.line_api_key)
        
        hbox_url = QHBoxLayout()
        self.line_base_url = QLineEdit()
        self.line_base_url.setPlaceholderText("默认 (https://api.openai.com/v1)")
        hbox_url.addWidget(QLabel("Base URL:"))
        hbox_url.addWidget(self.line_base_url)
        
        vbox_api.addLayout(hbox_key)
        vbox_api.addLayout(hbox_url)
        self.gb_api_settings.setLayout(vbox_api)
        layout.addWidget(self.gb_api_settings)
        
        # 4. Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.lbl_status = QLabel("")
        
        layout.addWidget(self.lbl_status)
        layout.addWidget(self.progress_bar)
        
        # 5. Buttons
        hbox_btns = QHBoxLayout()
        hbox_btns.addStretch()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_start = QPushButton("开始生成")
        self.btn_start.clicked.connect(self.start_generation)
        self.btn_start.setDefault(True)
        
        hbox_btns.addWidget(self.btn_cancel)
        hbox_btns.addWidget(self.btn_start)
        layout.addLayout(hbox_btns)
        
        self.setLayout(layout)
        self.update_ui_state()
        try:
            self.refresh_local_models()
        except Exception:
            pass

    def _has_whisperx(self) -> bool:
        try:
            ensure_subtitle_runtime_on_path()
            importlib.import_module("whisperx")
            return True
        except Exception:
            return False

    def update_ui_state(self):
        is_local = self.rb_local.isChecked()
        self.gb_local_settings.setVisible(is_local)
        self.gb_api_settings.setVisible(not is_local)
        self._update_engine_labels()

    def _update_engine_labels(self):
        local_mark = "√ " if self.rb_local.isChecked() else ""
        api_mark = "√ " if self.rb_api.isChecked() else ""
        self.rb_local.setText(local_mark + self._rb_local_label)
        self.rb_api.setText(api_mark + self._rb_api_label)

    def browse_model(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择模型文件夹")
        if dir_path:
            self._set_custom_model(dir_path)

    def refresh_local_models(self):
        selected = self.cmb_local_model.currentData()
        selected_id = None
        if isinstance(selected, dict):
            selected_id = selected.get("model_id")
        elif isinstance(selected, str):
            selected_id = selected

        self.cmb_local_model.clear()
        models = list_available_local_models(backend="whisperx")
        for m in models:
            self.cmb_local_model.addItem(m.display_name, {"model_id": m.model_id, "model_ref": m.model_ref})

        self.cmb_local_model.addItem("自定义路径...", {"model_id": "__custom__", "model_ref": ""})

        if selected_id:
            for i in range(self.cmb_local_model.count()):
                data = self.cmb_local_model.itemData(i)
                if isinstance(data, dict) and data.get("model_id") == selected_id:
                    self.cmb_local_model.setCurrentIndex(i)
                    break

    def choose_custom_model_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择本地模型文件夹")
        if dir_path:
            self._set_custom_model(dir_path)

    def _set_custom_model(self, dir_path: str):
        p = (dir_path or "").strip()
        if not p:
            return
        idx = self.cmb_local_model.findText("自定义路径...")
        if idx < 0:
            self.cmb_local_model.addItem("自定义路径...", {"model_id": "__custom__", "model_ref": ""})
            idx = self.cmb_local_model.findText("自定义路径...")
        self.cmb_local_model.setItemText(idx, f"自定义: {p}")
        self.cmb_local_model.setItemData(idx, {"model_id": p, "model_ref": p})
        self.cmb_local_model.setCurrentIndex(idx)

    def load_settings(self):
        self.rb_local.setChecked(self.settings.value("use_local", True, type=bool))
        self.rb_api.setChecked(not self.settings.value("use_local", True, type=bool))
        if self.cmb_local_model.count() == 0:
            self.refresh_local_models()
        saved_model = self.settings.value("local_model_id", "", type=str)
        if not saved_model:
            saved_model = self.settings.value("model_dir", "", type=str)
        if saved_model:
            for i in range(self.cmb_local_model.count()):
                data = self.cmb_local_model.itemData(i)
                if isinstance(data, dict) and data.get("model_id") == saved_model:
                    self.cmb_local_model.setCurrentIndex(i)
                    break
            else:
                if os.path.exists(saved_model):
                    self._set_custom_model(saved_model)
        else:
            default_id = get_default_whisperx_model_id()
            for i in range(self.cmb_local_model.count()):
                data = self.cmb_local_model.itemData(i)
                if isinstance(data, dict) and data.get("model_id") == default_id:
                    self.cmb_local_model.setCurrentIndex(i)
                    break
        saved_device = self.settings.value("asr_device", "", type=str)
        default_device = choose_default_asr_device(
            saved_device=saved_device,
            can_use_gpu=True,
            cuda_available=is_cuda_available(),
        )
        if default_device == "cuda" and self.chk_gpu.isEnabled():
            self.chk_gpu.setChecked(True)
        else:
            self.chk_cpu.setChecked(True)
        self.line_api_key.setText(self.settings.value("api_key", ""))
        self.line_base_url.setText(self.settings.value("base_url", ""))

    def save_settings(self):
        self.settings.setValue("use_local", self.rb_local.isChecked())
        data = self.cmb_local_model.currentData()
        model_id = ""
        if isinstance(data, dict):
            model_id = str(data.get("model_id") or "").strip()
        elif isinstance(data, str):
            model_id = data
        self.settings.setValue("local_model_id", model_id)
        self.settings.setValue("asr_device", "cuda" if bool(self.chk_gpu.isChecked()) else "cpu")
        self.settings.setValue("api_key", self.line_api_key.text())
        self.settings.setValue("base_url", self.line_base_url.text())

    def get_config(self):
        config = {
            'video_path': self.video_path,
            'mic_path': self.mic_path,
            'engine_type': 'whisperx' if self.rb_local.isChecked() else 'openai'
        }
        
        if config['engine_type'] == 'whisperx':
            data = self.cmb_local_model.currentData()
            model_id = ""
            if isinstance(data, dict):
                model_id = str(data.get("model_id") or "").strip()
            elif isinstance(data, str):
                model_id = data
            config['local_model_id'] = model_id
            cfg_device = "cuda" if bool(self.chk_gpu.isChecked()) else "cpu"
            if cfg_device == "cuda" and (not is_cuda_available()):
                cfg_device = "cpu"
            config['asr_device'] = cfg_device
        else:
            config['api_key'] = self.line_api_key.text()
            url = self.line_base_url.text().strip()
            if url:
                config['base_url'] = url
                
        return config

    def start_generation(self):
        # Validation
        if self.rb_local.isChecked():
            if not self._has_whisperx():
                msg = "未检测到本地字幕组件（whisperx/torch），无法使用本地字幕。\n\n是否现在一键下载字幕组件包？"
                if is_subtitle_runtime_installed():
                    msg = msg + "\n\n检测到字幕组件目录已存在，但导入失败；可以尝试重新下载覆盖安装。"
                box = QMessageBox(self)
                box.setWindowTitle("缺少字幕组件")
                box.setIcon(QMessageBox.Warning)
                box.setText(msg)
                btn_download = box.addButton("一键下载字幕组件包", QMessageBox.AcceptRole)
                box.addButton("取消", QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() == btn_download:
                    self._start_subtitle_runtime_download()
                return
            device = "cuda" if bool(self.chk_gpu.isChecked()) else "cpu"
            if device == "cuda" and (not is_cuda_available()):
                ok, reason, details = (False, "cuda_unavailable", {})
                try:
                    ok, reason, details = log_cuda_status(context="subtitle_dialog_gpu_selected")
                except Exception:
                    pass
                torch_ver = str(details.get("torch_version") or "")
                torch_build_cuda = str(details.get("torch_build_cuda") or "")
                QMessageBox.information(
                    self,
                    "GPU 不可用",
                    "当前未检测到可用的 CUDA 环境，将自动使用 CPU 生成字幕。\n\n"
                    f"诊断：reason={reason}\n"
                    f"PyTorch={torch_ver}\n"
                    f"build_cuda={torch_build_cuda}\n\n"
                    "如需 GPU 加速，请安装支持 CUDA 的 PyTorch（不要是 +cpu 版本），并确保显卡驱动可用。\n"
                    "更详细诊断已写入：logs/subtitle_cuda_diag.log",
                )
                self.chk_cpu.setChecked(True)
            data = self.cmb_local_model.currentData()
            model_id = ""
            if isinstance(data, dict):
                model_id = str(data.get("model_id") or "").strip()
            elif isinstance(data, str):
                model_id = data
            if not model_id:
                QMessageBox.warning(self, "错误", "请选择本地模型")
                return
        else:
            if not self.line_api_key.text():
                QMessageBox.warning(self, "错误", "请输入 API Key")
                return

        self.save_settings()
        self.accept() # Close dialog and return True

    def _start_subtitle_runtime_download(self):
        if getattr(self, "_subtitle_runtime_worker", None) is not None:
            try:
                if self._subtitle_runtime_worker.isRunning():
                    return
            except Exception:
                pass

        self.btn_start.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("正在下载字幕组件包...")

        w = SubtitleRuntimeDownloadWorker()
        self._subtitle_runtime_worker = w

        def on_progress(p: int):
            self.progress_bar.setValue(max(0, min(100, int(p))))

        def on_ok(ver: str):
            self.progress_bar.setValue(100)
            self.lbl_status.setText("字幕组件安装完成")
            self.btn_start.setEnabled(True)
            try:
                ensure_subtitle_runtime_on_path()
            except Exception:
                pass
            QMessageBox.information(self, "完成", f"字幕组件包已安装（版本：{ver or 'unknown'}）。\n现在可以开始生成字幕。")

        def on_fail(err: str):
            self.btn_start.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.lbl_status.setText("")
            QMessageBox.warning(self, "下载失败", str(err or "下载失败"))

        w.progress.connect(on_progress)
        w.finished_ok.connect(on_ok)
        w.failed.connect(on_fail)
        w.start()
