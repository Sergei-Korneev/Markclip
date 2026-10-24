# coding=utf-8
"""Запись заметок в Markdown-файлы и открытие папки заметок."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from .i18n import tr

log = logging.getLogger(__name__)

__all__ = [
    "IMAGES_SUBDIR",
    "save_note",
    "save_note_file",
    "save_note_image",
    "sanitize_file_name",
    "normalize_subdir",
    "open_folder",
]

PathLike = Union[str, "Path"]

#: Подпапка с картинками внутри папки заметок.
IMAGES_SUBDIR = "assets"

#: Символы, запрещённые в именах файлов на Windows (на Linux/macOS — лишнее).
_FORBIDDEN_NAME_CHARS = '<>:"/\\|?*'

#: Имена, зарезервированные Windows (к ним нельзя обращаться как к файлу).
_RESERVED_STEMS = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM{}".format(i) for i in range(1, 10)]
    + ["LPT{}".format(i) for i in range(1, 10)]
)


def save_note(text: str, notes_dir: PathLike) -> Optional[Path]:
    """Добавить текст в дневной Markdown-файл.

    Файл создаётся как ``ГГГГ-ММ-ДД.md`` в папке ``notes_dir``
    (создаётся при необходимости). Каждая заметка — заголовок второго
    уровня с временем и текст после него.

    Возвращает путь к файлу или ``None``, если текст пуст.
    """
    content = (text or "").strip()
    if not content:
        return None

    directory = Path(notes_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    path = directory / (now.strftime("%Y-%m-%d") + ".md")
    if not path.exists():
        # заголовок дневного файла — на текущем языке интерфейса
        header = tr("Заметки за {}").format(now.strftime("%Y-%m-%d"))
        path.write_text("# {}\n\n".format(header), encoding="utf-8")
    block = "## {stamp}\n\n{text}\n\n".format(
        stamp=now.strftime("%H:%M:%S"),
        text=content,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(block)
    log.debug("Заметка записана в %s", path)
    return path


def sanitize_file_name(name: str) -> str:
    """Подчистить имя файла для любой ОС (Linux, Windows, macOS).

    Убирает запрещённые символы (``<>:"/\\|?*`` и управляющие), краевые
    точки и пробелы, ограничивает длину. Пустая строка означает
    «подходящего имени нет».
    """
    cleaned = "".join(
        "_" if char in _FORBIDDEN_NAME_CHARS or ord(char) < 32 else char
        for char in (name or "")
    )
    return cleaned.strip().strip(". ")[:100]


def save_note_file(
    notes_dir: PathLike,
    text: str,
    title: str = "",
    name: str = "",
) -> Optional[Path]:
    """Сохранить заметку отдельным файлом с заданными заголовком и именем.

    Файл — ``<notes_dir>/<имя>.md``, заголовок (если есть) идёт первой
    строкой как ``# ...``. Имя берётся из ``name``, иначе из ``title``,
    иначе — метка времени.

    Если заданное имя совпадает с уже существующим файлом, текст
    **дописывается в конец** этого файла — так из окна заметки можно
    продолжить существующую заметку (заголовок при этом не повторяется).
    Имя, выведенное из заголовка/времени, чужой файл не трогает —
    добавляется суффикс (``_2``, ``_3``…), перезаписи нет.

    Возвращает путь к файлу или ``None``, если нет ни текста, ни заголовка.
    """
    content = (text or "").strip()
    clean_title = (title or "").strip()
    if not content and not clean_title:
        return None

    explicit_name = bool(sanitize_file_name(name))
    stem = sanitize_file_name(name) or sanitize_file_name(clean_title)
    if not stem:
        stem = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    if stem.lower().endswith(".md"):
        stem = stem[:-3].strip(". ")
        if not stem:  # пользователь ввёл просто «.md»
            stem = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    if stem.split(".")[0].upper() in _RESERVED_STEMS:
        stem = "_" + stem  # Windows не даёт файлы вида CON.md, AUX.md…

    directory = Path(notes_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (stem + ".md")

    if path.exists() and explicit_name:
        # явное имя совпало с существующим файлом — дописываем текст в конец
        if content:
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n" + content + "\n")
        log.debug("Текст дописан в существующий файл %s", path)
        return path

    counter = 2
    while path.exists():
        path = directory / "{}_{}.md".format(stem, counter)
        counter += 1

    parts = []
    if clean_title:
        parts.append("# {}".format(clean_title))
    if content:
        parts.append(content)
    path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    log.debug("Именованная заметка записана в %s", path)
    return path


def normalize_subdir(subdir: str) -> str:
    """Имя подпапки вложений: одно имя каталога, без путей; пусто → assets.

    Запрещённые символы вычищаются, ``.``/``..`` и пустота приводятся
    к значению по умолчанию ``assets``.
    """
    cleaned = sanitize_file_name(subdir or "")
    return cleaned or IMAGES_SUBDIR


def save_note_image(
    notes_dir: PathLike, name: str, data: bytes, subdir: str = ""
) -> str:
    """Сохранить картинку в ``<notes_dir>/<subdir>`` и вернуть относительный путь.

    ``subdir`` — имя подпапки вложений (пусто или мусор → ``assets``,
    см. :func:`normalize_subdir`). Относительный путь вида
    ``assets/2026-10-23_140512.png`` вставляется в Markdown-ссылку
    ``![...](assets/...)`` и продолжает работать, когда папку с заметками
    переносят куда угодно.

    Если файл с таким именем уже есть, добавляется суффикс (``_2``, ``_3``…),
    чужие файлы не перезаписываются; возвращается фактический путь.
    """
    clean_subdir = normalize_subdir(subdir)
    directory = Path(notes_dir).expanduser() / clean_subdir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    counter = 2
    while path.exists():
        path = directory / "{}_{}{}".format(
            Path(name).stem, counter, Path(name).suffix
        )
        counter += 1
    path.write_bytes(data)
    log.debug("Картинка сохранена: %s", path)
    return "{}/{}".format(clean_subdir, path.name)


def open_folder(path: PathLike) -> bool:
    """Открыть папку в файловом менеджере. True — команда отдана ОС."""
    directory = Path(path).expanduser()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(str(directory))  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(directory)])
        else:
            subprocess.Popen(
                ["xdg-open", str(directory)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except OSError:
        log.exception("Не удалось открыть %s", directory)
        return False
    return True
