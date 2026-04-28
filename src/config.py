import json
import os
import sys

class ConfigManager:
    def __init__(self, filename="config.json"):
        base_dir = None
        try:
            if getattr(sys, "frozen", False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        except Exception:
            base_dir = None
        if not base_dir:
            base_dir = os.getcwd()

        self.filename = os.path.join(base_dir, filename)
        self._legacy_filename = os.path.join(os.getcwd(), filename)
        self.config = {
            "mic_index": None,
            "mic_enabled": True,
            "sys_audio_enabled": True,
            "cam_index": 0,
            "cam_enabled": False,
            "cam_shape": "circle",
            "cam_border_enabled": True,
            "mouse_enabled": True,
            "mouse_style": "both", # none, highlight, ring, both
            "global_hotkey": "ctrl+l", # 呼出菜单
            "hotkey_record_start": "ctrl+f1",
            "hotkey_record_pause": "ctrl+f2",
            "hotkey_record_stop": "ctrl+f3",
            # 默认保存路径
            "save_path_capture": os.path.join(base_dir, "captures"),
            "save_path_record": os.path.join(base_dir, "recordings"),
            "video_quality": "1080p", # 1080p, 2k, 4k
            "gpu_acceleration": True, # GPU加速开关，默认开启
            "subtitle_offset_ms": 0,
            "subtitle_offset_start_ms": 0,
            "subtitle_offset_end_ms": 0,
            "subtitle_bg": "none",
            
            # 剪贴板设置
            "clipboard_retention_days": 10, # 保留天数
            "clipboard_max_items": 200      # 最大条数
        }
        self._migrate_legacy_config_if_needed()
        self.load()

    def _migrate_legacy_config_if_needed(self):
        try:
            if self._legacy_filename == self.filename:
                return
            if os.path.exists(self.filename):
                return
            if not os.path.exists(self._legacy_filename):
                return
            with open(self._legacy_filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            os.makedirs(os.path.dirname(os.path.abspath(self.filename)), exist_ok=True)
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception:
            return

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding="utf-8") as f:
                    saved = json.load(f)
                    self.config.update(saved)
            except Exception as e:
                print(f"Failed to load config: {e}")

    def save(self):
        try:
            with open(self.filename, 'w', encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
