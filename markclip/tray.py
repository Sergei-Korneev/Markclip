# coding=utf-8
"""Иконка в трее и контекстное меню (pystray).

Трей работает в собственном потоке, поэтому колбэки меню нельзя делать
блокирующими — они лишь кладут событие в потокобезопасную очередь, которую
опрашивает главный поток Tk.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

try:
    import pystray
except Exception as error:  # noqa: BLE001 — бэкенд трея может быть недоступен
    pystray = None  # type: ignore[assignment]
    _PYSTRAY_IMPORT_ERROR = str(error)
else:
    _PYSTRAY_IMPORT_ERROR = ""

from .hotkey import display as hotkey_display
from .i18n import tr
from .icons import make_icon

log = logging.getLogger(__name__)

__all__ = ["Tray"]

#: Бэкенд pystray, который НЕ поддерживает меню и пишет WM_NAME в latin-1.
_XORG_BACKEND = "pystray._xorg"


def _ascii_title(title: str) -> str:
    """ASCII-вариант заголовка (XEMBED-бэкенд трея не понимает кириллицу)."""
    cleaned = " ".join(title.encode("ascii", "ignore").decode("ascii").split())
    return cleaned or "Markclip"


def _callback(fn: Callable[[], None]) -> Callable[[], None]:
    """Обернуть колбэк так, чтобы pystray звал его без аргументов и без падений."""

    def run() -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("Ошибка обработчика меню трея")

    return run


class Tray:
    """Трей-иконка Markclip с меню."""

    def __init__(
        self,
        *,
        on_open: Callable[[], None],
        on_settings: Callable[[], None],
        on_open_folder: Callable[[], None],
        on_quit: Callable[[], None],
        get_hotkey: Callable[[], str],
    ) -> None:
        self._on_open = on_open
        self._on_settings = on_settings
        self._on_open_folder = on_open_folder
        self._on_quit = on_quit
        self._get_hotkey = get_hotkey
        self._icon = None
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Запуск / остановка
    # ------------------------------------------------------------------
    def start(self) -> Optional[str]:
        """Запустить трей в отдельном потоке.

        Возвращает ``None`` при успехе или текст ошибки (он показывается
        пользователю при старте).
        """
        if pystray is None:
            return tr("библиотека pystray недоступна: {}").format(
                _PYSTRAY_IMPORT_ERROR
            )
        try:
            # Заголовок при создании — только латиницей: бэкенд xorg пишет
            # его в WM_NAME через Xlib, а тот не принимает символы вне latin-1.
            icon = pystray.Icon(
                "markclip",
                make_icon(),
                title="Markclip",
                menu=self._build_menu(),
            )
            self._icon = icon
            if self._xorg_backend:
                log.warning(
                    "Бэкенд трея xorg: меню недоступно и нет подсказок. "
                    "Для полного меню установите PyGObject (python3-gi, "
                    "gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1)."
                )
            else:
                icon.title = tr("Markclip — заметки")
        except Exception:  # noqa: BLE001
            log.exception("Не удалось создать иконку трея")
            return tr("не удалось создать иконку трея (подробности в журнале)")
        # pystray на GTK требует, чтобы GLib-цикл крутился сам; запускаем
        # run() в потоке — это поддерживаемый обоими бэкендами способ
        # сосуществования с главным циклом Tk.
        self._thread = threading.Thread(
            target=self._run, name="markclip-tray", daemon=True
        )
        self._thread.start()
        log.info("Трей запущен (бэкенд: %s)", self._backend_name)
        return None

    @property
    def _xorg_backend(self) -> bool:
        return self._backend_name == _XORG_BACKEND

    @property
    def _backend_name(self) -> str:
        icon = self._icon
        return type(icon).__module__ if icon is not None else "нет"

    @property
    def menu_supported(self) -> bool:
        """Есть ли в этом бэкенде трея меню (xorg-бэкенд — без меню)."""
        if self._icon is None:
            return True  # трей ещё не создан — предупреждать рано
        return not self._xorg_backend

    def _run(self) -> None:
        try:
            self._icon.run()
        except Exception:  # noqa: BLE001
            log.exception("Цикл трея завершился с ошибкой")

    def stop(self) -> None:
        """Остановить трей (идемпотентно)."""
        icon, self._icon = self._icon, None
        thread, self._thread = self._thread, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                log.debug("Не удалось остановить трей", exc_info=True)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
            if thread.is_alive():
                log.debug("Поток трея не успел завершиться")

    # ------------------------------------------------------------------
    # Обновления из главного потока
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Перерисовать меню (тексты перечитываются на текущем языке)."""
        icon = self._icon
        if icon is None:
            return
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            log.debug("Не удалось обновить меню трея", exc_info=True)
        self.set_status(tr("Markclip — заметки"))  # подсказка на новом языке

    def set_status(self, title: str) -> None:
        """Показать подсказку при наведении на иконку.

        Защищено от обращений, пока цикл трея не запущен: бэкенд xorg
        ждёт ответа от своего цикла и заблокировал бы главный поток Tk.
        """
        icon = self._icon
        if icon is None:
            return
        if not getattr(icon, "_running", False):
            log.debug("Подсказка не обновлена: цикл трея не запущен")
            return
        # XEMBED-бэкенд (xorg) пишет заголовок в latin-1 — только ASCII.
        candidates = (
            [_ascii_title(title)]
            if self._xorg_backend
            else [title, _ascii_title(title)]
        )
        for candidate in candidates:
            try:
                icon.title = candidate
                return
            except Exception:  # noqa: BLE001
                log.debug(
                    "Заголовок трея %r не принят", candidate, exc_info=True
                )

    # ------------------------------------------------------------------
    # Меню
    # ------------------------------------------------------------------
    def _build_menu(self):
        # тексты пунктов — вызываемые функции: pystray перечитывает их
        # при обновлении меню, поэтому смена языка подхватывается сразу
        return pystray.Menu(
            pystray.MenuItem(self._open_text, _callback(self._on_open), default=True),
            pystray.MenuItem(
                lambda _item: tr("Настройки…"), _callback(self._on_settings)
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _item: tr("Открыть папку заметок"),
                _callback(self._on_open_folder),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _item: tr("Выход"), _callback(self._on_quit)),
        )

    def _open_text(self, _item) -> str:
        """Пункт меню с актуальной комбинацией: «Открыть окно заметки (Ctrl+Alt+Space)»."""
        try:
            hotkey = hotkey_display(self._get_hotkey())
        except Exception:  # noqa: BLE001
            hotkey = "—"
        if not hotkey:
            hotkey = tr("не задан")
        return tr("Открыть окно заметки ({})").format(hotkey)
