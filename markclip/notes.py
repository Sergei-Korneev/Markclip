# coding=utf-8
"""Запись заметок в Markdown-файлы и открытие папки заметок."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from .i18n import tr

log = logging.getLogger(__name__)

__all__ = [
    "IMAGES_SUBDIR",
    "LINK_STYLES",
    "NOTE_NAME_PLACEHOLDER",
    "save_note",
    "save_note_file",
    "save_note_image",
    "attach_note_file",
    "attachment_dest",
    "attachment_file_name",
    "escape_link_text",
    "normalize_subdir",
    "render_assets_dir",
    "sanitize_file_name",
    "open_folder",
]

PathLike = Union[str, "Path"]

#: Подпапка с картинками внутри папки заметок.
IMAGES_SUBDIR = "assets"

#: Символы, запрещённые в именах файлов на Windows (на Linux/macOS — лишнее).
_FORBIDDEN_NAME_CHARS = '<>:"/\\|?*'

#: Символы, ломающие Markdown-ссылку или URL: в имени вложения их быть
#: не должно — ``[текст](assets/файл)`` с такими именами не откроется.
_LINK_UNSAFE_CHARS = "[]()#%"


#: Стили ссылок на вложения в настройках: обычные и в угловых скобках
#: (``[текст](<путь>)`` — пробелы и скобки в имени файла не ломают ссылку).
LINK_STYLES = ("plain", "angle")


def escape_link_text(text: str) -> str:
    """Экранировать квадратные скобки в тексте Markdown-ссылки.

    В ``[имя файла](assets/файл)`` имя с ``[``/``]`` разрывает ссылку;
    обратный слэш перед скобкой решает это во всех парсерах.
    """
    return (text or "").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def attachment_dest(path: str, link_style: str = "plain") -> str:
    """Пункт назначения Markdown-ссылки на вложение.

    ``plain`` — путь как есть (имя файла очищено от спецсимволов),
    ``angle`` — путь в угловых скобках, тогда пробелы и скобки в имени
    файла допустимы: ``[текст](<assets/мой файл (1).pdf>)``.
    """
    if link_style == "angle":
        return "<{}>".format(path)
    return path


def _safe_attachment_stem(name: str, link_style: str = "plain") -> str:
    """Имя вложения без символов, ломающих ссылки и файловую систему.

    В обычном стиле скобки ``()[]``, решётка и процент заменяются на
    подчёркивания; в стиле с угловыми скобками они допустимы и остаются,
    убираются только ломающие URL ``#``/``%``. Пробелы сохраняются всегда,
    дубли подчёркиваний схлопываются.
    """
    cleaned = sanitize_file_name(name or "")
    unsafe = "#%" if link_style == "angle" else _LINK_UNSAFE_CHARS
    for char in unsafe:
        cleaned = cleaned.replace(char, "_")
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip(". ")
    if not cleaned:
        return datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return _escape_reserved_name(cleaned)

#: Имена, зарезервированные Windows (к ним нельзя обращаться как к файлу).
_RESERVED_STEMS = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM{}".format(i) for i in range(1, 10)]
    + ["LPT{}".format(i) for i in range(1, 10)]
)


def _escape_reserved_name(stem: str) -> str:
    """Обойти зарезервированные имена Windows (``prn``, ``con``, ``aux``…).

    На Windows такой файл создать нельзя — имя получает префикс ``_``
    (``prn`` → ``_prn``). На Linux и macOS имена не трогаются: ``prn``
    остаётся ``prn``.
    """
    if sys.platform != "win32":
        return stem
    if stem.split(".")[0].upper() in _RESERVED_STEMS:
        return "_" + stem
    return stem


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
    stem = _escape_reserved_name(stem)  # в Windows нельзя файлы CON.md, PRN.md…

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


#: Подстановка в пути папки вложений: имя заметки (файл .md без расширения).
#: Пример: ``assets/{$notename}`` — вложения в подпапке с именем заметки.
NOTE_NAME_PLACEHOLDER = "{$notename}"


def normalize_subdir(subdir: str) -> str:
    """Путь подпапки вложений: сегменты через «/»; пусто → ``assets``.

    Запрещённые символы в сегментах вычищаются, пустые сегменты и ``.``/``..``
    отбрасываются. Подстановка :data:`NOTE_NAME_PLACEHOLDER` сохраняется
    как есть — её рендерит :func:`render_assets_dir`.
    """
    segments = []
    for part in (subdir or "").replace("\\", "/").split("/"):
        if part == NOTE_NAME_PLACEHOLDER:
            segments.append(part)  # подстановка имени заметки — не трогаем
            continue
        cleaned = sanitize_file_name(part).strip(". ")
        if cleaned:
            segments.append(cleaned)
    return "/".join(segments) or IMAGES_SUBDIR


def render_assets_dir(assets_dir: str, note_name: str = "") -> str:
    """Путь папки вложений с подстановкой имени заметки.

    ``assets/{$notename}`` + «Моя заметка» → ``assets/Моя заметка``.
    Имя заметки вычищается вместе с сегментами; если имя неизвестно,
    подстановка даёт пустой сегмент (``assets/{$notename}`` → ``assets``).
    """
    clean_name = sanitize_file_name(note_name or "").strip(". ")
    rendered = (assets_dir or "").replace(NOTE_NAME_PLACEHOLDER, clean_name)
    return normalize_subdir(rendered)


def attachment_file_name(source: PathLike, link_style: str = "plain") -> str:
    """Имя файла вложения (с расширением) — каким оно станет в папке.

    Источник: :func:`_safe_attachment_stem` + расширение в нижнем регистре.
    """
    src = Path(source)
    return _safe_attachment_stem(src.stem, link_style) + src.suffix.lower()


def attach_note_file(
    notes_dir: PathLike,
    source: PathLike,
    subdir: str = "",
    link_style: str = "plain",
) -> Optional[str]:
    """Скопировать файл в ``<notes_dir>/<subdir>`` как вложение заметки.

    Имя файла сохраняется, но очищается от символов, ломающих ссылки
    (в обычном стиле — скобки и решётка; в стиле ``angle`` — только
    ломающие URL ``#``/``%``, см. :func:`attachment_dest`). При совпадении
    добавляется суффикс (``_2``, ``_3``…) — чужие файлы не перезаписываются.
    Возвращает относительный путь вида ``assets/договор.pdf`` для
    Markdown-ссылки или ``None``, если файла нет.
    """
    src = Path(source).expanduser()
    if not src.is_file():
        return None

    clean_subdir = normalize_subdir(subdir)
    directory = Path(notes_dir).expanduser() / clean_subdir
    directory.mkdir(parents=True, exist_ok=True)

    stem = _safe_attachment_stem(src.stem, link_style)
    suffix = src.suffix.lower()

    target = directory / (stem + suffix)
    counter = 2
    while target.exists():
        target = directory / "{}_{}{}".format(stem, counter, suffix)
        counter += 1

    shutil.copy2(src, target)
    log.debug("Вложение сохранено: %s → %s", src, target)
    return "{}/{}".format(clean_subdir, target.name)


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
