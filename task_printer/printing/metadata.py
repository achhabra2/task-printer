"""
Metadata rendering helpers.

Renders a compact metadata panel below a task, with optional fields:
- assigned date
- due date
- priority
- assignee

The output is a grayscale image (mode 'L') with the full receipt width and
modest padding. Only non-empty fields are shown.
"""

from __future__ import annotations

from typing import Mapping, Optional

from PIL import Image, ImageDraw

from .render import resolve_font, _measure_text  # reuse font logic
from .emoji import rasterize_emoji
from task_printer.core.config import load_config as load_app_config


def _label(draw, x, y, text, font):
    draw.text((x, y), text, font=font, fill=0)
    w, h = _measure_text(font, text)
    return w, h


def _format_mmdd(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return v
    # Accept YYYY-MM-DD, YYYY/MM/DD → MM-DD
    try:
        if len(v) >= 10 and v[4] in ("-", "/") and v[7] in ("-", "/"):
            return f"{v[5:7]}-{v[8:10]}"
    except Exception:
        pass
    # Accept MM/DD → MM-DD
    try:
        if len(v) >= 5 and v[2] == "/":
            return f"{v[0:2]}-{v[3:5]}"
    except Exception:
        pass
    # Accept MM-DD already
    return v[:5]


def render_metadata_block(
    meta: Mapping[str, object], config: Optional[Mapping[str, object]] = None
) -> Optional[Image.Image]:
    cfg = config or load_app_config() or {}

    # Extract and normalize values
    assigned = str(meta.get("assigned") or meta.get("assigned_date") or "").strip()
    due = str(meta.get("due") or meta.get("due_date") or "").strip()
    priority = str(meta.get("priority") or "").strip()
    assignee = str(meta.get("assignee") or "").strip()

    rows = []
    if assigned:
        rows.append(("assigned", _format_mmdd(assigned)))
    if due:
        rows.append(("due", _format_mmdd(due)))
    if assignee:
        rows.append(("assignee", assignee))
    if priority:
        rows.append(("priority", priority))

    if not rows:
        return None

    try:
        width = int(cfg.get("receipt_width", 512))
    except Exception:
        width = 512

    left_margin = int(cfg.get("print_left_margin", 16))
    right_margin = int(cfg.get("print_right_margin", 16))
    top_margin = int(cfg.get("print_top_margin", 12))
    bottom_margin = int(cfg.get("print_bottom_margin", 16))

    # Slightly smaller font than task text
    base_size = int(cfg.get("task_font_size", 72))
    font_size = max(20, min(36, base_size // 2))
    font = resolve_font(cfg, font_size)

    max_text_width = max(1, width - (left_margin + right_margin))
    line_spacing = max(6, font_size // 3)

    # Pre-rasterize emojis and measure
    gap = max(6, font_size // 3)
    prepared = []
    total_h = top_margin + bottom_margin
    for label, value in rows:
        if label == "assigned":
            em = rasterize_emoji("📋", target_height=font_size, config=cfg)
            tw, th = _measure_text(font, value)
            prepared.append({
                "type": "emoji_text",
                "emoji": em,
                "text": value,
                "size": (em.width + gap + tw, max(em.height, th)),
            })
        elif label == "due":
            em = rasterize_emoji("📅", target_height=font_size, config=cfg)
            tw, th = _measure_text(font, value)
            prepared.append({
                "type": "emoji_text",
                "emoji": em,
                "text": value,
                "size": (em.width + gap + tw, max(em.height, th)),
            })
        elif label == "assignee":
            em = rasterize_emoji("👤", target_height=font_size, config=cfg)
            tw, th = _measure_text(font, value)
            prepared.append({
                "type": "emoji_text",
                "emoji": em,
                "text": value,
                "size": (em.width + gap + tw, max(em.height, th)),
            })
        elif label == "priority":
            p = value.lower()
            count = 1 if p in ("normal", "norm", "n") else 2 if p.startswith("high") else 3 if p.startswith("urgent") else 0
            if count > 0:
                bolts = [rasterize_emoji("⚡️", target_height=font_size, config=cfg) for _ in range(count)]
                w = sum(b.width for b in bolts) + gap * (count - 1 if count > 0 else 0)
                h = max((b.height for b in bolts), default=font_size)
                prepared.append({"type": "priority", "bolts": bolts, "size": (w, h)})
            else:
                # Fallback to text if unknown
                tw, th = _measure_text(font, value)
                prepared.append({"type": "text", "text": value, "size": (tw, th)})
        else:
            # Generic fallback
            tw, th = _measure_text(font, f"{label}: {value}")
            prepared.append({"type": "text", "text": f"{label}: {value}", "size": (tw, th)})
        total_h += prepared[-1]["size"][1] + line_spacing

    img = Image.new("L", (int(width), int(total_h)), 255)
    d = ImageDraw.Draw(img)

    y = top_margin
    for item in prepared:
        itype = item.get("type")
        iw, ih = item.get("size", (0, 0))
        if itype == "emoji_text":
            em = item["emoji"]
            txt = item["text"]
            # Paste emoji
            ex = left_margin
            ey = y
            img.paste(em, (int(ex), int(ey)))
            # Text baseline align
            lw = em.width + gap
            d.text((left_margin + lw, y), txt, font=font, fill=0)
        elif itype == "priority":
            bolts = item.get("bolts", [])
            # Center the bolts line
            x0 = max(left_margin, (width - iw) // 2)
            x = x0
            for i, b in enumerate(bolts):
                img.paste(b, (int(x), int(y)))
                x += b.width + (gap if i < len(bolts) - 1 else 0)
        else:  # text fallback
            d.text((left_margin, y), str(item.get("text", "")), font=font, fill=0)
        y += ih + line_spacing

    return img


__all__ = ["render_metadata_block"]
