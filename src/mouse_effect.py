from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QPainter, QColor, QCursor
import pynput.mouse

class Ripple:
    def __init__(self, pos, color=QColor(255, 0, 0, 150)):
        self.pos = pos
        self.radius = 0
        self.max_radius = 40
        self.alpha = 200
        self.color = color
        self.finished = False

    def update(self):
        self.radius += 3
        self.alpha -= 10
        if self.alpha <= 0:
            self.alpha = 0
            self.finished = True

    def draw(self, painter):
        painter.save()
        c = QColor(self.color)
        c.setAlpha(self.alpha)
        # 绘制空心圆圈
        pen = painter.pen()
        pen.setColor(c)
        pen.setWidth(4)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush) # 空心
        
        painter.drawEllipse(self.pos, self.radius, self.radius)
        painter.restore()

class MouseEffectWidget(QWidget):
    def __init__(self, style="both"):
        super().__init__()
        # 全屏，无边框，置顶，透明，穿透鼠标
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        
        self.style = style # 'highlight', 'ring', 'both', 'none'
        self.cursor_pos = QPoint(-100, -100)
        self.ripples = []
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(16) # ~60 FPS
        
        # 鼠标监听
        self.listener = pynput.mouse.Listener(on_click=self.on_click, on_move=self.on_move)
        self.listener.start()

    def set_style(self, style):
        self.style = style
        self.update()

    def on_move(self, x, y):
        # 忽略 pynput 的物理坐标 x, y，使用 Qt 的逻辑坐标
        # 这能自动解决 DPI 缩放导致的坐标不一致问题
        local_pos = self.mapFromGlobal(QCursor.pos())
        self.cursor_pos = local_pos
        # 移动时不强制刷新整个屏幕，由定时器处理，或者只重绘必要区域
        # 为了流畅的高亮跟随，我们在 animate 里统一刷新

    def on_click(self, x, y, button, pressed):
        if self.style not in ['ring', 'both']:
            return
            
        if pressed:
            # 同样使用 Qt 逻辑坐标
            local_pos = self.mapFromGlobal(QCursor.pos())
            
            # 左键红色，右键蓝色
            color = QColor(255, 50, 50) if button == pynput.mouse.Button.left else QColor(50, 50, 255)
            # 在非 UI 线程更新列表可能有风险，但在 Python 中通常列表操作是原子的
            self.ripples.append(Ripple(local_pos, color))

    def animate(self):
        # 如果有高亮，需要一直刷新
        # 如果有波纹，也需要刷新
        should_update = False
        
        if self.style in ['highlight', 'both']:
            should_update = True
            
        if self.ripples:
            should_update = True
            for r in self.ripples:
                r.update()
            # 清理已结束的波纹
            self.ripples = [r for r in self.ripples if not r.finished]
            
        if should_update:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Explicitly clear the previous frame to prevent trails
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        
        # 绘制高亮光标
        if self.style in ['highlight', 'both']:
            painter.setPen(Qt.NoPen)
            color = QColor(255, 255, 0, 100) # 半透明黄色
            painter.setBrush(color)
            painter.drawEllipse(self.cursor_pos, 20, 20)
            
        # 绘制波纹
        for r in self.ripples:
            r.draw(painter)

    def closeEvent(self, event):
        if self.listener:
            self.listener.stop()
        super().closeEvent(event)