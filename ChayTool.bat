@echo off
chcp 65001 >nul
title Auto Video Renderer
cd /d "%~dp0"

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

REM 2. Kiem tra thu vien quan trong
".venv\Scripts\python.exe" -c "import PySide6, faster_whisper, ctranslate2, googleapiclient, yt_dlp" 2>nul
if errorlevel 1 (
    echo [THONG BAO] Phat hien thieu thu vien, dang tu dong cai dat tu requirements.txt...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [CANH BAO] Cai dat thu vien that bai. Vui long kiem tra ket noi mang.
        pause
    )
)

REM 3. Khoi chay ung dung che do an CMD (Khong giu cua so man hinh den)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" app.py
) else (
    start "" ".venv\Scripts\python.exe" app.py
)
exit
