# 示例：在字幕功能中集成模型下载
# 将此代码集成到你的字幕生成模块中

from src.model_downloader import ModelManager

def generate_subtitle(video_path, parent_widget=None):
    """
    生成字幕的入口函数

    Args:
        video_path: 视频文件路径
        parent_widget: 父窗口，用于显示对话框
    """

    # 检查并下载模型
    if not ModelManager.prompt_download("whisperx-base", parent_widget):
        print("用户取消下载或下载失败")
        return None

    # 模型已就绪，开始生成字幕
    print("开始生成字幕...")
    # 这里调用你原有的字幕生成逻辑
    # result = your_whisperx_function(video_path)

    return True
