@echo off
setlocal

echo ========================================================
echo  LuScreen Build Script (Nuitka)
echo  Enhancing security by compiling Python to C++
echo ========================================================

echo.
echo [1/4] Installing/Updating Nuitka and zstandard...
pip install -U nuitka zstandard ordered-set imageio-ffmpeg

echo.
echo [2/4] Locating FFmpeg...
set FFMPEG_PATH=
for /f "delims=" %%i in ('python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"') do set FFMPEG_PATH=%%i

if "%FFMPEG_PATH%"=="" (
    echo [ERROR] Could not find FFmpeg path!
    echo Please ensure imageio-ffmpeg is installed correctly.
    pause
    exit /b 1
)
echo FFmpeg found at: %FFMPEG_PATH%

echo.
echo [3/4] Cleaning up previous builds...
echo Closing running instances...
taskkill /F /IM LuScreen.exe 2>nul
if exist "main.dist" rmdir /s /q "main.dist"
if exist "main.build" rmdir /s /q "main.build"
if exist "dist_nuitka" rmdir /s /q "dist_nuitka"

echo.
echo [4/4] Compiling with Nuitka...
echo This process may take a while (10-30 mins).
echo Please be patient...
echo Build output will be shown below...

python -m nuitka ^
    --standalone ^
    --msvc=latest ^
    --lto=yes ^
    --plugin-enable=pyside6 ^
    --plugin-enable=numpy ^
    --include-qt-plugins=multimedia ^
    --include-package=soundcard ^
    --include-package-data=soundcard ^
    --include-package=soundfile ^
    --include-package=requests ^
    --nofollow-import-to=setuptools ^
    --include-data-dir=assets=assets ^
    --include-data-file="%FFMPEG_PATH%"=ffmpeg.exe ^
    --windows-console-mode=force ^
    --windows-icon-from-ico=assets/icon.png ^
    --company-name="LuScreen" ^
    --product-name="LuScreen" ^
    --file-version=1.0.0.0 ^
    --product-version=1.0.0.0 ^
    --output-dir=dist_nuitka ^
    --assume-yes-for-downloads ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Compilation failed!
    echo Check the console output above for details.
    pause
    exit /b 1
)

echo.
echo [5/5] Renaming build artifacts...
if exist "dist_nuitka\main.dist" (
    if exist "dist_nuitka\LuScreen.dist" rmdir /s /q "dist_nuitka\LuScreen.dist"
    
    REM 等待一小会儿确保文件释放
    timeout /t 2 /nobreak > NUL
    
    move "dist_nuitka\main.dist" "dist_nuitka\LuScreen.dist"
    if errorlevel 1 (
        echo [ERROR] Failed to rename dist folder!
        exit /b 1
    )
    
    if exist "dist_nuitka\LuScreen.dist\main.exe" (
        move "dist_nuitka\LuScreen.dist\main.exe" "dist_nuitka\LuScreen.dist\LuScreen.exe"
    )
) else (
    if not exist "dist_nuitka\LuScreen.dist" (
        echo [ERROR] Output directory not found!
        exit /b 1
    )
)

echo.
echo ========================================================
echo  Build Complete!
echo  The executable is located in: dist_nuitka\LuScreen.dist\LuScreen.exe
echo  (Folder mode: You must distribute the entire 'LuScreen.dist' folder)
echo ========================================================