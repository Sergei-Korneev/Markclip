#!/usr/bin/env python3
# coding=utf-8
"""Тесты ядра Markclip (без GUI и без реальной регистрации хоткея).

Запуск из корня проекта:

    python3 tests/test_core.py
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_hotkey_normalize() -> None:
    from markclip.hotkey import HotkeyError, display, normalize

    # человекочитаемый ввод → формат pynput
    assert normalize("Ctrl+Alt+Space") == "<ctrl>+<alt>+<space>"
    assert normalize("ctrl+alt+n") == "<ctrl>+<alt>+n"
    assert normalize("<CTRL>+<ALT>+N") == "<ctrl>+<alt>+n"
    assert normalize("Win+Shift+F5") == "<cmd>+<shift>+<f5>"
    assert normalize("Alt+F4") == "<alt>+<f4>"
    assert normalize("n+ctrl+alt") == "<ctrl>+<alt>+n"  # модификаторы вперёд
    assert normalize("Ctrl + Alt + N") == "<ctrl>+<alt>+n"  # пробелы
    assert normalize("Control+P") == "<ctrl>+p"  # синонимы
    assert normalize("Ctrl+PageUp") == "<ctrl>+<page_up>"
    assert normalize("Ctrl+Page Up") == "<ctrl>+<page_up>"
    assert normalize("Windows+T") == "<cmd>+t"

    # round-trip: display → normalize должен давать исходный формат
    for fmt in (
        "<ctrl>+<alt>+<space>",
        "<cmd>+<shift>+t",
        "<f8>",
        "<ctrl>+<alt>+<f12>",
        "<ctrl>+<page_up>",
        "<alt_gr>+z",
        "<shift>+<enter>",
    ):
        assert normalize(display(fmt)) == fmt, fmt

    # некорректный ввод → HotkeyError
    for bad in (
        "",
        "   ",
        "ctrl",          # только модификатор
        "ctrl+alt",      # только модификаторы
        "ctrl+alt+nope", # неизвестная клавиша
        "ctrl+ctrl+a",   # дубль
        "ctrl+alt+",     # лишний +
        "+n",            # ведущий +
        "Ctrl++",        # «+» как клавиша не поддерживается
    ):
        try:
            normalize(bad)
        except HotkeyError:
            pass
        else:
            raise AssertionError("ожидалась ошибка для {!r}".format(bad))


def test_hotkey_display() -> None:
    from markclip.hotkey import display

    assert display("<ctrl>+<alt>+<space>") == "Ctrl+Alt+Space"
    assert display("<cmd>+<shift>+t") == "Win+Shift+T"
    assert display("<alt>+<f4>") == "Alt+F4"
    assert display("<ctrl>+<page_up>") == "Ctrl+Page Up"
    assert display("<alt_gr>+z") == "AltGr+Z"
    assert display("") == ""


def test_config_portable() -> None:
    """Конфиг лежит в самой папке приложения (портативность)."""
    from markclip import config as config_mod
    from markclip.config import Config, app_dir, config_dir, default_notes_dir

    package_dir = Path(config_mod.__file__).resolve().parent
    saved_home = os.environ.pop("MARKCLIP_HOME", None)
    try:
        # папка приложения = корень проекта (рядом с run.py)
        assert app_dir() == package_dir.parent
        assert config_dir() == app_dir()
        # заметки по умолчанию — внутри папки приложения
        assert default_notes_dir() == app_dir() / "notes"
        assert Config(notes_dir="").notes_dir == str(app_dir() / "notes")
        assert Config(hotkey="").hotkey == "<ctrl>+<alt>+<space>"
    finally:
        if saved_home is not None:
            os.environ["MARKCLIP_HOME"] = saved_home

    # переопределение MARKCLIP_HOME (тесты и спецразвёртывания)
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        os.environ["MARKCLIP_HOME"] = tmp
        try:
            assert config_dir() == target

            cfg = Config(
                notes_dir=str(target / "notes-x"),
                hotkey="<f8>",
                title_template="Заметка {date}",
                name_template="{date} {time}",
                text_template="{url1}\n\n{text}",
                assets_dir="вложения",
                link_style="angle",
                language="zh",
            )
            cfg.save()
            assert (target / "config.json").is_file()
            # рядом не должно появиться подпапок вида ~/.config/markclip
            assert not (target / "markclip").exists()

            loaded = Config.load()
            assert loaded.notes_dir == str(target / "notes-x")
            assert loaded.hotkey == "<f8>"
            assert loaded.title_template == "Заметка {date}"
            assert loaded.name_template == "{date} {time}"
            assert loaded.text_template == "{url1}\n\n{text}"
            assert loaded.assets_dir == "вложения"
            assert loaded.link_style == "angle"
            assert loaded.language == "zh"
            # пустой язык приводится к русскому
            assert Config(language="").language == "ru"
            # неизвестный стиль ссылок приводится к обычному
            assert Config().link_style == "plain"
            assert Config(link_style="bogus").link_style == "plain"

            # битый JSON → не падаем
            (target / "config.json").write_text("{oops", encoding="utf-8")
            broken = Config.load()
            assert broken.hotkey
            assert broken.notes_dir
        finally:
            os.environ.pop("MARKCLIP_HOME", None)


def test_notes_write() -> None:
    from markclip.notes import save_note

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "deep" / "notes"

        path = save_note("Привет, мир!\nВторая строка", target)
        assert path is not None and path.is_file()
        assert path.parent == target

        content = path.read_text(encoding="utf-8")
        assert content.startswith("# Заметки за ")
        assert "Привет, мир!" in content
        assert "Вторая строка" in content
        assert re.search(r"(?m)^## \d{2}:\d{2}:\d{2}$", content)

        # вторая заметка — в тот же дневной файл
        again = save_note("Ещё одна", target)
        assert again == path
        merged = path.read_text(encoding="utf-8")
        assert merged.count("## ") >= 2
        assert "Ещё одна" in merged

        # пустой текст не создаёт файлов
        assert save_note("   \n  ", target) is None


def test_notes_image() -> None:
    """Картинки ложатся в assets/ (или свою подпапку) с Markdown-путём."""
    from markclip.notes import (
        IMAGES_SUBDIR,
        normalize_subdir,
        save_note_image,
    )

    assert normalize_subdir("") == IMAGES_SUBDIR
    assert normalize_subdir("   ") == IMAGES_SUBDIR
    assert normalize_subdir(" вложения ") == "вложения"
    assert normalize_subdir("a/b") == "a/b"  # путь из сегментов сохраняется
    assert normalize_subdir("..") == IMAGES_SUBDIR

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        data = b"\x89PNG\r\n\x1a\nfake-png"

        relative = save_note_image(base, "2026-10-23_120000.png", data)
        assert relative == IMAGES_SUBDIR + "/2026-10-23_120000.png"
        file_path = base / relative
        assert file_path.read_bytes() == data

        # повторное имя не перезаписывает файл, а получает новый путь
        other = save_note_image(base, "2026-10-23_120000.png", data + b"!")
        assert other != relative
        assert (base / other).read_bytes() == data + b"!"
        assert file_path.read_bytes() == data

        # своя папка вложений из настроек
        custom = save_note_image(base, "pic.png", data, "вложения")
        assert custom == "вложения/pic.png"
        assert (base / custom).read_bytes() == data


def test_notes_named() -> None:
    """Именованная заметка: заголовок, имя файла, чистка, дописывание."""
    from markclip.notes import sanitize_file_name, save_note_file

    assert sanitize_file_name('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
    assert sanitize_file_name("  ..  ") == ""
    assert sanitize_file_name("просто имя.md") == "просто имя.md"

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        path = save_note_file(base, "текст заметки", title="Идея", name="моя идея")
        assert path == base / "моя идея.md"
        body = path.read_text(encoding="utf-8")
        assert body.startswith("# Идея\n")
        assert "текст заметки" in body

        # имя пустое → файл по заголовку
        path2 = save_note_file(base, "part2", title="Вторая", name="")
        assert path2 == base / "Вторая.md"

        # явное имя совпало с существующим файлом — текст дописывается
        path3 = save_note_file(base, "part3", title="Другое", name="Вторая.md")
        assert path3 == base / "Вторая.md"
        merged = path3.read_text(encoding="utf-8")
        assert merged == "# Вторая\n\npart2\n\npart3\n"
        assert "Другое" not in merged  # заголовок при дописывании не повторяется

        # имя из заголовка чужой файл не трогает — суффикс _2
        path3b = save_note_file(base, "part3b", title="Вторая", name="")
        assert path3b == base / "Вторая_2.md"
        assert "part3b" in path3b.read_text(encoding="utf-8")
        assert path3.read_text(encoding="utf-8") == merged

        # запрещённые символы вычищаются; без заголовка — только текст
        path4 = save_note_file(base, "part4", title="", name="итог: 2026/10")
        assert path4 == base / "итог_ 2026_10.md"
        assert path4.read_text(encoding="utf-8") == "part4\n"

        # ни текста, ни заголовка — сохранять нечего
        assert save_note_file(base, "  ", title=" ") is None


def test_render_template() -> None:
    """Подстановки {date}/{time}/{datetime}/{text}/{text:N}/{url1}."""
    from markclip.gui import render_template

    now = datetime(2026, 10, 23, 21, 30, 45)
    assert render_template("Заметка {date}", now) == "Заметка 2026-10-23"
    assert render_template("{time}", now) == "21-30-45"
    assert render_template("{datetime}", now) == "2026-10-23 21-30-45"
    assert render_template("{date}_{time}", now) == "2026-10-23_21-30-45"
    # литеральная скобка {{ и неизвестные подстановки не ломают вывод
    assert render_template("{{date}} {nope}", now) == "{date} {nope}"
    assert render_template("", now) == ""
    # шаблон без now работает на текущем времени
    assert "{date}" not in render_template("{date}")

    # подстановки по тексту заметки
    text = "Смотри https://example.com/a/path, и ещё хвост."
    assert render_template("{url1}", text=text) == "https://example.com/a/path"
    assert render_template("{url1}", text="без ссылок") == ""
    assert render_template("{text}", text="Привет\nмир") == "Привет\nмир"
    # {text:N} — одна строка, пробелы свёрнуты, обрезка по N
    assert render_template("{text:10}", text="Привет\nмир") == "Привет мир"
    assert render_template("{text:5}", text="Привет\nмир") == "Приве"
    assert render_template("{text:20}", text="короткий") == "короткий"
    # подставленный текст повторно не разбирается
    assert render_template("{text}", text="скобки {{ и {нет}") == "скобки {{ и {нет}"
    # дата и текст вместе
    assert (
        render_template("{date} {text:5}", now, text="abcdefg") == "2026-10-23 abcde"
    )


def test_note_body_template() -> None:
    """Тело заметки по шаблону: {text} — место текста, иначе — в конец."""
    from markclip.gui import (
        first_url,
        has_text_placeholders,
        render_note_body,
    )

    # пустой шаблон — текст без изменений (время в тело не добавляется)
    assert render_note_body("", "Привет") == "Привет"
    assert render_note_body("   ", "Привет") == "Привет"

    # {text} — место текста, {url1} — первая ссылка
    body = render_note_body(
        "{url1}\n\n{text}", "Смотри https://example.com/x — подробно"
    )
    assert body == "https://example.com/x\n\nСмотри https://example.com/x — подробно"

    # подстановки {text} нет — текст дописывается в конец
    assert render_note_body("Заметка:", "мой текст") == "Заметка:\n\nмой текст"
    dated = render_note_body("{date} {time}", "мой текст")
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\n\nмой текст$", dated)

    # шаблон без текста — рендерится сам шаблон
    only = render_note_body("{date} {time}", "")
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}$", only)

    # распознавание текстовых подстановок
    assert has_text_placeholders("{text:90}")
    assert has_text_placeholders("{url1} и {text}")
    assert not has_text_placeholders("{date} {time} {{x}}")

    # первая ссылка: висячая пунктуация отрезается
    assert first_url("а (https://ex.com/path), б") == "https://ex.com/path"
    assert first_url("ссылки нет") == ""


def test_name_from_text_template() -> None:
    """Имя файла из {text:N}: нормализовано и не ломает файловую систему."""
    from markclip.gui import render_template
    from markclip.notes import sanitize_file_name, save_note_file

    text = (
        "Как настроить 1С:ERP? Читай тут https://example.com/1c/erp — "
        "подробно.\nВторая строка с ?:*|<> и прочим мусором"
    )
    name = sanitize_file_name(render_template("{text:90}", text=text))
    assert name
    assert "\n" not in name
    for char in '<>:"/\\|?*':
        assert char not in name
    with tempfile.TemporaryDirectory() as tmp:
        path = save_note_file(Path(tmp) / "notes", text, name=name)
        assert path is not None and path.is_file()
        assert path.stem.startswith(name[:40])


def test_icon() -> None:
    from PIL import Image

    from markclip.icons import make_icon

    img = make_icon(64)
    assert isinstance(img, Image.Image)
    assert img.size == (64, 64)
    # иконка не пустая: есть непрозрачные пиксели
    assert img.getextrema()[3][1] > 0  # альфа-канал
    small = make_icon(16)
    assert small.size == (16, 16)


def test_i18n() -> None:
    """Переключение языков, запасной вариант, язык в настройках."""
    from markclip import i18n

    try:
        # встроенные языки есть в списке, названия читаемы
        for code in ("ru", "en", "zh"):
            assert code in i18n.available_languages()
        assert i18n.language_name("ru") == "Русский"
        assert i18n.language_name("en") == "English"
        assert i18n.language_name("zh") == "中文"

        # русский — базовый: файл не нужен, текст возвращается как есть
        assert i18n.set_language("ru") == "ru"
        assert i18n.tr("Выход") == "Выход"

        # английский
        assert i18n.set_language("en") == "en"
        assert i18n.current_language() == "en"
        assert i18n.tr("Выход") == "Quit"
        # ключ с подстановкой остаётся шаблоном для .format()
        assert "{}" in i18n.tr("Открыть окно заметки ({})")
        # отсутствующий ключ — исходный текст, а не пустая строка
        assert i18n.tr("нет такого ключа") == "нет такого ключа"

        # китайский
        assert i18n.set_language("zh") == "zh"
        assert i18n.tr("Выход") == "退出"

        # регистр кода и пустое значение нормализуются
        assert i18n.set_language("EN") == "en"
        assert i18n.set_language("") == "ru"

        # неизвестный язык → предупреждение и возврат на русский
        assert i18n.set_language("de") == "ru"
        assert i18n.current_language() == "ru"
        assert i18n.tr("Выход") == "Выход"
    finally:
        i18n.set_language("ru")  # не влиять на остальные тесты


def test_i18n_keys() -> None:
    """Каждый ключ tr() из кода присутствует в файлах языков locales/*.json."""
    root = Path(__file__).resolve().parents[1]
    keys = set()
    for path in sorted((root / "markclip").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
    assert keys, "вызовов tr() в коде не найдено"
    for code in ("en", "zh"):
        data = json.loads(
            (root / "locales" / "{}.json".format(code)).read_text(encoding="utf-8")
        )
        missing = keys - set(data)
        assert not missing, "в {}.json нет переводов: {}".format(
            code, sorted(missing)
        )


def test_note_attachment() -> None:
    """Брошенный в окно файл копируется в папку вложений как вложение."""
    from markclip.gui import parse_drop_paths
    from markclip.notes import attach_note_file

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src_dir = base / "src"
        src_dir.mkdir()
        (src_dir / "contract.pdf").write_bytes(b"%PDF-1.4")
        notes = base / "notes"

        # файл копируется в assets с сохранением имени
        rel = attach_note_file(notes, src_dir / "contract.pdf")
        assert rel == "assets/contract.pdf"
        assert (notes / "assets" / "contract.pdf").read_bytes() == b"%PDF-1.4"

        # повторное вложение имени не перезаписывает — суффикс _2
        rel2 = attach_note_file(notes, src_dir / "contract.pdf")
        assert rel2 == "assets/contract_2.pdf"

        # подпапка вложений меняется, имя файла чистится
        weird = src_dir / "a:b*c?.txt"
        weird.write_text("x", encoding="utf-8")
        rel3 = attach_note_file(notes, weird, subdir="files")
        assert rel3 == "files/a_b_c_.txt"

        # маркдаун-спецсимволы в имени рвут ссылку — они вычищаются
        tricky = src_dir / "report (final) [v2]#x%.pdf"
        tricky.write_bytes(b"y")
        rel4 = attach_note_file(notes, tricky)
        assert rel4 == "assets/report _final_ _v2_x_.pdf"

        # стиль angle: скобки и пробелы допустимы, ломающие URL — нет
        rel5 = attach_note_file(notes, tricky, link_style="angle")
        assert rel5 == "assets/report (final) [v2]_x_.pdf"

        # несуществующий файл — None, ничего не создаётся
        assert attach_note_file(notes, src_dir / "missing.pdf") is None

    # пункт назначения ссылки и экранирование её текста
    from markclip.notes import attachment_dest, escape_link_text

    assert attachment_dest("assets/my file.pdf") == "assets/my file.pdf"
    assert (
        attachment_dest("assets/my file.pdf", "angle")
        == "<assets/my file.pdf>"
    )
    assert escape_link_text("a[b]c") == r"a\[b\]c"

    # разбор данных события Drop: пути с пробелами, file://-URI, пустота
    assert parse_drop_paths("{/tmp/a b.png} {/tmp/c.md}") == [
        "/tmp/a b.png",
        "/tmp/c.md",
    ]
    assert parse_drop_paths("/tmp/one.png") == ["/tmp/one.png"]
    assert parse_drop_paths("file:///home/u/pic.png") == ["/home/u/pic.png"]
    assert parse_drop_paths("") == []


def test_assets_dir_template() -> None:
    """Путь папки вложений с подстановкой {$notename} — имени заметки."""
    from pathlib import Path

    from markclip.notes import (
        NOTE_NAME_PLACEHOLDER,
        attachment_file_name,
        normalize_subdir,
        render_assets_dir,
    )

    assert NOTE_NAME_PLACEHOLDER == "{$notename}"
    # шаблон проходит нормализацию как есть (путь из нескольких сегментов)
    assert normalize_subdir("assets/{$notename}") == "assets/{$notename}"
    assert normalize_subdir("assets//{$notename}/") == "assets/{$notename}"
    # мусорные сегменты отбрасываются
    assert normalize_subdir("a//./b") == "a/b"
    assert normalize_subdir("../x") == "x"

    # подстановка имени заметки; имя вычищается вместе с сегментом
    assert render_assets_dir("assets/{$notename}", "My note") == "assets/My note"
    assert render_assets_dir("assets/{$notename}", "a/b") == "assets/a_b"
    # имя неизвестно — сегмент пропадает; пустой шаблон — assets
    assert render_assets_dir("assets/{$notename}", "") == "assets"
    assert render_assets_dir("", "Note") == "assets"

    # имя файла вложения чистится по стилю ссылок
    assert attachment_file_name(Path("report (final).pdf")) == "report _final_.pdf"
    assert (
        attachment_file_name(Path("report (final).pdf"), "angle")
        == "report (final).pdf"
    )


def test_template_conditional() -> None:
    """Условные блоки {имя: тело}: тело выводится при непустой подстановке."""
    from markclip.gui import (
        has_text_placeholders,
        render_note_body,
        render_template,
    )

    # ссылка найдена — тело выводится с подстановкой
    assert (
        render_template("{url1: text {url1} text2}", text="see https://ex.com")
        == "text https://ex.com text2"
    )
    # ссылки нет — блок не даёт ничего
    assert render_template("{url1: text {url1} text2}", text="no link here") == ""
    assert render_template("{url1: only}", text="") == ""

    # условия по тексту и вложенные блоки
    assert render_template("{text: A {text: B {text} C} D}", text="x") == "A B x C D"
    assert render_template("{text: A {text: B} C}", text="") == ""

    # литеральные скобки внутри тела, смешанный текст
    assert (
        render_template("head {url1: ({{ok}} {url1})} tail", text="u https://a.io")
        == "head ({ok} https://a.io) tail"
    )
    assert render_template("head {url1: ({ok})} tail", text="u") == "head  tail"

    # незакрытый блок не роняет разбор
    assert render_template("{url1: unclosed", text="u https://a") == "{url1: unclosed"

    # блоки распознаются как зависящие от текста (ждут сохранения)
    assert has_text_placeholders("{url1: found}")
    assert has_text_placeholders("{text: prefix}")

    # с телом заметки: блок умер — текст без изменений
    assert render_note_body("{url1: src {url1}}", "my text") == "my text"
    assert (
        render_note_body("{url1: src {url1}}", "see https://ex.com x")
        == "src https://ex.com\n\nsee https://ex.com x"
    )


def test_name_autocomplete() -> None:
    """Автопоиск по именам файлов: фильтр по подстроке, сначала префиксы."""
    from markclip.gui import filter_name_choices

    choices = ["Проект", "Входящее", "Проект-план", "2026-10-23"]
    assert filter_name_choices(choices, "") == choices
    # совпадение без учёта регистра, имена с префиксом — вперёд
    assert filter_name_choices(choices, "про") == ["Проект", "Проект-план"]
    assert filter_name_choices(choices, "ект") == ["Проект", "Проект-план"]
    assert filter_name_choices(choices, "ход") == ["Входящее"]
    assert filter_name_choices(choices, "нет") == []


def test_reserved_names() -> None:
    """Имя prn остаётся prn: правка зарезервированных имён — только Windows."""
    import sys

    from markclip.notes import _safe_attachment_stem, save_note_file

    if sys.platform == "win32":
        assert _safe_attachment_stem("prn") == "_prn"
    else:
        assert _safe_attachment_stem("prn") == "prn"
        assert _safe_attachment_stem("PRN") == "PRN"
        assert _safe_attachment_stem("con") == "con"
        with tempfile.TemporaryDirectory() as tmp:
            path = save_note_file(Path(tmp), "text", title="", name="prn")
            assert path == Path(tmp) / "prn.md"
            assert path.read_text(encoding="utf-8") == "text\n"


def test_note_edit_flow() -> None:
    """Выбор заметки из списка: разбор заголовка и перезапись файла."""
    from markclip.notes import save_note_file, split_note_title

    # заголовок # ... уходит отдельно, тело отдельно; ## — не заголовок
    assert split_note_title("# My note\n\nbody text\n") == ("My note", "body text\n")
    assert split_note_title("## stamp\n\nbody") == ("", "## stamp\n\nbody")
    assert split_note_title("just text") == ("", "just text")
    assert split_note_title("") == ("", "")

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        path = save_note_file(base, "first version", title="Note", name="note")

        # перезапись: содержимое заменяется целиком, без суффикса _2
        path2 = save_note_file(
            base, "second version", title="Note 2", name="note", overwrite=True
        )
        assert path2 == path == base / "note.md"
        assert path.read_text(encoding="utf-8") == "# Note 2\n\nsecond version\n"

        # без overwrite — прежний сценарий: дописывание в конец
        save_note_file(base, "third", title="Note 3", name="note")
        assert (
            path.read_text(encoding="utf-8")
            == "# Note 2\n\nsecond version\n\nthird\n"
        )


TESTS = (
    test_hotkey_normalize,
    test_hotkey_display,
    test_config_portable,
    test_notes_write,
    test_notes_image,
    test_notes_named,
    test_render_template,
    test_template_conditional,
    test_note_body_template,
    test_name_from_text_template,
    test_note_attachment,
    test_assets_dir_template,
    test_name_autocomplete,
    test_reserved_names,
    test_note_edit_flow,
    test_i18n,
    test_i18n_keys,
    test_icon,
)


def main() -> int:
    failed = 0
    for test in TESTS:
        try:
            test()
        except Exception:  # noqa: BLE001
            failed += 1
            print("FAIL  {}".format(test.__name__))
            traceback.print_exc()
        else:
            print("ok    {}".format(test.__name__))
    total = len(TESTS)
    print("----")
    print("Итого: {}/{} прошли".format(total - failed, total))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
