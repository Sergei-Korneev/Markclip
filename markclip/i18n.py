# coding=utf-8
"""Локализация интерфейса.

Ключ перевода — исходная русская строка (она же текст по умолчанию),
значение — перевод. Русский язык базовый, файл для него не нужен.

Файлы языков лежат в папке ``locales/`` рядом с программой
(``en.json``, ``zh.json`` и т. д.). Добавить язык: скопировать любой
файл, перевести значения и положить ``<код>.json`` — язык сам появится
в списке настроек.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Dict, List

from .config import app_dir

log = logging.getLogger(__name__)

__all__ = [
    "available_languages",
    "current_language",
    "language_name",
    "set_language",
    "tr",
]

#: Человекочитаемые названия известных языков (для списка в настройках).
_LANGUAGE_NAMES = {"ru": "Русский", "en": "English", "zh": "中文"}

_current = "ru"
_table: Dict[str, str] = {}


def _locales_dirs() -> List[Path]:
    """Где искать файлы языков: папка рядом с программой, затем бандл exe."""
    dirs = [app_dir() / "locales"]
    bundle = getattr(sys, "_MEIPASS", None)  # PyInstaller (onefile)
    if bundle:
        dirs.append(Path(bundle) / "locales")
    return dirs


def available_languages() -> List[str]:
    """Коды доступных языков: всегда ``ru`` + файлы из папки locales."""
    codes = {"ru"}
    for directory in _locales_dirs():
        try:
            for path in directory.glob("*.json"):
                codes.add(path.stem.lower())
        except OSError:  # нет папки — просто нечего перечислять
            pass
    return sorted(codes)


def language_name(code: str) -> str:
    """Название языка для списка в настройках («Русский», «English», …)."""
    return _LANGUAGE_NAMES.get(code, code)


def set_language(code: str) -> str:
    """Переключить язык интерфейса.

    Возвращает фактически применённый код: если файла языка нет или он
    битый — остаёмся/возвращаемся на русский и пишем предупреждение
    в журнал.
    """
    global _current, _table
    code = str(code or "").strip().lower() or "ru"
    if code == "ru":
        _current, _table = "ru", {}
        return code
    for directory in _locales_dirs():
        path = directory / "{}.json".format(code)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            log.warning("Язык %s: ожидаются пары ключ-значение", path)
            continue
        _current = code
        _table = {str(key): str(value) for key, value in data.items()}
        log.info("Язык интерфейса: %s (%s)", language_name(code), code)
        return code
    log.warning("Язык %r не найден в locales/ — русский", code)
    _current, _table = "ru", {}
    return "ru"


def current_language() -> str:
    """Текущий код языка."""
    return _current


def tr(text: str) -> str:
    """Перевести строку интерфейса; без перевода — исходный текст."""
    if not _table:
        return text
    return _table.get(text, text)
