"""
Emoji rasterization helpers for Task Printer.

This module provides a small, focused utility to turn an emoji string
into a Pillow Image. The output is grayscale (mode 'L') so it's safe
for ESC/POS printers and can be composed using the existing
`render_task_with_flair_image` pipeline.

Design notes:
- We try to use a dedicated emoji-capable font when available
  (config key `emoji_font_path`, env `TASKPRINTER_EMOJI_FONT_PATH`, or
  common system emoji fonts like Noto Color Emoji, Segoe UI Emoji, or
  Apple Color Emoji). If not found, we fall back to the regular text
  font via `render.resolve_font` so we at least render a visible glyph
  (often a fallback box) rather than failing.
- Because Pillow and FreeType support for color emoji varies by font
  format, we intentionally render to grayscale; ESC/POS is monochrome
  anyway. This keeps results consistent across environments.
"""

from __future__ import annotations

import logging
import os
from typing import Mapping, Optional
import sys
import glob

from PIL import Image, ImageChops, ImageDraw, ImageFont

from task_printer.core.config import load_config as load_app_config

logger = logging.getLogger(__name__)


def _resolve_text_font_fallback(
    config: Optional[Mapping[str, object]], font_size: int
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """A minimal copy of the text font resolver to avoid circular imports."""
    candidates: list[str] = []
    if config:
        try:
            val = config.get("font_path")  # type: ignore[call-arg]
            if isinstance(val, str) and val.strip():
                candidates.append(val.strip())
        except Exception:
            pass

    env_path = os.environ.get("TASKPRINTER_FONT_PATH")
    if env_path:
        candidates.append(env_path)

    common = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for p in common:
        if p not in candidates:
            candidates.append(p)

    for pth in candidates:
        try:
            return ImageFont.truetype(pth, font_size)
        except Exception:
            continue

    # Try Pillow’s packaged DejaVu as a last resort
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
    # As an absolute fallback, Pillow's default bitmap font
    return ImageFont.load_default()


def _normalize_emoji_for_monochrome(s: str) -> str:
    """
    Best-effort normalization to render something meaningful on monochrome printers.

    - Strips Variation Selector-16 (U+FE0F) and zero-width joiners that can
      force color emoji presentation.
    - Applies a small substitution map to replace popular colored emoji with
      similar black-and-white Unicode symbols that are widely available in
      standard fonts.
    """
    if not s:
        return s
    # Remove common variant selectors / ZWJ
    s = s.replace("\ufe0f", "").replace("\u200d", "")
    subs = {
        "✅": "✔",  # white heavy check mark -> heavy check mark
        "✔️": "✔",
        "❌": "✖",
        "✖️": "✖",
        "⭐": "★",
        "✨": "✦",
        "⚠️": "⚠",
        "❤️": "❤",
        "❤": "❤",
        "🖤": "♥",
        "💔": "♥",
        "➡️": "→",
        "⬅️": "←",
        "⬆️": "↑",
        "⬇️": "↓",
        "🔺": "▲",
        "🔻": "▼",
        "🔸": "◆",
        "🔹": "◆",
        "⭕": "◯",
        "🔲": "■",
        "🔳": "□",
    }
    # If entire string is a single known emoji, replace it
    if s in subs:
        return subs[s]
    return s


def resolve_emoji_font(
    config: Optional[Mapping[str, object]],
    font_size: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Resolve a font suitable for emoji rendering.

    Preference order:
      1) config["emoji_font_path"]
      2) env TASKPRINTER_EMOJI_FONT_PATH
      3) common system emoji fonts (Noto Color Emoji, Segoe UI Emoji, Apple Color Emoji)
      4) fallback to the regular text font resolver
    """
    candidates: list[str] = []

    if config:
        try:
            val = config.get("emoji_font_path")  # type: ignore[call-arg]
            if isinstance(val, str) and val.strip():
                candidates.append(val.strip())
        except Exception:
            pass

    env_path = os.environ.get("TASKPRINTER_EMOJI_FONT_PATH")
    if env_path:
        candidates.append(env_path)

    # Common emoji fonts across platforms
    common_fonts = [
        # Prefer monochrome emoji fonts when present
        "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoEmoji.ttf",
        "/usr/local/share/fonts/NotoEmoji-Regular.ttf",
        "/usr/share/fonts/opentype/openmoji/OpenMoji-Black.ttf",
        "/usr/share/fonts/truetype/ancient-scripts/Symbola.ttf",
        # Linux (various distros)
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/NotoColorEmoji.ttf",
        "/usr/local/share/fonts/NotoColorEmoji.ttf",
        # Windows
        "C:/Windows/Fonts/seguiemj.ttf",
        # macOS (Apple Color Emoji is typically a TTC)
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "/System/Library/Fonts/Supplemental/Apple Color Emoji.ttc",
    ]
    for p in common_fonts:
        if p not in candidates:
            candidates.append(p)

    # Add platform-specific scan for installed fonts (e.g., macOS Font Book)
    try:
        search_dirs: list[str] = []
        if sys.platform == "darwin":
            search_dirs.extend(
                [
                    "/Library/Fonts",
                    os.path.expanduser("~/Library/Fonts"),
                    "/System/Library/Fonts",
                    "/System/Library/Fonts/Supplemental",
                ],
            )
        elif os.name == "nt":
            search_dirs.append("C:/Windows/Fonts")
        else:
            search_dirs.extend(["/usr/share/fonts", "/usr/local/share/fonts", "/usr/share/fonts/opentype", "/usr/share/fonts/truetype"]) 

        patterns = [
            "*NotoEmoji*.ttf",
            "*OpenMoji-Black*.ttf",
            "*Symbola*.ttf",
        ]
        for d in search_dirs:
            for pat in patterns:
                for path in glob.glob(os.path.join(d, pat)):
                    if path not in candidates:
                        candidates.append(path)
    except Exception:
        pass

    for pth in candidates:
        try:
            # Pillow supports TTC in many cases; if not, this will raise and fall through.
            return ImageFont.truetype(pth, font_size)
        except Exception:
            continue

    # Fallback: use the regular text font so we get some visible glyph
    logger.debug("No emoji-specific font found; falling back to text font")
    return _resolve_text_font_fallback(config or {}, font_size)


def rasterize_emoji(
    emoji: str,
    target_height: Optional[int] = None,
    config: Optional[Mapping[str, object]] = None,
) -> Image.Image:
    """
    Rasterize an emoji string to a grayscale Pillow image (mode 'L').

    Args:
      emoji: The emoji string (can be multi-codepoint, e.g., with skin tones).
      target_height: Desired output height in pixels. If None, uses
        `flair_target_height` or 256 as a default.
      config: Optional config mapping for font and sizing hints.

    Returns:
      A 'L' mode image with the emoji rendered in black on white background,
      sized to `target_height` while preserving aspect ratio.
    """
    cfg = config or load_app_config() or {}

    try:
        th = int(target_height if target_height is not None else cfg.get("flair_target_height", 256))
    except Exception:
        th = 256
    th = max(8, min(1024, th))

    # Initial font size: aim to fill roughly the target height; we'll crop any extra
    font_size = int(cfg.get("emoji_font_size", th))
    font = resolve_emoji_font(cfg, font_size)
    # Normalize for monochrome rendering and better availability
    emoji = _normalize_emoji_for_monochrome(emoji)

    # Render on an oversized canvas to avoid clipping ascenders/descenders
    pad = max(4, th // 8)
    canvas_w = max(64, th * 2)
    canvas_h = max(64, th * 2)
    img = Image.new("L", (canvas_w, canvas_h), 255)
    draw = ImageDraw.Draw(img)

    # Draw near top-left with padding; we will crop afterwards
    try:
        draw.text((pad, pad), emoji, font=font, fill=0)
    except Exception as e:
        # As a last resort, render a simple placeholder box with the emoji string
        logger.warning(f"Emoji draw failed; using placeholder: {e}")
        draw.rectangle([pad, pad, canvas_w - pad, canvas_h - pad], outline=0, width=3)
        draw.text((pad * 2, pad * 2), emoji[:3], fill=0)

    # Compute tight bounding box around the drawn content
    bbox = ImageChops.invert(img).getbbox()
    if not bbox:
        # If nothing was drawn (unlikely), return a small placeholder
        ph = Image.new("L", (th, th), 255)
        d = ImageDraw.Draw(ph)
        d.rectangle([1, 1, th - 2, th - 2], outline=0)
        return ph

    cropped = img.crop(bbox)

    # Scale to target height preserving aspect ratio
    if cropped.height != th:
        ratio = th / float(max(1, cropped.height))
        new_w = max(1, int(round(cropped.width * ratio)))
        cropped = cropped.resize((new_w, th), Image.LANCZOS)

    return cropped


__all__ = ["resolve_emoji_font", "rasterize_emoji"]
