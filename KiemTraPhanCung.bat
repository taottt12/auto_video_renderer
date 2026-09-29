@echo off
chcp 65001 >nul
title Kiem Tra Phan Cung - Auto Video Renderer
cd /d "%~dp0"

echo Dang quet phan cung he thong...
if not exist ".venv\Scripts\python.exe" (
    call setup.bat
)

".venv\Scripts\python.exe" -m src_app.core.hardware_checker
echo.
pause
