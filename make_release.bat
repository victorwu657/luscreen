@echo off
echo Installing PyInstaller...
pip install pyinstaller

echo Cleaning up previous builds...
rmdir /s /q build
rmdir /s /q dist

echo Building LuScreen...
pyinstaller build.spec

echo.
echo ========================================================
echo Build Complete!
echo You can find the executable at: dist\LuScreen\LuScreen.exe
echo ========================================================
pause