# coding=utf-8
"""Глобальный хоткей: нормализация, отображение, слушатель и запись комбинации.

Пользователь в настройках печатает привычным языком (``Ctrl+Alt+Space``),
а внутри приложения комбинация хранится в формате pynput
(``<ctrl>+<alt>+<space>``) — модификаторы и спецклавиши в угловых скобках,
одиночные символы без скобок.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Iterable, Optional

from pynput import keyboard
from pynput.keyboard import HotKey, Key

from .i18n import tr

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_HOTKEY",
    "HotkeyCapture",
    "HotkeyError",
    "HotkeyListener",
    "display",
    "normalize",
    "validate",
]

#: Хоткей по умолчанию.
DEFAULT_HOTKEY = "<ctrl>+<alt>+<space>"

#: Сколько секунд даётся на запись комбинации в настройках.
CAPTURE_TIMEOUT = 20.0

# Имена клавиш, понимаемых pynput в <> — берём прямо из перечисления
# текущей платформы, чтобы список всегда совпадал с HotKey.parse.
try:
    _KNOWN_KEY_NAMES = frozenset(key.name for key in Key)
except Exception:  # pragma: no cover — бэкенд-заглушка
    _KNOWN_KEY_NAMES = frozenset()

#: Порядок вывода модификаторов (для канонического вида).
_MODIFIER_ORDER = ("ctrl", "alt", "cmd", "shift", "alt_gr")
_MODIFIERS = frozenset(_MODIFIER_ORDER)

#: Что пользователь может набирать вместо внутренних имён.
_ALIASES = {
    # модификаторы
    "control": "ctrl",
    "ctl": "ctrl",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "alt_l": "alt",
    "alt_r": "alt",
    "option": "alt",
    "opt": "alt",
    "shift_l": "shift",
    "shift_r": "shift",
    "win": "cmd",
    "windows": "cmd",
    "super": "cmd",
    "meta": "cmd",
    "command": "cmd",
    "cmd_l": "cmd",
    "cmd_r": "cmd",
    "altgr": "alt_gr",
    # спецклавиши
    "return": "enter",
    "escape": "esc",
    "spacebar": "space",
    "pgup": "page_up",
    "pgdn": "page_down",
    "pageup": "page_up",
    "pagedown": "page_down",
    "del": "delete",
    "ins": "insert",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "arrow_up": "up",
    "arrow_down": "down",
    "arrow_left": "left",
    "arrow_right": "right",
}

#: Как показывать имя клавиши человеку (остальное — Title Case).
_DISPLAY_OVERRIDES = {
    "cmd": "Win",
    "alt_gr": "AltGr",
}


class HotkeyError(ValueError):
    """Некорректная или непринятая комбинация клавиш."""


# ---------------------------------------------------------------------------
# Преобразования строк
# ---------------------------------------------------------------------------

def _wrap(token: str) -> str:
    """Обернуть токен в <> (для pynput), одиночный символ оставить как есть)."""
    if len(token) == 1:
        return token
    return "<{}>".format(token)


def _format_tokens(modifiers: Iterable[str], others: Iterable[str]) -> str:
    """Собрать каноничную строку комбинации: сначала модификаторы, потом остальное."""
    modifiers = list(modifiers)
    others = list(others)
    if len(set(modifiers + others)) != len(modifiers + others):
        raise HotkeyError(tr("Одна и та же клавиша используется дважды"))
    ordered_modifiers = sorted(
        set(modifiers),
        key=lambda name: _MODIFIER_ORDER.index(name)
        if name in _MODIFIERS
        else len(_MODIFIER_ORDER),
    )
    tokens = ordered_modifiers + others
    return "+".join(_wrap(token) for token in tokens)


def validate(formatted: str) -> None:
    """Проверить строку формата pynput. Бросает HotkeyError при ошибке."""
    try:
        HotKey.parse(formatted)
    except Exception as error:  # noqa: BLE001 — pynput кидает ValueError/KeyError
        raise HotkeyError(
            tr("Недопустимая комбинация «{}»").format(formatted)
        ) from error


def normalize(text: str) -> str:
    """Привести пользовательский ввод к формату pynput.

    Принимает и человекочитаемый вид (``Ctrl+Alt+Space``), и готовый формат
    (``<ctrl>+<alt>+<space>``). Бросает :class:`HotkeyError` с описанием
    проблемы на текущем языке интерфейса.
    """
    if not isinstance(text, str) or not text.strip():
        raise HotkeyError(tr("Хоткей не задан"))

    tokens = []
    for raw in text.split("+"):
        token = raw.strip().lower()
        if not token:
            raise HotkeyError(
                tr("Некорректная комбинация «{}»: лишний «+» "
                   "(клавиша «+» не поддерживается)").format(text.strip())
            )
        if len(token) > 1 and token[0] == "<" and token[-1] == ">":
            token = token[1:-1].strip()
        if token == " ":
            token = "space"
        elif len(token) > 1:
            token = token.replace(" ", "_")
        token = _ALIASES.get(token, token)
        tokens.append(token)

    modifiers = []
    others = []
    for token in tokens:
        if token in _MODIFIERS:
            modifiers.append(token)
        elif len(token) == 1:
            others.append(token)
        elif token in _KNOWN_KEY_NAMES:
            others.append(token)
        else:
            raise HotkeyError(tr("Неизвестная клавиша «{}»").format(token))

    if not others:
        raise HotkeyError(
            tr("Добавьте обычную клавишу: комбинация только из "
               "Ctrl/Alt/Shift/Win срабатывать не будет")
        )

    formatted = _format_tokens(modifiers, others)
    validate(formatted)
    return formatted


def display(formatted: str) -> str:
    """Показать формат pynput человекочитаемо: ``<ctrl>+<alt>+<space>`` → ``Ctrl+Alt+Space``."""
    if not formatted:
        return ""
    parts = []
    for raw in formatted.split("+"):
        name = raw.strip().strip("<>").strip()
        if not name:
            continue
        if name in _DISPLAY_OVERRIDES:
            parts.append(_DISPLAY_OVERRIDES[name])
        elif len(name) == 1:
            parts.append(name.upper())
        elif name[0] == "f" and name[1:].isdigit():
            parts.append(name.upper())
        else:
            parts.append(name.replace("_", " ").title())
    return "+".join(parts)


def _token_from_key(key) -> Optional[str]:
    """Преобразовать нажатую клавишу pynput в токен комбинации (или None)."""
    if key is None:
        return None
    if isinstance(key, Key):
        name = key.name
        if not name:
            return None
        return _ALIASES.get(name, name)
    char = getattr(key, "char", None)
    if char:
        if char == " ":
            return "space"
        if char == "+":
            # Клавиша «+» ломает синтаксис комбинации — не поддерживаем.
            log.debug("Клавиша «+» не используется в комбинациях")
            return None
        if char.isprintable():
            return char.lower()
    return None


# ---------------------------------------------------------------------------
# Слушатель (регистрация глобального хоткея)
# ---------------------------------------------------------------------------

class HotkeyListener:
    """Держит один зарегистрированный глобальный хоткей и зовёт callback.

    Callback выполняется в потоке pynput — он должен быть потокобезопасным
    (в Markclip туда кладут событие в очередь).
    """

    def __init__(self, on_trigger: Callable[[], None]) -> None:
        self._on_trigger = on_trigger
        self._listener: Optional[keyboard.GlobalHotKeys] = None
        self._hotkey: Optional[str] = None

    @property
    def hotkey(self) -> Optional[str]:
        """Текущая комбинация (None, если слушатель не запущен)."""
        return self._hotkey

    @property
    def active(self) -> bool:
        return self._listener is not None

    def start(self, formatted: str) -> None:
        """Зарегистрировать комбинацию.

        Старый слушатель снимается только после успешного разбора новой
        комбинации. Бросает :class:`HotkeyError`.
        """
        validate(formatted)
        listener = keyboard.GlobalHotKeys({formatted: self._activate})
        self._stop_quiet()
        try:
            listener.start()
        except Exception as error:  # noqa: BLE001
            raise HotkeyError(
                tr("Не удалось зарегистрировать хоткей: {}").format(error)
            ) from error
        self._listener = listener
        self._hotkey = formatted
        log.info("Зарегистрирован хоткей: %s", display(formatted))

    def stop(self) -> None:
        """Снять регистрацию (если была)."""
        self._stop_quiet()
        self._hotkey = None

    def _activate(self) -> None:
        try:
            self._on_trigger()
        except Exception:  # noqa: BLE001 — не ронять поток pynput
            log.exception("Ошибка в обработчике хоткея")

    def _stop_quiet(self) -> None:
        listener, self._listener = self._listener, None
        self._hotkey = None
        if listener is not None:
            try:
                listener.stop()
            except Exception:  # noqa: BLE001
                log.debug("Не удалось остановить слушатель хоткея", exc_info=True)


# ---------------------------------------------------------------------------
# Запись комбинации в настройках
# ---------------------------------------------------------------------------

class HotkeyCapture:
    """Записывает следующую нажатую комбинацию клавиш.

    Ровно один из колбэков вызывается один раз:

    * ``on_result(fmt)`` — комбинация записана;
    * ``on_cancel(reason)`` — отмена (``"user"`` — Esc, ``"timeout"`` — время,
      ``"cancelled"`` — программа сняла запись).

    Оба колбэка идут из потока pynput — их нельзя делать блокирующими.
    """

    def __init__(
        self,
        on_result: Callable[[str], None],
        on_cancel: Optional[Callable[[str], None]] = None,
        timeout: float = CAPTURE_TIMEOUT,
    ) -> None:
        self._on_result = on_result
        self._on_cancel: Callable[[str], None] = on_cancel or (lambda reason: None)
        self._timeout = timeout
        self._modifiers: set = set()
        self._finished = threading.Event()
        self._lock = threading.Lock()
        self._listener: Optional[keyboard.Listener] = None
        self._timer: Optional[threading.Timer] = None

    def start(self) -> None:
        """Начать слушать клавиатуру. Повторный вызов игнорируется."""
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()
        if self._timeout and self._timeout > 0:
            self._timer = threading.Timer(self._timeout, self._timeout_expired)
            self._timer.daemon = True
            self._timer.start()
        log.debug("Запись хоткея начата (таймаут %.0f с)", self._timeout)

    def cancel(self) -> None:
        """Снять запись вручную (пользователь закрыл окно и т.п.)."""
        self._finish("cancelled")

    def _timeout_expired(self) -> None:
        self._finish("timeout")

    def _on_press(self, key, *args) -> None:
        if self._finished.is_set():
            return
        token = _token_from_key(key)
        if token is None:
            return
        if token in _MODIFIERS:
            self._modifiers.add(token)
            return
        if token == "esc" and not self._modifiers:
            self._finish("user")
            return
        if token not in _KNOWN_KEY_NAMES and len(token) != 1:
            log.debug("Пропускаю неизвестную клавишу %r", token)
            return
        try:
            formatted = _format_tokens(self._modifiers, [token])
            validate(formatted)
        except HotkeyError as error:
            log.debug("Комбинация не принята: %s", error)
            return
        # Атомарно «забираем» результат: колбэк сработает ровно один раз —
        # либо здесь, либо в _finish (отмена/таймаут).
        if not self._claim():
            return
        self._cleanup()
        log.info("Записана комбинация: %s", formatted)
        self._fire(lambda: self._on_result(formatted))

    def _on_release(self, key, *args) -> None:
        # Модификаторы держим «запомненными» до фиксации основной клавиши,
        # поэтому реакции на отпускание не нужно.
        return

    def _finish(self, reason: str) -> None:
        """Завершить запись с отменой (не сработает, если результат уже отдан)."""
        if not self._claim():
            return
        self._cleanup()
        self._fire(lambda: self._on_cancel(reason))

    def _claim(self) -> bool:
        """Атомарно занять результат. False — если он уже занят."""
        with self._lock:
            if self._finished.is_set():
                return False
            self._finished.set()
            return True

    def _cleanup(self) -> None:
        """Снять таймер и слушатель клавиатуры."""
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.stop()
            except Exception:  # noqa: BLE001
                log.debug("Не удалось остановить запись", exc_info=True)

    def _fire(self, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception:  # noqa: BLE001
            log.exception("Ошибка колбэка записи хоткея")
