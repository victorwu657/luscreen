"""
在标准版中，当用户尝试使用字幕功能时显示此对话框
集成到 src/subtitle_system/runtime_installer.py
"""

from PySide6.QtWidgets import QMessageBox, QPushButton
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

def show_subtitle_runtime_required_dialog(parent=None):
    """
    显示字幕运行时缺失提示
    引导用户下载完整版
    """
    msg = QMessageBox(parent)
    msg.setWindowTitle("字幕功能需要额外组件")
    msg.setIcon(QMessageBox.Information)
    msg.setText(
        "字幕生成功能需要额外的 AI 运行时组件\n\n"
        "大小: 约 2.5 GB\n\n"
        "建议下载完整版安装包，包含所有功能"
    )

    # 添加自定义按钮
    download_btn = msg.addButton("下载完整版", QMessageBox.AcceptRole)
    cancel_btn = msg.addButton("取消", QMessageBox.RejectRole)

    msg.exec()

    if msg.clickedButton() == download_btn:
        # 打开下载页面
        QDesktopServices.openUrl(QUrl("https://luscreen.com/downloads"))
        return False

    return False
