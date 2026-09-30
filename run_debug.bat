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
    echo [THONG BAO] Dang khoi tao moi truong ao .venv...
    call setup.bat
    if errorlevel 1 (
        echo [LOI] Khoi tao moi truong that bai!
        pause
        exit /b 1
    )
)


echo [OK] He thong san sang! Dang mo giao dien Auto Video Renderer...
echo (Vui long khong tat cua so nay khi dang su dung tool)
echo.

REM 3. Khoi chay truc tiep ung dung
".venv\Scripts\python.exe" app.py

if errorlevel 1 (
    echo.
    echo ================================================================
    echo [LOI] Chuong trinh bi dung. Chi tiet loi o tren.
    echo ================================================================
    pause
)
