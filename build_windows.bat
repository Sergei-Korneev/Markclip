@echo off
REM Build a portable Markclip.exe (Windows).
REM Requires a prepared environment: install.bat
REM and the pyinstaller package:  .venv\Scripts\pip install pyinstaller
cd /d "%~dp0"

if not exist .venv\Scripts\pyinstaller.exe (
    echo PyInstaller not found. Run:
    echo     .venv\Scripts\pip install pyinstaller
    exit /b 1
)

REM --collect-submodules: pynput and pystray load platform backends
REM dynamically; static analysis does not always find them.
REM --collect-all: tkinterdnd2 bundles the tkdnd extension binaries used
REM for drag and drop of files into the note window.
REM --add-data: the interface language files (locales\*.json) go into the exe;
REM a locales\ folder next to the exe takes priority, so translations can be
REM edited without rebuilding.
.venv\Scripts\pyinstaller.exe --noconfirm --windowed --onefile ^
    --name Markclip ^
    --collect-submodules pynput ^
    --collect-submodules pystray ^
    --collect-all tkinterdnd2 ^
    --add-data "locales;locales" ^
    run.py

if errorlevel 1 (
    echo Build failed. See the output above.
    exit /b 1
)

echo.
echo Done: dist\Markclip.exe
echo Portability: config.json, markclip.log and the notes\ folder are created next to the exe
