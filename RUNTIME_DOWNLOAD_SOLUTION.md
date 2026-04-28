# 标准版用户下载运行依赖方案

## 🎯 最终推荐方案

### 方案：引导用户下载完整版（最简单）

**原因**：
- torch 运行时 7GB，在线下载不现实
- 完整版安装包已包含所有依赖
- 用户体验更好

### 实现流程

```
标准版用户点击"生成字幕"
    ↓
检测缺少运行时
    ↓
弹出对话框：
┌─────────────────────────────────────┐
│  字幕功能需要完整版                  │
│                                     │
│  标准版不含 AI 字幕组件              │
│  请下载完整版 (2.5GB)               │
│                                     │
│  [下载完整版] [取消]                │
└─────────────────────────────────────┘
    ↓
打开浏览器到下载页面
```

## 📝 集成代码

在 `src/subtitle_system/runtime_installer.py` 中添加：

```python
def check_runtime_and_prompt(parent=None):
    if not is_subtitle_runtime_installed():
        from src.subtitle_dialog_helper import show_subtitle_runtime_required_dialog
        return show_subtitle_runtime_required_dialog(parent)
    return True
```

## ✅ 优势

- 简单可靠
- 无需维护在线下载逻辑
- 完整版一次安装即用
- 避免大文件下载失败问题

## 📦 发布建议

**官网下载页面**：
- 标准版：主推，快速安装
- 完整版：含字幕功能，推荐需要字幕的用户

**说明文字**：
```
标准版 (636MB) - 推荐
包含录屏、截图、OCR、编辑器等核心功能

完整版 (2.5GB)
包含所有功能 + AI 字幕生成
```
