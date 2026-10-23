# Markclip — quick Markdown notes from the system tray

> Русская версия: [README.md](README.md)

A **cross-platform** (Linux and Windows; the code also carries macOS paths)
system-tray application: hit a global hotkey, type your text, press Enter —
it is appended to a Markdown file right away. Handy for on-the-go notes:
ideas, links, todos. Fully portable — just move the program folder
(even from a USB stick) and point the notes folder at an **Obsidian**
vault if you use one (see below).

## Features

* **Global hotkey** (default `Ctrl+Alt+Space`) opens a compact input window
  over any application.
* **One-movement notes**: text → `Enter` or `Ctrl+Enter` → done.
  `Escape` closes without saving.
* **Smart `Ctrl+V`** (and `Shift+Insert`): a single paste command for
  everything — the app checks what is in the clipboard: an image →
  an attachment file and a Markdown link in the text, text → a plain
  text insert.
* **Editor-style editing**: right-click in the note fields for a
  Cut/Copy/Paste/Select All context menu; the same actions are on
  `Ctrl+X`/`Ctrl+C`/`Ctrl+V`/`Ctrl+A` (plus `Ctrl+Insert`/`Shift+Insert`/
  `Shift+Delete`).
* **Images in notes**: `Ctrl+V` pastes an image from the clipboard
  (screenshot, image from a browser). The file is stored in
  `<notes folder>/assets/`, an inline preview appears in the input window,
  and a Markdown link `![image](assets/...)` goes into the note text.
  Works on Linux/X11, Windows and macOS.
* **Title and file name** — optional fields right in the note form.
  Fill them in and the note is saved as a standalone `<name>.md` file
  (the title goes on the first line as `# ...`); leave them empty and
  it behaves as before — appended to the daily `YYYY-MM-DD.md`. The file
  name follows the title automatically until you edit it by hand;
  existing files are never overwritten — a `_2` suffix is added.
  Both fields can be pre-filled with templates — date/time, the first
  N characters of the text, the first link (see below).
* **Daily Markdown files** `YYYY-MM-DD.md` in the configured folder, each
  note stamped with `## HH:MM:SS`. Open them in any Markdown editor and
  sync them as plain text.
* **Tray icon** (Linux and Windows) with a menu: open the window,
  settings, quit.
* **Settings**: notes folder, hotkey, default title/file-name/note-text
  templates for new notes, the attachments folder name and the interface
  language. No need to type the shortcut as a string — the “Record
  shortcut” button remembers whatever you press.
* **Interface languages**: Russian, English and Chinese — switch them in
  settings, the whole UI changes at once (see “Languages”).
* **Portability**: `config.json`, the `markclip.log` journal and the default
  notes folder (`notes/`) live **right next to the program** — just pick
  the folder up and move it.

Example note (with the interface in English):

```markdown
# Notes for 2026-10-23

## 14:05:12

Call Ivan about the contract

## 14:07:41

Idea: https://example.com/article about logistics

## 14:08:03

![image](assets/2026-10-23_140803.png)
```

## Requirements

* **Python 3.10 or newer** (Linux, Windows).
* **Linux**: X11. On pure Wayland the global hotkeys go through Xwayland
  and may not work everywhere (see “Troubleshooting”).
* A **full tray menu on Linux** needs PyGObject — the installer warns
  if it is missing.

## Installation

### Linux

```bash
./install.sh
```

The script creates a `.venv` virtual environment and installs the
dependencies. If the system has no kernel headers (typical for `evdev`,
a pynput dependency), the installer falls back to installing pynput
without dependencies — global hotkeys on X11 do not need evdev; the
X11/RECORD backend is used.

For a full tray menu install PyGObject system-wide (see “Troubleshooting”).

### Windows

Run `install.bat` (Python must be on PATH; when installing Python, tick
“Add python.exe to PATH”).

## Running

| System | Command |
|---|---|
| Linux | `./run.sh` |
| Windows | `run.bat` |

Command-line keys:

* `--note` (`-n`) — open the note window immediately;
* `--settings` (`-s`) — open the settings right away (a fallback entry
  when the tray menu is unavailable);
* `--version` — print the version; `--help` — usage.

Once started, the program sits in the tray: icon + hotkey.

## Settings

The **“Settings…”** item in the tray menu:

* **Notes folder** — where the Markdown files are written (default
  `<program folder>/notes`);
* **Hotkey** — the shortcut that opens the window. The **“Record shortcut”**
  button captures your next keypress (e.g. `F8` or `Ctrl+Alt+N`).
  Letters, digits, function keys, arrows, space and the modifiers
  `Ctrl`, `Alt`, `Shift`, `Win` are supported. The `+` key cannot be
  used in a shortcut.
* **Default title** — a template put into the “Title” field whenever an
  empty form opens (a draft is never overwritten). Placeholders:
  `{date}` — 2026-10-23, `{time}` — 21-30-45, `{datetime}` —
  “2026-10-23 21-30-45”, a literal brace — `{{`. Leave empty to keep
  the field blank. Text-based placeholders (`{text}`, `{text:90}`,
  `{url1}` — see below) are applied on save, once the text is typed,
  so they do not fill the field on open.
* **Default file name** — a template for the “File name” field (same
  placeholders, including `{text:90}` — the first 90 characters of the
  note text; the name is normalized: forbidden characters and line
  breaks are replaced, the edges are trimmed and the length is capped).
  While the template is set, the name no longer follows the title
  automatically.
* **Note text template** — wraps the typed text on save: `{text}` is
  where the text goes, `{url1}` — the first `http(s)://` link in it,
  `{date}`/`{time}`/`{datetime}` — the save moment. If the template
  has no `{text}`, the text is appended at the end. Leave empty
  (the default) and the text is saved as-is — no time is put into
  the note body.
* **Attachments folder** — the name of the subfolder inside the notes
  folder where clipboard images are stored (default `assets`);
* **Language** — the interface language: `Русский`, `English`, `中文`.
  The choice takes effect as soon as you press “Save” — open windows
  and the tray menu are switched immediately.

Settings are stored in `config.json` **in the program folder itself**
(portability), and so is the `markclip.log` diagnostics journal.
For special cases the state folder can be overridden with the
`MARKCLIP_HOME` environment variable (also used by the tests):

```bash
MARKCLIP_HOME=/tmp/markclip-state ./run.sh
```

A hotkey typed manually into `config.json` is canonicalized automatically
(`<ctrl>+<alt>+<n>` → `<ctrl>+<alt>+n`). If the combination cannot be
applied, `Ctrl+Alt+Space` is used for the session instead and your
settings file is not rewritten.

## Languages

The interface is localized into **Russian** (the base language),
**English** and **Chinese**. The language is chosen in settings and
stored in `config.json` (the `language` key). Everything is translated:
the note and settings windows, the tray menu, error messages, the
`--help` text; even the daily file heading is written in the selected
language (`# Заметки за …` / `# Notes for …` / `# … 的笔记`).

Language files live in the `locales/` folder next to the program:

```
locales/
├── en.json   # English
└── zh.json   # 中文
```

**Adding your own language**: copy any file, e.g. `locales/en.json` →
`locales/de.json`, translate the values (the keys are the original
Russian strings — leave them alone) and restart the program — the
language appears in the settings list by itself. Unknown keys and a
missing file simply fall back to Russian; nothing breaks.

Notes:

* inside the built `Markclip.exe` the languages are bundled into the
  file, but a `locales/` folder next to the exe takes priority —
  translations can be edited without rebuilding;
* displaying Chinese on Linux requires an installed CJK font
  (e.g. `wqy-zenhei` or `noto-cjk`); on Windows the system fonts
  already cover it.

## Using with Obsidian

Markclip writes plain Markdown with no application-specific format, which
makes it a great “quick capture” companion for an
[Obsidian](https://obsidian.md) knowledge base:

1. In settings, point the notes folder at your Obsidian vault (or a
   subfolder of it) — e.g. `~/Obsidian/KB/Inbox`.
2. Notes show up in Obsidian immediately: Obsidian picks up file changes
   on disk, nothing needs restarting.
3. **Named notes** (the “Title”/“File name” fields) become ready-made
   pages with an H1 heading. **Daily notes** are written as
   `2026-10-23.md` files, same as the Daily Notes plugin.
4. Images pasted from the clipboard live in an `assets/` subfolder (the
   name is configurable in settings) and the links are relative, so
   Obsidian opens them fine. If you would rather have images stored in
   Obsidian's own attachments folder, set “Attachments → Default location
   for new attachments” in Obsidian.
5. The settings templates turn quick captures into ready-made pages:
   e.g. title `Note {date}`, file name `{text:90}` (a name built from
   the first 90 characters of the text) and note text `{url1}\n\n{text}` —
   every capture is saved as a separate page with its first link on top.

Tip: keep Markclip in autostart and use it as an input field for Obsidian —
capture from any application in one keystroke, then structure and work
with the knowledge base inside Obsidian.

## Autostart

**Linux** — file `~/.config/autostart/markclip.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Markclip
Exec=/path/to/markclip/run.sh
Terminal=false
```

**Windows** — a shortcut to `run.bat` in the `shell:startup` folder
(Win+R → `shell:startup`).

## Building a portable app

A single file via PyInstaller:

**Windows** (after `install.bat` and `.venv\Scripts\pip install pyinstaller`):

```bat
build_windows.bat
```

The result is `dist\Markclip.exe`; `config.json`, `markclip.log` and `notes\`
are created next to it.

**Linux**:

```bash
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller --noconfirm --windowed --onefile --name Markclip \
    --collect-submodules pynput --collect-submodules pystray \
    --add-data "locales:locales" run.py
```

## Troubleshooting

Everything is written to `markclip.log` next to the program.

* **No icon in the tray (Linux).** A working tray host is required:
  in GNOME — the AppIndicator extension; in KDE it is built in; in tiling
  WMs (i3, sway) — trayer/stalonetray or a bar with tray support.
  Check for a host: `xprop -root _NET_SYSTEM_TRAY_SELECTION` (X11) —
  empty means no host.
* **Tray menu unavailable / startup warning.** PyGObject is missing and
  the reduced xorg backend is in use (icon without a menu). Install:

  | Distribution | Command |
  |---|---|
  | Fedora | `sudo dnf install python3-gi python3-gobject-gtk gir1.2-gtk-3.0 gnome-shell-extension-appindicator` |
  | Ubuntu/Debian | `sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1` |

  At any rate, settings open without the menu too: `./run.sh --settings`.
* **Hotkey does not fire (Wayland).** Global keyboard capture works via
  Xwayland: if the application appears in `xdotool getactivewindow`,
  it will work. Otherwise use an X11 session for now or launch Markclip
  with the `--note` key.
* **The window does not open on the hotkey** — check `markclip.log`,
  the reason is logged there (e.g. the combination is taken by another
  program).

## Tests

```bash
.venv/bin/python tests/test_core.py
```

They cover hotkey normalization, portable settings storage, writing
Markdown notes (daily and named), saving images, template substitution,
drawing the icon and the completeness of the language files (no network
or display required).

## Project structure

```
markclip/
├── run.py            # entry point
├── markclip/
│   ├── app.py        # main class: events, windows, settings, startup
│   ├── gui.py        # note window and settings window (Tkinter)
│   ├── tray.py       # tray icon and menu (pystray)
│   ├── hotkey.py     # hotkey formats, global listener (pynput)
│   ├── clipboard.py  # reading images from the clipboard (Pillow)
│   ├── config.py     # config.json in the program folder (portability)
│   ├── i18n.py       # interface languages (tr, set_language)
│   ├── notes.py      # daily and named notes, assets/ images
│   └── icons.py      # tray icon drawing (Pillow)
├── locales/          # interface translations: en.json, zh.json
├── tests/test_core.py
├── install.sh / install.bat
├── run.sh / run.bat
└── build_windows.bat
```
