# coding=utf-8
"""Главный модуль Markclip: поток событий, трей, хоткей, окна.

Архитектура потоков:

* **главный поток** — цикл Tk; только здесь создаются и трогаются виджеты;
* **поток трея** (pystray) — колбэки меню лишь кладут событие в очередь;
* **поток pynput** — срабатывание хоткея и запись комбинации кладут
  событие в очередь.

Главная нить опрашивает очередь каждые ``POLL_MS`` и выполняет события
уже у себя — так Tk остаётся потокобезопасным.
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import signal
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Optional, Tuple

from . import __version__
from .config import DEFAULT_HOTKEY, Config, config_dir
from .gui import NoteWindow, SettingsWindow, create_root
from .hotkey import (
    HotkeyCapture,
    HotkeyError,
    HotkeyListener,
    display as hotkey_display,
    normalize,
)
from .i18n import set_language, tr
from .notes import normalize_subdir, open_folder, save_note, save_note_file
from .tray import Tray

log = logging.getLogger(__name__)

#: Как часто главный поток опрашивает очередь событий, мс.
POLL_MS = 100

# События очереди
EV_OPEN = "open"
EV_SETTINGS = "settings"
EV_FOLDER = "folder"
EV_QUIT = "quit"
EV_CAPTURE_RESULT = "capture_result"
EV_CAPTURE_CANCEL = "capture_cancel"

__all__ = ["Markclip", "main"]


def _setup_logging() -> None:
    """Вывод в stderr (если есть) + файл markclip.log в каталоге конфигурации."""
    handlers = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    try:
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(directory / "markclip.log", encoding="utf-8"))
    except OSError:
        pass
    level = logging.DEBUG if os.environ.get("MARKCLIP_DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers or None,
    )


class Markclip:
    """Приложение Markclip."""

    def __init__(self) -> None:
        _setup_logging()
        log.info("Markclip %s запускается", __version__)

        self.config = Config.load()
        # язык интерфейса — до создания окон и до первого tr()
        set_language(self.config.language)
        self.events: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self.quitting = False
        self.settings: Optional[SettingsWindow] = None
        self.capture: Optional[HotkeyCapture] = None
        self.tray_error: Optional[str] = None
        self.hotkey_error: Optional[str] = None
        self._icon_photo = None  # не дать сборщику мусора удалить иконку окна

        self.root = create_root()
        self.note_window = NoteWindow(
            self.root,
            on_submit=self._submit_note,
            notes_dir_provider=lambda: self.config.notes_path,
            templates_provider=lambda: (
                self.config.title_template,
                self.config.name_template,
                self.config.text_template,
            ),
            link_style_provider=lambda: self.config.link_style,
            assets_provider=lambda: self.config.assets_dir,
        )
        self._setup_window_icon()

        self.hotkey = HotkeyListener(lambda: self.events.put((EV_OPEN, None)))
        self.tray = Tray(
            on_open=lambda: self.events.put((EV_OPEN, None)),
            on_settings=lambda: self.events.put((EV_SETTINGS, None)),
            on_open_folder=lambda: self.events.put((EV_FOLDER, None)),
            on_quit=lambda: self.events.put((EV_QUIT, None)),
            get_hotkey=lambda: self.config.hotkey,
        )

    # ------------------------------------------------------------------
    # Запуск
    # ------------------------------------------------------------------
    def run(self, open_note: bool = False, open_settings: bool = False) -> None:
        self._register_startup_hotkey()
        self.tray_error = self.tray.start()
        if self.tray_error:
            log.error("Трей недоступен: %s", self.tray_error)
        self._install_signal_handlers()
        self.root.after(POLL_MS, self._poll)
        self.root.after(400, self._show_startup_warnings)
        if open_settings:
            self.root.after(500, self.open_settings)
        elif open_note:
            self.root.after(500, self.open_note)
        self._schedule_smoke_test()
        try:
            self.root.mainloop()
        finally:
            log.info("Markclip остановлен")

    def _setup_window_icon(self) -> None:
        try:
            from PIL import ImageTk

            from .icons import make_icon

            photo = ImageTk.PhotoImage(make_icon(64))
            self.root.iconphoto(True, photo)
            self._icon_photo = photo
        except Exception:  # noqa: BLE001
            log.debug("Иконку окна установить не удалось", exc_info=True)

    def _show_startup_warnings(self) -> None:
        if self.quitting:
            return
        messages = []
        if self.tray_error:
            messages.append(tr("Иконка в трее: {}").format(self.tray_error))
        elif not self.tray.menu_supported:
            messages.append(
                tr(
                    "Меню трея не поддерживается выбранным бэкендом (xorg) — "
                    "пункт «Настройки» в трее недоступен.\n"
                    "Для полного меню установите PyGObject: python3-gi, "
                    "gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1.\n"
                    "Пока настройки можно открыть ключом запуска: --settings"
                )
            )
        if self.hotkey_error:
            messages.append(tr("Глобальный хоткей: {}").format(self.hotkey_error))
        if not messages:
            return
        try:
            messagebox.showwarning(
                tr("Markclip — проблемы запуска"),
                "\n\n".join(messages) + tr("\n\nПодробности — в журнале markclip.log."),
                parent=self.root,
            )
        except tk.TclError:
            log.debug("Не удалось показать окно предупреждения", exc_info=True)

    # ------------------------------------------------------------------
    # Хоткей
    # ------------------------------------------------------------------
    def _register_startup_hotkey(self) -> None:
        """Поставить хоткей из настроек, при неудаче — комбинацию по умолчанию.

        Хранимый в config.json хоткей сначала нормализуется (терпит
        ручные правки вроде ``<ctrl>+<alt>+<n>``). Если применить его
        не удалось, комбинация по умолчанию подставляется **только в
        памяти** — файл настроек не переписывается, чтобы не потерять
        введённую пользователем комбинацию.
        """
        stored = str(self.config.hotkey or "").strip()
        stored_error = None
        candidate = None
        try:
            candidate = normalize(stored)
        except HotkeyError as error:
            stored_error = "«{}»: {}".format(stored, error)
            log.warning("Хоткей из настроек %s", stored_error)

        if candidate is not None:
            error = self._register_hotkey(candidate)
            if error is None:
                if candidate != stored:
                    # привели к каноническому виду — закрепим в файле
                    self.config.hotkey = candidate
                    save_error = self._save_config_quiet()
                    if save_error:
                        log.warning(save_error)
                self.hotkey_error = None
                return
            stored_error = error
            log.warning("Хоткей из настроек не применился: %s", error)

        if candidate == DEFAULT_HOTKEY:
            self.hotkey_error = stored_error
            return

        fallback_error = self._register_hotkey(DEFAULT_HOTKEY)
        if fallback_error is None:
            self.config.hotkey = DEFAULT_HOTKEY  # только в памяти
            self.hotkey_error = None
            log.info(
                "Временно использую хоткей по умолчанию: %s (файл настроек "
                "не изменён)",
                hotkey_display(DEFAULT_HOTKEY),
            )
            return
        log.warning("Хоткей по умолчанию тоже не принят: %s", fallback_error)
        self.hotkey_error = tr("{}; по умолчанию также недоступен ({})").format(
            stored_error, fallback_error,
        )

    def _register_hotkey(self, formatted: str) -> Optional[str]:
        """Поставить хоткей; при ошибке вернуть текст и откатить прежний."""
        previous = self.hotkey.hotkey
        try:
            self.hotkey.start(formatted)
        except HotkeyError as error:
            return self._rollback_hotkey(previous, str(error))
        except Exception as error:  # noqa: BLE001
            log.exception("Сбой регистрации хоткея")
            return self._rollback_hotkey(previous, str(error))
        return None

    def _rollback_hotkey(self, previous: Optional[str], error: str) -> str:
        if previous:
            try:
                self.hotkey.start(previous)
            except Exception:  # noqa: BLE001
                log.exception("Не удалось вернуть прежний хоткей")
        return error

    # ------------------------------------------------------------------
    # Сохранение заметки
    # ------------------------------------------------------------------
    def _submit_note(
        self, text: str, title: str = "", name: str = ""
    ) -> Optional[str]:
        """Сохранить заметку: именованным файлом или в дневной файл.

        Заполненные заголовок/имя — отдельный файл ``<имя>.md``
        (заголовок — первой строкой ``# ...``); оба пуста — привычное
        дополнение в дневной ``ГГГГ-ММ-ДД.md``.
        """
        try:
            if (title or "").strip() or (name or "").strip():
                path = save_note_file(
                    self.config.notes_path, text, title=title, name=name
                )
            else:
                path = save_note(text, self.config.notes_path)
        except OSError as error:
            log.error("Не удалось записать заметку: %s", error)
            return tr("Не удалось записать файл: {}").format(error)
        if path is None:
            return tr("Введите текст заметки")
        log.info("Заметка сохранена: %s", path)
        try:
            self.tray.set_status(tr("Markclip — сохранено: {}").format(path.name))
        except Exception:  # noqa: BLE001
            log.debug("Не удалось обновить подсказку трея", exc_info=True)
        return None

    # ------------------------------------------------------------------
    # Окна
    # ------------------------------------------------------------------
    def open_note(self) -> None:
        """Открыть окно заметки (пока открыты настройки — фокусировать их)."""
        if self.settings is not None and self.settings.exists():
            self.settings.focus()
            return
        self.note_window.show()

    def open_settings(self) -> None:
        if self.settings is not None and self.settings.exists():
            self.settings.focus()
            return
        self.settings = SettingsWindow(
            self.root,
            notes_dir=self.config.notes_dir,
            hotkey=hotkey_display(self.config.hotkey),
            title_template=self.config.title_template,
            name_template=self.config.name_template,
            text_template=self.config.text_template,
            assets_dir=self.config.assets_dir,
            link_style=self.config.link_style,
            language=self.config.language,
            on_save=self._save_settings,
            on_capture=self._start_capture,
            on_close=self._on_settings_closed,
        )
        self.settings.show()

    def _save_settings(
        self,
        notes_dir: str,
        hotkey_text: str,
        title_template: str = "",
        name_template: str = "",
        assets_dir: str = "",
        language: str = "ru",
        text_template: str = "",
        link_style: str = "plain",
    ) -> Optional[str]:
        """Применить настройки из окна. Возвращает текст ошибки или None."""
        notes_dir = (notes_dir or "").strip()
        if not notes_dir:
            return tr("Укажите папку для заметок")
        try:
            path = Path(notes_dir).expanduser()
            path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return tr("Не удалось подготовить папку: {}").format(error)
        if not path.is_dir():
            return tr("Это не папка: {}").format(path)

        try:
            new_hotkey = normalize(hotkey_text)
        except HotkeyError as error:
            return str(error)

        error = self._register_hotkey(new_hotkey)
        if error:
            return tr("Хоткей не принят: {}").format(error)

        self.config.notes_dir = str(path)
        self.config.hotkey = new_hotkey
        self.config.title_template = (title_template or "").strip()
        self.config.name_template = (name_template or "").strip()
        self.config.text_template = (text_template or "").strip()
        self.config.assets_dir = normalize_subdir(assets_dir)
        self.config.link_style = (
            link_style if link_style in ("plain", "angle") else "plain"
        )
        # язык применяется последним: если он сменился, открытые окна и
        # меню трея сразу перерисовываются на новом языке
        self.config.language = set_language(language)
        save_error = self._save_config_quiet()
        self.tray.refresh()
        self.note_window.retranslate()
        if save_error:
            return save_error
        log.info(
            "Настройки применены: папка=%s, хоткей=%s, шаблоны=%r/%r/%r, "
            "вложения=%s, ссылки=%s, язык=%s",
            self.config.notes_dir,
            hotkey_display(new_hotkey),
            self.config.title_template,
            self.config.name_template,
            self.config.text_template,
            self.config.assets_dir,
            self.config.link_style,
            self.config.language,
        )
        return None

    def _save_config_quiet(self) -> Optional[str]:
        try:
            self.config.save()
            return None
        except OSError as error:
            log.error("Не удалось сохранить настройки: %s", error)
            return tr("Настройки применены, но не сохранены на диск: {}").format(
                error
            )

    # ------------------------------------------------------------------
    # Запись комбинации из окна настроек
    # ------------------------------------------------------------------
    def _start_capture(self) -> None:
        if self.capture is not None:
            return
        # Снимаем текущий хоткей, чтобы он не срабатывал во время записи
        self.hotkey.stop()
        self.capture = HotkeyCapture(
            on_result=lambda fmt: self.events.put((EV_CAPTURE_RESULT, fmt)),
            on_cancel=lambda reason: self.events.put((EV_CAPTURE_CANCEL, reason)),
        )
        try:
            self.capture.start()
        except Exception as error:  # noqa: BLE001
            log.exception("Не удалось начать запись комбинации")
            self.capture = None
            self._register_hotkey(self.config.hotkey)
            if self.settings is not None and self.settings.exists():
                self.settings.capture_finished(
                    hotkey_display(self.config.hotkey),
                    error=tr("Не удалось записать комбинацию: {}").format(error),
                )

    def _capture_done(self, formatted: Optional[str], reason: Optional[str]) -> None:
        """Итог записи комбинации (событие из потока pynput)."""
        self.capture = None
        if formatted is not None:
            error = self._register_hotkey(formatted)
            if not error:
                self.config.hotkey = formatted
                save_error = self._save_config_quiet()
                if save_error:
                    error = save_error
                self.tray.refresh()
            # при ошибке регистрации в конфигурации остаётся прежний хоткей
            current = self.config.hotkey
        else:
            # запись отменена/истекло время — возвращаем прежний хоткей
            self._register_hotkey(self.config.hotkey)
            current = self.config.hotkey
            error = (
                tr("Время истекло — комбинация не записана")
                if reason == "timeout"
                else None
            )
        if self.settings is not None and self.settings.exists():
            self.settings.capture_finished(hotkey_display(current), error=error)

    def _on_settings_closed(self) -> None:
        self.settings = None
        if self.capture is not None:
            capture, self.capture = self.capture, None
            # событие EV_CAPTURE_CANCEL вернёт прежний хоткей
            capture.cancel()

    # ------------------------------------------------------------------
    # Очередь событий
    # ------------------------------------------------------------------
    def _poll(self) -> None:
        if self.quitting:
            return
        while True:
            try:
                event, data = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._dispatch(event, data)
            except Exception:  # noqa: BLE001 — одна ошибка не должна убивать цикл
                log.exception("Ошибка обработки события «%s»", event)
            if self.quitting:
                break
        if not self.quitting:
            self.root.after(POLL_MS, self._poll)

    def _dispatch(self, event: str, data) -> None:
        if event == EV_OPEN:
            self.open_note()
        elif event == EV_SETTINGS:
            self.open_settings()
        elif event == EV_FOLDER:
            open_folder(self.config.notes_path)
        elif event == EV_QUIT:
            self.quit()
        elif event == EV_CAPTURE_RESULT:
            self._capture_done(str(data), None)
        elif event == EV_CAPTURE_CANCEL:
            self._capture_done(None, str(data) if data else "cancelled")
        else:
            log.warning("Неизвестное событие: %s", event)

    # ------------------------------------------------------------------
    # Остановка
    # ------------------------------------------------------------------
    def quit(self) -> None:
        if self.quitting:
            return
        self.quitting = True
        log.info("Выход…")
        if self.capture is not None:
            capture, self.capture = self.capture, None
            try:
                capture.cancel()
            except Exception:  # noqa: BLE001
                log.debug("Не удалось отменить запись хоткея", exc_info=True)
        try:
            self.hotkey.stop()
        except Exception:  # noqa: BLE001
            log.debug("Не удалось снять хоткей", exc_info=True)
        try:
            self.tray.stop()
        except Exception:  # noqa: BLE001
            log.debug("Не удалось остановить трей", exc_info=True)
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            log.debug("Не удалось закрыть окно", exc_info=True)

    def _install_signal_handlers(self) -> None:
        def handler(signum, _frame) -> None:
            log.info("Получен сигнал %s", signum)
            self.events.put((EV_QUIT, None))

        signals = [signal.SIGINT, signal.SIGTERM]
        sigbreak = getattr(signal, "SIGBREAK", None)
        if sigbreak is not None:
            signals.append(sigbreak)
        for sig in signals:
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                log.debug("Не удалось перехватить сигнал %s", sig, exc_info=True)

    # ------------------------------------------------------------------
    # Автотест (MARKCLIP_SMOKE_TEST=секунд)
    # ------------------------------------------------------------------
    def _schedule_smoke_test(self) -> None:
        raw = os.environ.get("MARKCLIP_SMOKE_TEST", "").strip()
        if not raw:
            return
        try:
            seconds = float(raw)
        except ValueError:
            seconds = 10.0
        log.info("SMOKE: автотест включён, выход через %.1f с", seconds)

        def open_window() -> None:
            log.info("SMOKE: открываю окно (как по хоткею)")
            self.events.put((EV_OPEN, None))

        def type_note() -> None:
            log.info("SMOKE: ввожу текст и жму ОК")
            try:
                self.note_window.text.insert(
                    "1.0", "Тестовая заметка Markclip (автотест)"
                )
                self.note_window.submit()
            except Exception:  # noqa: BLE001
                log.exception("SMOKE: ошибка при вводе/сохранении")

        def finish() -> None:
            log.info("SMOKE: завершение")
            self.events.put((EV_QUIT, None))

        self.root.after(1500, open_window)
        self.root.after(3000, type_note)
        self.root.after(max(2500, int(seconds * 1000)), finish)


def main(argv: Optional[list] = None) -> int:
    """Точка входа."""
    # язык из настроек — чтобы --help и сообщения старта были локализованы
    set_language(Config.load().language)
    parser = argparse.ArgumentParser(
        prog="markclip",
        description=tr(
            "Markclip — быстрые текстовые заметки (Markdown) из трея. "
            "Настройки и журнал находятся рядом с программой (config.json, "
            "markclip.log) — папка полностью переносима."
        ),
    )
    parser.add_argument(
        "-s",
        "--settings",
        action="store_true",
        help=tr("сразу открыть окно настроек (запасной вход, если недоступно меню трея)"),
    )
    parser.add_argument(
        "-n",
        "--note",
        action="store_true",
        help=tr("сразу открыть окно ввода заметки"),
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Markclip {}".format(__version__),
    )
    args = parser.parse_args(argv)

    try:
        app = Markclip()
    except tk.TclError as error:
        # в pythonw (Windows, без консоли) sys.stderr может быть None
        stream = sys.stderr or sys.stdout
        if stream is not None:
            stream.write(
                tr(
                    "Markclip: не удалось запустить интерфейс: {}\n"
                    "Проверьте, что есть дисплей (на Linux — X11/Wayland, "
                    "переменная DISPLAY).\n"
                ).format(error)
            )
        return 1
    try:
        app.run(open_note=args.note, open_settings=args.settings)
    except KeyboardInterrupt:
        log.info("Прерывание с клавиатуры")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
