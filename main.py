import sys
import os
import subprocess
import threading
from datetime import datetime

if "--subtitle-service" in sys.argv:
    import importlib
    _mod = importlib.import_module("src.subtitle_system.service_process")
    print(f"[SubtitleServiceMain] argv={sys.argv!r}")
    print(f"[SubtitleServiceMain] executable={sys.executable!r}")
    print(f"[SubtitleServiceMain] cwd={os.getcwd()!r}")
    raise SystemExit(_mod.main())

if "--subtitle-worker" in sys.argv:
    import importlib
    _mod = importlib.import_module("src.subtitle_system.worker_process")
    print(f"[SubtitleWorkerMain] argv={sys.argv!r}")
    print(f"[SubtitleWorkerMain] executable={sys.executable!r}")
    print(f"[SubtitleWorkerMain] cwd={os.getcwd()!r}")
    raise SystemExit(_mod.main())

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("QT_DISABLE_HW_TEXTURES_CONVERSION", "1")
os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", ",")

# 初始化全局日志和异常捕获
from src.logger import (
    install_faulthandler,
    install_global_exception_hooks,
    setup_global_logger,
)
# 立即安装钩子
install_global_exception_hooks()
# 初始化日志记录器
# 不在应用内再次重定向 stdout/stderr，避免录制热路径的 print 压垮日志锁或磁盘 IO。
logger = setup_global_logger(redirect_stdout=False)
fault_path = install_faulthandler()
logger.info(
    "Startup context | pid=%s frozen=%s exe=%s cwd=%s",
    os.getpid(),
    getattr(sys, "frozen", False),
    sys.executable,
    os.getcwd(),
)
logger.info("Startup argv=%r", sys.argv)
if fault_path:
    logger.info("Faulthandler enabled: %s", fault_path)
else:
    logger.warning("Faulthandler was not enabled.")

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox, QWidget, QFileDialog
from PySide6.QtCore import Qt, QTimer, QSharedMemory, QRect, qInstallMessageHandler, QtMsgType

def qt_message_handler(mode, context, message):
    """
    Custom Qt message handler to intercept and filter warnings.
    """
    # Filter out specific libpng warnings
    if "libpng warning: eXIf: duplicate" in message:
        return
        
    import logging
    qt_logger = logging.getLogger("Qt")
    
    if mode == QtMsgType.QtDebugMsg:
        qt_logger.debug(message)
    elif mode == QtMsgType.QtInfoMsg:
        qt_logger.info(message)
    elif mode == QtMsgType.QtWarningMsg:
        qt_logger.warning(message)
    elif mode == QtMsgType.QtCriticalMsg:
        qt_logger.error(message)
    elif mode == QtMsgType.QtFatalMsg:
        qt_logger.critical(message)

# Install the handler immediately
qInstallMessageHandler(qt_message_handler)
from PySide6.QtGui import QIcon, QAction, QCursor, QPixmap
import mss
import numpy as np
import cv2
from datetime import datetime
from src.camera import CameraWidget
from src.selector import SelectionWidget
from src.recorder import ScreenRecorder
from src.control_bar import ControlBar
from src.audio_recorder import AudioRecorder
from src.recording_frame import RecordingFrame
from src.scroll_capture import ScrollCaptureWorker
from src.countdown import CountdownWidget

from src.control_panel import ControlPanel
from src.config import ConfigManager
from src.settings_dialog import SettingsDialog
from src.hotkey_manager import HotkeyManager
from src.mouse_effect import MouseEffectWidget
from src.main_window import MainWindow
from src.ocr_widget import OCRWidget
from src.screenshot_editor import ScreenshotEditor
from src.updater import UpdateWorker, install_update
from src.version import APP_VERSION
import ctypes

# Force Nuitka to detect rapidocr_onnxruntime dependency and its submodules
try:
    import rapidocr_onnxruntime
    import sys

    _det_mod = None
    _rec_mod = None
    _cls_mod = None
    _TextDetector = None
    _TextRecognizer = None
    _TextClassifier = None

    try:
        import rapidocr_onnxruntime.ch_ppocr_det as _det_mod
        import rapidocr_onnxruntime.ch_ppocr_rec as _rec_mod
        import rapidocr_onnxruntime.ch_ppocr_cls as _cls_mod
        from rapidocr_onnxruntime.ch_ppocr_det.text_detect import TextDetector as _TextDetector
        from rapidocr_onnxruntime.ch_ppocr_rec.text_recognize import TextRecognizer as _TextRecognizer
        from rapidocr_onnxruntime.ch_ppocr_cls.text_cls import TextClassifier as _TextClassifier
        from rapidocr_onnxruntime.ch_ppocr_cls import text_cls  # noqa: F401
        from rapidocr_onnxruntime.ch_ppocr_det import text_detect  # noqa: F401
        from rapidocr_onnxruntime.ch_ppocr_rec import text_recognize  # noqa: F401
    except Exception:
        import rapidocr_onnxruntime.ch_ppocr_v3_det as _det_mod
        import rapidocr_onnxruntime.ch_ppocr_v3_rec as _rec_mod
        import rapidocr_onnxruntime.ch_ppocr_v2_cls as _cls_mod
        from rapidocr_onnxruntime.ch_ppocr_v3_det.text_detect import TextDetector as _TextDetector
        from rapidocr_onnxruntime.ch_ppocr_v3_rec.text_recognize import TextRecognizer as _TextRecognizer
        from rapidocr_onnxruntime.ch_ppocr_v2_cls.text_cls import TextClassifier as _TextClassifier
        from rapidocr_onnxruntime.ch_ppocr_v2_cls import text_cls  # noqa: F401
        from rapidocr_onnxruntime.ch_ppocr_v3_det import text_detect  # noqa: F401
        from rapidocr_onnxruntime.ch_ppocr_v3_rec import text_recognize  # noqa: F401

    if _det_mod and _rec_mod and _cls_mod and _TextDetector and _TextRecognizer and _TextClassifier:
        try:
            _det_mod.TextDetector = _TextDetector
            _rec_mod.TextRecognizer = _TextRecognizer
            _cls_mod.TextClassifier = _TextClassifier
        except Exception:
            pass

        sys.modules[_det_mod.__name__] = _det_mod
        sys.modules[_rec_mod.__name__] = _rec_mod
        sys.modules[_cls_mod.__name__] = _cls_mod

        if _det_mod.__name__.startswith("rapidocr_onnxruntime."):
            sys.modules[_det_mod.__name__.split(".", 1)[1]] = _det_mod
        if _rec_mod.__name__.startswith("rapidocr_onnxruntime."):
            sys.modules[_rec_mod.__name__.split(".", 1)[1]] = _rec_mod
        if _cls_mod.__name__.startswith("rapidocr_onnxruntime."):
            sys.modules[_cls_mod.__name__.split(".", 1)[1]] = _cls_mod
except ImportError:
    pass

# Set AppUserModelID to ensure taskbar icon shows correctly
try:
    myappid = 'luscreen.app.v1' # Arbitrary unique ID
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except ImportError:
    pass

# 启用高分屏支持 (High DPI Support)
# Qt 6 默认启用 High DPI 支持，手动设置会导致 "SetProcessDpiAwarenessContext() failed" 错误
# 因此移除手动 ctypes 调用，让 Qt 自动处理
# if os.name == 'nt':
#     try:
#         # Windows 8.1+
#         ctypes.windll.shcore.SetProcessDpiAwareness(1) # 1 = PROCESS_SYSTEM_DPI_AWARE
#     except Exception:
#         # Windows Vista/7/8
#         try:
#             ctypes.windll.user32.SetProcessDPIAware()
#         except:
#             pass

from src.clipboard_manager import ClipboardManager
from src.clipboard_window import ClipboardWindow
from src.ai_tools_window import AIToolsWindow

class LuScreenApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False) # 关闭所有窗口不退出程序
        
        # Set global application icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'icon.png')
        if os.path.exists(icon_path):
            self.app.setWindowIcon(QIcon(icon_path))
        
        # 加载配置
        self.config_manager = ConfigManager()

        # 初始化剪贴板管理器
        self.clipboard_manager = ClipboardManager()
        self.clipboard_window = ClipboardWindow(self.clipboard_manager)
        
        # 初始化AI工具窗口
        self.ai_tools_window = AIToolsWindow()
        
        # 初始化快捷键管理器
        self.hotkey_manager = HotkeyManager()
        
        # 注册全局菜单快捷键
        hotkey_menu = self.config_manager.get("global_hotkey", "ctrl+shift+f1")
        self.hotkey_manager.register_hotkey("menu", hotkey_menu)
        
        # 注册录制快捷键
        hk_start = self.config_manager.get("hotkey_record_start", "ctrl+f1")
        hk_pause = self.config_manager.get("hotkey_record_pause", "ctrl+f2")
        hk_stop = self.config_manager.get("hotkey_record_stop", "ctrl+f3")
        
        self.hotkey_manager.register_hotkey("record_start", hk_start)
        self.hotkey_manager.register_hotkey("record_pause", hk_pause)
        self.hotkey_manager.register_hotkey("record_stop", hk_stop)
        
        # Use QueuedConnection to ensure UI updates happen on the main thread
        # regardless of which thread triggers the hotkey (keyboard/mouse listeners)
        self.hotkey_manager.hotkey_triggered.connect(self.on_hotkey_triggered, Qt.QueuedConnection)

        # 初始化组件
        self.camera_widget = None
        self.selection_widget = None
        self.recorder = None
        self.control_bar = None
        self.recording_frame = None
        self.mouse_effect = None
        self.editors = [] # Keep track of open image editors
        self._stop_poll_timer = None
        self._stopping_recorder = None
        
        # 主程序窗口
        self.main_window = MainWindow()
        self.main_window.action_triggered.connect(self.on_main_window_action)
        
        # 从配置中读取默认设置
        self.selected_mic_index = self.config_manager.get("mic_index")
        self.selected_cam_index = self.config_manager.get("cam_index", 0)
        self.selected_cam_shape = self.config_manager.get("cam_shape", "circle")
        self.record_audio = self.config_manager.get("mic_enabled", True)
        self.record_sys_audio = self.config_manager.get("sys_audio_enabled", True)
        self.cam_enabled = self.config_manager.get("cam_enabled", False)
        self.mouse_enabled = self.config_manager.get("mouse_enabled", True)
        self.mouse_style = self.config_manager.get("mouse_style", "both")
        
        # 系统托盘
        self.setup_tray()

        # 启动时显示主窗口
        self.main_window.show_at_bottom_right()

        self.update_worker = None
        
        # 启动时自动检查更新 (延迟3秒，避免拖慢启动速度)
        QTimer.singleShot(3000, lambda: self.check_for_updates(silent=True))

    def check_for_updates(self, silent=False):
        if self.update_worker and self.update_worker.isRunning():
            return
            
        self.update_worker = UpdateWorker(mode='check')
        self.update_worker.check_finished.connect(lambda h, v, u: self.on_check_finished(h, v, u, silent))
        
        if not silent:
            self.update_worker.error.connect(lambda e: QMessageBox.warning(None, "更新检查失败", e))
        
        self.update_worker.start()
        
    def on_check_finished(self, has_update, version, url, silent):
        if has_update:
            reply = QMessageBox.question(
                None, "发现新版本", 
                f"发现新版本 {version}！\n当前版本: {APP_VERSION}\n\n是否立即更新？",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.start_download(url)
        else:
            if not silent:
                QMessageBox.information(None, "检查更新", f"当前已是最新版本 ({APP_VERSION})")
            
    def start_download(self, url):
        # 显示下载进度条 (简单的 ProgressDialog)
        from PySide6.QtWidgets import QProgressDialog
        self.progress_dialog = QProgressDialog("正在下载更新...", "取消", 0, 100, None)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()
        
        self.update_worker = UpdateWorker(mode='download', download_url=url)
        self.update_worker.download_progress.connect(self.progress_dialog.setValue)
        self.update_worker.download_finished.connect(self.on_download_finished)
        self.update_worker.error.connect(lambda e: QMessageBox.warning(None, "下载失败", e))
        self.update_worker.start()
        
        self.progress_dialog.canceled.connect(self.update_worker.terminate)

    def on_download_finished(self):
        from src.updater import log
        log("Signal received: LuScreenApp.on_download_finished")
        
        self.progress_dialog.close()
        
        # 硬编码路径，避免信号传参风险
        base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
        file_path = os.path.join(base_dir, "update.zip")
        
        log(f"Using fixed path: {file_path}")
        
        # 强制 GC，防止 Nuitka 环境下的资源释放崩溃
        import gc
        gc.collect()
        
        # 使用 QTimer.singleShot 延迟执行
        from PySide6.QtCore import QTimer
        log("Scheduling prompt_install...")
        QTimer.singleShot(500, lambda: self.prompt_install(file_path))

    def prompt_install(self, file_path):
        from src.updater import log
        log("Executing LuScreenApp.prompt_install...")
        
        reply = QMessageBox.question(
            None, "下载完成", 
            "更新包已下载完成。\n\n程序将重启以完成更新。\n是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if install_update(file_path):
                QApplication.quit()

    def get_resource_path(self, relative_path):
        """ Get absolute path to resource, works for dev and for PyInstaller/Nuitka """
        try:
            # PyInstaller/Nuitka creates a temp folder and stores path in _MEIPASS or similar
            if hasattr(sys, '_MEIPASS'):
                 base_path = sys._MEIPASS
            else:
                 base_path = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        return os.path.join(base_path, relative_path)

    def get_ffmpeg_path(self):
        """Locate ffmpeg.exe: Check current dir (for onefile) then system path"""
        # 1. Check same directory as the executable (Best for OneFile distribution)
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        local_ffmpeg = os.path.join(base_path, 'ffmpeg.exe')
        if os.path.exists(local_ffmpeg):
            return local_ffmpeg
            
        # 2. Check assets folder (if embedded)
        embedded_ffmpeg = self.get_resource_path('ffmpeg.exe')
        if os.path.exists(embedded_ffmpeg):
             return embedded_ffmpeg

        # 3. Fallback to imageio-ffmpeg or system path (handled by recorder)
        return None
   

    def setup_tray(self):
        # 设置托盘图标
        icon_path = self.get_resource_path(os.path.join("assets", "icon.png"))
        if os.path.exists(icon_path):
            self.tray_icon = QSystemTrayIcon(QIcon(icon_path), self.app)
        else:
            self.tray_icon = QSystemTrayIcon(self.app)
            print(f"Warning: Icon not found at {icon_path}")
        
        # 托盘菜单
        # 创建一个隐形的父窗口以确保菜单能正确获取焦点
        self.dummy_widget = QWidget()
        self.dummy_widget.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        
        self.tray_menu = QMenu(self.dummy_widget)
        self.tray_menu.setStyleSheet("""
            QMenu {
                background-color: #2b2b2b;
                color: white;
                border: 1px solid #3f3f3f;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #007aff;
            }
            QMenu::separator {
                height: 1px;
                background: #3f3f3f;
                margin: 5px 0;
            }
        """)
        
        # --- 截图区域 ---
        # 区域截图
        self.action_capture_area = QAction("⛶  区域截图 (Capture Area)", self.app)
        self.action_capture_area.triggered.connect(lambda: self.start_selection(mode='capture'))
        self.tray_menu.addAction(self.action_capture_area)
        
        # 全屏截图
        self.action_capture_full = QAction("🖥️  全屏截图 (Capture Fullscreen)", self.app)
        self.action_capture_full.triggered.connect(self.capture_fullscreen)
        self.tray_menu.addAction(self.action_capture_full)
        
        self.tray_menu.addSeparator()
        
        # --- 录屏区域 ---
        # 录制屏幕
        self.action_record = QAction("🔴  录制屏幕 (Record Screen)", self.app)
        self.action_record.triggered.connect(lambda: self.start_selection(mode='record'))
        self.tray_menu.addAction(self.action_record)
        
        # 视频编辑
        self.action_edit_video = QAction("🎞️  视频编辑 (Video Editor)", self.app)
        self.action_edit_video.triggered.connect(self.open_video_editor)
        self.tray_menu.addAction(self.action_edit_video)
        
        self.tray_menu.addSeparator()
        
        # 剪贴板
        self.action_clipboard = QAction("📋  剪贴板 (Clipboard)", self.app)
        self.action_clipboard.triggered.connect(lambda: self.on_main_window_action('clipboard'))
        self.tray_menu.addAction(self.action_clipboard)
        
        # AI工具
        self.action_ai_tools = QAction("🤖  AI 工具 (AI Tools)", self.app)
        self.action_ai_tools.triggered.connect(lambda: self.on_main_window_action('ai_tools'))
        self.tray_menu.addAction(self.action_ai_tools)
        
        self.tray_menu.addSeparator()
        
        # 增加设置选项
        self.action_settings = QAction("⚙️  设置 (Settings)", self.app)
        self.action_settings.triggered.connect(self.open_settings)
        self.tray_menu.addAction(self.action_settings)
        
        # 增加检查更新选项
        self.action_update = QAction("🚀  检查更新 (Check Update)", self.app)
        self.action_update.triggered.connect(self.check_for_updates)
        self.tray_menu.addAction(self.action_update)
        
        self.tray_menu.addSeparator()
        
        # 退出
        self.action_quit = QAction("退出 LuScreen", self.app)
        self.action_quit.triggered.connect(self.confirm_quit)
        self.tray_menu.addAction(self.action_quit)
        
        # 不再设置默认的右键菜单
        # self.tray_icon.setContextMenu(self.tray_menu)
        
        self.tray_icon.show()
        self.tray_icon.setToolTip("LuScreen")
        
        # 监听点击事件
        self.tray_icon.activated.connect(self.on_tray_activated)

    def on_hotkey_triggered(self, action):
        if action == "menu":
            self.main_window.show_at_cursor()
        elif action == "record_start":
            # 如果选区工具已打开，按下开始键等于点击“开始录制”按钮
            if self.selection_widget is not None:
                self.selection_widget.confirm_selection()
            # 如果未录制且无选区，开始选区录制
            elif self.recorder is None:
                self.start_selection(mode='record')
        elif action == "record_pause":
            # 切换暂停/继续
            if self.recorder:
                if self.recorder.is_paused:
                    self.recorder.resume()
                    if self.control_bar: self.control_bar.resume_timer()
                else:
                    self.recorder.pause()
                    if self.control_bar: self.control_bar.pause_timer()
        elif action == "record_stop":
            # 停止录制
            if self.recorder:
                self.stop_recording()

    def on_tray_activated(self, reason):
        # Trigger (单击) 或 DoubleClick (双击) 都显示主窗口
        if reason == QSystemTrayIcon.Trigger or reason == QSystemTrayIcon.DoubleClick:
            self.main_window.show_at_bottom_right() # 显示在右下角
            # 考虑到用户习惯，点击托盘通常希望看到界面

    def open_image_editor(self):
        # Open editor directly in standalone mode (empty canvas)
        editor = ScreenshotEditor(mode='standalone')
        editor.show()
        editor.activateWindow()
        
        self.editors.append(editor)
        # Remove from list when closed to allow GC
        editor.destroyed.connect(lambda: self.editors.remove(editor) if editor in self.editors else None)

    def on_main_window_action(self, action):
        if action == 'capture_area':
            self.start_selection(mode='capture')
        elif action == 'capture_full':
            self.capture_fullscreen()
        elif action == 'record':
            self.start_selection(mode='record')
        elif action == 'edit_video':
            self.open_video_editor()
        elif action == 'ocr':
            self.start_selection(mode='ocr')
        elif action == 'edit_image':
            self.open_image_editor()
        elif action == 'clipboard':
            # 显示剪贴板窗口
            # 定位到屏幕右下角，距离边缘 30px
            screen_geo = self.app.primaryScreen().availableGeometry()
            w = self.clipboard_window.width()
            h = self.clipboard_window.height()
            
            x = screen_geo.right() - w - 30
            y = screen_geo.bottom() - h - 30
            
            self.clipboard_window.move(x, y)
            self.clipboard_window.show()
            self.clipboard_window.activateWindow()
        elif action == 'ai_tools':
            # 显示AI工具窗口
            # 居中显示
            screen_geo = self.app.primaryScreen().availableGeometry()
            w = self.ai_tools_window.width()
            h = self.ai_tools_window.height()
            x = screen_geo.center().x() - w // 2
            y = screen_geo.center().y() - h // 2
            
            self.ai_tools_window.move(x, y)
            self.ai_tools_window.show()
            self.ai_tools_window.activateWindow()
        elif action == 'settings':
            self.open_settings()
        elif action == 'quit':
            self.confirm_quit()



    # 摄像头和麦克风逻辑已迁移至 ControlPanel 和 on_selection_settings_changed

    def open_camera(self, index):
        if self.camera_widget is None:
            try:
                print(f"DEBUG: Creating CameraWidget with index {index}")
                self.camera_widget = CameraWidget(camera_index=index)
                self.camera_widget.set_shape(self.selected_cam_shape) # 应用保存的形状
                self.camera_widget.set_border_visible(self.config_manager.get("cam_border_enabled", False))
                self.camera_widget.show()
                self.camera_widget.raise_() # 强制置顶
                print(f"Camera opened with index {index}")
            except Exception as e:
                print(f"Failed to open camera: {e}")
        else:
            # 如果已经打开，则切换
            print(f"DEBUG: Switching CameraWidget to index {index}")
            self.camera_widget.change_camera(index)
            self.camera_widget.set_shape(self.selected_cam_shape) # 确保形状正确
            self.camera_widget.show()
            self.camera_widget.raise_() # 强制置顶
            print(f"Camera switched to index {index}")

    def close_camera(self):
        if self.camera_widget:
            self.camera_widget.close()
            self.camera_widget = None
            print("Camera closed")

    def get_device_name(self, index, type_):
        try:
            if type_ == 'mic':
                devices = AudioRecorder.get_input_devices()
                for d in devices:
                    if d['index'] == index: return d['name']
            elif type_ == 'cam':
                cameras = CameraWidget.get_available_cameras()
                for c in cameras:
                    if c['index'] == index: return c['name']
        except:
            pass
        return None

    def validate_device_index(self, index, name, type_):
        """
        Check if the device at `index` matches `name`.
        If not, try to find `name` in current devices.
        If not found, return default index 0.
        """
        try:
            current_devices = []
            if type_ == 'mic':
                current_devices = AudioRecorder.get_input_devices()
            else:
                current_devices = CameraWidget.get_available_cameras()
                
            if not current_devices: return 0
            
            # 1. Check if index is valid and name matches
            for d in current_devices:
                if d['index'] == index:
                    if name and d['name'] == name:
                        return index # Match!
                    if name is None:
                        return index # Legacy config, accept current
                    break # Index exists but name mismatch
            
            # 2. Try to find by name
            if name:
                for d in current_devices:
                    if d['name'] == name:
                        return d['index']
            
            # 3. Fallback
            return 0
            
        except Exception as e:
            print(f"Device validation error: {e}")
            return 0

    def start_selection(self, mode='record'):
        try:
            for ed in list(getattr(self, "editors", []) or []):
                try:
                    if hasattr(ed, "prop_panel") and ed.prop_panel:
                        ed.prop_panel.hide()
                except Exception:
                    pass
        except Exception:
            pass

        # Check if selection widget already exists
        if self.selection_widget is not None:
            print(f"DEBUG: Selection widget already open, bringing to front. Mode: {mode}")
            
            # If switching modes, update the mode? 
            # The user requirement implies "don't open a second one", but maybe they want to switch mode?
            # Assuming "click Record Screen" means "I want to record". 
            # If it's already open, just showing it is enough.
            # But we might want to ensure it's in the right mode if feasible, 
            # but usually restarting selection is cleaner if mode differs significantly.
            # However, requirement says "Only open existing control panel".
            # So we just activate it.
            
            self.selection_widget.show_panel()
            self.selection_widget.activateWindow()
            
            if self.selection_widget.control_panel:
                if self.selection_widget.control_panel.isMinimized():
                    self.selection_widget.control_panel.showNormal()
                self.selection_widget.control_panel.show()
                self.selection_widget.control_panel.raise_()
                self.selection_widget.control_panel.activateWindow()
            return

        # --- Device Auto-Correction Logic ---
        # Mic
        if self.record_audio:
            mic_idx = self.config_manager.get("mic_index")
            mic_name = self.config_manager.get("mic_name")
            new_mic_idx = self.validate_device_index(mic_idx, mic_name, 'mic')
            if new_mic_idx != mic_idx:
                print(f"Auto-corrected Mic Index: {mic_idx} -> {new_mic_idx}")
                self.selected_mic_index = new_mic_idx
                self.config_manager.set("mic_index", new_mic_idx)
            
            # Update name in config if missing or changed
            curr_name = self.get_device_name(self.selected_mic_index, 'mic')
            if curr_name and curr_name != mic_name:
                self.config_manager.set("mic_name", curr_name)

        # Cam
        if self.cam_enabled:
            cam_idx = self.config_manager.get("cam_index", 0)
            cam_name = self.config_manager.get("cam_name")
            new_cam_idx = self.validate_device_index(cam_idx, cam_name, 'cam')
            if new_cam_idx != cam_idx:
                print(f"Auto-corrected Cam Index: {cam_idx} -> {new_cam_idx}")
                self.selected_cam_index = new_cam_idx
                self.config_manager.set("cam_index", new_cam_idx)
                
            # Update name
            curr_cam_name = self.get_device_name(self.selected_cam_index, 'cam')
            if curr_cam_name and curr_cam_name != cam_name:
                self.config_manager.set("cam_name", curr_cam_name)
        
        # 1. 创建控制面板
        control_panel = ControlPanel()
        
        # 应用保存的配置到面板
        control_panel.btn_mic.setChecked(self.record_audio)
        control_panel.btn_sys.setChecked(self.record_sys_audio)
        control_panel.btn_cam.setChecked(self.cam_enabled)
        control_panel.btn_mouse.setChecked(self.mouse_enabled)
        
        # 还需要设置面板内部选中的 index，以便右键菜单显示正确
        control_panel.current_mic_index = self.selected_mic_index
        control_panel.current_mic_name = self.config_manager.get("mic_name") # Pass saved name
        control_panel.current_cam_index = self.selected_cam_index
        control_panel.current_mouse_style = self.mouse_style
        
        # 2. 创建选区工具 (将面板传递给它)
        self.selection_widget = SelectionWidget(control_panel, mode=mode)
        # 安全清理：当对象销毁时自动置空引用，防止 Dangling Pointer
        self.selection_widget.destroyed.connect(self.on_selection_widget_destroyed)
        
        # 如果是录屏模式，且配置中开启了摄像头，确保它是打开的
        if mode == 'record':
            # 如果摄像头开启且未显示，则显示
            if self.cam_enabled and self.camera_widget is None:
                # 只有在录制中或选区中才自动打开
                if self.recorder is not None or self.selection_widget is not None:
                    self.open_camera(self.selected_cam_index)
            # 如果摄像头关闭且已显示，则关闭
        
        # 截图模式下，保持摄像头现状（不自动打开，也不自动关闭）
        
        # 连接信号
        if mode == 'record':
            self.selection_widget.area_selected.connect(self.start_recording)
        elif mode == 'ocr':
            self.selection_widget.area_selected.connect(self.ocr_area)
        else:
            self.selection_widget.area_selected.connect(self.capture_area)
            self.selection_widget.scroll_area_selected.connect(self.start_scroll_capture)
            
        self.selection_widget.cancelled.connect(self.selection_cancelled)
        self.selection_widget.settings_changed.connect(self.on_selection_settings_changed)
        self.selection_widget.camera_ratio_changed.connect(self.update_camera_ratio)
        self.selection_widget.mode_changed.connect(self.on_selection_mode_changed)
        
        # 3. 初始状态：只显示面板，不显示全屏遮罩
        # self.selection_widget.show() # 移除此行，由模式切换控制显示
        
        # 显示面板 (它会计算初始位置)
        self.selection_widget.show_panel()
        
        # 关键修复：确保摄像头在选区工具之上，以便用户可以拖拽它
        if self.camera_widget and self.camera_widget.isVisible():
            self.camera_widget.raise_()

    def update_camera_ratio(self, ratio):
        if self.camera_widget:
            # Force custom shape mode when ratio is explicitly set via UI
            if self.camera_widget.shape_mode == 'circle':
                self.camera_widget.shape_mode = 'custom'
            self.camera_widget.set_aspect_ratio(ratio)
            print(f"DEBUG: Camera ratio updated to {ratio}")

    def on_selection_mode_changed(self, mode):
        print(f"DEBUG: Mode changed to {mode}")
        try:
            logger.info(
                "on_selection_mode_changed start mode=%s selection_widget_visible=%s panel_visible=%s panel_geom=%s camera_visible=%s camera_geom=%s",
                mode,
                self.selection_widget.isVisible() if self.selection_widget else None,
                self.selection_widget.control_panel.isVisible() if self.selection_widget and self.selection_widget.control_panel else None,
                self.selection_widget.control_panel.geometry() if self.selection_widget and self.selection_widget.control_panel else None,
                self.camera_widget.isVisible() if self.camera_widget else None,
                self.camera_widget.geometry() if self.camera_widget else None,
            )
        except Exception:
            pass
        if mode == 'camera_only':
            # Ensure camera is open and visible
            if not self.camera_widget:
                self.open_camera(self.selected_cam_index)
            elif not self.camera_widget.isVisible():
                self.camera_widget.show()
                self.camera_widget.raise_()

            if self.camera_widget:
                print("DEBUG: Applying Camera Only settings (9:16, 400px, Center)")
                # 1. 形状：矩形 9:16
                self.camera_widget.set_shape('9:16')
                # 2. 尺寸：大 (400px)
                self.camera_widget.resize_to_width(400)
                # 3. 位置：居中
                self.camera_widget.move_to_center()
                
                # Log position
                geo = self.camera_widget.geometry()
                print(f"DEBUG: Camera moved to Center: x={geo.x()}, y={geo.y()}, w={geo.width()}, h={geo.height()}")
        
        elif mode in ['fullscreen', 'area']:
            print(f"DEBUG: Applying {mode} settings (Circle, 200px, Bottom-Right)")
            # 切换回普通录制模式时，如果摄像头已打开
            if self.camera_widget and self.camera_widget.isVisible():
                # 1. 形状：圆形
                self.camera_widget.set_shape('circle')
                # 2. 尺寸：小 (200px - 默认小尺寸)
                self.camera_widget.resize_to_width(200)
                # 3. 位置：右下角
                self.camera_widget.move_to_bottom_right()
                
                # Log position
                geo = self.camera_widget.geometry()
                print(f"DEBUG: Camera moved to Bottom-Right: x={geo.x()}, y={geo.y()}, w={geo.width()}, h={geo.height()}")
            try:
                if self.selection_widget and self.selection_widget.control_panel:
                    self.selection_widget.control_panel.show()
                    self.selection_widget.control_panel.raise_()
                    self.selection_widget.control_panel.activateWindow()
            except Exception as e:
                print(f"DEBUG: Failed to raise control panel in {mode} mode: {e}")
        try:
            logger.info(
                "on_selection_mode_changed end mode=%s selection_widget_visible=%s panel_visible=%s panel_active=%s panel_geom=%s camera_visible=%s camera_geom=%s",
                mode,
                self.selection_widget.isVisible() if self.selection_widget else None,
                self.selection_widget.control_panel.isVisible() if self.selection_widget and self.selection_widget.control_panel else None,
                self.selection_widget.control_panel.isActiveWindow() if self.selection_widget and self.selection_widget.control_panel else None,
                self.selection_widget.control_panel.geometry() if self.selection_widget and self.selection_widget.control_panel else None,
                self.camera_widget.isVisible() if self.camera_widget else None,
                self.camera_widget.geometry() if self.camera_widget else None,
            )
        except Exception:
            pass

    def start_scroll_capture(self, rect):
        print(f"Starting scroll capture for area: {rect}")
        self.selection_widget = None
        
        # 暂时隐藏鼠标特效，防止录入滚动截图
        self.mouse_effect_hidden_for_scroll = False
        if self.mouse_effect and self.mouse_effect.isVisible():
            self.mouse_effect.hide()
            self.mouse_effect_hidden_for_scroll = True
        
        # 1. 确定保存路径
        save_path = self.config_manager.get("save_path_capture")
        if not os.path.exists(save_path):
            os.makedirs(save_path)
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(save_path, f"ScrollCapture_{timestamp}.png")
        
        # 2. 启动 Worker
        # 转换 rect 为 dict
        region = {'top': rect.top(), 'left': rect.left(), 'width': rect.width(), 'height': rect.height()}
        
        self.scroll_worker = ScrollCaptureWorker(region, filename)
        self.scroll_worker.finished.connect(self.on_scroll_capture_finished)
        self.scroll_worker.error.connect(self.on_scroll_capture_error)
        self.scroll_worker.progress.connect(lambda n: print(f"Captured {n} frames..."))
        
        # 提示用户
        self.tray_icon.showMessage("滚动截图开始", "请勿移动鼠标，按 ESC 停止", QSystemTrayIcon.Information, 3000)
        
        self.scroll_worker.start()

    def on_scroll_capture_finished(self, path):
        # 恢复鼠标特效
        if getattr(self, 'mouse_effect_hidden_for_scroll', False):
            if self.mouse_effect:
                self.mouse_effect.show()
            self.mouse_effect_hidden_for_scroll = False
            
        print(f"Scroll capture finished: {path}")
        self.tray_icon.showMessage("滚动截图完成", f"已保存至: {path}", QSystemTrayIcon.Information, 3000)
        
        # 打开文件
        try:
            if os.name == 'nt':
                subprocess.run(['explorer', '/select,', os.path.normpath(path)])
        except:
            pass
        self.scroll_worker = None

    def on_scroll_capture_error(self, error):
        # 恢复鼠标特效
        if getattr(self, 'mouse_effect_hidden_for_scroll', False):
            if self.mouse_effect:
                self.mouse_effect.show()
            self.mouse_effect_hidden_for_scroll = False
            
        print(f"Scroll capture error: {error}")
        self.tray_icon.showMessage("滚动截图失败", error, QSystemTrayIcon.Warning, 3000)
        self.scroll_worker = None

    def ocr_area(self, rect, mode=None):
        print(f"OCR area: {rect}, mode: {mode}")
        self.selection_widget = None
        
        try:
            with mss.mss() as sct:
                # DPI Scaling Correction
                monitor = sct.monitors[1]
                qt_screen = self.app.primaryScreen().geometry()
                
                scale_x = monitor['width'] / qt_screen.width()
                scale_y = monitor['height'] / qt_screen.height()
                
                region = {
                    'top': int(rect.top() * scale_y),
                    'left': int(rect.left() * scale_x),
                    'width': int(rect.width() * scale_x),
                    'height': int(rect.height() * scale_y)
                }
                
                sct_img = sct.grab(region)
                img = np.array(sct_img)
                # MSS returns BGRA, RapidOCR needs BGR
                img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                
                self.ocr_widget = OCRWidget(img_bgr)
                self.ocr_widget.show()
                
        except Exception as e:
            print(f"OCR Error: {e}")
            QMessageBox.warning(None, "OCR 错误", str(e))

    def on_selection_settings_changed(self, settings):
        print(f"DEBUG: Received settings change: {settings}") # 调试日志
        type_ = settings['type']
        value = settings['value']
        
        if type_ == 'mic_toggle':
            self.record_audio = value
            self.config_manager.set("mic_enabled", value)
            print(f"Mic toggled: {value}")
        elif type_ == 'mic_idx':
            self.selected_mic_index = value
            self.config_manager.set("mic_index", value)
            name = self.get_device_name(value, 'mic')
            if name: self.config_manager.set("mic_name", name)
            print(f"Mic changed: {value} ({name})")
        elif type_ == 'sys_toggle':
            self.record_sys_audio = value
            self.config_manager.set("sys_audio_enabled", value)
            print(f"System audio toggled: {value}")
        elif type_ == 'cam_toggle':
            self.cam_enabled = value
            self.config_manager.set("cam_enabled", value)
            if value:
                # 开启摄像头
                print(f"DEBUG: Toggling camera ON with index {self.selected_cam_index}")
                self.open_camera(self.selected_cam_index)
            else:
                # 关闭摄像头
                print("DEBUG: Toggling camera OFF")
                self.close_camera()
        elif type_ == 'cam_idx':
            self.selected_cam_index = value
            self.config_manager.set("cam_index", value)
            name = self.get_device_name(value, 'cam')
            if name: self.config_manager.set("cam_name", name)
            print(f"DEBUG: Camera index changed to {value} ({name}), opening camera...")
            self.open_camera(self.selected_cam_index)
        elif type_ == 'cam_shape':
            self.selected_cam_shape = value
            self.config_manager.set("cam_shape", value)
            if self.camera_widget:
                self.camera_widget.set_shape(value)
            print(f"DEBUG: Camera shape changed to {value}")
        elif type_ == 'cam_size':
            self.config_manager.set("cam_size", value)
            if self.camera_widget:
                self.camera_widget.resize_to_width(value)
        elif type_ == 'mouse_style':
            self.mouse_style = value
            self.config_manager.set("mouse_style", value)
            print(f"DEBUG: Mouse style changed to {value}")
            
        # 实时保存配置
        self.config_manager.save()

    def open_video_editor(self):
        # 1. Select Video File
        file_path, _ = QFileDialog.getOpenFileName(
            None, 
            "打开视频文件", 
            self.config_manager.get("save_path_record", ""), 
            "视频文件 (*.mp4 *.avi *.mkv *.mov);;所有文件 (*.*)"
        )
        
        if not file_path:
            return
            
        try:
            from src.video_editor import VideoEditor
            
            # 2. Auto-detect related files (mic/sys audio, metadata)
            # Assuming standard naming convention: name.mp4 -> name_mic.wav, name_sys.wav, name.json
            base_path = os.path.splitext(file_path)[0]
            
            mic_path = f"{base_path}_mic.wav"
            if not os.path.exists(mic_path): mic_path = None
            
            sys_path = f"{base_path}_sys.wav"
            if not os.path.exists(sys_path): sys_path = None
            
            # 兼容性处理：如果未找到分离音轨，尝试将视频本身作为系统音频源，以便显示音量控制
            # 注意：这需要 VideoEditor 内部逻辑支持将视频文件作为 audio_sys 输入
            if not mic_path and not sys_path:
                # 只有当它是普通视频文件时才这样做
                sys_path = file_path

            meta_path = f"{base_path}.json"
            if not os.path.exists(meta_path): meta_path = None
            
            # Default output path (add 'edit' suffix)
            output_path = f"{base_path}_edit.mp4"
            
            if not hasattr(self, 'editors'):
                self.editors = []
            
            # 3. Launch Editor reusing the existing class
            editor = VideoEditor(file_path, mic_path, sys_path, meta_path, output_path)
            self.editors.append(editor)
            editor.show()
            
            # Cleanup closed editors
            self.editors = [e for e in self.editors if e.isVisible()]
            
        except Exception as e:
            print(f"Failed to launch editor: {e}")
            QMessageBox.critical(None, "错误", f"无法启动视频编辑器: {str(e)}")

    def open_settings(self):
        # 暂停全局快捷键，防止在设置时触发或死锁
        self.hotkey_manager.unregister_all()
        
        dialog = SettingsDialog(self.config_manager)
        dialog.exec()
        
        # 设置关闭后，重新从 config 读取配置到内存变量
        self.selected_mic_index = self.config_manager.get("mic_index")
        self.selected_cam_index = self.config_manager.get("cam_index", 0)
        self.selected_cam_shape = self.config_manager.get("cam_shape", "circle")
        self.record_audio = self.config_manager.get("mic_enabled", True)
        self.record_sys_audio = self.config_manager.get("sys_audio_enabled", True)
        self.cam_enabled = self.config_manager.get("cam_enabled", False)
        self.mouse_enabled = self.config_manager.get("mouse_enabled", True)
        self.mouse_style = self.config_manager.get("mouse_style", "both")
        
        # 更新快捷键
        hk_menu = self.config_manager.get("global_hotkey", "ctrl+l")
        self.hotkey_manager.register_hotkey("menu", hk_menu)
        
        hk_start = self.config_manager.get("hotkey_record_start", "ctrl+f1")
        self.hotkey_manager.register_hotkey("record_start", hk_start)
        
        hk_pause = self.config_manager.get("hotkey_record_pause", "f2")
        self.hotkey_manager.register_hotkey("record_pause", hk_pause)
        
        hk_stop = self.config_manager.get("hotkey_record_stop", "ctrl+f3")
        self.hotkey_manager.register_hotkey("record_stop", hk_stop)
        
        # 如果摄像头开启且未显示，则显示
        if self.cam_enabled and self.camera_widget is None:
            # 只有在录制中或选区中才自动打开
            if self.recorder is not None or self.selection_widget is not None:
                self.open_camera(self.selected_cam_index)
        # 如果摄像头关闭且已显示，则关闭
        elif not self.cam_enabled and self.camera_widget is not None:
            self.close_camera()
        # 如果摄像头开启且索引/形状变了，刷新
        elif self.cam_enabled and self.camera_widget:
            try:
                self.camera_widget.set_shape(self.selected_cam_shape)
                self.camera_widget.set_border_visible(self.config_manager.get("cam_border_enabled", False))
                if self.camera_widget.camera_index != self.selected_cam_index:
                    self.open_camera(self.selected_cam_index) # 这会切换摄像头
            except Exception as e:
                print(f"Error updating camera settings: {e}")
                
        # 强制处理一次事件，防止 UI 状态滞后
        QApplication.processEvents()

    def capture_fullscreen(self):
        self.capture_area(self.app.primaryScreen().geometry())

    def capture_area(self, rect, mode=None):
        print(f"Capturing area: {rect}, mode: {mode}")
        # 清理选区工具
        self.selection_widget = None
        
        # 截图逻辑
        try:
            with mss.mss() as sct:
                # DPI Scaling Correction
                monitor = sct.monitors[1]
                qt_screen = self.app.primaryScreen().geometry()
                
                scale_x = monitor['width'] / qt_screen.width()
                scale_y = monitor['height'] / qt_screen.height()
                
                region = {
                    'top': int(rect.top() * scale_y),
                    'left': int(rect.left() * scale_x),
                    'width': int(rect.width() * scale_x),
                    'height': int(rect.height() * scale_y)
                }
                
                # Check for fullscreen
                if rect == qt_screen:
                    region = {
                        'top': monitor['top'],
                        'left': monitor['left'],
                        'width': monitor['width'],
                        'height': monitor['height']
                    }
                    
                img = sct.grab(region)
                
                # Convert to QPixmap for Editor
                # mss returns BGRA
                from PySide6.QtGui import QImage, QPixmap
                img_bytes = img.bgra
                q_img = QImage(img_bytes, img.width, img.height, QImage.Format_ARGB32)
                
                # Set DPI
                q_img.setDevicePixelRatio(scale_x)
                
                pixmap = QPixmap.fromImage(q_img)
                
                # Open Editor
                # Pass the logical rect for positioning
                self.editor = ScreenshotEditor(pixmap, rect)
                self.editor.show()
                
        except Exception as e:
            print(f"Capture failed: {e}")
            import traceback
            traceback.print_exc()

    def selection_cancelled(self):
        # 注意：这里我们手动置空，但如果 destroyed 信号随后触发，
        # on_selection_widget_destroyed 也会被调用。
        # 由于我们设置为 None 了，on_selection_widget_destroyed 中的 check (is obj) 可能会失败（因为 self.selection_widget 已经是 None），
        # 或者如果 self.selection_widget 被重新赋值了，check 也会保护它。
        self.selection_widget = None
        # 当用户点击X关闭面板时，同时关闭摄像头（如果已打开）
        self.close_camera()
        print("Selection cancelled")

    def on_selection_widget_destroyed(self, obj=None):
        """
        Slot to handle safe cleanup when selection widget is destroyed.
        This handles cases where the widget is closed/destroyed not via the cancel path
        (e.g. system close, parent destruction, or unexpected errors).
        """
        if self.selection_widget is obj:
            self.selection_widget = None
            print("Selection widget destroyed safely (Dangling pointer cleanup).")

    def start_recording(self, rect, mode=None):
        print(f"Recording area selected: {rect}, mode: {mode}")
        
        # 保存选区 rect 和 mode 以便后续使用
        self.pending_recording_rect = rect
        self.pending_recording_mode = mode
        
        # 清理选区工具 (此时选区工具已经隐藏，但可以完全清理)
        self.selection_widget = None
        
        # 启动倒计时
        self.countdown = CountdownWidget()
        self.countdown.finished.connect(self._real_start_recording)
        self.countdown.show()
        
    def _real_start_recording(self):
        rect = self.pending_recording_rect
        mode = getattr(self, 'pending_recording_mode', None)
        print("Countdown finished, starting recording...")
        
        # 处理特殊模式
        if mode == 'camera_only':
            if not self.camera_widget or not self.camera_widget.isVisible():
                self.open_camera(self.selected_cam_index)
                # 等待窗口显示
                QApplication.processEvents()
                import time
                time.sleep(0.5)
            
            if self.camera_widget:
                # 确保不在全屏模式，而是使用自定义比例
                if getattr(self.camera_widget, 'is_fullscreen_mode', False):
                    self.camera_widget.set_fullscreen(False)
                
                # 如果是圆形，切换到默认矩形 (9:16)
                if self.camera_widget.shape_mode == 'circle':
                    self.camera_widget.set_shape('9:16')
                    # 调整为大尺寸 (例如 400px 宽度)
                    self.camera_widget.resize_to_width(400)
                    # 移动到屏幕中央
                    self.camera_widget.move_to_center()
                
                QApplication.processEvents()
                import time
                time.sleep(0.2) # 等待渲染更新
                
                rect = self.camera_widget.geometry()
                print(f"Camera Only mode: using camera geometry {rect}")
            else:
                QMessageBox.warning(None, "错误", "无法打开摄像头，将使用全屏录制")
                rect = self.app.primaryScreen().geometry()
        
        # 如果开启了鼠标特效，启动特效窗口
        if self.mouse_enabled:
            self.mouse_effect = MouseEffectWidget(style=self.mouse_style)
            self.mouse_effect.show()
        
        # Calculate recording region
        region = {}
        
        if mode == 'camera_only' and self.camera_widget:
            # For camera only, use the optimal recording resolution from the camera
            rec_w, rec_h = self.camera_widget.get_recording_size()
            geo = self.camera_widget.geometry()
            
            # Note: top/left are used for cursor offset. 
            # Since we record at native resolution which might differ from window size,
            # cursor position mapping would be inaccurate without scaling.
            # But high resolution is the priority here.
            region = {
                'top': geo.top(),
                'left': geo.left(),
                'width': rec_w,
                'height': rec_h
            }
            print(f"[DEBUG] Camera Only Mode: Recording at {rec_w}x{rec_h} (Window: {geo.width()}x{geo.height()})")
            
        else:
            # Screen recording mode: Calculate MSS region with DPI scaling
            try:
                with mss.mss() as sct:
                    monitor = sct.monitors[1] # 主屏幕
                    qt_screen = self.app.primaryScreen().geometry()
                    
                    scale_x = monitor['width'] / qt_screen.width()
                    scale_y = monitor['height'] / qt_screen.height()
                    
                    region = {
                        'top': int(rect.top() * scale_y),
                        'left': int(rect.left() * scale_x),
                        'width': int(rect.width() * scale_x),
                        'height': int(rect.height() * scale_y)
                    }
                    
                    # Check for fullscreen
                    if rect == qt_screen:
                        print("[DEBUG] Detected Fullscreen recording, using monitor geometry directly.")
                        region = {
                            'top': monitor['top'],
                            'left': monitor['left'],
                            'width': monitor['width'],
                            'height': monitor['height']
                        }
                        
                    print(f"[DEBUG] DPI Scaling - Qt: {qt_screen.width()}x{qt_screen.height()}, MSS: {monitor['width']}x{monitor['height']}")
                    print(f"[DEBUG] Scale Factors - X: {scale_x:.2f}, Y: {scale_y:.2f}")
                    print(f"[DEBUG] Final Region: {region}")
                    
            except Exception as e:
                print(f"[ERROR] Failed to calculate DPI scaling: {e}")
                # Fallback
                region = {
                    'top': rect.top(), 
                    'left': rect.left(), 
                    'width': rect.width(), 
                    'height': rect.height()
                }
        
        # 启动录制线程
        # 获取配置中的录制路径
        output_dir = self.config_manager.get("save_path_record")
        video_quality = self.config_manager.get("video_quality", "1080p")
        
        camera_only = (mode == 'camera_only')
        audio_only = (mode == 'audio_only')
        
        # Get audio device name if index is selected
        audio_device_name = None
        if self.selected_mic_index is not None:
            try:
                devices = AudioRecorder.get_input_devices()
                for dev in devices:
                    if dev['index'] == self.selected_mic_index:
                        audio_device_name = dev['name']
                        break
            except Exception as e:
                print(f"Error getting audio device name: {e}")

        self.recorder = ScreenRecorder(
            region=region, 
            output_filename=None, 
            record_audio=self.record_audio,
            audio_device_index=self.selected_mic_index,
            audio_device_name=audio_device_name,
            record_system_audio=self.record_sys_audio,
            output_dir=output_dir,
            video_quality=video_quality,
            use_gpu=self.config_manager.get("gpu_acceleration", False),
            camera_only=camera_only,
            camera_index=self.selected_cam_index,
            audio_only=audio_only,
            frame_provider=self.camera_widget if camera_only else None
        )
            
        self.recorder.start()
        
        # 显示悬浮控制条
        self.control_bar = ControlBar(recording_region=region)
        self.control_bar.stop_clicked.connect(self.stop_recording)
        self.control_bar.pause_clicked.connect(self.toggle_pause_recording)
        self.control_bar.show()
        
        # 显示录制红框
        self.recording_frame = RecordingFrame(rect)
        self.recording_frame.show()
        
        # 清理选区工具
        # self.selection_widget = None # 已在 start_recording 中清理
        
        # 更改托盘菜单状态
        self.action_record.setEnabled(False)

    def toggle_pause_recording(self):
        if self.recorder:
            if self.recorder.is_paused:
                self.recorder.resume()
                if self.control_bar:
                    self.control_bar.resume_timer()
                if self.recording_frame:
                    self.recording_frame.set_paused(False)
            else:
                self.recorder.pause()
                if self.control_bar:
                    self.control_bar.pause_timer()
                if self.recording_frame:
                    self.recording_frame.set_paused(True)

    def stop_recording(self):
        if not self.recorder:
            logger.info("stop_recording called with no active recorder")
            return

        if self._stopping_recorder is not None:
            logger.info("stop_recording ignored because shutdown is already in progress")
            return

        rec = self.recorder
        self.recorder = None
        self._stopping_recorder = rec
        logger.info(
            "stop_recording requested recorder_alive=%s paused=%s audio_only=%s final_output=%s",
            rec.is_alive(),
            getattr(rec, "is_paused", None),
            getattr(rec, "audio_only", None),
            getattr(rec, "final_output", None),
        )

        if self.control_bar:
            self.control_bar.setEnabled(False)
            self.control_bar.close()
            self.control_bar = None

        if self.recording_frame:
            self.recording_frame.close()
            self.recording_frame = None

        if self.mouse_effect:
            self.mouse_effect.close()
            self.mouse_effect = None

        # 停止录制时关闭摄像头
        self.close_camera()

        # 如果摄像头处于全屏模式，退出全屏
        if self.camera_widget and getattr(self.camera_widget, 'is_fullscreen_mode', False):
            self.camera_widget.set_fullscreen(False)

        def _stop_worker():
            try:
                logger.info("Background recorder stop worker started")
                rec.stop()
                logger.info("Background recorder stop worker finished alive=%s", rec.is_alive())
            except Exception:
                logger.exception("Background recorder stop worker failed")

        threading.Thread(target=_stop_worker, daemon=True).start()
        self._start_stop_poll()

    def _start_stop_poll(self):
        if self._stop_poll_timer is None:
            self._stop_poll_timer = QTimer()
            self._stop_poll_timer.setInterval(200)
            self._stop_poll_timer.timeout.connect(self._poll_stop_recording_complete)
        self._stop_poll_timer.start()
        logger.info("Started polling for recorder shutdown")

    def _poll_stop_recording_complete(self):
        rec = self._stopping_recorder
        if rec is None:
            if self._stop_poll_timer:
                self._stop_poll_timer.stop()
            return
        if rec.is_alive():
            return
        if self._stop_poll_timer:
            self._stop_poll_timer.stop()
        logger.info("Recorder shutdown completed. Finalizing stop workflow.")
        self._stopping_recorder = None
        self._finalize_recording_stop(rec)

    def _finalize_recording_stop(self, rec):
        self.action_record.setEnabled(True)
        print("Recording stopped.")

        # Launch Video Editor
        if rec and not rec.audio_only:
            try:
                from src.video_editor import VideoEditor
                video_path = rec.final_output
                mic_path = rec.temp_audio_mic
                sys_path = rec.temp_audio_sys
                base_path = os.path.splitext(video_path)[0]
                meta_path = f"{base_path}.json"
                output_path = rec.final_output

                if not hasattr(self, 'editors'):
                    self.editors = []

                editor = VideoEditor(video_path, mic_path, sys_path, meta_path, output_path)
                self.editors.append(editor)
                editor.show()

                # Cleanup closed editors
                self.editors = [e for e in self.editors if e.isVisible()]
                logger.info("Video editor opened for %s", video_path)
            except Exception:
                logger.exception("Failed to launch editor")
        
        # 录制结束后，重新显示选区面板，方便下一次操作
        # 使用 QTimer.singleShot 稍微延迟一下，避免与停止录制的 UI 更新冲突
        # from PySide6.QtCore import QTimer
        # QTimer.singleShot(500, lambda: self.start_selection(mode='record'))

    def confirm_quit(self):
        if self.recorder is not None:
            QMessageBox.warning(None, "提示", "正在录制中，请先停止录制！")
            return
            
        # Explicitly close all widgets to ensure threads are stopped
        try:
            if self.camera_widget:
                self.camera_widget.close()
                self.camera_widget = None
                
            if self.selection_widget:
                self.selection_widget.close()
                self.selection_widget = None
                
            if self.control_bar:
                self.control_bar.close()
                self.control_bar = None
                
            if self.mouse_effect:
                self.mouse_effect.close()
                self.mouse_effect = None
                
            if hasattr(self, 'editors'):
                for editor in self.editors:
                    try: editor.close()
                    except: pass
                self.editors = []
                
        except Exception as e:
            print(f"Error during cleanup: {e}")
            
        self.app.quit()

    def run(self):
        if hasattr(self, 'app'):
            sys.exit(self.app.exec())
        else:
            print("Error: QApplication not initialized.")
            sys.exit(1)

if __name__ == "__main__":
    # 确保src目录在路径中
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    # --- 单实例检查 (Windows Mutex) ---
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        
        mutex_name = "Global\\LuScreen_Single_Instance_Mutex"
        mutex = kernel32.CreateMutexW(None, False, mutex_name)
        last_error = kernel32.GetLastError()
        
        if last_error == 183: # ERROR_ALREADY_EXISTS
            # 弹窗提示 (使用原生 Windows API，不需要 Qt)
            ctypes.windll.user32.MessageBoxW(0, "LuScreen 已经在运行中！\n请检查系统托盘图标。", "提示", 0x30)
            sys.exit(0)
    # ------------------------------------
    
    app = LuScreenApp()
    app.run()
