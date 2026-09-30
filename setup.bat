@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Auto Video Renderer - Setup & Auto Installer
cd /d "%~dp0"

echo ================================================================
echo        🚀 AUTO VIDEO RENDERER - THIET LAP MOI TRUONG
echo ================================================================
echo.

set "PY_EXE="

REM 1. Kiem tra py.exe (Python Launcher chuan cua Windows)
for /f "delims=" %%P in ('where py.exe 2^>nul') do (
    set "PY_EXE=%%P"
    goto :PYTHON_FOUND
)

REM 2. Kiem tra python.exe trong PATH
for /f "delims=" %%P in ('where python.exe 2^>nul') do (
    set "PY_EXE=%%P"
    goto :PYTHON_FOUND
)

REM 3. Quet cac thu muc cai dat Python pho bien tren Windows
set "SEARCH_PATHS="
set "SEARCH_PATHS=!SEARCH_PATHS!;%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "SEARCH_PATHS=!SEARCH_PATHS!;%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
set "SEARCH_PATHS=!SEARCH_PATHS!;%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
set "SEARCH_PATHS=!SEARCH_PATHS!;%ProgramFiles%\Python312\python.exe"
set "SEARCH_PATHS=!SEARCH_PATHS!;%ProgramFiles%\Python311\python.exe"
set "SEARCH_PATHS=!SEARCH_PATHS!;%ProgramFiles%\Python310\python.exe"
set "SEARCH_PATHS=!SEARCH_PATHS!;C:\Python312\python.exe"
set "SEARCH_PATHS=!SEARCH_PATHS!;C:\Python311\python.exe"
set "SEARCH_PATHS=!SEARCH_PATHS!;C:\Python310\python.exe"

for %%P in (%SEARCH_PATHS%) do (
    if exist "%%P" (
        set "PY_EXE=%%P"
        goto :PYTHON_FOUND
    )
)

REM 4. Neu khong tim thay Python -> Tu dong tai va cai dat Python 3.10 chinh thuc
echo [THONG BAO] Khong tim thay Python tren may tinh cua ban!
echo Dang tien hanh tu dong tai va cai dat Python 3.10 tu trang chu python.org...
echo (Vui long cho trong it phut de may tai va cai dat tu dong)...
echo.

set "INSTALLER_URL=https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
set "INSTALLER_FILE=%TEMP%\python-3.10.11-installer.exe"

REM Dung curl hoac powershell de tai
where curl.exe >nul 2>&1
if not errorlevel 1 (
    curl.exe -L -o "!INSTALLER_FILE!" "!INSTALLER_URL!"
) else (
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('!INSTALLER_URL!', '!INSTALLER_FILE!')"
)

if not exist "!INSTALLER_FILE!" (
    echo [LOI] Khong the tai bo cai Python tu dong. Vui long kiem tra ket noi mang!
    pause
    exit /b 1
)

echo [OK] Da tai xong. Dang tu dong cai dat Python vao he thong...
"!INSTALLER_FILE!" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 SimpleInstall=1
timeout /t 5 >nul
del "!INSTALLER_FILE!" 2>nul

REM Quet lai sau khi cai
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :PYTHON_FOUND
)
for /f "delims=" %%P in ('where python.exe 2^>nul') do (
    set "PY_EXE=%%P"
    goto :PYTHON_FOUND
)

echo [LOI] Cai dat Python chua hoan tat. Vui long khoi dong lai may va thu lai!
pause
exit /b 1

:PYTHON_FOUND
echo [OK] Phat hien Python: "!PY_EXE!"
"!PY_EXE!" --version

echo.
echo [1/3] Dang tao moi truong ao (.venv) tu Python nay...
if not exist ".venv\Scripts\python.exe" (
    "!PY_EXE!" -m venv ".venv"
    if errorlevel 1 (
        echo [LOI] Tao moi truong ao .venv that bai!
        pause
        exit /b 1
    )
) else (
    echo [OK] Moi truong .venv da san sang.
)

echo.
echo [2/4] Kiem tra va nang cap trinh quan ly pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1

echo.
echo [3/4] Dang quet GPU va cai dat PyTorch CUDA phu hop cho card do hoa...
where nvidia-smi.exe >nul 2>&1
if not errorlevel 1 (
    echo [OK] Phat hien card do hoa NVIDIA GPU!
    echo Dang cai dat PyTorch CUDA 12.4 chinh thuc cho GPU...
    ".venv\Scripts\python.exe" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
) else (
    echo [THONG BAO] Khong tim thay GPU NVIDIA. Dang cai dat PyTorch CPU...
    ".venv\Scripts\python.exe" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
)

echo.
echo [4/4] Dang tu dong cai dat tat ca thu vien con lai tu requirements.txt...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [CANH BAO] Co loi khi cai dat thu vien. Vui long kiem tra ket noi mang va thu lai!
    pause
    exit /b 1
)

echo.
echo ================================================================
echo 🔍 KIEM TRA TINH TRANG PYTORCH CUDA:
".venv\Scripts\python.exe" -c "import torch; print('• PyTorch Version:', torch.__version__); print('• CUDA Available:', torch.cuda.is_available()); print('• GPU Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'Khong co GPU')"
echo ================================================================
echo 🎉 THIET LAP HOAN TAT! HE THONG DA SAN SANG 100%.
echo Tu nay ban chi can nhap dup vao [ ChayTool.bat ] de mo app.
echo ================================================================
pause
exit /b 0
