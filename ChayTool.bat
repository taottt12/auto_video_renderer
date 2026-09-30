@echo off
chcp 65001 >nul
title Auto Video Renderer
cd /d "%~dp0"

REM 1. Kiem tra moi truong Python va tinh hop le
if not exist ".venv\Scripts\python.exe" (
    echo [THONG BAO] Dang khoi tao moi truong ao .venv...
    call setup.bat
    if errorlevel 1 (
        echo [LOI] Khoi tao moi truong that bai!
        pause
        exit /b 1
    )
) else (
    for /f "tokens=*" %%C in ('".venv\Scripts\python.exe" -c "import sys; print('INVALID' if sys.version_info >= (3, 13) or sys.version_info < (3, 10) else 'VALID')" 2^>nul') do (
        if "%%C"=="INVALID" (
            echo [CANH BAO] Moi truong .venv hien tai khong tuong thich AI. Dang thiet lap lai...
            call setup.bat
        )
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
    )
)

REM 3. Khoi chay ung dung che do an CMD (Khong giu cua so man hinh den)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" app.py
) else (
    start "" ".venv\Scripts\python.exe" app.py
)
exit
