@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Auto Video Renderer - Setup & Auto Installer
cd /d "%~dp0"

echo ================================================================
echo        🚀 AUTO VIDEO RENDERER - THIET LAP MOI TRUONG
echo ================================================================
echo.

REM 0. Kiem tra va don dep .venv cu neu tao boi Python >= 3.13 (nhu Python 3.14)
if exist ".venv\Scripts\python.exe" (
    set "VENV_STATUS=VALID"
    for /f "tokens=*" %%C in ('".venv\Scripts\python.exe" -c "import sys; print('INVALID' if sys.version_info >= (3, 13) or sys.version_info < (3, 10) else 'VALID')" 2^>nul') do set "VENV_STATUS=%%C"
    
    if "!VENV_STATUS!"=="INVALID" (
        for /f "tokens=*" %%V in ('".venv\Scripts\python.exe" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2^>nul') do set "BAD_VER=%%V"
        echo [CANH BAO] Phat hien moi truong .venv cu dang dung Python !BAD_VER!
        echo (Luu y: PyTorch CUDA hien chi ho tro tot nhat tren Python 3.10, 3.11, 3.12).
        echo Dang tien hanh xoa sach thu muc .venv cu de thiet lap lai tu Python chuan...
        rmdir /s /q ".venv"
        echo [OK] Da xoa .venv cu thanh cong.
        echo.
    )
)

set "PY_EXE="

REM 1. Thu tim thong qua Python Launcher (py.exe) voi phien ban 3.11, 3.12, 3.10
for %%V in (3.11 3.12 3.10) do (
    if not defined PY_EXE (
        py -%%V -c "import sys; exit(0 if sys.version_info.major == 3 and sys.version_info.minor in (10, 11, 12) else 1)" >nul 2>&1
        if not errorlevel 1 (
            for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do (
                if exist "%%P" (
                    set "PY_EXE=%%P"
                )
            )
        )
    )
)

REM 2. Quet truc tiep cac thu muc cai dat Python 3.11, 3.12, 3.10 tren Windows
if not defined PY_EXE (
    set "SEARCH_PATHS="
    set "SEARCH_PATHS=!SEARCH_PATHS!;%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    set "SEARCH_PATHS=!SEARCH_PATHS!;%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    set "SEARCH_PATHS=!SEARCH_PATHS!;%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    set "SEARCH_PATHS=!SEARCH_PATHS!;%ProgramFiles%\Python311\python.exe"
    set "SEARCH_PATHS=!SEARCH_PATHS!;%ProgramFiles%\Python312\python.exe"
    set "SEARCH_PATHS=!SEARCH_PATHS!;%ProgramFiles%\Python310\python.exe"
    set "SEARCH_PATHS=!SEARCH_PATHS!;C:\Python311\python.exe"
    set "SEARCH_PATHS=!SEARCH_PATHS!;C:\Python312\python.exe"
    set "SEARCH_PATHS=!SEARCH_PATHS!;C:\Python310\python.exe"

    for %%P in (!SEARCH_PATHS!) do (
        if not defined PY_EXE (
            if exist "%%P" (
                "%%P" -c "import sys; exit(0 if sys.version_info.major == 3 and sys.version_info.minor in (10, 11, 12) else 1)" >nul 2>&1
                if not errorlevel 1 (
                    set "PY_EXE=%%P"
                )
            )
        )
    )
)

REM 3. Kiem tra python.exe mac dinh trong PATH co thuoc 3.10 -> 3.12 hay khong
if not defined PY_EXE (
    for /f "delims=" %%P in ('where python.exe 2^>nul') do (
        echo "%%P" | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            if not defined PY_EXE (
                "%%P" -c "import sys; exit(0 if sys.version_info.major == 3 and sys.version_info.minor in (10, 11, 12) else 1)" >nul 2>&1
                if not errorlevel 1 (
                    set "PY_EXE=%%P"
                )
            )
        )
    )
)

REM 4. Neu van chua co -> Tu dong tai va cai dat Python 3.11.9 (64-bit Chuan AI)
if not defined PY_EXE (
    echo [THONG BAO] Khong tim thay Python 3.10, 3.11 hoac 3.12 phu hop.
    echo (Cac ban Python 3.13+ nhu Python 3.14 chua duoc NVIDIA / PyTorch CUDA ho tro).
    echo.
    echo Dang tien hanh tu dong tai va cai dat Python 3.11.9 (64-bit) tu python.org...
    echo (Qua trinh cai dat hoan toan tu dong, vui long doi trong 1-2 phut)...
    echo.

    set "INSTALLER_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    set "INSTALLER_FILE=%TEMP%\python-3.11.9-amd64.exe"

    where curl.exe >nul 2>&1
    if not errorlevel 1 (
        curl.exe -L -o "!INSTALLER_FILE!" "!INSTALLER_URL!"
    ) else (
        powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('!INSTALLER_URL!', '!INSTALLER_FILE!')"
    )

    if not exist "!INSTALLER_FILE!" (
        echo [LOI] Khong the tai bo cai Python tu dong. Vui long kiem tra ket noi mang hoac tai thu cong Python 3.11!
        pause
        exit /b 1
    )

    echo [OK] Da tai xong bo cai. Dang tu dong cai dat vao he thong...
    start /wait "" "!INSTALLER_FILE!" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 SimpleInstall=1
    del "!INSTALLER_FILE!" 2>nul

    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    ) else if exist "%ProgramFiles%\Python311\python.exe" (
        set "PY_EXE=%ProgramFiles%\Python311\python.exe"
    ) else if exist "C:\Python311\python.exe" (
        set "PY_EXE=C:\Python311\python.exe"
    ) else (
        for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do set "PY_EXE=%%P"
    )
)

if not defined PY_EXE (
    echo [LOI] Khong the khoi tao Python tuong thich.
    echo Vui long tai va cai dat thu cong Python 3.11 (64-bit) tu: https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
    echo (Luu y tich vao o 'Add python.exe to PATH' khi cai dat).
    pause
    exit /b 1
)

:PYTHON_FOUND
echo [OK] Phat hien Python tuong thich AI: "!PY_EXE!"
"!PY_EXE!" --version

echo.
echo [1/4] Dang tao moi truong ao (.venv)...
if not exist ".venv\Scripts\python.exe" (
    "!PY_EXE!" -m venv ".venv"
    if errorlevel 1 (
        echo [LOI] Tao moi truong ao .venv that bai!
        pause
        exit /b 1
    )
)
echo [OK] Moi truong .venv da san sang.

echo.
echo [2/4] Kiem tra va nang cap pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1

echo.
echo [3/4] Dang quet card do hoa va cai dat PyTorch CUDA...
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
echo [4/4] Dang cai dat tat ca thu vien con lai tu requirements.txt...
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
