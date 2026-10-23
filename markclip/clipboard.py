# coding=utf-8
"""Чтение картинки из системного буфера обмена.

На **Linux/X11** картинку читает подпроцесс ``xclip -t image/png`` сам,
а не через ``PIL.ImageGrab.grabclipboard()``: PIL тоже запускает xclip,
но ждёт его синхронно — если буфера владеет наше же Tk-окно (пользователь
скопировал текст внутри приложения), Tk отдаёт содержимое буфера только
из цикла событий, который в этот момент заблокирован ожиданием xclip.
Получается вечный дедлок. Поэтому здесь xclip ждёт в фоне, а главный поток
пока прокручивает события Tk (параметр ``pump``) — и буфер обслуживается.

На **Windows/macOS** (и как запасной путь без xclip) работает штатное
``PIL.ImageGrab.grabclipboard()`` — там чтение буфера не зависит от
циклов событий Tk.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable, Optional, Tuple

log = logging.getLogger(__name__)

__all__ = ["get_clipboard_image"]

#: Режимы PIL, которые PNG принимает без преобразования.
_PNG_MODES = ("1", "L", "LA", "P", "RGB", "RGBA", "I;16")

#: Сколько ждать xclip, пока он читает буфер (секунды).
_X11_TIMEOUT = 2.0


def get_clipboard_image(
    pump: Optional[Callable[[], None]] = None,
) -> Optional[Tuple[bytes, str]]:
    """Картинка из буфера обмена как ``(байты PNG, "png")`` либо ``None``.

    ``None`` означает «картинки нет» (в буфере текст, файлы или пусто) —
    вызывающая сторона в таком случае делает вставку текста.

    :param pump: функция обслуживания событий (например ``root.update``);
        вызывается, пока подпроцесс читает буфер на X11. Нужна, чтобы Tk
        успевал отвечать на запросы буфера, в том числе своему xclip.
    """
    if _is_x11() and shutil.which("xclip") is not None:
        raw = _grab_png_x11(pump)
        if raw is not None and _looks_like_png(raw):
            return raw, "png"
        # xclip отработал (или истёк таймаут) — за PIL не идём: его путь
        # на X11 ведёт к тому же subprocess и тому же дедлоку
        return None
    return _grab_png_pil()


def _is_x11() -> bool:
    """Мы на Linux с X11-дисплеем (не headless и не чистый Wayland)."""
    return sys.platform.startswith("linux") and bool(os.environ.get("DISPLAY"))


def _grab_png_x11(pump: Optional[Callable[[], None]]) -> Optional[bytes]:
    """Байты PNG из CLIPBOARD через xclip; ``None`` — картинки нет/нет xclip.

    Если картинки нет или буфер занят текстом, xclip завершается с ошибкой —
    это нормальный «нет картинки», не сбой.
    """
    if shutil.which("xclip") is None:
        return None
    try:
        proc = subprocess.Popen(  # noqa: S603 — фиксированные аргументы
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        log.debug("Не удалось запустить xclip", exc_info=True)
        return None

    # читать stdout нужно параллельно: большие картинки не поместятся
    # в буфер канала, и xclip заблокируется на записи
    chunks: list = []

    def _drain() -> None:
        try:
            chunks.append(proc.stdout.read())
        except OSError:
            chunks.append(b"")

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()

    deadline = time.monotonic() + _X11_TIMEOUT
    while proc.poll() is None and time.monotonic() < deadline:
        if pump is not None:
            try:
                pump()
            except Exception:  # noqa: BLE001 — прокрутка не должна ронять вставку
                log.debug("Прокрутка событий при чтении буфера упала", exc_info=True)
        time.sleep(0.01)
    if proc.poll() is None:
        proc.kill()  # буфер не отвечает — не вешаем приложение
        proc.wait()
        log.debug("xclip не уложился в %.1f c, буфер пропущен", _X11_TIMEOUT)
        return None
    reader.join(timeout=0.5)
    if proc.returncode != 0:
        return None  # «не image/png» — обычное отсутствие картинки
    return chunks[0] if chunks else b""


def _grab_png_pil() -> Optional[Tuple[bytes, str]]:
    """Запасной путь (Windows/macOS/без xclip): PIL, как раньше."""
    try:
        from PIL import Image, ImageGrab
    except ImportError:
        return None
    try:
        data = ImageGrab.grabclipboard()
    except Exception:  # noqa: BLE001 — буфер может быть вовсе недоступен
        log.debug("Не удалось прочитать буфер обмена", exc_info=True)
        return None
    if data is None or isinstance(data, list):
        # None — пусто/текст; список — скопированные файлы, их не вставляем
        return None
    if not isinstance(data, Image.Image):
        return None
    if data.mode not in _PNG_MODES:
        try:
            data = data.convert("RGBA")
        except Exception:  # noqa: BLE001
            log.debug("Не удалось преобразовать картинку режима %s", data.mode)
            return None
    buffer = io.BytesIO()
    try:
        data.save(buffer, format="PNG")
    except Exception:  # noqa: BLE001
        log.debug("Не удалось закодировать картинку из буфера", exc_info=True)
        return None
    return buffer.getvalue(), "png"


def _looks_like_png(data: bytes) -> bool:
    """Минимальная проверка, что байты — валидная картинка PNG."""
    if not data:
        return False
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:  # noqa: BLE001
        return False
    return True
