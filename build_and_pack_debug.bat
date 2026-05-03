@echo off
setlocal
cd /d "%~dp0"
set "LUSCREEN_WINDOWS_CONSOLE_MODE=force"
set "LUSCREEN_PACKAGE_FLAVOR=debug"
call :load_app_version
if errorlevel 1 (
    pause
    exit /b 1
)
set "OLD_LUSCREEN_APP_VERSION=%LUSCREEN_APP_VERSION%"
set "LUSCREEN_APP_VERSION=%APP_VERSION%"
echo ========================================
echo LuScreen Debug Build And Pack
echo ========================================
echo [INFO] App version: %APP_VERSION%

echo [1/2] Running Nuitka build...
set "OLD_LUSCREEN_NO_PAUSE=%LUSCREEN_NO_PAUSE%"
set "LUSCREEN_NO_PAUSE=1"
call "%~dp0build_nuitka.bat"
set "LUSCREEN_NO_PAUSE=%OLD_LUSCREEN_NO_PAUSE%"
set "LUSCREEN_APP_VERSION=%OLD_LUSCREEN_APP_VERSION%"
if errorlevel 1 (
    echo [ERROR] Nuitka build failed
    pause
    exit /b 1
)

echo(
echo [2/2] Running Inno Setup pack...
if not exist "dist_nuitka\LuScreen.dist\LuScreen.exe" (
    echo [ERROR] LuScreen.exe not found
    pause
    exit /b 1
)

call :resolve_iscc
if errorlevel 1 (
    pause
    exit /b 1
)
echo [INFO] Using ISCC: %ISCC_EXE%
"%ISCC_EXE%" /DLUSCREEN_PACKAGE_FLAVOR=%LUSCREEN_PACKAGE_FLAVOR% /DMyAppVersion=%APP_VERSION% "%~dp0installer.iss"
if errorlevel 1 (
    echo [ERROR] Inno Setup pack failed
    pause
    exit /b 1
)

echo(
echo ========================================
echo Pack completed
echo Installer path: dist_installer\LuScreen-Debug-Setup-v%APP_VERSION%.exe
echo ========================================
pause
exit /b 0

:load_app_version
set "RAW_VERSION="
set "APP_VERSION="
for /f "tokens=2 delims==" %%I in ('findstr /b /c:"APP_VERSION" "%~dp0src\version.py"') do set "RAW_VERSION=%%I"
set "APP_VERSION=%RAW_VERSION:"=%"
set "APP_VERSION=%APP_VERSION: =%"
if not defined APP_VERSION (
    echo [ERROR] Failed to read APP_VERSION from src\version.py
    exit /b 1
)
exit /b 0

:resolve_iscc
set "ISCC_EXE=%ISCC_EXE%"
if defined ISCC_EXE if exist "%ISCC_EXE%" exit /b 0
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC_EXE=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    exit /b 0
)
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "ISCC_EXE=C:\Program Files\Inno Setup 6\ISCC.exe"
    exit /b 0
)
for /f "delims=" %%i in ('where.exe ISCC.exe 2^>nul') do (
    set "ISCC_EXE=%%i"
    exit /b 0
)
echo [ERROR] ISCC.exe not found
echo [ERROR] Set ISCC_EXE or install Inno Setup 6.
echo [ERROR] Expected common path: C:\Program Files ^(x86^)\Inno Setup 6\ISCC.exe
exit /b 1
