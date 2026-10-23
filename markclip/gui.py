# coding=utf-8
"""Окна приложения: окно заметки и окно настроек (Tkinter)."""

from __future__ import annotations

import logging
import re
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable, Optional, Tuple

from .clipboard import get_clipboard_image
from .i18n import available_languages, language_name, tr
from .notes import (
    IMAGES_SUBDIR,
    normalize_subdir,
    sanitize_file_name,
    save_note_image,
)

log = logging.getLogger(__name__)

__all__ = ["NoteWindow", "SettingsWindow"]

_ERROR_COLOR = "#b00020"
_MUTED_COLOR = "#666666"


#: Токены шаблона: ``{{``/``}}`` (литеральные скобки) и ``{имя}``/``{имя:N}``
#: с известными именами; всё остальное остаётся как есть.
_TOKEN_RE = re.compile(
    r"\{\{|\}\}|\{(date|time|datetime|text|url1)(?::(\d+))?\}"
)

#: Подстановки, которым нужен введённый текст заметки (применяются
#: только при сохранении — при открытии формы текста ещё нет).
_TEXT_PLACEHOLDER_RE = re.compile(r"\{text(?::\d+)?\}|\{url1\}")

#: Первая ссылка в тексте (без висячей пунктуации в конце).
_URL_RE = re.compile(r"https?://[^\s<>'\"()\[\]{}]+")


def first_url(text: str) -> str:
    """Первая ссылка ``http(s)://…`` в тексте; ссылки нет — пустая строка."""
    match = _URL_RE.search(text or "")
    if not match:
        return ""
    return match.group(0).rstrip(".,;:!?…")


def has_text_placeholders(template: str) -> bool:
    """Есть ли в шаблоне подстановки, зависящие от текста заметки."""
    return bool(_TEXT_PLACEHOLDER_RE.search(template or ""))


def _text_snippet(text: str, limit: Optional[int]) -> str:
    """Фрагмент текста для подстановки: пробелы → один пробел, обрезка."""
    flat = " ".join((text or "").split())
    return flat[:limit] if limit else flat


def render_template(
    template: str, now: Optional["datetime"] = None, text: str = ""
) -> str:
    """Подставить в шаблон дату/время и подстановки по тексту заметки.

    Подстановки даты/времени: ``{date}`` — ГГГГ-ММ-ДД, ``{time}`` — ЧЧ-ММ-СС,
    ``{datetime}`` — «ГГГГ-ММ-ДД ЧЧ-ММ-СС».

    Подстановки по тексту (нужен аргумент ``text``): ``{text}`` — весь текст,
    ``{text:90}`` — первые 90 символов (пробелы сворачиваются в один),
    ``{url1}`` — первая ссылка ``http(s)://`` в тексте.

    Литеральная фигурная скобка удваивается: ``{{``. Неизвестные
    подстановки остаются как есть, кривой шаблон не приводит к ошибке.
    Подставляемый текст повторно не разбирается — фигурные скобки
    внутри него доходят до результата как есть.
    """
    moment = now or datetime.now()
    source = template or ""
    values = {
        "date": moment.strftime("%Y-%m-%d"),
        "time": moment.strftime("%H-%M-%S"),
        "datetime": moment.strftime("%Y-%m-%d %H-%M-%S"),
        "url1": first_url(text),
    }

    parts = []
    position = 0
    for match in _TOKEN_RE.finditer(source):
        parts.append(source[position : match.start()])
        position = match.end()
        token = match.group(0)
        if token == "{{":
            parts.append("{")
            continue
        if token == "}}":
            parts.append("}")
            continue
        name, limit = match.group(1), match.group(2)
        if name == "text":
            parts.append(
                (text or "") if limit is None else _text_snippet(text, int(limit))
            )
        else:
            parts.append(values[name])
    parts.append(source[position:])
    return "".join(parts)


def render_note_body(template: str, text: str) -> str:
    """Собрать тело заметки по шаблону (применяется при сохранении).

    ``{text}`` в шаблоне — место текста. Если подстановки нет, введённый
    текст дописывается в конец отрендеренного шаблона. Пустой шаблон —
    текст возвращается без изменений.
    """
    if not (template or "").strip():
        return text or ""
    rendered = render_template(template, text=text).strip("\n")
    body = (text or "").strip("\n")
    if not body:
        return rendered
    if re.search(r"\{text(:\d+)?\}", template or ""):
        return rendered
    return "{}\n\n{}".format(rendered, body) if rendered else body


class NoteWindow:
    """Окно с полями заголовка, имени файла, текстом и кнопкой ОК.

    :param on_submit: ``(text, title, name) -> Optional[str]`` — вызывается
        при ОК; возвращает ``None`` при успехе или сообщение об ошибке —
        тогда окно остаётся открытым. Заполненные заголовок/имя означают
        сохранение отдельным файлом; пустые — привычное дополнение
        в дневной файл.
    :param notes_dir_provider: возвращает текущую папку заметок; нужен
        для сохранения картинок, вставленных через Ctrl+V. Если не задан,
        картинки вставить нельзя (сообщается в строке статуса).
    :param templates_provider: возвращает ``(шаблон заголовка,
        шаблон имени файла, шаблон текста заметки)``. Шаблоны только
        с датой/временем заполняют поля при открытии пустой формы;
        шаблоны с ``{text…}``/``{url1}`` применяются при сохранении
        (см. :func:`render_template`), а шаблон текста — всегда
        при сохранении. Если не задан — поля открываются пустыми.
    :param assets_provider: возвращает текущее имя подпапки вложений
        для картинок из буфера; если не задан — ``assets``.
    """

    def __init__(
        self,
        root: tk.Tk,
        on_submit: Callable[[str, str, str], Optional[str]],
        notes_dir_provider: Optional[Callable[[], Optional[Path]]] = None,
        templates_provider: Optional[Callable[[], Tuple[str, str, str]]] = None,
        assets_provider: Optional[Callable[[], str]] = None,
    ) -> None:
        self.root = root
        self.on_submit = on_submit
        self.notes_dir_provider = notes_dir_provider
        self.templates_provider = templates_provider
        self.assets_provider = assets_provider
        # картинки, вставленные, но ещё не сохранённые на диск:
        # (имя файла, PNG-байты) — файлы пишутся только по ОК
        self._pending_images: list = []
        self._preview_photos: list = []  # ссылки, чтобы Tk не удалил превью
        self._renamed: dict = {}  # «ожидалось» → «фактически сохранено»
        # последнее имя, подставленное автоматически из заголовка: пока
        # пользователь не правит имя вручную, оно следует за заголовком
        self._auto_name = ""
        # текущие шаблоны настроек (заполняются при открытии формы);
        # шаблоны с подстановками по тексту применяются при сохранении
        self._title_template = ""
        self._name_template = ""
        self._text_template = ""
        self._deferred_title = False
        self._deferred_name = False
        # поле, под которым открылось контекстное меню
        self._context_target: Optional[tk.Widget] = None
        # защита от повторного Ctrl+V, пока читается буфер обмена
        self._pasting = False

        root.title(tr("Markclip — новая заметка"))
        root.geometry("560x380")
        root.minsize(420, 300)
        root.protocol("WM_DELETE_WINDOW", self.hide)
        root.withdraw()  # на старте окно спрятано в трей

        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)

        # -- заголовок и имя файла (необязательные) ------------------------
        row_title = ttk.Frame(outer)
        row_title.pack(fill="x", pady=(0, 4))
        self.label_title = ttk.Label(row_title, text=tr("Заголовок:"))
        self.label_title.pack(anchor="w")
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(row_title, textvariable=self.title_var)
        self.title_entry.pack(fill="x")

        row_name = ttk.Frame(outer)
        row_name.pack(fill="x", pady=(0, 8))
        self.label_name = ttk.Label(row_name, text=tr("Имя файла:"))
        self.label_name.pack(anchor="w")
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(row_name, textvariable=self.name_var)
        self.name_entry.pack(fill="x")

        self.label_text = ttk.Label(outer, text=tr("Текст заметки:"))
        self.label_text.pack(anchor="w")

        self.text = tk.Text(
            outer,
            height=8,
            wrap="word",
            undo=True,
            relief="solid",
            borderwidth=1,
            font=("Sans", 11),
            padx=6,
            pady=6,
        )
        self.text.pack(fill="both", expand=True, pady=(4, 8))

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x")

        self.status = ttk.Label(bottom, text="", foreground=_ERROR_COLOR)
        self.status.pack(side="left")

        # ОК — правая кнопка по умолчанию, Отмена — левее её
        self.btn_ok = ttk.Button(bottom, text=tr("ОК"), command=self.submit, width=10)
        self.btn_ok.pack(side="right")
        self.btn_cancel = ttk.Button(bottom, text=tr("Отмена"), command=self.hide, width=10)
        self.btn_cancel.pack(side="right", padx=(0, 8))

        self.hint = ttk.Label(
            outer,
            text=tr(
                "Ctrl+Enter — сохранить, Esc — закрыть, "
                "Ctrl+V — вставить картинку или текст. "
                "Правый клик — меню правки."
            ),
            foreground=_MUTED_COLOR,
        )
        self.hint.pack(anchor="w", pady=(6, 0))

        self.text.bind("<<Modified>>", self._on_modified)
        self.title_entry.bind("<KeyRelease>", self._on_title_changed)
        self.title_entry.bind("<<Paste>>", self._on_title_changed)
        root.bind("<Control-Return>", self._on_ctrl_enter)
        root.bind("<Escape>", self._on_escape)

        # Правка полей задаётся явно: в Tk 9 на X11 у Ctrl+C/X/V/A нет
        # дефолтных классовых привязок. Плюс контекстное меню по правому
        # клику (клавиша Menu / Shift+F10).
        self._context_menu = self._build_context_menu()
        for widget in (self.title_entry, self.name_entry, self.text):
            widget.bind("<Control-c>", self._on_copy)
            widget.bind("<Control-Insert>", self._on_copy)
            widget.bind("<Control-x>", self._on_cut)
            widget.bind("<Shift-Delete>", self._on_cut)
            widget.bind("<Control-v>", self._on_paste)
            widget.bind("<Shift-Insert>", self._on_paste)
            widget.bind("<Control-a>", self._on_select_all)
            widget.bind("<Button-3>", self._on_context)
            widget.bind("<Menu>", self._on_context)
            widget.bind("<Shift-F10>", self._on_context)

    # ------------------------------------------------------------------
    # Обработчики
    # ------------------------------------------------------------------
    def _on_title_changed(self, _event=None) -> None:
        """Имя файла следует за заголовком, пока его не правили вручную.

        Если задан шаблон имени файла — имя подчиняется шаблону,
        а не заголовку.
        """
        if self._name_template:
            return
        new_auto = sanitize_file_name(self.title_var.get())
        if self.name_var.get() == self._auto_name:
            try:
                self.name_var.set(new_auto)
            except tk.TclError:
                pass
        self._auto_name = new_auto

    def _apply_templates(self) -> None:
        """Подставить шаблонные заголовок/имя в пустую форму новой заметки.

        Черновик (непустые поля) не трогается: шаблоны действуют только
        при открытии пустой формы. Шаблоны с ``{text…}``/``{url1}``
        не заполняют поле — они вычисляются при сохранении, когда текст
        уже введён; соответствующие флаги запоминаются для :meth:`submit`.
        """
        if not self.templates_provider:
            return
        try:
            title_template, name_template, text_template = (
                self.templates_provider()
            )
        except Exception:  # noqa: BLE001
            log.debug("Шаблоны недоступны", exc_info=True)
            return
        # шаблоны читаем всегда — submit должен применять актуальные
        self._title_template = (title_template or "").strip()
        self._name_template = (name_template or "").strip()
        self._text_template = (text_template or "").strip()
        self._deferred_title = has_text_placeholders(self._title_template)
        self._deferred_name = has_text_placeholders(self._name_template)
        try:
            if self.title_var.get().strip() or self.name_var.get().strip():
                return  # это черновик — его не перезаписываем
            if self._title_template and not self._deferred_title:
                self.title_var.set(render_template(self._title_template))
            if self._name_template:
                if not self._deferred_name:
                    self.name_var.set(render_template(self._name_template))
                    self._auto_name = self.name_var.get()
            elif self.title_var.get().strip():
                # шаблона имени нет — имя, как обычно, следует за заголовком
                self._auto_name = sanitize_file_name(self.title_var.get())
                self.name_var.set(self._auto_name)
        except tk.TclError:
            log.debug("Не удалось подставить шаблоны", exc_info=True)
    def _on_ctrl_enter(self, _event):
        self.submit()
        return "break"

    def _on_escape(self, _event):
        self.hide()
        return "break"

    def _on_paste(self, event) -> str:
        """Ctrl+V / Shift+Insert: в текст — картинка или текст, в поля — текст."""
        if event.widget is not self.text:
            self._field_paste(event.widget)
            return "break"
        return self._paste_smart()

    def _on_copy(self, event) -> str:
        """Ctrl+C / Ctrl+Insert — копировать выделенное."""
        self._field_copy(event.widget)
        return "break"

    def _on_cut(self, event) -> str:
        """Ctrl+X / Shift+Delete — вырезать выделенное."""
        self._field_cut(event.widget)
        return "break"

    def _paste_smart(self) -> str:
        """Умная вставка в текстовое поле: картинка → ссылка, иначе текст.

        Текст вставляется вручную: в Tk 9 на X11 у ``Ctrl+V`` нет
        дефолтной классовой привязки, полагаться на неё нельзя. Чтение
        картинки идёт с прокруткой событий Tk (``pump``) — иначе запрос
        буфера к собственному окну и ожидание xclip образуют дедлок.
        """
        if self._pasting:
            return "break"  # повторное нажатие во время чтения буфера
        self._pasting = True
        try:
            try:
                image = get_clipboard_image(pump=self.root.update)
            except Exception:  # noqa: BLE001 — буфер не должен ронять вставку
                log.debug("Буфер не прочитан как картинка", exc_info=True)
                image = None
            if image is None:
                self._insert_field_text(self.text)
                return "break"
            data, ext = image
            name = "{}.{}".format(datetime.now().strftime("%Y-%m-%d_%H%M%S"), ext)
            self._pending_images.append((name, data))
            self._insert_image_preview(data)
            # в текст попадает Markdown-ссылка — по ней картинка будет найдена
            subdir = self._assets_subdir()
            self.text.insert(
                "insert",
                "\n![{}]({}/{})\n".format(tr("изображение"), subdir, name),
            )
            try:
                if self.status.cget("text"):
                    self.status.config(text="")
            except tk.TclError:
                pass
            return "break"
        finally:
            self._pasting = False

    # ------------------------------------------------------------------
    # Правка полей: работаем явно, без дефолтных привязок клавиатуры
    # ------------------------------------------------------------------
    def _insert_field_text(self, widget, text: Optional[str] = None) -> None:
        """Вставить текст в поле (заменяя выделение, если оно есть)."""
        if text is None:
            try:
                text = widget.clipboard_get()
            except tk.TclError:
                return  # в буфере не текст — вставлять нечего
        try:
            if widget is self.text:
                sel = widget.tag_ranges(tk.SEL)
                inside = (
                    bool(sel)
                    and widget.compare(tk.INSERT, ">=", sel[0])
                    and widget.compare(tk.INSERT, "<=", sel[1])
                )
                if inside:
                    widget.delete(sel[0], sel[1])
            elif widget.selection_present():
                widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
            widget.insert(tk.INSERT, text)
        except tk.TclError:
            log.debug("Не удалось вставить текст", exc_info=True)

    def _field_copy(self, widget) -> None:
        """Скопировать выделенное из поля в буфер обмена."""
        try:
            start, end = self._selection_range(widget)
            if start is not None:
                widget.clipboard_clear()
                widget.clipboard_append(widget.get(start, end))
        except tk.TclError:
            pass

    def _field_cut(self, widget) -> None:
        """Вырезать выделенное из поля."""
        try:
            start, end = self._selection_range(widget)
            if start is None:
                return
            self._field_copy(widget)
            widget.delete(start, end)
            if widget is self.title_entry:
                self._on_title_changed()
        except tk.TclError:
            pass

    def _selection_range(self, widget) -> Tuple[str, str]:
        """Начало и конец выделения в поле; без выделения — ``(None, None)``."""
        if widget is self.text:
            sel = widget.tag_ranges(tk.SEL)
            return (sel[0], sel[1]) if sel else (None, None)
        if widget.selection_present():
            return tk.SEL_FIRST, tk.SEL_LAST
        return None, None

    def _field_paste(self, widget) -> None:
        """Вставить буфер в поле: для текстового поля — сначала картинка."""
        if widget is self.text and self._paste_smart() == "break":
            return  # вставилась картинка
        self._insert_field_text(widget)
        if widget is self.title_entry:
            self._on_title_changed()

    def _field_select_all(self, widget) -> None:
        """Выделить всё содержимое поля."""
        try:
            if widget is self.text:
                widget.tag_add(tk.SEL, "1.0", "end-1c")
            else:
                widget.select_range(0, tk.END)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Контекстное меню и мышь
    # ------------------------------------------------------------------
    def _build_context_menu(self) -> tk.Menu:
        """Меню правой кнопки: вырезать/копировать/вставить/выделить всё."""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(
            label=tr("Вырезать"),
            accelerator="Ctrl+X",
            command=lambda: self._ctx_act(self._field_cut),
        )
        menu.add_command(
            label=tr("Копировать"),
            accelerator="Ctrl+C",
            command=lambda: self._ctx_act(self._field_copy),
        )
        menu.add_command(
            label=tr("Вставить"),
            accelerator="Ctrl+V",
            command=lambda: self._ctx_act(self._field_paste),
        )
        menu.add_separator()
        menu.add_command(
            label=tr("Выделить всё"),
            accelerator="Ctrl+A",
            command=lambda: self._ctx_act(self._field_select_all),
        )
        return menu

    def _on_context(self, event) -> str:
        """Показать контекстное меню для поля, где кликнули."""
        self._context_target = event.widget
        if event.widget is self.text and getattr(event, "num", 0) == 3:
            self._context_place_caret(event)
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self._context_menu.grab_release()
            except tk.TclError:
                pass
        return "break"

    def _context_place_caret(self, event) -> None:
        """Правый клик по тексту: каретка в точку клика, выделение цело."""
        widget = self.text
        index = "@{},{}".format(event.x, event.y)
        try:
            sel = widget.tag_ranges(tk.SEL)
            inside = (
                bool(sel)
                and widget.compare(index, ">=", sel[0])
                and widget.compare(index, "<", sel[1])
            )
            if not inside:
                widget.mark_set(tk.INSERT, index)
                widget.tag_remove(tk.SEL, "1.0", "end")
        except tk.TclError:
            pass

    def _ctx_act(self, action) -> None:
        """Выполнить действие правки в поле, под которым открыто меню."""
        if self._context_target is not None:
            action(self._context_target)

    def _on_select_all(self, event) -> str:
        """Ctrl+A — выделить всё в поле заметки."""
        self._field_select_all(event.widget)
        return "break"

    def _insert_image_preview(self, data: bytes) -> None:
        """Показать вставленную картинку прямо в окне (только для вида)."""
        try:
            import io

            from PIL import Image, ImageTk

            source = Image.open(io.BytesIO(data))
            source.thumbnail((480, 320))
            photo = ImageTk.PhotoImage(source)
            self._preview_photos.append(photo)  # иначе Tk соберёт мусор
            self.text.image_create("insert", image=photo)
        except Exception:  # noqa: BLE001 — превью необязательно
            log.debug("Превью картинки недоступно", exc_info=True)

    def _on_modified(self, _event) -> None:
        """Гасить сообщение об ошибке, как только пользователь начал править."""
        try:
            if self.text.edit_modified():
                self.text.edit_modified(False)
                if self.status.cget("text"):
                    self.status.config(text="")
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------
    def show(self) -> None:
        """Показать окно поверх остальных и перевести фокус в поле ввода."""
        self._apply_templates()
        try:
            self.status.config(text="")
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.focus_force()
            self.text.focus_set()
            # всё содержимое выделено — новый текст перезапишет старый
            self.text.tag_add(tk.SEL, "1.0", "end-1c")
            self.text.mark_set(tk.INSERT, "end-1c")
        except tk.TclError:
            log.debug("Не удалось показать окно заметки", exc_info=True)
        # Повторный захват фокуса: некоторые WM игнорируют первый вызов
        self.root.after(150, self._focus_again)
        # Верхний слой снимаем — чтобы не мешал другим окнам
        self.root.after(500, self._unset_topmost)

    def hide(self) -> None:
        """Спрятать окно (текст сохраняется на случай возврата)."""
        try:
            self.root.withdraw()
        except tk.TclError:
            pass

    def submit(self) -> None:
        """Отправить текст на сохранение (сначала — картинки, если были)."""
        content = self.text.get("1.0", "end-1c")
        if self._pending_images:
            error = self._save_pending_images()
            if error:
                self.status.config(text=error)
                self.text.focus_set()
                return
            content = self._fix_image_refs(content)
        # шаблоны с {text…}/{url1} применяются здесь — текст уже введён
        title = self.title_var.get()
        name = self.name_var.get()
        if self._deferred_title and self._title_template and not title.strip():
            title = render_template(self._title_template, text=content).strip()
        if self._deferred_name and self._name_template and not name.strip():
            name = render_template(self._name_template, text=content)
        if self._text_template:
            content = render_note_body(self._text_template, content)
        try:
            error = self.on_submit(content, title, name)
        except Exception:  # noqa: BLE001 — не ронять UI из-за ошибки сохранения
            log.exception("Ошибка сохранения заметки")
            error = tr("Внутренняя ошибка сохранения (подробности в журнале)")
        if error:
            self.status.config(text=error)
            self.text.focus_set()
            return
        self.status.config(text="")
        self._pending_images.clear()
        self._preview_photos.clear()
        self._renamed.clear()
        self.text.delete("1.0", "end")
        try:
            self.title_var.set("")
            self.name_var.set("")
        except tk.TclError:
            pass
        self._auto_name = ""
        self.hide()

    def exists(self) -> bool:
        try:
            return bool(self.root.winfo_exists())
        except tk.TclError:
            return False

    def retranslate(self) -> None:
        """Обновить все тексты окна после смены языка интерфейса."""
        try:
            self.root.title(tr("Markclip — новая заметка"))
            self.label_title.config(text=tr("Заголовок:"))
            self.label_name.config(text=tr("Имя файла:"))
            self.label_text.config(text=tr("Текст заметки:"))
            self.btn_ok.config(text=tr("ОК"))
            self.btn_cancel.config(text=tr("Отмена"))
            self.hint.config(
                text=tr(
                    "Ctrl+Enter — сохранить, Esc — закрыть, "
                    "Ctrl+V — вставить картинку или текст. "
                    "Правый клик — меню правки."
                )
            )
            menu = self._context_menu
            menu.entryconfig(0, label=tr("Вырезать"))
            menu.entryconfig(1, label=tr("Копировать"))
            menu.entryconfig(2, label=tr("Вставить"))
            menu.entryconfig(4, label=tr("Выделить всё"))
        except tk.TclError:
            log.debug("Не удалось обновить тексты окна заметки", exc_info=True)

    # ------------------------------------------------------------------
    def _focus_again(self) -> None:
        try:
            if self.root.state() == "withdrawn":
                return
            self.root.lift()
            self.text.focus_set()
        except tk.TclError:
            pass

    def _unset_topmost(self) -> None:
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Картинки из буфера
    # ------------------------------------------------------------------
    def _save_pending_images(self) -> Optional[str]:
        """Записать вставленные картинки в папку assets/ заметок.

        Возвращает сообщение об ошибке или ``None``. Файлы пишутся только
        здесь — по нажатию ОК; при Esc или закрытии окна ничего не создаётся.
        """
        notes_dir = self.notes_dir_provider() if self.notes_dir_provider else None
        if not notes_dir:
            return tr("Не задана папка для заметок — вставьте картинку текстом")
        subdir = self._assets_subdir()
        self._renamed.clear()
        for name, data in self._pending_images:
            try:
                relative = save_note_image(notes_dir, name, data, subdir)
            except OSError:
                log.exception("Не удалось сохранить картинку %s", name)
                return tr("Не удалось сохранить картинку (подробности в журнале)")
            expected = "{}/{}".format(subdir, name)
            if relative != expected:
                # файл попал под новое имя (защита от перезаписи или другая
                # папка вложений) — запомним, чтобы поправить ссылку в тексте
                self._renamed[expected] = relative
        return None

    def _assets_subdir(self) -> str:
        """Текущее имя подпапки вложений из настроек (пусто/мусор → assets)."""
        if self.assets_provider:
            try:
                return normalize_subdir(self.assets_provider())
            except Exception:  # noqa: BLE001
                log.debug("Имя папки вложений недоступно", exc_info=True)
        return IMAGES_SUBDIR

    def _fix_image_refs(self, content: str) -> str:
        """Подставить в тексте фактические имена файлов картинок."""
        for expected, actual in self._renamed.items():
            content = content.replace(expected, actual)
        return content


class SettingsWindow:
    """Окно настроек: папка, хоткей, шаблоны, вложения, язык интерфейса.

    :param on_save: ``(notes_dir, hotkey_text, title_template, name_template,
        assets_dir, language, text_template) -> Optional[str]`` — ошибка или
        ``None``, если настройки применены (окно закрывается).
    :param on_capture: начать запись комбинации клавиш из поля хоткея.
    :param on_close: окно закрыто (сюда приложение подчищает ссылку).
    """

    def __init__(
        self,
        parent: tk.Tk,
        *,
        notes_dir: str,
        hotkey: str,
        title_template: str = "",
        name_template: str = "",
        text_template: str = "",
        assets_dir: str = "",
        language: str = "ru",
        on_save: Callable[[str, str, str, str, str, str, str], Optional[str]],
        on_capture: Callable[[], None],
        on_close: Callable[[], None],
    ) -> None:
        self.on_save = on_save
        self.on_capture = on_capture
        self.on_close = on_close
        self._capturing = False

        win = tk.Toplevel(parent)
        self.win = win
        win.title(tr("Markclip — настройки"))
        win.transient(parent)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)

        # -- папка заметок ------------------------------------------------
        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=(0, 8))
        ttk.Label(row1, text=tr("Папка для заметок:"), width=23).pack(side="left")
        self.notes_var = tk.StringVar(value=notes_dir)
        ttk.Entry(row1, textvariable=self.notes_var, width=44).pack(
            side="left", fill="x", expand=True, padx=(0, 6)
        )
        self.btn_browse = ttk.Button(row1, text=tr("Обзор…"), command=self._browse)
        self.btn_browse.pack(side="left")

        # -- хоткей -------------------------------------------------------
        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=(0, 4))
        ttk.Label(row2, text=tr("Глобальный хоткей:"), width=23).pack(side="left")
        self.hotkey_var = tk.StringVar(value=hotkey)
        self.hotkey_entry = ttk.Entry(row2, textvariable=self.hotkey_var, width=44)
        self.hotkey_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.btn_capture = ttk.Button(
            row2, text=tr("Записать"), command=self._start_capture
        )
        self.btn_capture.pack(side="left")

        ttk.Label(
            frame,
            text=tr(
                "Например: Ctrl+Alt+Space, Ctrl+Shift+N, F8.\n"
                "Модификаторы: Ctrl, Alt, Shift, Win; спецклавиши: Space, Enter, "
                "F1–F12, стрелки, PageUp/PageDown.\n"
                "Клавиша «+» в комбинациях не поддерживается."
            ),
            foreground=_MUTED_COLOR,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # -- шаблоны новой заметки ----------------------------------------
        row3 = ttk.Frame(frame)
        row3.pack(fill="x", pady=(0, 4))
        ttk.Label(row3, text=tr("Заголовок по умолчанию:"), width=23).pack(
            side="left"
        )
        self.title_template_var = tk.StringVar(value=title_template)
        ttk.Entry(row3, textvariable=self.title_template_var, width=44).pack(
            side="left", fill="x", expand=True
        )

        row4 = ttk.Frame(frame)
        row4.pack(fill="x", pady=(0, 4))
        ttk.Label(row4, text=tr("Имя файла по умолчанию:"), width=23).pack(
            side="left"
        )
        self.name_template_var = tk.StringVar(value=name_template)
        ttk.Entry(row4, textvariable=self.name_template_var, width=44).pack(
            side="left", fill="x", expand=True
        )

        row_text = ttk.Frame(frame)
        row_text.pack(fill="x", pady=(0, 4))
        ttk.Label(row_text, text=tr("Шаблон текста заметки:"), width=23).pack(
            side="left", anchor="n"
        )
        # многострочное поле: шаблон тела заметки часто содержит переводы
        # строк ({url1}\n\n{text}) — Enter вставляет строку, Ctrl+Enter сохраняет
        self.text_template_text = tk.Text(
            row_text, height=4, width=44, wrap="word", undo=True
        )
        self.text_template_text.insert("1.0", text_template)
        self.text_template_text.pack(side="left", fill="both", expand=True)
        self.text_template_text.bind("<Return>", self._text_template_return)

        row5 = ttk.Frame(frame)
        row5.pack(fill="x", pady=(0, 4))
        ttk.Label(row5, text=tr("Папка вложений:"), width=23).pack(side="left")
        self.assets_var = tk.StringVar(value=assets_dir)
        ttk.Entry(row5, textvariable=self.assets_var, width=44).pack(
            side="left", fill="x", expand=True
        )

        ttk.Label(
            frame,
            text=tr(
                "Шаблоны подставляются в поля новой заметки. Подстановки: "
                "{date} — 2026-10-23, {time} — 21-30-45, "
                "{datetime} — «2026-10-23 21-30-45»; литеральная скобка — {{ .\n"
                "Подстановки по тексту ({text}, {text:90} — первые 90 символов, "
                "{url1} — первая ссылка в тексте) применяются при сохранении.\n"
                "Шаблон текста заметки оборачивает введённый текст: "
                "{text} — сам текст; без него текст дописывается в конец. "
                "Пустой шаблон — текст без изменений.\n"
                "Папка вложений — имя подпапки внутри папки заметок для картинок "
                "из буфера (по умолчанию assets)."
            ),
            foreground=_MUTED_COLOR,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # -- язык интерфейса ----------------------------------------------
        row6 = ttk.Frame(frame)
        row6.pack(fill="x", pady=(0, 4))
        ttk.Label(row6, text=tr("Язык:"), width=23).pack(side="left")
        # список языков — файлы из папки locales рядом с программой
        self.language_codes = available_languages()
        name_to_code = {language_name(code): code for code in self.language_codes}
        self._name_to_code = name_to_code
        self.language_var = tk.StringVar(value=language_name(language))
        self.language_combo = ttk.Combobox(
            row6,
            textvariable=self.language_var,
            values=[language_name(code) for code in self.language_codes],
            state="readonly",
            width=41,
        )
        self.language_combo.pack(side="left", fill="x", expand=True)

        self.error_var = tk.StringVar(value="")
        ttk.Label(
            frame,
            textvariable=self.error_var,
            foreground=_ERROR_COLOR,
            wraplength=440,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        # -- кнопки -------------------------------------------------------
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.btn_save = ttk.Button(buttons, text=tr("Сохранить"), command=self._save)
        self.btn_save.pack(side="right")
        ttk.Button(buttons, text=tr("Отмена"), command=self.close).pack(
            side="right", padx=(0, 8)
        )

        win.bind("<Escape>", lambda _event: self.close())
        win.bind("<Return>", lambda _event: self._save())

        self._center()

    # ------------------------------------------------------------------
    def _center(self) -> None:
        try:
            self.win.update_idletasks()
            width = self.win.winfo_reqwidth()
            height = self.win.winfo_reqheight()
            x = max(0, (self.win.winfo_screenwidth() - width) // 2)
            y = max(0, (self.win.winfo_screenheight() - height) // 3)
            self.win.geometry("+{}+{}".format(x, y))
        except tk.TclError:
            pass

    def show(self) -> None:
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
        except tk.TclError:
            pass

    def focus(self) -> None:
        """Вернуть фокус в уже открытое окно настроек."""
        self.show()

    def exists(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def close(self) -> None:
        """Закрыть окно и уведомить приложение."""
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        try:
            self.on_close()
        except Exception:  # noqa: BLE001
            log.exception("Ошибка закрытия настроек")

    # ------------------------------------------------------------------
    def capture_finished(self, hotkey_text: str, error: Optional[str] = None) -> None:
        """Вызывается приложением: запись комбинации завершена."""
        self._capturing = False
        try:
            self.hotkey_entry.config(state="normal")
            for button in (self.btn_capture, self.btn_save, self.btn_browse):
                button.config(state="normal")
            self.hotkey_var.set(hotkey_text)
            if error:
                self.error_var.set(error)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    def _browse(self) -> None:
        initial = self.notes_var.get().strip() or None
        chosen = filedialog.askdirectory(
            parent=self.win,
            initialdir=initial,
            title=tr("Выберите папку для заметок"),
        )
        if chosen:
            self.notes_var.set(chosen)

    def _start_capture(self) -> None:
        if self._capturing:
            return
        self._capturing = True
        self.error_var.set("")
        self.hotkey_var.set(tr("Нажмите комбинацию клавиш… (Esc — отмена)"))
        self.hotkey_entry.config(state="readonly")
        for button in (self.btn_capture, self.btn_save, self.btn_browse):
            button.config(state="disabled")
        try:
            self.on_capture()
        except Exception:  # noqa: BLE001
            log.exception("Не удалось начать запись комбинации")
            self.capture_finished(
                self.hotkey_var.get(),
                error=tr("Не удалось начать запись комбинации"),
            )

    def _text_template_value(self) -> str:
        """Содержимое многострочного поля шаблона текста одной строкой."""
        try:
            return self.text_template_text.get("1.0", "end-1c")
        except tk.TclError:
            return ""

    def _text_template_return(self, event: tk.Event) -> str:
        """Enter в поле шаблона — новая строка, Ctrl+Enter — сохранить.

        ``"break"`` останавливает дальнейшую обработку, чтобы оконный
        биндинг ``<Return>`` («сохранить настройки») не срабатывал
        при вводе переноса строки.
        """
        if event.state & 0x0004:  # Control — сохранить настройки
            self._save()
        else:
            event.widget.insert(tk.INSERT, "\n")
        return "break"

    def _save(self) -> None:
        if self._capturing:
            return
        language = self._name_to_code.get(
            self.language_var.get().strip(), "ru"
        )
        error = self.on_save(
            self.notes_var.get(),
            self.hotkey_var.get(),
            self.title_template_var.get(),
            self.name_template_var.get(),
            self.assets_var.get(),
            language,
            self._text_template_value(),
        )
        if error:
            self.error_var.set(error)
            return
        self.close()
