import os
import subprocess
import sys
import imageio_ffmpeg
import re
import time
import ctypes
from ctypes import wintypes

def get_ffmpeg_path():
    """
    获取 FFmpeg 可执行文件路径。
    优先查找当前程序目录下的 ffmpeg.exe (用于打包后的环境)，
    如果未找到，则使用 imageio_ffmpeg 提供的内置版本。
    """
    # 1. 检查应用程序根目录 (打包后 ffmpeg.exe 通常放在这里)
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        # 开发环境：src/utils.py -> src -> root
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
    local_ffmpeg = os.path.join(base_path, 'ffmpeg.exe')
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg
        
    # 2. 回退到 imageio_ffmpeg (开发环境通常用这个)
    return imageio_ffmpeg.get_ffmpeg_exe()

def get_media_duration_sec(path: str) -> float | None:
    if not path:
        return None
    try:
        p = os.path.abspath(path)
    except Exception:
        p = path
    if not os.path.exists(p):
        return None
    ffmpeg_exe = get_ffmpeg_path()
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        proc = subprocess.run(
            [ffmpeg_exe, "-hide_banner", "-i", p],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            startupinfo=startupinfo,
            check=False,
        )
        text = (proc.stdout or b"").decode("utf-8", errors="ignore")
        m = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}\.\d{2})", text)
        if not m:
            return None
        h = float(m.group(1))
        mi = float(m.group(2))
        s = float(m.group(3))
        return h * 3600.0 + mi * 60.0 + s
    except Exception:
        return None

def get_wav_duration_sec(path: str) -> float | None:
    if not path:
        return None
    try:
        p = os.path.abspath(path)
    except Exception:
        p = path
    if not os.path.exists(p):
        return None
    try:
        import soundfile as sf
        f = sf.SoundFile(p)
        return float(len(f)) / float(f.samplerate or 1)
    except Exception:
        return None

def get_long_windows_path(path: str) -> str:
    if not path:
        return path
    if os.name != "nt":
        return path
    try:
        p = os.path.abspath(path)
    except Exception:
        p = path
    try:
        buf = ctypes.create_unicode_buffer(32768)
        GetLongPathNameW = ctypes.windll.kernel32.GetLongPathNameW
        GetLongPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        GetLongPathNameW.restype = wintypes.DWORD
        n = GetLongPathNameW(p, buf, wintypes.DWORD(len(buf)))
        if n and n < len(buf):
            return buf.value
    except Exception:
        return p
    return p

def get_short_windows_path(path: str) -> str:
    if not path:
        return path
    if os.name != "nt":
        return path
    try:
        p = os.path.abspath(path)
    except Exception:
        p = path
    try:
        buf = ctypes.create_unicode_buffer(32768)
        GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
        GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        GetShortPathNameW.restype = wintypes.DWORD
        n = GetShortPathNameW(p, buf, wintypes.DWORD(len(buf)))
        if n and n < len(buf):
            return buf.value
    except Exception:
        return p
    return p

def safe_add_dll_directory(path: str):
    if os.name != "nt":
        return None
    if not hasattr(os, "add_dll_directory"):
        return None
    if not path:
        return None

    def _prefixed(p: str) -> str:
        if p.startswith("\\\\?\\") or p.startswith("\\\\.\\" ):
            return p
        return "\\\\?\\" + p

    try:
        p0 = os.path.abspath(path)
    except Exception:
        p0 = path

    try:
        return os.add_dll_directory(p0)
    except OSError as e:
        winerr = getattr(e, "winerror", None)
        if winerr in (206, 3, 2, 123):
            try:
                p1 = get_long_windows_path(p0)
            except Exception:
                p1 = p0
            try:
                return os.add_dll_directory(_prefixed(p1))
            except Exception:
                pass
            try:
                return os.add_dll_directory(_prefixed(p0))
            except Exception:
                pass
        raise

def get_runtime_base_dir() -> str:
    if getattr(sys, "frozen", False):
        try:
            argv0 = sys.argv[0] if sys.argv else ""
        except Exception:
            argv0 = ""
        try:
            p0 = os.path.abspath(argv0) if argv0 else ""
        except Exception:
            p0 = argv0
        if p0 and os.path.exists(p0) and str(p0).lower().endswith(".exe"):
            return os.path.dirname(p0)
        try:
            return os.path.dirname(sys.executable)
        except Exception:
            return os.getcwd()
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _is_writable_dir(path: str) -> bool:
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        return False
    try:
        p = os.path.join(path, f".w_{os.getpid()}_{int(time.time() * 1000)}.tmp")
        with open(p, "wb") as f:
            f.write(b"x")
        os.remove(p)
        return True
    except Exception:
        return False

def get_runtime_data_dir() -> str:
    base = get_runtime_base_dir()
    if not getattr(sys, "frozen", False):
        return base
    if _is_writable_dir(base):
        return base
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or ""
    if local:
        p = os.path.join(local, "LuScreen")
        try:
            os.makedirs(p, exist_ok=True)
        except Exception:
            return base
        return p
    return base

def open_folder_and_select_file(file_path):
    """
    使用 PowerShell 脚本查找已打开的资源管理器窗口并选中文件。
    如果未找到，则打开新窗口。
    """
    if os.name != 'nt':
        return False
        
    try:
        file_path = os.path.abspath(file_path)
        folder_path = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)
        
        # PowerShell 脚本：遍历窗口，如果找到匹配路径，则选中文件；否则调用 explorer /select
        # 注意：需要处理路径中的单引号
        ps_file_path = file_path.replace("'", "''")
        ps_folder_path = folder_path.replace("'", "''")
        ps_file_name = file_name.replace("'", "''")
        
        ps_script = f"""
        $filePath = '{ps_file_path}';
        $folderPath = '{ps_folder_path}'.TrimEnd('\\');
        $fileName = '{ps_file_name}';
        $shell = New-Object -ComObject Shell.Application;
        
        function Activate-Window {{
            param($targetPath)
            foreach ($window in $shell.Windows()) {{
                try {{
                    if ($window.Document -and $window.Document.Folder) {{
                        $winPath = $window.Document.Folder.Self.Path;
                        if ($winPath) {{
                            $winPath = $winPath.TrimEnd('\\');
                            if ($winPath -eq $targetPath) {{
                                $window.Visible = $true;
                                if ($window.WindowState -eq 1) {{ $window.WindowState = 0; }}
                                
                                $wshell = New-Object -ComObject WScript.Shell;
                                if ($window.LocationName) {{
                                    $wshell.AppActivate($window.LocationName);
                                }}
                                
                                $folder = $window.Document.Folder;
                                $item = $folder.ParseName($fileName);
                                if ($item) {{
                                    $window.Document.SelectItem($item, 29);
                                }}
                                return $true;
                            }}
                        }}
                    }}
                }} catch {{ }}
            }}
            return $false;
        }}
        
        # 第一次尝试查找
        $found = Activate-Window -targetPath $folderPath;
        
        if (-not $found) {{
            # 没找到，打开新窗口
            # 使用 Start-Process 并加上引号，确保路径被正确解析
            Start-Process explorer.exe -ArgumentList "/select, `"$filePath`""
        }}
        """
        
        # 使用 subprocess 运行 PowerShell，隐藏窗口
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], startupinfo=startupinfo)
        return True
    except Exception as e:
        print(f"PowerShell select failed: {e}")
        return False
