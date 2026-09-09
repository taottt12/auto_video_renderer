@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Auto Video Renderer - Setup

echo ==================================================
echo  Auto Video Renderer - SETUP LAN DAU
echo ==================================================
echo Thu muc hien tai: %CD%
echo.

set "PY_EXE="

REM Uu tien Python cua ban neu dang de tai E:\appp\python
if exist "E:\appp\python\python.exe" set "PY_EXE=E:\appp\python\python.exe"

REM Neu khong co thi tim python trong PATH
if not defined PY_EXE (
    for /f "delims=" %%P in ('where python.exe 2^>nul') do (
        set "PY_EXE=%%P"
        goto :PYTHON_FOUND
    )
)

:PYTHON_FOUND
if not defined PY_EXE (
    echo [LOI] Khong tim thay python.exe.
    echo Hay sua dong PY_EXE trong file setup.bat thanh duong dan Python cua ban.
    echo Vi du: set "PY_EXE=E:\appp\python\python.exe"
    pause
    exit /b 1
)

echo Dang dung Python:
echo "%PY_EXE%"
"%PY_EXE%" --version
if errorlevel 1 (
    echo [LOI] Python khong chay duoc.
    pause
    exit /b 1
)

echo.
echo [1/3] Tao moi truong ao .venv neu chua co...
if not exist ".venv\Scripts\python.exe" (
    "%PY_EXE%" -m venv ".venv"
    if errorlevel 1 (
        echo [LOI] Tao .venv that bai.
        pause
        exit /b 1
    )
) else (
    echo .venv da ton tai, bo qua buoc tao moi.
)

echo.
echo [2/3] Nang cap pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo [CANH BAO] Nang cap pip loi, van thu cai requirements tiep.
)

echo.
echo [3/3] Cai thu vien can thiet...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [LOI] Cai requirements that bai.
    echo Neu loi mang, hay chay lai setup.bat sau.
    pause
    exit /b 1
)

echo.
echo ==================================================
echo  SETUP XONG. Tu lan sau chi can mo run.bat
echo ==================================================
pause
exit /b 0
