# coding=utf-8
"""Иконка трея, нарисованная кодом — без внешних файлов."""

from __future__ import annotations

from PIL import Image, ImageDraw

__all__ = ["make_icon"]

_BACKGROUND = (47, 111, 237, 255)  # синий
_FOREGROUND = (255, 255, 255, 255)  # белые «строки текста»
_ACCENT = (255, 202, 40, 255)  # жёлтая точка-акцент


def make_icon(size: int = 64) -> Image.Image:
    """Квадратная иконка со скруглением: лист с текстом.

    :param size: сторона иконки в пикселях (масштабируется)
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = max(1, size // 16)
    radius = max(3, size // 5)
    draw.rounded_rectangle(
        (pad, pad, size - pad - 1, size - pad - 1),
        radius=radius,
        fill=_BACKGROUND,
    )

    line_width = max(2, size // 14)
    left = size // 4
    right = size - size // 4
    top = max(4, size // 3 - line_width)
    gap = line_width + max(3, size // 16)
    for index in range(3):
        y = top + index * gap
        # последняя строка короче — как в настоящей заметке
        x2 = right if index < 2 else left + (right - left) * 2 // 3
        draw.line((left, y, x2, y), fill=_FOREGROUND, width=line_width)

    dot = max(3, size // 10)
    cx = size - size // 4
    cy = size - size // 4
    draw.ellipse(
        (cx - dot, cy - dot, cx + dot, cy + dot),
        fill=_ACCENT,
    )
    return img


if __name__ == "__main__":
    # Быстрая проверка: python3 -m markclip.icons > icon.png
    import sys

    make_icon(64).save(sys.stdout.buffer, format="PNG")
