import sys
import os
# 初始化全局日志和异常捕获
from src.logger import setup_global_logger, handle_exception
# 立即安装钩子
sys.excepthook = handle_exception
# 初始化日志记录器
logger = setup_global_logger()

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QAction, QCursor
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
import ctypes

# 启用高分屏支持 (High DPI Support)
# 必须在创建 QApplication 之前设置
if os.name == 'nt':
    try:
        # Windows 8.1+
        ctypes.windll.shcore.SetProcessDpiAwareness(1) # 1 = PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        # Windows Vista/7/8
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except:
            pass

class LuScreenApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False) # 关闭所有窗口不退出程序
        
        # 加载配置
        self.config_manager = ConfigManager()
        
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
        
        self.hotkey_manager.hotkey_triggered.connect(self.on_hotkey_triggered)

        # 初始化组件
        self.camera_widget = None
        self.selection_widget = None
        self.recorder = None
        self.control_bar = None
        self.recording_frame = None
        self.mouse_effect = None
        
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
        self.main_window.show_centered()

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
        
        self.tray_menu.addSeparator()
        
from src.updater import UpdateWorker, install_update
from src.version import APP_VERSION

class LuScreenApp:
    def __init__(self):
        # ... (existing init code)
        self.update_worker = None

    def check_for_updates(self):
        if self.update_worker and self.update_worker.isRunning():
            return
            
        self.update_worker = UpdateWorker(mode='check')
        self.update_worker.check_finished.connect(self.on_check_finished)
        self.update_worker.error.connect(lambda e: QMessageBox.warning(None, "更新检查失败", e))
        self.update_worker.start()
        
    def on_check_finished(self, has_update, version, url):
        if has_update:
            reply = QMessageBox.question(
                None, "发现新版本", 
                f"发现新版本 {version}！\n当前版本: {APP_VERSION}\n\n是否立即更新？",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.start_download(url)
        else:
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

    def on_download_finished(self, file_path):
        self.progress_dialog.close()
        reply = QMessageBox.question(
            None, "下载完成", 
            "更新包已下载完成。\n\n程序将重启以完成更新。\n是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            install_update(file_path)

    def setup_tray(self):
        # ... (existing code)
        
        # 增加设置选项
        self.tray_menu.addSeparator()
        self.action_settings = QAction("⚙️  设置 (Settings)", self.app)
        self.action_settings.triggered.connect(self.open_settings)
        self.tray_menu.addAction(self.action_settings)
        
        # 增加检查更新选项
        self.action_update = QAction("🚀  检查更新 (Check Update)", self.app)
        self.action_update.triggered.connect(self.check_for_updates)
        self.tray_menu.addAction(self.action_update)
        
        self.tray_menu.addSeparator()
        # ... (rest of setup_tray)
        
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
            self.main_window.show_centered() # 总是居中显示，或者 show_at_cursor 也可以
            # 考虑到用户习惯，点击托盘通常希望看到界面

    def on_main_window_action(self, action):
        if action == 'capture_area':
            self.start_selection(mode='capture')
        elif action == 'capture_full':
            self.capture_fullscreen()
        elif action == 'record':
            self.start_selection(mode='record')
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

    def start_selection(self, mode='record'):
        # 1. 创建控制面板
        control_panel = ControlPanel()
        
        # 应用保存的配置到面板
        control_panel.btn_mic.setChecked(self.record_audio)
        control_panel.btn_sys.setChecked(self.record_sys_audio)
        control_panel.btn_cam.setChecked(self.cam_enabled)
        control_panel.btn_mouse.setChecked(self.mouse_enabled)
        
        # 还需要设置面板内部选中的 index，以便右键菜单显示正确
        control_panel.current_mic_index = self.selected_mic_index
        control_panel.current_cam_index = self.selected_cam_index
        control_panel.current_mouse_style = self.mouse_style
        
        # 2. 创建选区工具 (将面板传递给它)
        self.selection_widget = SelectionWidget(control_panel, mode=mode)
        
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
        else:
            self.selection_widget.area_selected.connect(self.capture_area)
            self.selection_widget.scroll_area_selected.connect(self.start_scroll_capture)
            
        self.selection_widget.cancelled.connect(self.selection_cancelled)
        self.selection_widget.settings_changed.connect(self.on_selection_settings_changed)
        
        # 3. 初始状态：只显示面板，不显示全屏遮罩
        # self.selection_widget.show() # 移除此行，由模式切换控制显示
        
        # 显示面板 (它会计算初始位置)
        self.selection_widget.show_panel()
        
        # 关键修复：确保摄像头在选区工具之上，以便用户可以拖拽它
        if self.camera_widget and self.camera_widget.isVisible():
            self.camera_widget.raise_()

    def start_scroll_capture(self, rect):
        print(f"Starting scroll capture for area: {rect}")
        self.selection_widget = None
        
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
        print(f"Scroll capture error: {error}")
        self.tray_icon.showMessage("滚动截图失败", error, QSystemTrayIcon.Warning, 3000)
        self.scroll_worker = None

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
            print(f"Mic changed: {value}")
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
            print(f"DEBUG: Camera index changed to {value}, opening camera...")
            self.open_camera(self.selected_cam_index)
        elif type_ == 'cam_shape':
            self.selected_cam_shape = value
            self.config_manager.set("cam_shape", value)
            if self.camera_widget:
                self.camera_widget.set_shape(value)
            print(f"DEBUG: Camera shape changed to {value}")
        elif type_ == 'mouse_style':
            self.mouse_style = value
            self.config_manager.set("mouse_style", value)
            print(f"DEBUG: Mouse style changed to {value}")
            
        # 实时保存配置
        self.config_manager.save()

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

    def capture_area(self, rect):
        print(f"Capturing area: {rect}")
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
                
                # 保存文件
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_dir = self.config_manager.get("save_path_capture")
                if not os.path.exists(output_dir):
                    os.makedirs(output_dir)
                    
                filename = os.path.join(output_dir, f"Screenshot_{timestamp}.png")
                mss.tools.to_png(img.rgb, img.size, output=filename)
                
                print(f"Screenshot saved to {filename}")
                # 自动打开文件
                os.startfile(filename)
                
        except Exception as e:
            print(f"Capture failed: {e}")
            import traceback
            traceback.print_exc()

    def selection_cancelled(self):
        self.selection_widget = None
        # 当用户点击X关闭面板时，同时关闭摄像头（如果已打开）
        self.close_camera()
        print("Selection cancelled")

    def start_recording(self, rect):
        print(f"Recording area selected: {rect}")
        
        # 保存选区 rect 以便后续使用
        self.pending_recording_rect = rect
        
        # 清理选区工具 (此时选区工具已经隐藏，但可以完全清理)
        self.selection_widget = None
        
        # 启动倒计时
        self.countdown = CountdownWidget()
        self.countdown.finished.connect(self._real_start_recording)
        self.countdown.show()
        
    def _real_start_recording(self):
        rect = self.pending_recording_rect
        print("Countdown finished, starting recording...")
        
        # 如果开启了鼠标特效，启动特效窗口
        if self.mouse_enabled:
            self.mouse_effect = MouseEffectWidget(style=self.mouse_style)
            self.mouse_effect.show()
        
        # 转换 QRect 到 mss 需要的 dict 格式
        # 修正 DPI 缩放问题：
        # Qt 获取的是逻辑像素 (例如 1536x864)，而 mss 需要物理像素 (例如 1920x1080)
        # 我们需要手动计算缩放比例
        
        region = {}
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1] # 主屏幕
                qt_screen = self.app.primaryScreen().geometry()
                
                scale_x = monitor['width'] / qt_screen.width()
                scale_y = monitor['height'] / qt_screen.height()
                
                # 如果比例接近 1.0，说明没有缩放或已正确处理 DPI
                # 但为了保险，我们总是应用缩放
                
                region = {
                    'top': int(rect.top() * scale_y),
                    'left': int(rect.left() * scale_x),
                    'width': int(rect.width() * scale_x),
                    'height': int(rect.height() * scale_y)
                }
                
                # 再次校准：如果这是全屏录制，直接使用 mss 的 monitor 数据
                # 判断是否全屏：比较 rect 和 qt_screen
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
        
        self.recorder = ScreenRecorder(
            region=region, 
            output_filename=None, 
            record_audio=self.record_audio,
            audio_device_index=self.selected_mic_index,
            record_system_audio=self.record_sys_audio,
            output_dir=output_dir,
            video_quality=video_quality,
            use_gpu=self.config_manager.get("gpu_acceleration", False)
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
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
            
        if self.control_bar:
            self.control_bar.close()
            self.control_bar = None
            
        if self.recording_frame:
            self.recording_frame.close()
            self.recording_frame = None
            
        if self.mouse_effect:
            self.mouse_effect.close()
            self.mouse_effect = None
            
        self.action_record.setEnabled(True)
        print("Recording stopped.")
        
        # 录制结束后，重新显示选区面板，方便下一次操作
        # 使用 QTimer.singleShot 稍微延迟一下，避免与停止录制的 UI 更新冲突
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, lambda: self.start_selection(mode='record'))

    def confirm_quit(self):
        if self.recorder is not None:
            QMessageBox.warning(None, "提示", "正在录制中，请先停止录制！")
            return
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec())

if __name__ == "__main__":
    # 确保src目录在路径中
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    app = LuScreenApp()
    app.run()