# ⚠️ subtitle_runtime.zip 生成建议

## 问题
torch 包有 7GB，加上其他依赖，subtitle_runtime.zip 会超过 8-10GB，不适合在线下载。

## 💡 推荐方案

### 方案 1: 不使用 subtitle_runtime.zip（推荐）

**直接在 Nuitka 打包时包含所有依赖**

修改 `build_nuitka.bat`，包含 whisperx 和 torch：
- 安装包会变大（约 2-3GB）
- 但用户无需额外下载
- 一次安装即可使用

### 方案 2: 提供离线安装包

提供两个版本：
- **精简版**: 不含字幕功能（100-300MB）
- **完整版**: 包含字幕功能（2-3GB）

### 方案 3: 使用 CPU 版本 torch

从 `.venv_release_cpu_py312` 打包，体积会小很多（约 500MB-1GB）

### 方案 4: 让用户自行安装 Python 环境

提供安装脚本：
```batch
pip install whisperx torch
```

## 🎯 我的建议

**使用方案 1 或方案 2**，将依赖直接打包到安装程序中，不要让用户在线下载 8GB+ 的文件。

需要我帮你修改打包脚本吗？
