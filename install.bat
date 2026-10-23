@echo off
REM Install Markclip into a virtual environment (Windows).
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python 3.10 or newer from https://python.org
    echo and tick "Add python.exe to PATH".
    exit /b 1
)

if not exist .venv (
    python -m venv .venv
)

.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies. See the output above.
    exit /b 1
)

echo.
echo Checking dependencies...
.venv\Scripts\python.exe -c "import tkinter, PIL, pynput.keyboard, pystray; print('  tkinter, Pillow, pynput, pystray - ok'); print('  tray backend:', pystray.Icon.__module__)"
if errorlevel 1 (
    echo Dependencies are incomplete. Run install.bat again.
    exit /b 1
)

echo.
echo Done. Run: run.bat
