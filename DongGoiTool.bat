@echo off
chcp 65001 >nul
title Dong Goi Tool - Auto Video Renderer
cd /d "%~dp0"

echo ================================================================
echo        📦 TU DONG LAM SACH VA DONG GOI BAN PHAN PHOI
echo ================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    call setup.bat
)

".venv\Scripts\python.exe" -m src_app.core.export_release
echo.
pause
