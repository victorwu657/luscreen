import requests
import os
import sys
import subprocess
import time
import zipfile
import shutil
from PySide6.QtCore import QThread, Signal
from src.version import APP_VERSION, UPDATE_URL

class UpdateWorker(QThread):
    check_finished = Signal(bool, str, str) # has_update, version, url
    download_progress = Signal(int)
    download_finished = Signal(str) # file_path
    error = Signal(str)

    def __init__(self, mode='check', download_url=None):
        super().__init__()
        self.mode = mode # 'check' or 'download'
        self.download_url = download_url

    def run(self):
        if self.mode == 'check':
            self.check_update()
        elif self.mode == 'download':
            self.download_update()

    def check_update(self):
        for attempt in range(3):
            try:
                print(f"Checking update from {UPDATE_URL} (Attempt {attempt+1})...")
                # 增加 Headers 模拟浏览器
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                # 增加时间戳防止 CDN 缓存
                url_with_ts = f"{UPDATE_URL}?t={int(time.time())}"
                response = requests.get(url_with_ts, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                remote_version = data.get('version')
                download_url = data.get('url')
                
                if not remote_version or not download_url:
                    self.error.emit("Invalid version info")
                    return

                if self.is_newer(remote_version, APP_VERSION):
                    self.check_finished.emit(True, remote_version, download_url)
                else:
                    self.check_finished.emit(False, remote_version, "")
                return # 成功后退出循环
                
            except Exception as e:
                print(f"Check failed: {e}")
                if attempt == 2: # 最后一次尝试也失败
                    self.error.emit(str(e))
                time.sleep(1) # 等待一秒重试

    def download_update(self):
        for attempt in range(3):
            try:
                print(f"Downloading update from {self.download_url} (Attempt {attempt+1})...")
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                response = requests.get(self.download_url, headers=headers, stream=True, timeout=30)
                response.raise_for_status()
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                # 下载到临时文件 (ZIP)
                base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
                temp_path = os.path.join(base_dir, "update.zip")
                
                with open(temp_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                progress = int((downloaded / total_size) * 100)
                                self.download_progress.emit(progress)
                                
                self.download_finished.emit(temp_path)
                return # 成功后退出循环
                
            except Exception as e:
                print(f"Download failed: {e}")
                if attempt == 2:
                    self.error.emit(str(e))
                time.sleep(2)

    def is_newer(self, remote, current):
        try:
            r_parts = [int(x) for x in remote.split('.')]
            c_parts = [int(x) for x in current.split('.')]
            return r_parts > c_parts
        except:
            return remote != current

def install_update(zip_path):
    """
    解压更新包并覆盖安装 (文件夹模式)
    """
    try:
        current_exe = sys.executable
        app_dir = os.path.dirname(current_exe)
        
        # 1. 解压到 update_temp 目录
        extract_dir = os.path.join(app_dir, "update_temp")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir)
        
        print(f"Extracting {zip_path} to {extract_dir}...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
            
        # 2. 生成更新脚本
        bat_path = os.path.join(app_dir, "update.bat")
        
        # 构建批处理脚本：
        # 1. 杀进程
        # 2. 将 update_temp 里的内容覆盖到主目录
        # 3. 清理临时文件
        # 4. 重启
        
        bat_content = f"""
@echo off
chcp 65001 > NUL
timeout /t 1 /nobreak > NUL

echo Killing process {os.getpid()}...
taskkill /F /PID {os.getpid()} > NUL 2>&1

:loop_check
tasklist /FI "PID eq {os.getpid()}" 2>NUL | find /I /N "{os.getpid()}" >NUL
if "%ERRORLEVEL%"=="0" (
    timeout /t 1 /nobreak > NUL
    goto loop_check
)

echo Updating files...
xcopy /s /e /y "{extract_dir}\\*" "{app_dir}\\"

if errorlevel 1 (
    echo Update failed!
    pause
    exit
)

echo Cleaning up...
rd /s /q "{extract_dir}"
del "{zip_path}"

echo Restarting...
start "" "{current_exe}"
del "%~f0"
"""
        
        with open(bat_path, 'w', encoding='utf-8') as f:
            f.write(bat_content)
            
        # 3. 启动脚本
        print(f"Starting update script: {bat_path}")
        os.startfile(bat_path)
        
        # 4. 返回 True (后续主程序会收到信号并退出，实际上脚本也会杀进程双重保险)
        return True
        
    except Exception as e:
        print(f"Install update failed: {e}")
        return False