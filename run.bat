@echo off
REM Run Markclip (Windows) without a console window.
cd /d "%~dp0"

if not exist .venv\Scripts\pythonw.exe (
    echo Virtual environment not found. Run install.bat first.
    exit /b 1
)

start "" .venv\Scripts\pythonw.exe run.py %*
