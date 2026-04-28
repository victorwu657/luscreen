@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv_cpu_py312\\Scripts\\python.exe" (
  py -3.12 -m venv .venv_cpu_py312
)

".venv_cpu_py312\\Scripts\\python.exe" -m pip install --upgrade pip
".venv_cpu_py312\\Scripts\\python.exe" -m pip install -r requirements.txt

echo.
echo [OK] CPU 环境已就绪：.venv_cpu_py312
echo 运行：.venv_cpu_py312\\Scripts\\python.exe main.py
echo.
pause
