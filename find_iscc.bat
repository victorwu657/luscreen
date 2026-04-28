@echo off
echo 请输入 Inno Setup 的安装路径（例如：D:\Inno Setup 6）
echo.
where ISCC.exe 2>nul
if %errorlevel% equ 0 (
    echo.
    echo 找到 ISCC.exe 路径如上
) else (
    echo 未在系统 PATH 中找到 ISCC.exe
)
pause
