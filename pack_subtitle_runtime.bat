@echo off
setlocal enabledelayedexpansion

echo ========================================
echo 打包字幕 Runtime
echo ========================================

set "VENV_DIR=.venv_release_gpu_py312"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    set "VENV_DIR=.venv_release_cpu_py312"
)
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [ERROR] 找不到虚拟环境
    pause
    exit /b 1
)

set "PYTHON=%VENV_DIR%\Scripts\python.exe"
echo [INFO] 使用 Python: %PYTHON%

echo.
echo [1/4] 查找依赖包位置...
set "TORCH_DIR="
for /f "delims=" %%i in ('%PYTHON% -c "import torch, os; print(os.path.dirname(torch.__file__))"') do set TORCH_DIR=%%i
if not defined TORCH_DIR (
    echo [ERROR] 无法定位 torch
    pause
    exit /b 1
)
if not exist "%TORCH_DIR%" (
    echo [ERROR] torch 路径不存在: %TORCH_DIR%
    pause
    exit /b 1
)
set "WHISPERX_DIR="
for /f "delims=" %%i in ('%PYTHON% -c "import whisperx, os; print(os.path.dirname(whisperx.__file__))"') do set WHISPERX_DIR=%%i
if not defined WHISPERX_DIR (
    echo [ERROR] 无法定位 whisperx
    pause
    exit /b 1
)
if not exist "%WHISPERX_DIR%" (
    echo [ERROR] whisperx 路径不存在: %WHISPERX_DIR%
    pause
    exit /b 1
)
set "TORCHGEN_DIR="
for /f "delims=" %%i in ('%PYTHON% -c "import torchgen, os; print(os.path.dirname(torchgen.__file__))"') do set TORCHGEN_DIR=%%i
if not defined TORCHGEN_DIR (
    echo [ERROR] 无法定位 torchgen
    pause
    exit /b 1
)
if not exist "%TORCHGEN_DIR%" (
    echo [ERROR] torchgen 路径不存在: %TORCHGEN_DIR%
    pause
    exit /b 1
)
set "TORCHAUDIO_DIR="
for /f "delims=" %%i in ('%PYTHON% -c "import torchaudio, os; print(os.path.dirname(torchaudio.__file__))"') do set TORCHAUDIO_DIR=%%i
if not defined TORCHAUDIO_DIR (
    echo [ERROR] 无法定位 torchaudio
    pause
    exit /b 1
)
if not exist "%TORCHAUDIO_DIR%" (
    echo [ERROR] torchaudio 路径不存在: %TORCHAUDIO_DIR%
    pause
    exit /b 1
)
set "TRANSFORMERS_DIR="
for /f "delims=" %%i in ('%PYTHON% -c "import transformers, os; print(os.path.dirname(transformers.__file__))"') do set TRANSFORMERS_DIR=%%i
if not defined TRANSFORMERS_DIR (
    echo [ERROR] 无法定位 transformers
    pause
    exit /b 1
)
if not exist "%TRANSFORMERS_DIR%" (
    echo [ERROR] transformers 路径不存在: %TRANSFORMERS_DIR%
    pause
    exit /b 1
)

echo torch: %TORCH_DIR%
echo whisperx: %WHISPERX_DIR%
echo torchgen: %TORCHGEN_DIR%
echo torchaudio: %TORCHAUDIO_DIR%
echo transformers: %TRANSFORMERS_DIR%

echo.
echo [2/4] 创建临时目录...
set "TEMP_DIR=temp_subtitle_runtime"
if exist "%TEMP_DIR%" rmdir /s /q "%TEMP_DIR%"
mkdir "%TEMP_DIR%"

echo.
echo [3/4] 复制文件...
echo 复制 torch...
xcopy "%TORCH_DIR%" "%TEMP_DIR%\torch\" /E /I /Q /Y
if errorlevel 1 (
    echo [ERROR] 复制 torch 失败
    pause
    exit /b 1
)
echo 复制 whisperx...
xcopy "%WHISPERX_DIR%" "%TEMP_DIR%\whisperx\" /E /I /Q /Y
if errorlevel 1 (
    echo [ERROR] 复制 whisperx 失败
    pause
    exit /b 1
)
echo 复制 torchgen...
xcopy "%TORCHGEN_DIR%" "%TEMP_DIR%\torchgen\" /E /I /Q /Y
if errorlevel 1 (
    echo [ERROR] 复制 torchgen 失败
    pause
    exit /b 1
)
echo 复制 torchaudio...
xcopy "%TORCHAUDIO_DIR%" "%TEMP_DIR%\torchaudio\" /E /I /Q /Y
if errorlevel 1 (
    echo [ERROR] 复制 torchaudio 失败
    pause
    exit /b 1
)
echo 复制 transformers...
xcopy "%TRANSFORMERS_DIR%" "%TEMP_DIR%\transformers\" /E /I /Q /Y
if errorlevel 1 (
    echo [ERROR] 复制 transformers 失败
    pause
    exit /b 1
)
if not exist "%TEMP_DIR%\torch\__init__.py" (
    echo [ERROR] 打包内容缺少 torch
    pause
    exit /b 1
)
if not exist "%TEMP_DIR%\torch\lib" (
    echo [ERROR] 打包内容缺少 torch\lib
    pause
    exit /b 1
)
if not exist "%TEMP_DIR%\whisperx\__init__.py" (
    echo [ERROR] 打包内容缺少 whisperx
    pause
    exit /b 1
)
if not exist "%TEMP_DIR%\torchgen\__init__.py" (
    echo [ERROR] 打包内容缺少 torchgen
    pause
    exit /b 1
)

echo.
echo [4/4] 打包 ZIP...
if exist "subtitle_runtime.zip" del /f /q "subtitle_runtime.zip"
powershell -Command "Compress-Archive -Path '%TEMP_DIR%\*' -DestinationPath 'subtitle_runtime.zip' -CompressionLevel Optimal"
if errorlevel 1 (
    echo [ERROR] 生成 ZIP 失败
    pause
    exit /b 1
)
if not exist "subtitle_runtime.zip" (
    echo [ERROR] 未生成 subtitle_runtime.zip
    pause
    exit /b 1
)

echo.
echo [INFO] 清理临时文件...
rmdir /s /q "%TEMP_DIR%"

echo.
echo [INFO] 计算 SHA256...
for /f "delims=" %%i in ('powershell -Command "(Get-FileHash -Algorithm SHA256 'subtitle_runtime.zip').Hash.ToLower()"') do set SHA256=%%i
for /f "delims=" %%i in ('powershell -Command "(Get-Item 'subtitle_runtime.zip').Length"') do set SIZE=%%i

echo.
echo ========================================
echo 打包完成！
echo ========================================
echo 文件: subtitle_runtime.zip
echo 大小: %SIZE% bytes
echo SHA256: %SHA256%
echo.
echo 请将以下内容保存为 subtitle_runtime.json:
echo {
echo   "version": "1.0.0",
echo   "url": "你的下载地址/subtitle_runtime.zip",
echo   "sha256": "%SHA256%",
echo   "size": %SIZE%,
echo   "description": "WhisperX Runtime"
echo }
echo ========================================
pause
