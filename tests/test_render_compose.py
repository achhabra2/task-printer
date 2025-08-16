from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from task_printer.printing.render import render_task_with_flair_image


def _locate_dejavu_sans() -> str | None:
    """
    Try to locate a TrueType DejaVuSans.ttf shipped with Pillow so the renderer
    can always resolve a TTF in test environments.
    """
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
    """
    Fraction of (y0..y1) pixels in column x that are darker than threshold.
    Image is expected to be mode 'L' (0=black, 255=white).
    """
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
    """
    Check if a region contains at least some dark pixels (indicating text/flair presence).
    """
    x0 = max(0, min(x0, img.width - 1))
    x1 = max(0, min(x1, img.width - 1))
    y0 = max(0, min(y0, img.height - 1))
    y1 = max(0, min(y1, img.height - 1))
    if x1 <= x0 or y1 <= y0:
        return False
    px = img.load()
    total_dark = 0
    # Sample a grid of points to keep it fast
    xs = range(x0, x1, max(1, (x1 - x0) // 25 or 1))
    ys = range(y0, y1, max(1, (y1 - y0) // 25 or 1))
    for x in xs:
        for y in ys:
            if px[x, y] <= threshold:
                total_dark += 1
                if total_dark >= 3:
                    return True
    return False


@pytest.mark.parametrize("receipt_width,font_size", [(512, 48), (576, 54)])
def test_render_task_with_flair_image_composes_text_separator_and_flair(monkeypatch, receipt_width, font_size):
    # Ensure a reliable TrueType font is available for the renderer
    djv = _locate_dejavu_sans()
    if djv:
        monkeypatch.setenv("TASKPRINTER_FONT_PATH", djv)

    # Build a simple flair image (dark rectangle)
    flair = Image.new("L", (140, 180), 255)
    d = ImageDraw.Draw(flair)
    d.rectangle([0, 0, 139, 179], fill=0)  # solid black block

    # Compose image
    cfg = {"receipt_width": receipt_width, "task_font_size": font_size}
    text = "Task Text Can Wrap In to Multi Line Editing"
    out = render_task_with_flair_image(text, flair, cfg)

    # Basic properties
    assert out.mode == "L"
    assert out.width == receipt_width
    assert out.height > 40

    # Heuristic: find a vertical separator column (mostly dark through the center band)
    y0 = int(out.height * 0.05)
    y1 = int(out.height * 0.95)

    sep_x = None
    # Search within a sensible band (between 25% and 85% width)
    x_search_start = int(out.width * 0.25)
    x_search_end = int(out.width * 0.85)
    for x in range(x_search_start, x_search_end):
        frac = _column_dark_fraction(out, x, y0, y1, threshold=30)
        # The separator is a solid line; accept a high dark fraction as a match
        if frac >= 0.75:
            sep_x = x
            break

    assert sep_x is not None, "Separator line was not detected in the composed image"

    # Validate text area (left of separator) contains some dark pixels (text)
    assert _region_has_dark_pixels(out, 0, max(1, sep_x - 4), y0, y1), "No dark pixels found in text region"

    # Validate flair area (right of separator) contains dark pixels (flair block)
    right_start = min(out.width - 1, sep_x + 5)
    assert _region_has_dark_pixels(out, right_start, out.width - 1, y0, y1), "No dark pixels found in flair region"
