# coding=utf-8
"""Хранение настроек приложения.

Портативный режим: config.json и журнал markclip.log лежат **в самой папке
приложения**, поэтому её можно просто переносить (в т.ч. на флешке).
Для тестов и нестандартных развёртываний папку можно переопределить
переменной окружения ``MARKCLIP_HOME``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: Хоткей по умолчанию (формат pynput: имя клавиши в угловых скобках).
DEFAULT_HOTKEY = "<ctrl>+<alt>+<space>"

__all__ = [
    "DEFAULT_HOTKEY",
    "Config",
    "app_dir",
    "config_dir",
    "default_notes_dir",
]


def app_dir() -> Path:
    """Папка самого приложения.

    * собранный exe (PyInstaller) — каталог рядом с ``Markclip.exe``;
    * запуск из исходников — корень проекта (там, где лежит ``run.py``).
    """
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(sys.executable).resolve().parent
    # markclip/config.py → корень проекта
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    """Каталог для config.json и журнала markclip.log.

    По умолчанию — сама папка приложения (портативность).
    Переопределяется переменной окружения ``MARKCLIP_HOME``
    (используется тестами и для запуска с настройками в отдельном месте).
    """
    override = os.environ.get("MARKCLIP_HOME")
    if override:
        return Path(override).expanduser()
    return app_dir()


def default_notes_dir() -> Path:
    """Папка для заметок по умолчанию — внутри папки приложения.

    В настройках её можно указать любую другую.
    """
    return app_dir() / "notes"


@dataclass
class Config:
    """Настройки приложения.

    :param notes_dir: папка, куда пишутся Markdown-заметки
    :param hotkey:    глобальная комбинация клавиш в формате pynput
    :param title_template: шаблон заголовка новой заметки
        (подстановки `{date}`, `{time}`, `{datetime}`; пусто — не подставлять)
    :param name_template:  шаблон имени файла новой заметки (те же подстановки)
    :param text_template: шаблон тела заметки — оборачивает введённый текст
        при сохранении (подстановки `{text}`, `{text:90}`, `{url1}`, `{date}`
        и т. д.; пусто — текст без изменений, время в тело не добавляется)
    :param assets_dir: путь подпапки для вложений внутри папки заметок;
        поддерживается подстановка ``{$notename}`` (имя заметки), например
        ``assets/{$notename}`` — вложения в подпапке с именем заметки;
        пусто — ``assets``
    :param link_style: стиль Markdown-ссылок на вложения — ``plain``
        (обычные, имя файла очищено от скобок) или ``angle``
        (``[текст](<путь>)``, допустимы пробелы и скобки в имени файла)
    :param language: код языка интерфейса (``ru``/``en``/``zh``/…;
        файлы языков лежат в папке ``locales``)
    """

    notes_dir: str = ""
    hotkey: str = DEFAULT_HOTKEY
    title_template: str = ""
    name_template: str = ""
    text_template: str = ""
    assets_dir: str = ""
    link_style: str = "plain"
    language: str = "ru"

    def __post_init__(self) -> None:
        if not str(self.notes_dir).strip():
            self.notes_dir = str(default_notes_dir())
        if not str(self.hotkey).strip():
            self.hotkey = DEFAULT_HOTKEY
        if not str(self.language).strip():
            self.language = "ru"
        if self.link_style not in ("plain", "angle"):
            self.link_style = "plain"

    @property
    def notes_path(self) -> Path:
        """Папка заметок с поддержкой «~»."""
        return Path(self.notes_dir).expanduser()

    @classmethod
    def load(cls) -> "Config":
        """Прочитать config.json; при любой ошибке — настройки по умолчанию."""
        path = config_dir() / "config.json"
        data = {}
        try:
            if path.is_file():
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
                else:
                    log.warning("config.json не объект — беру настройки по умолчанию")
        except ValueError:
            log.warning(
                "config.json повреждён (%s) — беру настройки по умолчанию", path
            )
        except OSError:
            log.warning(
                "Не удалось прочитать %s — беру настройки по умолчанию",
                path,
                exc_info=True,
            )

        known = {
            key: value
            for key, value in data.items()
            if key
            in (
                "notes_dir",
                "hotkey",
                "title_template",
                "name_template",
                "text_template",
                "assets_dir",
                "link_style",
                "language",
            )
            and isinstance(value, str)
        }
        return cls(**known)

    def save(self) -> Path:
        """Атомарно записать настройки. Бросает OSError при проблемах с диском."""
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "config.json"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        log.debug("Настройки сохранены: %s", path)
        return path
