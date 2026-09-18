"""Generate the PWA icons (dark surface + emerald sparkle) with Pillow.

Run: ``python scripts/make_icons.py`` — writes frontend/public/icon-*.png.
The motif is drawn in code so the icons can be regenerated without a designer
file; it matches the in-app brand (bg #0f0f0f, accent #00d4aa, gold #e6a82c).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

PUBLIC = Path(__file__).resolve().parent.parent / "frontend" / "public"
BG = (15, 15, 15, 255)
ACCENT = (0, 212, 170, 255)
GOLD = (230, 168, 44, 255)


def sparkle(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    r: float,
    color,
    waist: float = 0.22,
) -> None:
    """Four-point star with concave sides (the app's sparkle motif)."""
    w = r * waist
    points = [
        (cx, cy - r),
        (cx + w, cy - w),
        (cx + r, cy),
        (cx + w, cy + w),
        (cx, cy + r),
        (cx - w, cy + w),
        (cx - r, cy),
        (cx - w, cy - w),
    ]
    draw.polygon(points, fill=color)


def build(size: int, maskable: bool) -> Image.Image:
    image = Image.new("RGBA", (size, size), BG)
    draw = ImageDraw.Draw(image)
    scale = 0.72 if maskable else 0.88  # maskable keeps the motif in the safe zone
    big = size * scale * 0.34
    small = big * 0.45
    sparkle(draw, size * 0.44, size * 0.44, big, ACCENT)
    sparkle(draw, size * 0.70, size * 0.70, small, GOLD)
    draw.ellipse(
        [size * 0.26, size * 0.70, size * 0.26 + size * 0.06, size * 0.70 + size * 0.06],
        fill=(255, 255, 255, 220),
    )
    return image


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        build(size, maskable=False).save(PUBLIC / f"icon-{size}.png")
    build(512, maskable=True).save(PUBLIC / "icon-maskable-512.png")
    build(180, maskable=False).save(PUBLIC / "apple-touch-icon.png")
    print("icons written to", PUBLIC)


if __name__ == "__main__":
    main()
