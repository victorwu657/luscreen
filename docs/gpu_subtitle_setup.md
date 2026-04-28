# GPU 字幕（WhisperX）环境说明

## 目标

让所有用户（免费/Pro）在具备 NVIDIA GPU + CUDA 环境时，都可以选择 GPU 来生成字幕；若环境不满足则自动回退 CPU，并写入诊断日志。

## 现状与限制

- Windows 上，PyTorch 的 CUDA wheel 需要匹配特定 Python 版本的 ABI；如果你使用的 Python 版本没有对应的 `win_amd64` CUDA wheel，pip 会报 “No matching distribution found for torch”。
- 目前建议用 Python 3.12 来创建 GPU 测试环境。

## 一键创建环境（推荐）

- CPU 环境（Python 3.12）
  - 双击运行：`run_env_cpu_py312.bat`
  - 运行应用：`.venv_cpu_py312\Scripts\python.exe main.py`

- CUDA 环境（Python 3.12 + cu128）
  - 双击运行：`run_env_cuda_py312.bat`
  - 运行应用：`.venv_cuda_py312\Scripts\python.exe main.py`

## 运行时验证

1) 打开“生成字幕”对话框 → 本地模型（WhisperX） → 运行设备选择 GPU。

2) 查看日志（项目根目录 logs）：

- `logs/subtitle_cuda_diag.log`：CUDA 检测与失败原因（例如 torch CPU 构建、CUDA 不可用等）
- `logs/subtitle_asr_device_selected.log`：字幕任务实际使用的设备（requested/final）以及降级原因
- `logs/subtitle_whisperx_model_load.log`：WhisperX 模型加载参数（device/compute_type 等）
