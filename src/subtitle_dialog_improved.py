"""
改进版：支持在线下载运行时或下载完整版
"""

from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

def show_subtitle_runtime_options(parent=None):
    """
    显示字幕运行时选项
    """
    msg = QMessageBox(parent)
    msg.setWindowTitle("字幕功能需要额外组件")
    msg.setIcon(QMessageBox.Information)
    msg.setText(
        "字幕生成功能需要 AI 运行时组件\n\n"
        "选项 1: 在线下载组件 (约 2.5 GB)\n"
        "选项 2: 下载完整版安装包\n\n"
        "推荐：如果网络较慢，建议下载完整版"
    )

    # 三个按钮
    download_runtime_btn = msg.addButton("在线下载组件", QMessageBox.AcceptRole)
    download_full_btn = msg.addButton("下载完整版", QMessageBox.ActionRole)
    cancel_btn = msg.addButton("取消", QMessageBox.RejectRole)

    msg.exec()

    if msg.clickedButton() == download_runtime_btn:
        # 调用运行时下载器
        from src.subtitle_system.runtime_installer import download_and_install_runtime
        return download_and_install_runtime(parent)

    elif msg.clickedButton() == download_full_btn:
        # 打开完整版下载页面
        QDesktopServices.openUrl(QUrl("https://luscreen.com/downloads"))
        return False

    return False
