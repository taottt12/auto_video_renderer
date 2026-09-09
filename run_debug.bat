@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Auto Video Renderer - Debug Console

echo Dang chay app o che do debug. Neu app loi, loi se hien tai cua so nay.
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "%~dp0app.py"
) else (
    echo [LOI] Chua thay .venv\Scripts\python.exe
    echo Hay chay setup.bat truoc mot lan.
)

echo.
echo App da dong hoac bi loi. Nhan phim bat ky de thoat.
pause >nul
