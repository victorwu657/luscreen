# 📦 模型文件上传指南

## ✅ 已完成的步骤

### 1. 模型压缩
- ✅ 文件: `F:\luscreen\downloads\models\whisperx-small.zip`
- ✅ 大小: 852 MB
- ✅ MD5: `ab7f38c421cdc900a7dd61507290c25d`

### 2. 配置文件更新
- ✅ 已更新 `manifest.json`
- ✅ MD5 值已填入

## 📤 需要手动上传的文件

请将以下文件上传到服务器：

### 上传到: `https://luscreen.com/downloads/models/`

1. **whisperx-small.zip** (852 MB)
   - 本地路径: `F:\luscreen\downloads\models\whisperx-small.zip`
   - 上传到: `https://luscreen.com/downloads/models/whisperx-small.zip`

2. **manifest.json**
   - 本地路径: `F:\luscreen\manifest.json`
   - 上传到: `https://luscreen.com/downloads/models/manifest.json`

## 🔍 验证步骤

上传完成后，在浏览器访问：
```
https://luscreen.com/downloads/models/manifest.json
```

应该能看到 JSON 配置内容。

## 📝 manifest.json 内容预览

```json
{
  "version": "1.0",
  "update_time": "2026-03-14",
  "models": {
    "whisperx-small": {
      "display_name": "小型模型 (推荐)",
      "description": "适合大多数场景，速度快",
      "size_mb": 852,
      "url": "https://luscreen.com/downloads/models/whisperx-small.zip",
      "md5": "ab7f38c421cdc900a7dd61507290c25d",
      "min_app_version": "0.046.0"
    }
  }
}
```

## ✨ 完成后

用户首次使用字幕功能时，程序会：
1. 检测本地无模型
2. 从官网获取 manifest.json
3. 显示下载提示（852 MB）
4. 下载并验证 MD5
5. 自动解压到用户目录

全部准备就绪！
