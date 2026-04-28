@echo off
setlocal EnableDelayedExpansion

set PYTHON_EXE=%~1
if "%PYTHON_EXE%"=="" set PYTHON_EXE=python

set PY_VER=
for /f "tokens=2 delims= " %%v in ('%PYTHON_EXE% --version 2^>^&1') do set PY_VER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PY_VER%") do set PY_TAG=%%a%%b
if "%PY_TAG%"=="" (
    echo Failed to detect Python version from "%PYTHON_EXE%"
    exit /b 1
)

echo Building rust_core from rust_src for Python cp%PY_TAG%...
cd /d "%~dp0rust_src"
maturin build --release -i "%PYTHON_EXE%"
if errorlevel 1 (
    echo Build failed!
    exit /b 1
)
cd /d "%~dp0"

echo Installing rust_core wheel...
set LATEST_WHEEL=
for /f "delims=" %%f in ('dir /b /s /od rust_src\target\wheels\rust_core-*-cp%PY_TAG%-*.whl') do set LATEST_WHEEL=%%f
if "%LATEST_WHEEL%"=="" (
    echo No wheel found for cp%PY_TAG%
    exit /b 1
)

set PIP_NO_CACHE_DIR=1
"%PYTHON_EXE%" -m pip install "%LATEST_WHEEL%" --force-reinstall --no-cache-dir
if errorlevel 1 (
    echo Wheel install failed!
    exit /b 1
)

echo Done! Installed: %LATEST_WHEEL%
