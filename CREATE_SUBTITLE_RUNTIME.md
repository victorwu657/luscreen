# 生成 subtitle_runtime.zip 指南

## 方法 1: 从现有虚拟环境打包（推荐）

### 步骤 1: 确定需要打包的库

```
whisperx/
torch/
torchaudio/
numpy/
其他依赖...
```

### 步骤 2: 从虚拟环境提取

```batch
cd F:\luscreen\.venv_cuda_py312\Lib\site-packages

# 创建临时目录
mkdir F:\luscreen\downloads\subtitle_runtime_temp

# 复制必需的包
xcopy whisperx F:\luscreen\downloads\subtitle_runtime_temp\whisperx /E /I
xcopy torch F:\luscreen\downloads\subtitle_runtime_temp\torch /E /I
xcopy torchaudio F:\luscreen\downloads\subtitle_runtime_temp\torchaudio /E /I
```

### 步骤 3: 压缩

```batch
cd F:\luscreen\downloads
powershell -Command "Compress-Archive -Path 'subtitle_runtime_temp\*' -DestinationPath 'subtitle_runtime.zip' -Force"
```

### 步骤 4: 计算 SHA256

```batch
certutil -hashfile subtitle_runtime.zip SHA256
```

## 方法 2: 使用 pip 下载（离线包）

```batch
pip download whisperx torch torchaudio -d subtitle_runtime_packages
# 然后打包整个目录
```

## 注意事项

- GPU 版本包含 CUDA，体积约 2-3GB
- CPU 版本较小，约 1-2GB
- 确保包含所有依赖

## 需要我帮你执行吗？

回复 "是" 我来自动生成这个包。
