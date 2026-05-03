@echo off
setlocal enabledelayedexpansion
if "%LUSCREEN_NO_PAUSE%"=="" set "LUSCREEN_NO_PAUSE=0"
if "%LUSCREEN_BUILD_LOGGED%"=="" (
    set "LUSCREEN_BUILD_LOGGED=1"
    for %%f in ("%~f0") do set "SCRIPT_DIR=%%~dpf"
    set "LOG_DIR=!SCRIPT_DIR!logs"
    if not exist "!LOG_DIR!" mkdir "!LOG_DIR!" >nul 2>&1
    for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "LOG_TS=%%i"
    set "LOG_FILE=!LOG_DIR!\build_nuitka_!LOG_TS!.log"
    set "RUNNER_FILE=!LOG_DIR!\build_nuitka_runner_!LOG_TS!.cmd"
    set "RC_FILE=!LOG_DIR!\build_nuitka_rc_!LOG_TS!.txt"
    > "!RUNNER_FILE!" echo @echo off
    >> "!RUNNER_FILE!" echo setlocal
    >> "!RUNNER_FILE!" echo set "LUSCREEN_BUILD_LOGGED=1"
    >> "!RUNNER_FILE!" echo call "%~f0" %*
    >> "!RUNNER_FILE!" echo set "INNER_RC=%%ERRORLEVEL%%"
    >> "!RUNNER_FILE!" echo ^> "!RC_FILE!" echo %%INNER_RC%%
    >> "!RUNNER_FILE!" echo exit /b %%INNER_RC%%
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$env:LUSCREEN_BUILD_LOGGED='1'; $psi = New-Object System.Diagnostics.ProcessStartInfo; $psi.FileName = 'cmd.exe'; $psi.Arguments = '/d /c ""!RUNNER_FILE!""'; $psi.WorkingDirectory = '!SCRIPT_DIR!'; $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $p = New-Object System.Diagnostics.Process; $p.StartInfo = $psi; $writer = [System.IO.StreamWriter]::new('!LOG_FILE!', $false, [System.Text.UTF8Encoding]::new($false)); $writer.AutoFlush = $true; function Handle-Line([string]$line) { if ($null -eq $line) { return }; Write-Host $line; $writer.WriteLine($line) }; try { $null = $p.Start(); while(-not $p.HasExited -or -not $p.StandardOutput.EndOfStream -or -not $p.StandardError.EndOfStream) { while(-not $p.StandardOutput.EndOfStream) { Handle-Line ($p.StandardOutput.ReadLine()) } while(-not $p.StandardError.EndOfStream) { Handle-Line ($p.StandardError.ReadLine()) } Start-Sleep -Milliseconds 50 }; $p.WaitForExit(); exit $p.ExitCode } finally { $writer.Dispose(); $p.Dispose() }"
    set "BUILD_RC=1"
    if exist "!RC_FILE!" (
        for /f "usebackq delims=" %%r in ("!RC_FILE!") do set "BUILD_RC=%%r"
    ) else (
        set "BUILD_RC=%errorlevel%"
    )
    del /f /q "!RUNNER_FILE!" >nul 2>&1
    del /f /q "!RC_FILE!" >nul 2>&1
    echo(
    echo [INFO] Build log saved: !LOG_FILE!
    if not "!BUILD_RC!"=="0" (
        echo [ERROR] Build failed with exit code !BUILD_RC!. Opening log...
        start "" "!LOG_FILE!"
    )
    if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
    exit /b !BUILD_RC!
)
for /f %%i in ('powershell -NoProfile -Command "[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()"') do set BUILD_START_MS=%%i

set "LUSCREEN_PYTHON_EXE=%LUSCREEN_PYTHON%"
set "NUITKA_CACHE_DIR=%~dp0.nuitka_cache"
set "CLCACHE_DIR=%~dp0.clcache"
set "TEMP=%~dp0temp_build"
set "TMP=%~dp0temp_build"
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
if "%LUSCREEN_WINDOWS_CONSOLE_MODE%"=="" set "LUSCREEN_WINDOWS_CONSOLE_MODE=disable"
set "LUSCREEN_STDIO_LOG_OPTIONS="
if /i "%LUSCREEN_WINDOWS_CONSOLE_MODE%"=="disable" (
    set "LUSCREEN_STDIO_LOG_OPTIONS=--force-stdout-spec={PROGRAM_BASE}/../logs/stdout.log --force-stderr-spec={PROGRAM_BASE}/../logs/stderr.log"
)

if not exist "%NUITKA_CACHE_DIR%" mkdir "%NUITKA_CACHE_DIR%" >nul 2>&1
if not exist "%CLCACHE_DIR%" mkdir "%CLCACHE_DIR%" >nul 2>&1
if not exist "%TEMP%" mkdir "%TEMP%" >nul 2>&1

if "%LUSCREEN_PYTHON_EXE%"=="" (
    set "CANDIDATE_PY="
    if /i "%LUSCREEN_RELEASE_FLAVOR%"=="gpu" (
        if exist "%~dp0.venv_release_gpu_py312\Scripts\python.exe" set "CANDIDATE_PY=%~dp0.venv_release_gpu_py312\Scripts\python.exe"
    )
    if "!CANDIDATE_PY!"=="" (
        if exist "%~dp0.venv_release_cpu_py312\Scripts\python.exe" set "CANDIDATE_PY=%~dp0.venv_release_cpu_py312\Scripts\python.exe"
    )
    if not "!CANDIDATE_PY!"=="" set "LUSCREEN_PYTHON_EXE=!CANDIDATE_PY!"
)
if not "%LUSCREEN_PYTHON_EXE%"=="" (
    set "PY=%LUSCREEN_PYTHON_EXE%"
    set "PIP=%LUSCREEN_PYTHON_EXE% -m pip"
) else (
    set "PY=python"
    set "PIP=pip"
)

if "%LUSCREEN_APP_VERSION%"=="" (
    for /f "delims=" %%i in ('%PY% -c "from src.version import APP_VERSION; print(APP_VERSION)"') do set "LUSCREEN_APP_VERSION=%%i"
)
if "%LUSCREEN_APP_VERSION%"=="" (
    echo [ERROR] Failed to load APP_VERSION from src\version.py
    if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
    exit /b 1
)
for /f "delims=" %%i in ('%PY% -c "v = '%LUSCREEN_APP_VERSION%'.split('.'); v = (v + ['0'] * 4)[:4]; print('.'.join(str(int(p)) for p in v))"') do set "LUSCREEN_FILE_VERSION=%%i"
if "%LUSCREEN_FILE_VERSION%"=="" (
    echo [ERROR] Failed to normalize Windows file version from %LUSCREEN_APP_VERSION%
    if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo [INFO] Using Python: %PY%
echo [INFO] App version: %LUSCREEN_APP_VERSION%
echo [INFO] Windows file version: %LUSCREEN_FILE_VERSION%
echo [INFO] Windows console mode: %LUSCREEN_WINDOWS_CONSOLE_MODE%
if not "%LUSCREEN_STDIO_LOG_OPTIONS%"=="" (
    echo [INFO] Stdout/Stderr log files: logs\stdout.log , logs\stderr.log
)
echo ========================================================
echo  LuScreen Build Script (Nuitka)
echo  Enhancing security by compiling Python to C++
echo ========================================================

echo(
set "LUSCREEN_BUILD_CLEAN=1"
if "%LUSCREEN_SKIP_PIP%"=="" set "LUSCREEN_SKIP_PIP=0"

set "PREP_ONLY=0"
:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--prep-only" (
    set "PREP_ONLY=1"
    shift
    goto :parse_args
)
shift
goto :parse_args
:args_done

if /i "%LUSCREEN_SKIP_PIP%"=="1" (
    echo [1/4] Skipping pip install - LUSCREEN_SKIP_PIP=1...
) else (
    echo [1/4] Installing/Updating build dependencies...
    %PIP% install -U nuitka zstandard ordered-set imageio-ffmpeg rapidocr_onnxruntime onnxruntime pyclipper shapely
    if errorlevel 1 (
        echo [ERROR] pip install failed!
        call :print_elapsed
        if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
        exit /b 1
    )
)

echo(
echo [INFO] Subtitle runtime (WhisperX/Torch) is NOT bundled by default.
echo [INFO] Users will download/install it on first use.

echo(
echo [CHECK] Verifying rapidocr_onnxruntime installation...
%PY% -c "import rapidocr_onnxruntime; print('Found rapidocr_onnxruntime at: ' + rapidocr_onnxruntime.__path__[0])" > nul 2>&1
if errorlevel 1 (
    echo [ERROR] rapidocr_onnxruntime is NOT installed! Nuitka will fail to bundle it.
    call :print_elapsed
    if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
    exit /b 1
) else (
    echo [OK] rapidocr_onnxruntime is installed.
)

echo(
echo [2/4] Locating FFmpeg...
set FFMPEG_PATH=
for /f "delims=" %%i in ('%PY% -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"') do set FFMPEG_PATH=%%i

if "%FFMPEG_PATH%"=="" (
    echo [ERROR] Could not find FFmpeg path!
    echo Please ensure imageio-ffmpeg is installed correctly.
    call :print_elapsed
    if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
    exit /b 1
)
echo FFmpeg found at: %FFMPEG_PATH%

echo(
echo [3/4] Preparing build directories...
echo Closing running instances...
taskkill /F /IM LuScreen.exe 2>nul
taskkill /F /IM main.exe 2>nul

echo Waiting for file handles to release...
timeout /t 2 /nobreak > NUL

echo Full clean build: removing previous build artifacts...
if exist "dist_nuitka\main.dist\main.exe" (
    attrib -R -S -H "dist_nuitka\main.dist\main.exe" > nul 2>&1
    del /F /Q "dist_nuitka\main.dist\main.exe" > nul 2>&1
)
if exist "dist_nuitka\LuScreen.dist\LuScreen.exe" (
    attrib -R -S -H "dist_nuitka\LuScreen.dist\LuScreen.exe" > nul 2>&1
    del /F /Q "dist_nuitka\LuScreen.dist\LuScreen.exe" > nul 2>&1
)
if exist "main.dist" rmdir /s /q "main.dist"
if exist "main.build" rmdir /s /q "main.build"
if exist "dist_nuitka" (
    rmdir /s /q "dist_nuitka"
    if exist "dist_nuitka" (
        echo [WARN] rmdir failed. Trying again...
        timeout /t 2 /nobreak > NUL
        rmdir /s /q "dist_nuitka"
    )
)
if exist "dist_nuitka" (
    echo [ERROR] Failed to remove dist_nuitka. A process may still be using dist_nuitka\main.dist\main.exe
    echo Please close any running LuScreen/main.exe and try again. Antivirus real-time scanning may also lock files.
    call :print_elapsed
    if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
    exit /b 1
)

if /i "%PREP_ONLY%"=="1" (
    echo(
    echo Prep-only mode enabled --prep-only. Exiting before compilation.
    call :print_elapsed
    exit /b 0
)

echo(
echo [4/4] Compiling with Nuitka...
echo This process may take a while (10-30 mins).
echo Please be patient...
echo Build output will be shown below...

set /a NUITKA_JOBS=%NUMBER_OF_PROCESSORS%/2
if %NUITKA_JOBS% LSS 1 set NUITKA_JOBS=1
if not "%LUSCREEN_NUITKA_JOBS%"=="" set NUITKA_JOBS=%LUSCREEN_NUITKA_JOBS%
set NUITKA_CCACHE_OPT=--disable-ccache
if "%LUSCREEN_NUITKA_DISABLE_CCACHE%"=="0" set NUITKA_CCACHE_OPT=
set NUITKA_SHOW_MEMORY_OPT=
if "%LUSCREEN_NUITKA_SHOW_MEMORY%"=="1" set NUITKA_SHOW_MEMORY_OPT=--show-memory

echo(
echo [CHECK] Verifying Nuitka availability...
%PY% -m nuitka --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Nuitka is not installed in this Python environment.
    echo [ERROR] Fix option A: remove LUSCREEN_SKIP_PIP and rerun build_nuitka.bat
    echo [ERROR] Fix option B: install Nuitka manually:
    echo [ERROR]   %PIP% install -U nuitka zstandard ordered-set
    call :print_elapsed
    if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo(
echo [CHECK] Verifying rapidocr_onnxruntime subpackages...
set "RAPIDOCR_NUITKA_OPTS=--include-package=rapidocr_onnxruntime --include-package-data=rapidocr_onnxruntime"
%PY% -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('rapidocr_onnxruntime.ch_ppocr_cls') else 1)" > nul 2>&1
if not errorlevel 1 (
    set "RAPIDOCR_NUITKA_OPTS=!RAPIDOCR_NUITKA_OPTS! --include-package=rapidocr_onnxruntime.ch_ppocr_cls --include-package-data=rapidocr_onnxruntime.ch_ppocr_cls --include-module=rapidocr_onnxruntime.ch_ppocr_cls.text_cls"
) else (
    echo [WARN] rapidocr_onnxruntime.ch_ppocr_cls not found. Skipping explicit include.
)
%PY% -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('rapidocr_onnxruntime.ch_ppocr_det') else 1)" > nul 2>&1
if not errorlevel 1 (
    set "RAPIDOCR_NUITKA_OPTS=!RAPIDOCR_NUITKA_OPTS! --include-package=rapidocr_onnxruntime.ch_ppocr_det --include-package-data=rapidocr_onnxruntime.ch_ppocr_det --include-module=rapidocr_onnxruntime.ch_ppocr_det.text_detect"
) else (
    echo [WARN] rapidocr_onnxruntime.ch_ppocr_det not found. Skipping explicit include.
)
%PY% -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('rapidocr_onnxruntime.ch_ppocr_rec') else 1)" > nul 2>&1
if not errorlevel 1 (
    set "RAPIDOCR_NUITKA_OPTS=!RAPIDOCR_NUITKA_OPTS! --include-package=rapidocr_onnxruntime.ch_ppocr_rec --include-package-data=rapidocr_onnxruntime.ch_ppocr_rec --include-module=rapidocr_onnxruntime.ch_ppocr_rec.text_recognize"
) else (
    echo [WARN] rapidocr_onnxruntime.ch_ppocr_rec not found. Skipping explicit include.
)

echo Running Nuitka command...
echo python -m nuitka [options] main.py
set "NUITKA_HEARTBEAT_PS=%~dp0tools\run_command_with_heartbeat.ps1"
set "NUITKA_RUNNER_FILE=%TEMP%\run_nuitka_%RANDOM%_%RANDOM%.cmd"

if not exist "%NUITKA_HEARTBEAT_PS%" (
    echo [ERROR] Missing helper script: %NUITKA_HEARTBEAT_PS%
    call :print_elapsed
    if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
    exit /b 1
)

set "NUITKA_COMPILE_CMD="%PY%" -m nuitka --show-scons --show-progress %NUITKA_SHOW_MEMORY_OPT% --standalone --msvc=latest --lto=no --jobs=%NUITKA_JOBS% %NUITKA_CCACHE_OPT% --plugin-enable=pyside6 --plugin-enable=anti-bloat --noinclude-pytest-mode=nofollow --noinclude-setuptools-mode=allow --nofollow-import-to=sympy --nofollow-import-to=scipy --nofollow-import-to=matplotlib --nofollow-import-to=pandas --nofollow-import-to=sqlalchemy --nofollow-import-to=tkinter --nofollow-import-to=ipython --nofollow-import-to=unittest --nofollow-import-to=PIL.TiffImagePlugin --nofollow-import-to=PIL.JpegImagePlugin --nofollow-import-to=PIL.BmpImagePlugin --nofollow-import-to=openai --nofollow-import-to=httpx --nofollow-import-to=httpcore --nofollow-import-to=h11 --nofollow-import-to=distro --nofollow-import-to=jiter --nofollow-import-to=pydantic --nofollow-import-to=pydantic_core --nofollow-import-to=sniffio --nofollow-import-to=anyio --nofollow-import-to=annotated_types --nofollow-import-to=shapely.tests --nofollow-import-to=shapely.vectorized --nofollow-import-to=torch --nofollow-import-to=whisperx --nofollow-import-to=transformers --no-deployment-flag=excluded-module-usage --include-qt-plugins=multimedia,platforms,styles,imageformats,iconengines --include-package=soundcard --include-package-data=soundcard --include-package=soundfile --include-package=requests --include-package=certifi --include-package-data=certifi --include-module=rust_core !RAPIDOCR_NUITKA_OPTS! --include-package=onnxruntime --include-package-data=onnxruntime --include-package=pyclipper --include-package=shapely --include-package-data=shapely --include-package=PIL --nofollow-import-to=setuptools --include-data-dir=assets=assets --include-data-file=models/manifest.json=models/manifest.json --include-data-file="%FFMPEG_PATH%"=ffmpeg.exe --windows-console-mode=%LUSCREEN_WINDOWS_CONSOLE_MODE% %LUSCREEN_STDIO_LOG_OPTIONS% --windows-icon-from-ico=assets/icon.ico --company-name="LuScreen" --product-name="LuScreen" --file-version=%LUSCREEN_FILE_VERSION% --product-version=%LUSCREEN_FILE_VERSION% --output-dir=dist_nuitka --assume-yes-for-downloads main.py"
(
echo @echo off
echo setlocal
echo echo^(
echo echo [RUNNER] ========================================
echo echo [RUNNER] Preflight Start
echo echo [RUNNER] ========================================
echo echo [RUNNER] Child runner started.
echo echo [RUNNER] Working directory: %%CD%%
echo echo [RUNNER] Python executable: %PY%
echo echo [RUNNER] --- Python Startup Check ---
echo echo [RUNNER] Checking child Python startup...
echo "%PY%" -c "import sys; print('child-python=' + sys.executable)"
echo if errorlevel 1 exit /b %%errorlevel%%
echo echo [RUNNER] --- Nuitka Import Check ---
echo echo [RUNNER] Checking child Nuitka import...
echo "%PY%" -c "import nuitka; print('nuitka-module=' + getattr(nuitka, '__file__', '<unknown>'))"
echo if errorlevel 1 exit /b %%errorlevel%%
echo echo [RUNNER] ========================================
echo echo [RUNNER] Preflight OK
echo echo [RUNNER] ========================================
echo echo^(
echo echo [RUNNER] ========================================
echo echo [RUNNER] Nuitka Compile Start
echo echo [RUNNER] ========================================
echo echo [RUNNER] Launching Nuitka compile...
echo !NUITKA_COMPILE_CMD!
echo exit /b %%errorlevel%%
) > "%NUITKA_RUNNER_FILE%"

echo(
echo [INFO] ========================================
echo [INFO] Runner Phase: Preflight + Nuitka Compile
echo [INFO] ========================================
echo [INFO] Nuitka runner script: %NUITKA_RUNNER_FILE%
echo [INFO] Heartbeat helper: %NUITKA_HEARTBEAT_PS%
echo [INFO] Runner preflight will verify child Python and child Nuitka import before compile.
powershell -NoProfile -ExecutionPolicy Bypass -File "%NUITKA_HEARTBEAT_PS%" ^
 -RunnerPath "%NUITKA_RUNNER_FILE%" ^
 -WorkingDirectory "%PROJECT_ROOT%" ^
 -BuildDir "%~dp0dist_nuitka\main.build" ^
 -DistDir "%~dp0dist_nuitka\main.dist" ^
 -HeartbeatSeconds 10
set NUITKA_RC=%errorlevel%
del /f /q "%NUITKA_RUNNER_FILE%" >nul 2>&1

if not "%NUITKA_RC%"=="0" (
    if exist "dist_nuitka\main.dist\main.exe" (
        echo(
        echo [WARN] Nuitka exited with code %NUITKA_RC% but main.exe exists. Continuing...
        echo [WARN] If you need memory trace, set LUSCREEN_NUITKA_SHOW_MEMORY=1 ^(may crash on low RAM^).
    ) else (
        echo(
        echo [ERROR] Compilation failed!
        echo Check the console output above for details.
        call :print_elapsed
        if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
        exit /b 1
    )
)

echo(
echo [5/5] Renaming build artifacts...
if exist "dist_nuitka\main.dist" (
    call :rename_dist
    if errorlevel 1 (
         echo [ERROR] Failed to rename/move dist folder.
         call :print_elapsed
         if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
         exit /b 1
    )
    
    if exist "dist_nuitka\LuScreen.dist\main.exe" (
        move "dist_nuitka\LuScreen.dist\main.exe" "dist_nuitka\LuScreen.dist\LuScreen.exe"
    )
    if not exist "dist_nuitka\LuScreen.dist\logs" (
        mkdir "dist_nuitka\LuScreen.dist\logs"
    )
    
    echo(
    echo [CHECK] Verifying bundled dependencies...
    if exist "dist_nuitka\LuScreen.dist\rapidocr_onnxruntime" (
        echo [OK] rapidocr_onnxruntime package data found in distribution.
        if exist "dist_nuitka\LuScreen.dist\rapidocr_onnxruntime\config.yaml" (
            echo [OK] rapidocr_onnxruntime/config.yaml present.
        ) else (
            echo [WARNING] config.yaml missing under rapidocr_onnxruntime!
        )
        if exist "dist_nuitka\LuScreen.dist\rapidocr_onnxruntime\ch_ppocr_det" (
            echo [OK] ch_ppocr_det model package present.
        ) else (
            echo [WARNING] ch_ppocr_det missing!
        )
        if exist "dist_nuitka\LuScreen.dist\rapidocr_onnxruntime\ch_ppocr_rec" (
            echo [OK] ch_ppocr_rec model package present.
        ) else (
            echo [WARNING] ch_ppocr_rec missing!
        )
        if exist "dist_nuitka\LuScreen.dist\rapidocr_onnxruntime\ch_ppocr_cls" (
            echo [OK] ch_ppocr_cls model package present.
        ) else (
            echo [WARNING] ch_ppocr_cls missing!
        )
    ) else (
        echo [WARNING] rapidocr_onnxruntime folder missing in output! OCR may fail.
        echo This might be due to Nuitka configuration or missing package data.
    )
) else (
    if not exist "dist_nuitka\LuScreen.dist" (
        echo [ERROR] Output directory not found!
        call :print_elapsed
        if /i not "%LUSCREEN_NO_PAUSE%"=="1" pause
        exit /b 1
    )
)

echo(
echo ========================================================
echo  Build Complete!
echo  The executable is located in: dist_nuitka\LuScreen.dist\LuScreen.exe

echo(
echo Tips:
echo - Full clean build is always enabled in this script.
echo - Skip pip install: set LUSCREEN_SKIP_PIP=1
echo - Folder mode: you must distribute the entire 'LuScreen.dist' folder
echo ========================================================
call :print_elapsed
exit /b 0

:rename_dist
    if exist "dist_nuitka\LuScreen.dist" (
        rmdir /s /q "dist_nuitka\LuScreen.dist"
        REM 重试一次，防止文件被锁
        if exist "dist_nuitka\LuScreen.dist" (
             timeout /t 2 /nobreak > NUL
             rmdir /s /q "dist_nuitka\LuScreen.dist"
        )
    )
    
    REM 等待一小会儿确保文件释放
    timeout /t 5 /nobreak > NUL
    
    move "dist_nuitka\main.dist" "dist_nuitka\LuScreen.dist"
    if errorlevel 1 (
        echo [WARN] move main.dist to LuScreen.dist failed. Trying robocopy...
        mkdir "dist_nuitka\LuScreen.dist" >nul 2>&1
        robocopy "dist_nuitka\main.dist" "dist_nuitka\LuScreen.dist" /E /MOVE /NFL /NDL /NJH /NJS >nul 2>&1
        if errorlevel 8 exit /b 1
    )
    exit /b 0

:print_elapsed
set BUILD_END_MS=
for /f %%i in ('powershell -NoProfile -Command "[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()"') do set BUILD_END_MS=%%i
for /f "delims=" %%i in ('powershell -NoProfile -Command "$s=%BUILD_START_MS%; $e=%BUILD_END_MS%; $d=$e-$s; if($d -lt 0){$d=0}; $ts=[TimeSpan]::FromMilliseconds($d); $h=[int]$ts.TotalHours; $m=$ts.Minutes; $sec=$ts.Seconds; \"Total build time: {0:00}:{1:00}:{2:00}\" -f $h,$m,$sec"') do set BUILD_ELAPSED=%%i
echo(
echo %BUILD_ELAPSED%
goto :eof
