import requests
import os
import sys
import subprocess
import time
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
        try:
            print(f"Checking update from {UPDATE_URL}...")
            response = requests.get(UPDATE_URL, timeout=10)
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
                
        except Exception as e:
            self.error.emit(str(e))

    def download_update(self):
        try:
            print(f"Downloading update from {self.download_url}...")
            response = requests.get(self.download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            # 下载到临时文件
            temp_path = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd(), "LuScreen_new.exe")
            
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = int((downloaded / total_size) * 100)
                            self.download_progress.emit(progress)
                            
            self.download_finished.emit(temp_path)
            
        except Exception as e:
            self.error.emit(str(e))

    def is_newer(self, remote, current):
        try:
            r_parts = [int(x) for x in remote.split('.')]
            c_parts = [int(x) for x in current.split('.')]
            return r_parts > c_parts
        except:
            return remote != current

def install_update(new_exe_path):
    """
    生成并执行更新脚本
    """
    current_exe = sys.executable
    work_dir = os.path.dirname(current_exe)
    bat_path = os.path.join(work_dir, "update.bat")
    
    # 构建批处理脚本
    # 1. 等待主程序退出
    # 2. 替换文件
    # 3. 启动新程序
    # 4. 删除自己
    
    bat_content = f"""
@echo off
timeout /t 2 /nobreak > NUL
:loop
tasklist /FI "PID eq {os.getpid()}" 2>NUL | find /I /N "{os.getpid()}" >NUL
if "%ERRORLEVEL%"=="0" (
    timeout /t 1 /nobreak > NUL
    goto loop
)
move /Y "{new_exe_path}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
"""
    
    with open(bat_path, 'w') as f:
        f.write(bat_content)
        
    # 运行脚本并退出主程序
    subprocess.Popen(bat_path, shell=True)
    sys.exit(0)