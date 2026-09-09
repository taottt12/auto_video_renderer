@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Auto Video Renderer

REM Chay bang pythonw de khong hien cua so CMD treo.
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
    exit /b 0
)

echo [LOI] Chua thay .venv\Scripts\pythonw.exe
echo Hay chay setup.bat truoc mot lan.
echo.
pause
exit /b 1
