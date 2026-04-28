@echo off
setlocal enabledelayedexpansion

echo ========================================================
echo  LuScreen Release Automation (Build + Pack + Publish)
echo ========================================================
if not exist "logs" mkdir "logs" >nul 2>&1

set "RELEASE_FLAVOR=%~1"
if "%RELEASE_FLAVOR%"=="" set "RELEASE_FLAVOR=cpu"
if /i not "%RELEASE_FLAVOR%"=="cpu" if /i not "%RELEASE_FLAVOR%"=="gpu" (
    echo Usage:
    echo   make_release.bat cpu
    echo   make_release.bat gpu
    echo   make_release.bat cpu --prep-only
    echo   make_release.bat gpu --prep-only
    exit /b 1
)
set "PREP_ONLY=0"
if /i "%~2"=="--prep-only" set "PREP_ONLY=1"

REM Record start time
for /f "delims=" %%i in ('powershell -command "Get-Date -UFormat %%s"') do set START_TIME=%%i

REM 1. 获取版本号 (从 src/version.py 提取)
for /f "tokens=2 delims==" %%I in ('findstr "APP_VERSION" src\version.py') do set "RAW_VERSION=%%I"
REM 去掉引号和空格
set "VERSION=%RAW_VERSION:"=%"
set "VERSION=%VERSION: =%"
echo Target Version: v%VERSION%
echo Release Flavor: %RELEASE_FLAVOR%

echo.
if /i "%LUSCREEN_AUTO_CONFIRM%"=="1" (
    echo [INFO] Auto-confirm enabled. Proceeding without prompt.
) else (
    choice /c YN /n /m "Ready to build and publish v%VERSION%? "
    if errorlevel 2 exit /b 0
)

echo.
echo [0/5] Preparing build venv (Python 3.12)...
set "VENV_DIR=.venv_release_%RELEASE_FLAVOR%_py312"
if not exist "%VENV_DIR%\\Scripts\\python.exe" (
    py -3.12 -m venv "%VENV_DIR%"
    if errorlevel 1 goto :error
)
set "PY_EXE=%cd%\\%VENV_DIR%\\Scripts\\python.exe"
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "LOG_TS=%%i"
set "PIP_UPGRADE_LOG=logs\pip_upgrade_%RELEASE_FLAVOR%_%LOG_TS%.log"
set "PIP_INSTALL_LOG=logs\pip_install_%RELEASE_FLAVOR%_%LOG_TS%.log"
echo [INFO] pip logs:
echo - %PIP_UPGRADE_LOG%
echo - %PIP_INSTALL_LOG%
if /i "%LUSCREEN_SKIP_RELEASE_PIP%"=="1" (
    echo [INFO] Skipping pip install - LUSCREEN_SKIP_RELEASE_PIP=1
) else (
    %PY_EXE% -m pip install --upgrade pip > "%PIP_UPGRADE_LOG%" 2>&1
    if errorlevel 1 goto :error

    echo Installing project dependencies...
    %PY_EXE% -m pip install -r requirements.txt > "%PIP_INSTALL_LOG%" 2>&1
    if errorlevel 1 goto :error

    echo Building rust_core extension...
    if exist dist_wheels rmdir /s /q dist_wheels
    mkdir dist_wheels
    pushd rust_src
    %PY_EXE% -m maturin build --release --out ..\dist_wheels >> "..\%PIP_INSTALL_LOG%" 2>&1
    if errorlevel 1 (
        popd
        echo [ERROR] Failed to build rust_core!
        goto :error
    )
    popd

    echo Installing rust_core wheel...
    for %%f in (dist_wheels\rust_core*.whl) do (
        echo Installing %%f...
        %PY_EXE% -m pip install --force-reinstall --no-deps "%%f" >> "%PIP_INSTALL_LOG%" 2>&1
    )
    if errorlevel 1 (
        echo [ERROR] Failed to install rust_core wheel!
        goto :error
    )
)

if /i "%RELEASE_FLAVOR%"=="gpu" (
    echo.
    echo Installing CUDA torch ^(cu128^)...
    %PY_EXE% -m pip uninstall -y torch torchvision torchaudio
    if errorlevel 1 goto :error
    %PY_EXE% -m pip install torch==2.8.0+cu128 torchvision==0.23.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128
    if errorlevel 1 goto :error
)

echo.
echo [1/5] Building Application...
set "LUSCREEN_PYTHON=%PY_EXE%"
set "LUSCREEN_RELEASE_FLAVOR=%RELEASE_FLAVOR%"
set "OLD_LUSCREEN_NO_PAUSE=%LUSCREEN_NO_PAUSE%"
set "LUSCREEN_NO_PAUSE=1"
if /i "%PREP_ONLY%"=="1" (
    call build_nuitka.bat --prep-only
) else (
    call build_nuitka.bat
)
set "LUSCREEN_NO_PAUSE=%OLD_LUSCREEN_NO_PAUSE%"
if errorlevel 1 goto :error
if /i "%PREP_ONLY%"=="1" (
    echo.
    echo Prep-only mode complete. Skipping ZIP packaging.
    pause
    exit /b 0
)

echo.
echo [1.5/5] Copying OpenAI dependencies...
%PY_EXE% tools\copy_deps.py
if errorlevel 1 goto :error


echo.
echo [2/5] Packaging to ZIP...
set "PACKAGE_LOG=logs\package_zip_%RELEASE_FLAVOR%_%LOG_TS%.log"
echo [INFO] Packaging log: %PACKAGE_LOG%
%PY_EXE% tools\package_zip.py > "%PACKAGE_LOG%" 2>&1
if errorlevel 1 goto :error

REM 定义文件路径
set "ZIP_FILE=dist_nuitka\luscreen.zip"
set "EXE_FILE=dist_nuitka\LuScreen.dist\LuScreen.exe"

if exist "%ZIP_FILE%" (
    echo [INFO] ZIP package ready: %ZIP_FILE%
) else (
    echo [ERROR] ZIP file not found: %ZIP_FILE%
    goto :error
)

echo.
echo ========================================================
echo  Build & Packaging Complete! v%VERSION%
echo ========================================================

REM Calculate duration
for /f "delims=" %%i in ('powershell -command "Get-Date -UFormat %%s"') do set END_TIME=%%i
for /f "delims=" %%i in ('powershell -command "$diff = %END_TIME% - %START_TIME%; $min = [math]::floor($diff / 60); $sec = [math]::floor($diff %% 60); Write-Host \"${min}m ${sec}s\""') do set DURATION=%%i

echo Total Build Time: %DURATION%
echo.
echo Please manually upload the following file to luscreen.com:
echo ZIP File: %ZIP_FILE%
echo.
echo Notes:
echo - 默认分发 CPU 版；GPU 版单独提供下载地址。
echo - WhisperX 本地模型不随安装包分发，按需下载。
echo.
echo Opening folder for you...
explorer "dist_nuitka"
REM pause
exit /b 0

:error
echo.
echo [ERROR] Process failed!
echo Please check logs\build_nuitka_*.log (if build step ran).
if exist "%PIP_INSTALL_LOG%" (
    echo Also check:
    echo - %PIP_UPGRADE_LOG%
    echo - %PIP_INSTALL_LOG%
    echo - %PACKAGE_LOG%
)
explorer "logs"
REM pause
exit /b 1
