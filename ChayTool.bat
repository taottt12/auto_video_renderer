@echo off
chcp 65001 >nul
title Auto Video Renderer
cd /d "%~dp0"

echo ================================================================
echo        🚀 AUTO VIDEO RENDERER - DANG KHOI DONG...
echo ================================================================
echo.

REM 1. Kiem tra moi truong Python
if not exist ".venv\Scripts\python.exe" (
    echo [THONG BAO] Chua co moi truong .venv. Dang thiet lap tu dong qua setup.bat...
    call setup.bat
    if errorlevel 1 (
        echo [LOI] Khoi tao moi truong that bai!
        pause
        exit /b 1
    )
)

echo [OK] He thong san sang! Dang mo ung dung...
echo.

start "" ".venv\Scripts\pythonw.exe" app.py
exit /b 0

