import keyboard
from PySide6.QtCore import QObject, Signal
from pynput import mouse
import time

class HotkeyManager(QObject):
    hotkey_triggered = Signal(str) # 发送 action name

    def __init__(self):
        super().__init__()
        self.hotkeys = {} # {action: hotkey_str}
        
        # 鼠标右键长按检测
        self.mouse_listener = None
        self.right_click_start_time = 0
        self.long_press_threshold = 0.5 # 500ms
        self.start_mouse_listener()

    def start_mouse_listener(self):
        try:
            self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
            self.mouse_listener.start()
        except Exception as e:
            print(f"Failed to start mouse listener: {e}")

    def on_mouse_click(self, x, y, button, pressed):
        try:
            if button == mouse.Button.right:
                if pressed:
                    self.right_click_start_time = time.time()
                else:
                    duration = time.time() - self.right_click_start_time
                    # 如果按压时间超过阈值，且没有过长（比如超过 3 秒可能是忘了松开或者拖拽）
                    if self.long_press_threshold <= duration <= 3.0:
                        print(f"Right click long press detected ({duration:.2f}s)")
                        
                        # 1. 尝试发送 Alt 键来关闭系统菜单
                        # Alt 键会激活窗口菜单栏，从而强制关闭上下文菜单（Context Menu）
                        # 相比 ESC，Alt 键通常不会关闭窗口（如微信），副作用更小
                        keyboard.send('alt')
                        # 稍微延迟一点点防止 Alt 还没处理完
                        time.sleep(0.05)
                        
                        self.emit_signal("menu")
        except Exception as e:
            print(f"Mouse listener error: {e}")

    def register_hotkey(self, action, hotkey_str):
        # 移除旧的 action 绑定
        if action in self.hotkeys:
            old_hotkey = self.hotkeys[action]
            try:
                keyboard.remove_hotkey(old_hotkey)
            except:
                pass
        
        if hotkey_str:
            try:
                # 使用 lambda 捕获 action
                keyboard.add_hotkey(hotkey_str, lambda a=action: self.emit_signal(a))
                self.hotkeys[action] = hotkey_str
                print(f"Registered hotkey '{hotkey_str}' for action '{action}'")
                return True
            except Exception as e:
                print(f"Failed to set hotkey {hotkey_str}: {e}")
                return False
        return True

    def set_hotkey(self, hotkey_str):
        # 兼容旧接口，默认映射到 'global_menu'
        return self.register_hotkey('global_menu', hotkey_str)

    def emit_signal(self, action):
        self.hotkey_triggered.emit(action)

    def unregister_all(self):
        # 安全地逐个移除快捷键，而不是粗暴地 unhook_all
        for action, hotkey_str in list(self.hotkeys.items()):
            try:
                keyboard.remove_hotkey(hotkey_str)
            except Exception as e:
                print(f"Error removing hotkey {hotkey_str}: {e}")
        self.hotkeys.clear()