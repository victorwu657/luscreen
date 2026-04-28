@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv_cuda_py312\\Scripts\\python.exe" (
  py -3.12 -m venv .venv_cuda_py312
)

".venv_cuda_py312\\Scripts\\python.exe" -m pip install --upgrade pip
".venv_cuda_py312\\Scripts\\python.exe" -m pip install -r requirements.txt

".venv_cuda_py312\\Scripts\\python.exe" -m pip uninstall -y torch torchvision torchaudio
".venv_cuda_py312\\Scripts\\python.exe" -m pip install torch==2.8.0+cu128 torchvision==0.23.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128

echo.
echo [INFO] 验证 CUDA：
".venv_cuda_py312\\Scripts\\python.exe" -c "import torch; print('torch',torch.__version__); print('build_cuda',torch.version.cuda); print('is_available',torch.cuda.is_available()); print('count',torch.cuda.device_count())"

echo.
echo [OK] CUDA 环境已就绪：.venv_cuda_py312
echo 运行：.venv_cuda_py312\\Scripts\\python.exe main.py
echo.
pause
