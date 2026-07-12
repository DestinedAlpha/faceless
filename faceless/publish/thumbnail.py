"""Thumbnail: AI background (from metadata.thumbnail_prompt) + bold overlaid text.

Generates a 1280x720 YouTube thumbnail — the AI still as background, a dark scrim
for legibility, then the punchy thumbnail_text drawn in a heavy font with an outline.
Degrades gracefully: if image generation fails it uses a solid gradient; if a nice
font isn't found it falls back to PIL's default.
"""
from __future__ import annotations

from pathlib import Path

from ..assets import images
from ..core.log import get_logger

log = get_logger(__name__)

THUMB_W, THUMB_H = 1280, 720

# Common heavy fonts across platforms; first that loads wins.
_FONT_CANDIDATES = [
    "arialbd.ttf", "Arial Bold.ttf", "ARIALBD.TTF",
    "DejaVuSans-Bold.ttf", "Helvetica-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _load_font(size: int):
    from PIL import ImageFont
    for cand in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(cand, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _background(prompt: str, work_dir: Path) -> "object":
    from PIL import Image
    bg_path = work_dir / "thumb_bg.jpg"
    try:
        images.generate(prompt, bg_path, THUMB_W, THUMB_H, seed=7)
        img = Image.open(bg_path).convert("RGB").resize((THUMB_W, THUMB_H))
    except Exception as exc:  # noqa: BLE001
        log.warning("[thumbnail] bg generation failed (%s) -> gradient", exc)
        img = Image.new("RGB", (THUMB_W, THUMB_H), (18, 18, 28))
    return img


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def generate(metadata: dict, selection: dict, out_path: Path) -> Path:
    from PIL import Image, ImageDraw

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    img = _background(metadata.get("thumbnail_prompt", selection.get("topic", "")),
                      out_path.parent)

    # Dark scrim from the bottom for text legibility.
    scrim = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(scrim)
    for y in range(THUMB_H):
        alpha = int(200 * max(0.0, (y - THUMB_H * 0.35) / (THUMB_H * 0.65)))
        sdraw.line([(0, y), (THUMB_W, y)], fill=(0, 0, 0, min(alpha, 200)))
    img = Image.alpha_composite(img.convert("RGBA"), scrim).convert("RGB")

    draw = ImageDraw.Draw(img)
    text = (metadata.get("thumbnail_text") or selection.get("topic", "")).upper()

    font_size = 120
    font = _load_font(font_size)
    margin = 70
    max_w = THUMB_W - 2 * margin
    lines = _wrap(draw, text, font, max_w)
    # Shrink until it fits vertically in the lower ~55%.
    while font_size > 48 and len(lines) * font_size * 1.15 > THUMB_H * 0.55:
        font_size -= 8
        font = _load_font(font_size)
        lines = _wrap(draw, text, font, max_w)

    line_h = int(font_size * 1.15)
    total_h = len(lines) * line_h
    y = THUMB_H - margin - total_h
    for line in lines:
        w = draw.textlength(line, font=font)
        x = margin
        # Outline for pop.
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-3, -3), (3, 3)):
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 229, 92))
        y += line_h

    img.save(out_path, "JPEG", quality=90)
    log.info("[thumbnail] saved %s", out_path.name)
    return out_path
