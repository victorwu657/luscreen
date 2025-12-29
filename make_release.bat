@echo off
setlocal enabledelayedexpansion

echo ========================================================
echo  LuScreen Release Automation (Build + Pack + Publish)
echo ========================================================

REM 1. 获取版本号 (从 src/version.py 提取)
for /f "tokens=2 delims==" %%I in ('findstr "APP_VERSION" src\version.py') do set "RAW_VERSION=%%I"
REM 去掉引号和空格
set "VERSION=%RAW_VERSION:"=%"
set "VERSION=%VERSION: =%"
echo Target Version: v%VERSION%

echo.
set /p CONFIRM="Ready to build and publish v%VERSION%? (Y/N): "
if /i not "%CONFIRM%"=="Y" exit /b

echo.
echo [1/5] Building Application...
call build_nuitka.bat
if errorlevel 1 goto :error

echo.
echo [2/5] Packaging to ZIP...
python tools\package_zip.py
if errorlevel 1 goto :error

REM 定义文件路径
set "ZIP_FILE=dist_nuitka\LuScreen.zip"
set "EXE_FILE=dist_nuitka\LuScreen.dist\LuScreen.exe"

echo.
echo ========================================================
echo  Build & Packaging Complete! v%VERSION%
echo ========================================================
echo.
echo Please manually upload the following file to GitHub Releases:
echo ZIP File: %ZIP_FILE%
echo.
echo Opening folder for you...
explorer "dist_nuitka"
pause
exit /b 0

:error
echo.
echo [ERROR] Process failed!
pause
exit /b 1