import json
import os

class ConfigManager:
    def __init__(self, filename="config.json"):
        self.filename = os.path.join(os.getcwd(), filename)
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
            "hotkey_record_pause": "f2",
            "hotkey_record_stop": "ctrl+f3",
            # 默认保存路径
            "save_path_capture": os.path.join(os.getcwd(), "captures"),
            "save_path_record": os.path.join(os.getcwd(), "recordings"),
            "video_quality": "1080p", # 1080p, 2k, 4k
            "gpu_acceleration": False # GPU加速开关，默认关闭
        }
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    saved = json.load(f)
                    self.config.update(saved)
            except Exception as e:
                print(f"Failed to load config: {e}")

    def save(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value