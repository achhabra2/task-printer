from pathlib import Path

import pytest
from PIL import Image

from task_printer.printing.render import render_task_with_emoji


def _locate_dejavu_sans() -> str | None:
    try:
        import PIL  # type: ignore

        pil_dir = Path(PIL.__file__).resolve().parent
        candidates = [
            pil_dir / "fonts" / "DejaVuSans.ttf",
            pil_dir / "Tests" / "fonts" / "DejaVuSans.ttf",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    except Exception:
        pass
    return None


def _column_dark_fraction(img: Image.Image, x: int, y0: int, y1: int, threshold: int = 40) -> float:
    y0 = max(0, min(y0, img.height - 1))
    y1 = max(0, min(y1, img.height - 1))
    if y1 <= y0:
        return 0.0
    px = img.load()
    total = y1 - y0 + 1
    dark = 0
    for y in range(y0, y1 + 1):
        if px[x, y] <= threshold:
            dark += 1
    return dark / float(total)


def _region_has_dark_pixels(img: Image.Image, x0: int, x1: int, y0: int, y1: int, threshold: int = 60) -> bool:
    x0 = max(0, min(x0, img.width - 1))
    x1 = max(0, min(x1, img.width - 1))
    y0 = max(0, min(y0, img.height - 1))
    y1 = max(0, min(y1, img.height - 1))
    if x1 <= x0 or y1 <= y0:
        return False
    px = img.load()
    # Sample a coarse grid of pixels
    xs = range(x0, x1, max(1, (x1 - x0) // 25 or 1))
    ys = range(y0, y1, max(1, (y1 - y0) // 25 or 1))
    hits = 0
    for x in xs:
        for y in ys:
            if px[x, y] <= threshold:
                hits += 1
                if hits >= 3:
                    return True
    return False


@pytest.mark.parametrize("receipt_width,font_size", [(512, 48), (576, 54)])
def test_render_task_with_emoji_composes_and_shows_separator(monkeypatch, receipt_width, font_size):
    # Ensure we have a TrueType font for text fallback
    djv = _locate_dejavu_sans()
    if djv:
        monkeypatch.setenv("TASKPRINTER_FONT_PATH", djv)

    cfg = {"receipt_width": receipt_width, "task_font_size": font_size}
    out = render_task_with_emoji("Task With Emoji", "✅", cfg)

    assert out.mode == "L"
    assert out.width == receipt_width
    assert out.height > 40

    # Find separator column
    y0 = int(out.height * 0.05)
    y1 = int(out.height * 0.95)
    sep_x = None
    for x in range(int(out.width * 0.25), int(out.width * 0.85)):
        if _column_dark_fraction(out, x, y0, y1, threshold=30) >= 0.75:
            sep_x = x
            break
    assert sep_x is not None

    # Validate both text (left) and emoji region (right) have dark pixels
    assert _region_has_dark_pixels(out, 0, max(1, sep_x - 3), y0, y1)
    assert _region_has_dark_pixels(out, min(out.width - 1, sep_x + 4), out.width - 1, y0, y1)

