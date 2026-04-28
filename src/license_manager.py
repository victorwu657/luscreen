import os
import json
import datetime
import base64
from pathlib import Path

import logging
from src.license_crypto import decode_license_signature, normalize_license_key, verify_rsa_pkcs1v15_sha256

class LicenseManager:
    # 单例模式
    _instance = None
    
    # RSA Public Key (2048-bit) - 用于验证签名
    # 这是配套的公钥，对应的私钥用于签发 License
    # 默认允许的 License: LUSCREEN-PRO-DEV (仅用于开发环境兼容，生产环境请移除)
    PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEApuGXhXDLPiy27wPAOX7H
yHdTmQk66kRglNR4uaUpPVjGIYx3epU2mHIGgq3FsCWwg3wdD2GvR+RSYAMf00iY
xaHjaebG8cPHnWgiLmQbuuvl96r9DdiisQ08LvvKSGfAnwD4E/6pinskUdwI4h43
HWzomJnBv3sB4PlhZo5pvhuEH1EHEID9VJhwR9CuCrKVDU0w9Ki26AvZjBjn+KXd
taOG3TNbuYtZKPbTliiYVg18hHjJsVqUXm2H5bS0STEjFmTFkvqTKvIs3hORHKyp
bNxIvjQLt/9ZmpVSoSWcwSiIn/Tk8r+aPxI/LrYDiiHRNREWnuZ6rctIwyOI6p6/
zwIDAQAB
-----END PUBLIC KEY-----"""

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LicenseManager, cls).__new__(cls)
            cls._instance.init()
        return cls._instance

    def init(self):
        # 默认配置
        self.is_pro = False # 默认为 Free 版
        self.license_key = None
        self.last_error = ""
        
        # 限制配置
        self.LIMITS = {
            "free": {
                "max_resolution": "1080p", # 1080p
                "max_fps": 30,
                "gpu_acceleration": False,
                "ocr_daily_limit": -1, # 无限制
                "watermark": False, # 你决定不加水印
                "record_duration": -1 # -1 表示无限制
            },
            "pro": {
                "max_resolution": "4k",
                "max_fps": 60,
                "gpu_acceleration": True,
                "ocr_daily_limit": -1, # 无限制
                "watermark": False,
                "record_duration": -1
            }
        }
        
        # 本地数据存储路径
        self.data_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'LuScreen')
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        self.usage_file = os.path.join(self.data_dir, 'usage_data.json')
        self.license_file = os.path.join(self.data_dir, 'license.key')
        
        self.load_usage_data()
        self.load_license()

    def load_license(self):
        if os.path.exists(self.license_file):
            try:
                with open(self.license_file, 'r') as f:
                    key = normalize_license_key(f.read())
                    if self.verify_key(key):
                        self.is_pro = True
                        self.license_key = key
            except Exception as e:
                logging.getLogger("License").exception("加载本地激活码失败: %s", e)

    def verify_key(self, key):
        """
        Verify the license key using RSA signature.
        The key is expected to be a Base64 encoded SHA256 signature of the string "LUSCREEN_PRO_LICENSE".
        """
        self.last_error = ""
        if not key:
            self.last_error = "激活码为空"
            return False
        try:
            signature = decode_license_signature(key)
            ok = verify_rsa_pkcs1v15_sha256(self.PUBLIC_KEY_PEM, b"LUSCREEN_PRO_LICENSE", signature)
            if not ok:
                self.last_error = "激活码签名校验失败（可能复制错误或不是本版本签发）"
            return ok
        except ValueError as e:
            self.last_error = str(e)
            logging.getLogger("License").warning("激活码校验失败: %s", e)
            return False
        except Exception as e:
            self.last_error = "激活码校验异常"
            logging.getLogger("License").exception("激活码校验异常: %s", e)
            return False

    def load_usage_data(self):
        self.usage_data = {
            "ocr_count": 0,
            "last_ocr_date": datetime.date.today().isoformat()
        }
        
        if os.path.exists(self.usage_file):
            try:
                with open(self.usage_file, 'r') as f:
                    data = json.load(f)
                    # 检查日期，如果是新的一天则重置
                    today = datetime.date.today().isoformat()
                    if data.get("last_ocr_date") != today:
                        data["ocr_count"] = 0
                        data["last_ocr_date"] = today
                    self.usage_data = data
            except Exception as e:
                print(f"Error loading usage data: {e}")
                
        # 立即保存一次以确保文件存在且日期最新
        self.save_usage_data()

    def save_usage_data(self):
        try:
            with open(self.usage_file, 'w') as f:
                json.dump(self.usage_data, f)
        except Exception as e:
            print(f"Error saving usage data: {e}")

    # --- License 状态管理 ---
    
    def activate_pro(self, key):
        key = normalize_license_key(key)
        if self.verify_key(key):
            self.is_pro = True
            self.license_key = key
            # Save license
            try:
                with open(self.license_file, 'w') as f:
                    f.write(key)
            except Exception as e:
                logging.getLogger("License").exception("保存激活码失败: %s", e)
            return True
        if not self.last_error:
            self.last_error = "无效的激活码"
        return False

    def deactivate(self):
        """Remove license file and reset status to Free"""
        self.is_pro = False
        self.license_key = None
        if os.path.exists(self.license_file):
            try:
                os.remove(self.license_file)
                return True
            except Exception as e:
                logging.getLogger("License").exception("删除激活码文件失败: %s", e)
        return False

    def get_current_limits(self):
        return self.LIMITS["pro"] if self.is_pro else self.LIMITS["free"]

    # --- 功能检查 ---

    def can_use_gpu(self):
        return self.get_current_limits()["gpu_acceleration"]

    def get_max_quality_label(self):
        limits = self.get_current_limits()
        return f"{limits['max_resolution']} @ {limits['max_fps']}fps"

    def can_use_resolution(self, resolution_tag):
        # resolution_tag: "1080p", "2k", "4k"
        limit = self.get_current_limits()["max_resolution"]
        levels = ["1080p", "2k", "4k"]
        try:
            limit_idx = levels.index(limit)
            target_idx = levels.index(resolution_tag)
            return target_idx <= limit_idx
        except ValueError:
            return True # 未知格式默认允许

    def can_use_fps(self, fps):
        return fps <= self.get_current_limits()["max_fps"]

    # --- OCR 限制逻辑 ---

    def can_use_ocr(self):
        limit = self.get_current_limits()["ocr_daily_limit"]
        if limit == -1: return True
        return self.usage_data["ocr_count"] < limit

    def increment_ocr_count(self):
        self.usage_data["ocr_count"] += 1
        self.save_usage_data()

    def get_ocr_usage_text(self):
        limit = self.get_current_limits()["ocr_daily_limit"]
        if limit == -1: return "无限制"
        return f"{self.usage_data['ocr_count']} / {limit}"
