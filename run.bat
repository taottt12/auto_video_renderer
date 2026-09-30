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

REM 2. Kiem tra thu vien quan trong va PyTorch
".venv\Scripts\python.exe" -c "import PySide6, whisper, torch, googleapiclient, yt_dlp, openpyxl, PIL" 2>nul
if errorlevel 1 (
    echo [THONG BAO] Phat hien thieu thu vien hoac PyTorch, dang tien hanh cai dat chuan hoa qua setup.bat...
    call setup.bat
    if errorlevel 1 (
        echo [CANH BAO] Cai dat thu vien that bai. Vui long kiem tra ket noi mang.
        pause
        exit /b 1
    )
)

echo [OK] He thong san sang! Dang mo ung dung...
echo (Vui long khong dong cua so nay khi dang render video)
echo.

REM 3. Khoi chay ung dung
".venv\Scripts\python.exe" app.py

if errorlevel 1 (
    echo.
    echo ================================================================
    echo [LOI] Ung dung bi dung dot ngot hoac gap loi khi khoi chay!
    echo Vui long chup anh thong bao loi o tren de duoc ho tro.
    echo ================================================================
    pause
)

