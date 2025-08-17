"""
Text rendering utilities for Task Printer.

Extracted responsibilities from the monolithic app:
- Resolve a font from config/env/common locations
- Render large wrapped text into a grayscale Pillow image suitable for ESC/POS printers
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

from task_printer.core.config import load_config as load_app_config

logger = logging.getLogger(__name__)


def _measure_text(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, text: str) -> tuple[int, int]:
    """
    Robust text measurement across Pillow font types.
    Tries getbbox() first, then getsize(), then getmask() as fallback.
    Returns (width, height).
    """
    try:
        bbox = font.getbbox(text)
        return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
    except Exception:
        try:
            # Deprecated but widely available
            w, h = font.getsize(text)  # type: ignore[attr-defined]
            return int(w), int(h)
        except Exception:
            try:
                mask = font.getmask(text)  # type: ignore[attr-defined]
                # getmask().size returns (width, height)
                return int(mask.size[0]), int(mask.size[1])
            except Exception:
                return 0, 0


def resolve_font(
    config: Optional[Mapping[str, object]],
    font_size: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Resolve a TTF font to use for rendering, preferring:
    1) config["font_path"] when provided
    2) TASKPRINTER_FONT_PATH environment variable
    3) A list of common system font paths (DejaVu, FreeSans, Liberation, Noto, Arial)
    Falls back to PIL's default bitmap font if none are found.

    Returns:
        An ImageFont instance (TrueType when available, otherwise PIL default).
    """
    candidates: List[str] = []
    cfg_path = None
    if config:
        # config may not have the key; be tolerant
        try:
            val = config.get("font_path")  # type: ignore[call-arg]
            if isinstance(val, str) and val.strip():
                cfg_path = val.strip()
        except Exception:
            cfg_path = None

    env_path = os.environ.get("TASKPRINTER_FONT_PATH")

    if cfg_path:
        candidates.append(cfg_path)
    if env_path and env_path not in candidates:
        candidates.append(env_path)

    common: Sequence[str] = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    )
    for pth in common:
        if pth not in candidates:
            candidates.append(pth)

    for pth in candidates:
        try:
            return ImageFont.truetype(pth, font_size)
        except Exception:
            continue

    # Attempt to use a packaged DejaVuSans.ttf from the Pillow installation as a last-resort TrueType font
    try:
        from pathlib import Path

        import PIL  # type: ignore

        pil_dir = Path(PIL.__file__).resolve().parent
        for rel in ("fonts/DejaVuSans.ttf", "Tests/fonts/DejaVuSans.ttf"):
            candidate = pil_dir / rel
            if candidate.exists():
                return ImageFont.truetype(str(candidate), font_size)
    except Exception:
        pass
    raise RuntimeError("No TTF font found; install DejaVuSans or set TASKPRINTER_FONT_PATH")


def wrap_text(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int) -> List[str]:
    """
    Greedy word-wrapping for a given pixel width. Uses font.getbbox to measure width.

    Args:
        text: The input text to wrap.
        font: Pillow font used for measurement.
        max_width: Maximum pixel width available for text.

    Returns:
        List of wrapped lines.
    """
    if not text:
        return [""]

    words = text.split()
    lines: List[str] = []
    current_line = ""

    for word in words:
        test_line = current_line + (" " if current_line else "") + word
        w, _ = _measure_text(font, test_line)
        if w <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines or [""]


def render_large_text_image(text: str, config: Optional[Mapping[str, object]] = None) -> Image.Image:
    """
    Render the provided text into a grayscale Pillow Image suitable for ESC/POS printing.

    Config keys used (with defaults):
      - receipt_width: int (default 512)
      - task_font_size: int (default 72)
      - font_path: optional, resolved by resolve_font()

    Args:
        text: The text to render.
        config: Optional config mapping. If None, load_config() will be used.

    Returns:
        A 'L' mode PIL Image where black=0 and white=255.
    """
    cfg = config or load_app_config()
    if cfg is None:
        raise RuntimeError("No config found. Please complete setup at /setup.")

    try:
        width = int(cfg.get("receipt_width", 512))  # type: ignore[arg-type]
    except Exception:
        width = 512

    try:
        font_size = int(cfg.get("task_font_size", 72))  # type: ignore[arg-type]
    except Exception:
        font_size = 72

    font = resolve_font(cfg, font_size)

    # Margins and spacing
    left_margin = 0
    right_margin = 0
    top_margin = 10
    extra_spacing = 10

    max_text_width = max(1, width - (left_margin + right_margin))
    lines = wrap_text(text or "", font, max_text_width)

    # Derive line height from bounding box of a representative glyph
    _, line_height = _measure_text(font, "A")
    line_height = max(1, line_height)

    img_height = top_margin * 2 + (line_height + extra_spacing) * len(lines)
    img = Image.new("L", (int(width), int(img_height)), 255)
    draw = ImageDraw.Draw(img)

    y = top_margin
    for line in lines:
        draw.text((left_margin, y), line, font=font, fill=0)
        y += line_height + extra_spacing

    return img


def render_task_with_flair_image(
    text: str,
    flair_image: Image.Image | str,
    config: Optional[Mapping[str, object]] = None,
) -> Image.Image:
    """
    Compose a single grayscale image that contains:
    - Wrapped task text on the left
    - A vertical separator line
    - The flair image on the right

    The overall canvas width follows `receipt_width` from config.
    The text block width and flair block width are automatically balanced so
    that the text has enough room while the flair image remains readable.

    Args:
        text: The task text to render (wrapped).
        flair_image: A PIL Image or a filesystem path to an image.
        config: Optional config mapping; if None, the saved config is loaded.

    Returns:
        A single 'L' mode PIL Image ready for ESC/POS printing.
    """
    cfg = config or load_app_config()
    if cfg is None:
        raise RuntimeError("No config found. Please complete setup at /setup.")

    # Resolve printing width and font
    try:
        width = int(cfg.get("receipt_width", 512))  # type: ignore[arg-type]
    except Exception:
        width = 512
    try:
        font_size = int(cfg.get("task_font_size", 72))  # type: ignore[arg-type]
    except Exception:
        font_size = 72
    font = resolve_font(cfg, font_size)

    # Load flair image (path or PIL Image)
    try:
        if isinstance(flair_image, Image.Image):
            flair_img = flair_image.convert("L")
        else:
            flair_img = Image.open(flair_image).convert("L")
    except Exception:
        # If flair loading fails, fall back to text-only rendering.
        return render_large_text_image(text, cfg)

    # Layout constants
    left_margin = 0
    right_margin = 0
    top_margin = 10
    extra_spacing = 10

    # Separator and gaps (configurable)
    sep_width = int(cfg.get("flair_separator_width", 3))
    gap_sep = int(cfg.get("flair_separator_gap", 14))
    gap_before_sep = gap_sep
    gap_after_sep = gap_sep

    # Fixed right column content width for flair (configurable), target 256px by default
    flair_content_target = int(cfg.get("flair_col_width", 256))

    # Keep a reasonable minimum text width; allow override via config
    min_text_width = int(cfg.get("min_text_width", max(180, int(width * 0.45))))

    # Total width consumed by the right block (separator + gaps + flair content)
    flair_block_width = gap_before_sep + sep_width + gap_after_sep + flair_content_target

    # Compute text column width from the remaining space
    text_col_width = width - left_margin - right_margin - flair_block_width

    # If text would be too cramped, shrink the flair content target slightly (but keep consistent as much as possible)
    if text_col_width < min_text_width:
        delta = min_text_width - text_col_width
        flair_content_target = max(128, flair_content_target - delta)
        flair_block_width = gap_before_sep + sep_width + gap_after_sep + flair_content_target
        text_col_width = width - left_margin - right_margin - flair_block_width
        # Clamp to valid range and log layout inputs
        text_col_width = max(text_col_width, 1)
        flair_content_target = max(flair_content_target, 1)
        logger.debug(
            "layout pre-wrap: width=%d, text_col=%d, flair_target=%d, flair_block=%d, min_text=%d",
            width,
            text_col_width,
            flair_content_target,
            flair_block_width,
            min_text_width,
        )

    # If still impossible, fall back to text-only image
    if text_col_width <= 0 or flair_content_target <= 0:
        return render_large_text_image(text, cfg)

    # Wrap text for the left column
    lines = wrap_text(text or "", font, text_col_width)
    _, line_height = _measure_text(font, "A")
    line_height = max(1, line_height)
    text_block_height = top_margin * 2 + (line_height + extra_spacing) * len(lines)

    # Scale flair image to fit the fixed right column content area
    fw, fh = max(1, flair_img.width), max(1, flair_img.height)
    flair_target_height = int(cfg.get("flair_target_height", 256))
    # Allow tasteful upscaling (cap via flair_icon_scale_max) and fit within a fixed right column area
    ratio = min(flair_content_target / float(fw), flair_target_height / float(fh))
    ratio = max(0.01, min(ratio, float(cfg.get("flair_icon_scale_max", 2.0))))
    new_w = max(1, int(round(fw * ratio)))
    new_h = max(1, int(round(fh * ratio)))
    logger.debug(
        "flair scale: src=(%d,%d) ratio=%.3f -> new=(%d,%d), target_h=%d, target_w=%d",
        fw,
        fh,
        ratio,
        new_w,
        new_h,
        flair_target_height,
        flair_content_target,
    )
    if (new_w, new_h) != (fw, fh):
        flair_img = flair_img.resize((new_w, new_h), Image.LANCZOS)

    # Final canvas height is based on text height vs a fixed flair target area
    flair_total_h = top_margin * 2 + flair_target_height
    out_h = max(text_block_height, flair_total_h)

    # Compose canvas
    out_img = Image.new("L", (int(width), int(out_h)), 255)
    draw = ImageDraw.Draw(out_img)

    # Draw text
    y = top_margin
    for line in lines:
        draw.text((left_margin, y), line, font=font, fill=0)
        y += line_height + extra_spacing

    # Anchor separator and flair area to the right for consistency
    flair_right = width - right_margin
    flair_left = flair_right - flair_content_target

    # Draw vertical separator (to the immediate left of the flair block)
    sep_x_left = flair_left - gap_before_sep - sep_width
    # Clamp separator into drawable area
    sep_x_left = max(left_margin, min(sep_x_left, width - right_margin - sep_width))
    logger.debug(
        "layout post-wrap: width=%d text_w=%d flair_w=%d sep_x=%d flair_left=%d flair_right=%d out_h=%d",
        width,
        text_col_width,
        flair_content_target,
        int(sep_x_left),
        int(flair_left),
        int(flair_right),
        out_h,
    )
    draw.rectangle(
        [int(sep_x_left), top_margin, int(sep_x_left + sep_width - 1), out_h - top_margin],
        fill=0,
    )

    # Paste flair image centered within the right content area, vertically centered in available space
    flair_x = int(flair_left + max(0, (flair_content_target - new_w) // 2))
    flair_y = int(top_margin + max(0, (out_h - (top_margin * 2) - new_h) // 2))
    # Clamp paste position to canvas bounds
    flair_x = max(0, min(flair_x, width - new_w))
    flair_y = max(0, min(flair_y, out_h - new_h))
    logger.debug(
        "paste flair at (%d,%d) size=(%d,%d); separator at %d",
        flair_x,
        flair_y,
        new_w,
        new_h,
        int(sep_x_left),
    )
    out_img.paste(flair_img, (flair_x, flair_y))

    return out_img


__all__ = ["render_large_text_image", "render_task_with_flair_image", "resolve_font", "wrap_text"]
