@echo off
chcp 65001 >nul
title "Auto Video Renderer - Setup (Python 3.11 Chuẩn Hóa)"
cd /d "%~dp0"

echo ================================================================
echo        AUTO VIDEO RENDERER - THIET LAP MOI TRUONG CHUAN HOA
echo           (Phien ban toi uu: Python 3.11.9 64-bit)
echo ================================================================
echo.

set "PY_EXE="

REM 1. Kiem tra chinh xac Python 3.11 qua Windows Python Launcher
py -3.11 -V >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)"') do set "PY_EXE=%%P"
    goto :PYTHON_READY
)

REM 2. Kiem tra cac thu muc cai dat Python 3.11 thong dung
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :PYTHON_READY
)
if exist "%ProgramFiles%\Python311\python.exe" (
    set "PY_EXE=%ProgramFiles%\Python311\python.exe"
    goto :PYTHON_READY
)
if exist "C:\Python311\python.exe" (
    set "PY_EXE=C:\Python311\python.exe"
    goto :PYTHON_READY
)

REM 3. Neu chua co Python 3.11: Tu dong tai va cai dat chinh xac Python 3.11.9 64-bit
echo [THONG BAO] Chua tim thay Python 3.11 tren he thong.
echo Dang tu dong tai va cai dat chinh xac Python 3.11.9 64-bit (phien ban toi uu on dinh nhat cho yt-dlp, PyTorch, Whisper)...
echo Vui long cho trong it phut...
echo.

set "INSTALLER_FILE=%TEMP%\python-3.11.9-amd64.exe"
if exist "%INSTALLER_FILE%" del "%INSTALLER_FILE%" 2>nul

curl.exe -L -o "%INSTALLER_FILE%" "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
if not exist "%INSTALLER_FILE%" (
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe', '%INSTALLER_FILE%')"
)

if not exist "%INSTALLER_FILE%" (
    echo [LOI] Khong the tai bo cai Python tu dong. Vui long tai thu cong Python 3.11.9 64-bit tu:
    echo https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
    pause
    exit /b 1
)

echo [OK] Da tai xong. Dang tien hanh cai dat vao he thong...
start /wait "" "%INSTALLER_FILE%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 SimpleInstall=1
del "%INSTALLER_FILE%" 2>nul

if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :PYTHON_READY
)
if exist "%ProgramFiles%\Python311\python.exe" (
    set "PY_EXE=%ProgramFiles%\Python311\python.exe"
    goto :PYTHON_READY
)
for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do (
    set "PY_EXE=%%P"
    goto :PYTHON_READY
)

echo [LOI] Khong tim thay Python 3.11 sau khi cai dat. Vui long khoi dong lai may va chay lai setup.bat.
pause
exit /b 1

:PYTHON_READY
echo [OK] Chinh xac dang su dung: "%PY_EXE%"
"%PY_EXE%" --version
echo.

REM 4. Kiem tra va tao moi truong ao .venv
if exist ".venv\Scripts\python.exe" (
    echo [OK] Moi truong .venv da co san.
) else (
    echo [1/4] Dang tao moi truong ao .venv voi Python 3.11...
    "%PY_EXE%" -m venv ".venv"
    if errorlevel 1 (
        echo [LOI] Tao moi truong ao .venv that bai!
        pause
        exit /b 1
    )
    echo [OK] Tao moi truong .venv thanh cong.
)
echo.

echo [2/4] Kiem tra va nang cap pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
echo.

echo [3/4] Dang quet card do hoa va cai dat PyTorch CUDA...
where nvidia-smi.exe >nul 2>&1
if not errorlevel 1 (
    echo [OK] Phat hien card do hoa NVIDIA GPU!
    echo Dang cai dat PyTorch CUDA 12.4 cho GPU...
    ".venv\Scripts\python.exe" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
) else (
    echo [THONG BAO] Khong co NVIDIA GPU. Dang cai dat PyTorch CPU...
    ".venv\Scripts\python.exe" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
)
echo.

echo [4/4] Dang cai dat va cap nhat cac thu vien (yt-dlp, whisper, pyside6)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt --upgrade
if errorlevel 1 (
    echo [CANH BAO] Co loi khi cai dat thu vien. Vui long kiem tra mang va thu lai!
    pause
    exit /b 1
)
echo.

echo ================================================================
echo KIEM TRA TINH TRANG HE THONG:
".venv\Scripts\python.exe" -c "import sys; print('• Python:', sys.version); import yt_dlp; print('• yt-dlp version:', yt_dlp.version.__version__); import torch; print('• PyTorch Version:', torch.__version__); print('• CUDA Available:', torch.cuda.is_available()); print('• GPU Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'Khong co GPU')"
echo ================================================================
echo THIET LAP HOAN TAT! HE THONG DA SAN SANG 100%%.
echo Tu nay ban chi can nhap dup vao [ ChayTool.bat ] de mo app.
echo ================================================================
pause
exit /b 0
