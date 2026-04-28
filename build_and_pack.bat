@echo off
setlocal
cd /d "%~dp0"
echo ========================================
echo LuScreen 轻量版构建和打包
echo ========================================

echo [1/2] 运行 Nuitka 构建...
call "%~dp0build_nuitka.bat"
if errorlevel 1 (
    echo [ERROR] Nuitka 构建失败
    pause
    exit /b 1
)

echo.
echo [2/2] 运行 Inno Setup 打包...
if not exist "dist_nuitka\LuScreen.dist\LuScreen.exe" (
    echo [ERROR] 找不到 LuScreen.exe
    pause
    exit /b 1
)

"D:\ProgramFile\Inno Setup 6\ISCC.exe" installer.iss
if errorlevel 1 (
    echo [ERROR] Inno Setup 打包失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo 打包完成！
echo 安装包位置: dist_installer\LuScreen-Setup-v0.046.9.exe
echo ========================================
pause
