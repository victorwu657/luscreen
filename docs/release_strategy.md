# 发布策略（CPU 默认 + GPU 按需）

## 目标

- 默认分发 CPU 版：体积更小、下载更快、覆盖所有用户。
- GPU 版按需提供：仅给需要 GPU 加速字幕的用户下载。
- WhisperX 模型不随安装包分发：用户首次使用或按需下载，避免安装包体积膨胀。

## 打包入口

- CPU 版（默认）
  - `make_release.bat cpu`
- GPU 版（单独构建）
  - `make_release.bat gpu`

说明：`make_release.bat` 会创建独立的 Python 3.12 venv，并在该环境中安装依赖后调用 `build_nuitka.bat` 进行编译打包。

## 用户侧下载指引（建议）

- 官网下载页默认提供 CPU 版。
- 当用户在“生成字幕”中选择 GPU、但检测不到 CUDA 时，提示用户下载 GPU 版安装包（并提供链接）。
- WhisperX 模型首次使用可能会自动下载；也支持用户将模型放入 `models/whisperx/whisper` 以离线使用。

## 备注

- Windows 的 CUDA torch 体积非常大（GB 级），强烈建议不要作为默认下载。
- GPU 版与 CPU 版应使用一致的业务逻辑；仅运行时依赖（torch CUDA/CPU）不同。
