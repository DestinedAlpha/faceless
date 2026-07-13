"""Thumbnails: 2-3 distinct 1280x720 variants so you can pick the strongest click.

Each variant = an AI background (from metadata.thumbnail_prompt) + a legibility scrim
+ bold playbook-styled text drawn in a heavy font with an outline. Variants differ by
background seed, thumbnail-text option, and a look preset (text color / position).
One variant optionally composites a rembg **subject cutout** of a hero scene image over
the background for a subject-forward, "produced" feel.

Degrades gracefully at every step: if image generation fails it uses a gradient; if a
heavy font isn't found it falls back to PIL's default; if rembg is absent the cutout
variant simply renders like the others. `generate()` returns the primary path (back-
compat); `generate_variants()` returns every path produced.
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
    "C:/Windows/Fonts/impact.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# Look presets: (text fill, position). Kept small + high-contrast; the playbook's
# thumbnail.style biases which fills we prefer but all stay legible over the scrim.
_PRESETS = [
    {"fill": (255, 229, 92), "pos": "bottom"},   # punchy yellow, lower third
    {"fill": (255, 255, 255), "pos": "top"},     # clean white, upper third
    {"fill": (255, 90, 90), "pos": "bottom"},    # alarm red, lower third
]


def _load_font(size: int):
    from PIL import ImageFont
    for cand in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(cand, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _background(prompt: str, work_dir: Path, seed: int, tag: str):
    from PIL import Image
    bg_path = work_dir / f"thumb_bg_{tag}.jpg"
    try:
        images.generate(prompt, bg_path, THUMB_W, THUMB_H, seed=seed)
        return Image.open(bg_path).convert("RGB").resize((THUMB_W, THUMB_H))
    except Exception as exc:  # noqa: BLE001
        log.warning("[thumbnail] bg generation failed (%s) -> gradient", exc)
        return Image.new("RGB", (THUMB_W, THUMB_H), (18, 18, 28))


def _composite_subject(img, hero_image: Path | None):
    """Composite a rembg subject cutout of `hero_image` onto the right side of img."""
    if not hero_image or not Path(hero_image).exists():
        return img
    try:
        from ..assets import motion  # lazy: only import rembg path when needed
        fg = motion.cutout(Path(hero_image))
        if fg is None:
            return img
        # Scale the subject to ~85% of the thumb height, anchor bottom-right.
        target_h = int(THUMB_H * 0.85)
        ratio = target_h / fg.height
        fg = fg.resize((max(1, int(fg.width * ratio)), target_h))
        x = THUMB_W - fg.width - 20
        y = THUMB_H - fg.height
        base = img.convert("RGBA")
        base.alpha_composite(fg, (max(0, x), max(0, y)))
        return base.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        log.warning("[thumbnail] subject composite failed (%s) -> flat bg", exc)
        return img


def _scrim(img, pos: str):
    """Dark gradient scrim from the text side for legibility."""
    from PIL import Image, ImageDraw
    scrim = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(scrim)
    for y in range(THUMB_H):
        if pos == "top":
            a = int(200 * max(0.0, (THUMB_H * 0.65 - y) / (THUMB_H * 0.65)))
        else:
            a = int(200 * max(0.0, (y - THUMB_H * 0.35) / (THUMB_H * 0.65)))
        d.line([(0, y), (THUMB_W, y)], fill=(0, 0, 0, min(a, 200)))
    return Image.alpha_composite(img.convert("RGBA"), scrim).convert("RGB")


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
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


def _draw_text(img, text: str, fill, pos: str):
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    margin = 70
    max_w = THUMB_W - 2 * margin
    font_size = 120
    font = _load_font(font_size)
    lines = _wrap(draw, text, font, max_w)
    while font_size > 48 and len(lines) * font_size * 1.15 > THUMB_H * 0.5:
        font_size -= 8
        font = _load_font(font_size)
        lines = _wrap(draw, text, font, max_w)
    line_h = int(font_size * 1.15)
    total_h = len(lines) * line_h
    y = margin if pos == "top" else THUMB_H - margin - total_h
    for line in lines:
        x = margin
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-3, -3), (3, 3)):
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return img


def _one(metadata: dict, selection: dict, out_path: Path, *, text: str,
         seed: int, preset: dict, hero_image: Path | None) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = metadata.get("thumbnail_prompt", selection.get("topic", ""))
    img = _background(prompt, out_path.parent, seed, out_path.stem)
    if hero_image is not None:
        img = _composite_subject(img, hero_image)
    img = _scrim(img, preset["pos"])
    img = _draw_text(img, (text or selection.get("topic", "")).upper(),
                     preset["fill"], preset["pos"])
    img.save(out_path, "JPEG", quality=90)
    log.info("[thumbnail] saved %s", out_path.name)
    return out_path


def generate_variants(metadata: dict, selection: dict, out_dir: Path,
                      hero_image: Path | None = None, n: int = 3) -> list[Path]:
    """Produce up to `n` distinct thumbnail variants. Returns their paths (>=1)."""
    out_dir = Path(out_dir)
    texts = metadata.get("thumbnail_variants") or [metadata.get("thumbnail_text", "")]
    n = max(1, min(3, n, max(len(texts), 1) + 1))
    paths: list[Path] = []
    for i in range(n):
        preset = _PRESETS[i % len(_PRESETS)]
        text = texts[i % len(texts)]
        # Variant 0 gets the subject cutout (subject-forward hero); rest are clean bgs.
        hero = hero_image if i == 0 else None
        out = out_dir / (f"thumbnail_{i}.jpg" if i else "thumbnail.jpg")
        try:
            paths.append(_one(metadata, selection, out, text=text, seed=7 + i * 13,
                              preset=preset, hero_image=hero))
        except Exception as exc:  # noqa: BLE001
            log.warning("[thumbnail] variant %d failed: %s", i, exc)
    return paths


def generate(metadata: dict, selection: dict, out_path: Path) -> Path:
    """Back-compat single-thumbnail entry point."""
    return _one(metadata, selection, out_path,
                text=metadata.get("thumbnail_text", ""), seed=7,
                preset=_PRESETS[0], hero_image=None)
