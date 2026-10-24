#!/usr/bin/env bash
# Install Markclip into a virtual environment (Linux).
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
    echo "python3 not found. Install Python 3.10 or newer." >&2
    exit 1
fi

if [ ! -d .venv ]; then
    # --system-site-packages: if PyGObject (the python3-gi package) is
    # available system-wide, pystray gets the full tray menu (the
    # appindicator backend) instead of the reduced xorg one.
    "$PY" -m venv --system-site-packages .venv
fi

.venv/bin/python -m pip install --quiet --upgrade pip

if ! .venv/bin/python -m pip install --quiet -r requirements.txt; then
    # On Linux pynput pulls in evdev, which needs kernel headers.
    # Global hotkeys do not need evdev (the X11/RECORD backend is used),
    # so install pynput without dependencies.
    echo
    echo "Full installation failed (most likely evdev without kernel headers)."
    echo "Installing dependencies one by one, pynput without dependencies..."
    .venv/bin/python -m pip install --quiet Pillow pystray six python-xlib tkinterdnd2
    .venv/bin/python -m pip install --quiet --no-deps pynput
fi

echo
echo "Checking dependencies:"
.venv/bin/python - <<'EOF'
import tkinter  # noqa: F401
import PIL  # noqa: F401
import pynput.keyboard  # noqa: F401
import pystray

backend = pystray.Icon.__module__
print("  tkinter, Pillow, pynput — ok")
try:
    import tkinterdnd2  # noqa: F401
except ImportError:
    print("  tkinterdnd2 NOT installed — drag and drop is disabled")
else:
    print("  tkinterdnd2 (drag and drop) — ok")
print("  tray backend:", backend)
if backend == "pystray._xorg":
    print()
    print("  WARNING: the tray menu is unavailable (PyGObject is not installed).")
    print("  For the full menu with settings:")
    print("    Fedora:  sudo dnf install python3-gi python3-gobject-gtk gir1.2-gtk-3.0 \\")
    print("                    gnome-shell-extension-appindicator")
    print("    Debian:  sudo apt install python3-gi gir1.2-gtk-3.0 \\")
    print("                    gir1.2-ayatanaappindicator3-0.1")
    print("  Meanwhile settings can be opened with: ./run.sh --settings")
EOF

echo
echo "Done. Run: ./run.sh"
