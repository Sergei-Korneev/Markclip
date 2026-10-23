#!/usr/bin/env python3
# coding=utf-8
"""Точка входа Markclip: python run.py"""

import sys
from pathlib import Path

# Позволяет запускать из любого места: python /путь/к/run.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

from markclip.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
