@echo off
rem One-time setup for the book-indexing tool on a Windows machine with an NVIDIA GPU.
rem Creates .venv here, installs the CUDA build of torch that matches the driver, then the
rem pinned packages. Safe to run again: it reuses .venv and reinstalls only what changed.
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo == checking the NVIDIA driver
where nvidia-smi >nul 2>nul
if errorlevel 1 (
    echo No nvidia-smi found. Install the latest NVIDIA driver, then run this again.
    exit /b 1
)
set DRIVER_MAJOR=0
for /f "tokens=1 delims=." %%a in ('nvidia-smi --query-gpu^=driver_version --format^=csv^,noheader') do set DRIVER_MAJOR=%%a
echo    driver major version: %DRIVER_MAJOR%
rem RTX 50-series needs CUDA 12.8 or newer. torch 2.13 is built for CUDA 13.0, which needs
rem driver R580+; older drivers get torch 2.11 built for CUDA 12.8 (the newest cu128 build).
if %DRIVER_MAJOR% GEQ 580 (
    set TORCH_INDEX=https://download.pytorch.org/whl/cu130
    set TORCH_PIN=torch==2.13.0+cu130
    set VISION_PIN=torchvision==0.28.0+cu130
) else (
    echo    driver older than R580: using the CUDA 12.8 build. Updating the driver is better.
    set TORCH_INDEX=https://download.pytorch.org/whl/cu128
    set TORCH_PIN=torch==2.11.0+cu128
    set VISION_PIN=torchvision==0.26.0+cu128
)

echo == finding Python 3.12
set PY=
py -3.12 -c "import sys" >nul 2>nul && set PY=py -3.12
if "%PY%"=="" (
    python -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>nul && set PY=python
)
if "%PY%"=="" (
    echo Python 3.12 not found. Install it from python.org ^(tick "Add to PATH"^), then run this again.
    exit /b 1
)

if not exist .venv\Scripts\python.exe (
    echo == creating .venv
    %PY% -m venv .venv || exit /b 1
)
set VPY=.venv\Scripts\python.exe
%VPY% -m pip install --upgrade pip || exit /b 1

echo == installing %TORCH_PIN% from %TORCH_INDEX%
rem Never a plain "pip install torch": that is a CPU-only build and about 100x slower.
%VPY% -m pip install %TORCH_PIN% %VISION_PIN% --index-url %TORCH_INDEX% || exit /b 1
%VPY% -c "import torch, torchvision; print('torch==' + torch.__version__); print('torchvision==' + torchvision.__version__)" > .torch-constraint.txt || exit /b 1

echo == installing the pinned packages
%VPY% -m pip install -r requirements.txt -r requirements-figures.txt -c constraints.txt -c .torch-constraint.txt || exit /b 1

echo == checking
%VPY% -c "import torch; print('torch', torch.__version__, '| CUDA available:', torch.cuda.is_available())" || exit /b 1
echo.
echo Setup done. Next:  .venv\Scripts\python.exe encode_books.py calibrate
endlocal
