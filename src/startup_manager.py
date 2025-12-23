import sys
import os
import winreg

class StartupManager:
    def __init__(self, app_name="LuScreen"):
        self.app_name = app_name
        self.key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def _get_executable_path(self):
        # 判断是否是打包后的 exe (PyInstaller 等)
        if getattr(sys, 'frozen', False):
            return f'"{sys.executable}"'
        else:
            # 开发环境：python.exe "path/to/main.py"
            # 这里的 sys.argv[0] 通常是入口脚本的路径
            script_path = os.path.abspath(sys.argv[0])
            # 为了保险，用 pythonw.exe 避免弹黑框（如果用户有的话），或者直接用当前解释器
            # 这里直接使用当前的 sys.executable
            return f'"{sys.executable}" "{script_path}"'

    def is_enabled(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path, 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, self.app_name)
            winreg.CloseKey(key)
            
            # 简单的校验：检查路径是否包含我们的程序名或路径
            # 只要存在这个 key，我们就认为开启了
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            print(f"Error checking startup: {e}")
            return False

    def set_enabled(self, enabled):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path, 0, winreg.KEY_SET_VALUE)
            if enabled:
                exe_path = self._get_executable_path()
                winreg.SetValueEx(key, self.app_name, 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, self.app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            return True
        except Exception as e:
            print(f"Error setting startup: {e}")
            return False