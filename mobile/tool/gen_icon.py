#!/usr/bin/env python3
"""Generate Nurby app icon source PNGs.

Outputs (relative to mobile/):
  assets/icon/icon_1024.png       1024x1024, near-black background, lens glyph.
  assets/icon/icon_foreground.png 1024x1024, transparent background, glyph
                                  scaled into the inner 66% safe zone for the
                                  Android adaptive icon foreground layer.
  assets/icon/launch_icon.png     200x200 downscale of icon_1024 for launch
                                  screens (iOS LaunchIcon imageset, Android
                                  launch_background bitmap).

Also writes the launch-screen bitmaps their platforms consume:
  ios/Runner/Assets.xcassets/LaunchIcon.imageset/LaunchIcon[@2x|@3x].png
      (100pt logical size: 100/200/300 px)
  android/app/src/main/res/drawable-{m,h,x,xx,xxx}hdpi/launch_icon.png
      (100dp logical size: 100/150/200/300/400 px)

Usage: python3 tool/gen_icon.py   (run from the mobile/ directory)
Requires: pillow (pip install pillow)
"""

import os

from PIL import Image, ImageDraw

BACKGROUND = (0x0A, 0x0A, 0x0A, 255)  # near-black #0A0A0A
GREEN = (0x22, 0xC5, 0x5E, 255)  # brand green #22C55E
SPECULAR = (0xF5, 0xF7, 0xF5, 235)  # white-ish specular highlight

SIZE = 1024
SUPERSAMPLE = 4  # draw large, downscale for smooth antialiased edges


def draw_glyph(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float) -> None:
    """Minimal camera-lens glyph centred at (cx, cy).

    scale is the glyph radius in pixels (outer edge of the outer ring).
    """
    outer_r = scale
    ring_w = scale * 0.16  # thick stroke
    inner_r = scale * 0.52  # inner filled circle

    # Outer ring (thick stroke).
    draw.ellipse(
        [cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r],
        outline=GREEN,
        width=round(ring_w),
    )

    # Inner filled circle.
    draw.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=GREEN,
    )

    # Specular dot, offset upper-left inside the inner circle.
    dot_r = inner_r * 0.28
    dot_cx = cx - inner_r * 0.38
    dot_cy = cy - inner_r * 0.38
    draw.ellipse(
        [dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r],
        fill=SPECULAR,
    )


def render(glyph_fraction: float, background) -> Image.Image:
    """Render a 1024px icon. glyph_fraction is glyph diameter / canvas size."""
    big = SIZE * SUPERSAMPLE
    img = Image.new("RGBA", (big, big), background)
    draw = ImageDraw.Draw(img)
    draw_glyph(draw, big / 2, big / 2, big * glyph_fraction / 2)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    out_dir = os.path.join(os.path.dirname(__file__), "..", "assets", "icon")
    os.makedirs(out_dir, exist_ok=True)

    # Main icon: full-bleed near-black square, glyph at 56% of the canvas.
    icon = render(0.56, BACKGROUND)
    icon_path = os.path.join(out_dir, "icon_1024.png")
    icon.convert("RGB").save(icon_path.replace(".png", ".tmp.png"), "PNG")
    # iOS strips alpha anyway; keep the canonical file RGBA-free of surprises.
    os.replace(icon_path.replace(".png", ".tmp.png"), icon_path)

    # Adaptive-icon foreground: transparent background, glyph inside the
    # inner 66% safe zone (0.56 * 0.66 ~= 0.37 of the canvas).
    fg = render(0.56 * 0.66, (0, 0, 0, 0))
    fg.save(os.path.join(out_dir, "icon_foreground.png"), "PNG")

    # Launch-screen bitmap: 200px downscale of the full icon.
    icon.resize((200, 200), Image.LANCZOS).convert("RGB").save(
        os.path.join(out_dir, "launch_icon.png"), "PNG"
    )

    mobile_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    def save_scaled(px: int, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        icon.resize((px, px), Image.LANCZOS).convert("RGB").save(path, "PNG")

    # iOS LaunchIcon imageset (100pt logical size).
    imageset = os.path.join(
        mobile_dir, "ios", "Runner", "Assets.xcassets", "LaunchIcon.imageset"
    )
    save_scaled(100, os.path.join(imageset, "LaunchIcon.png"))
    save_scaled(200, os.path.join(imageset, "LaunchIcon@2x.png"))
    save_scaled(300, os.path.join(imageset, "LaunchIcon@3x.png"))

    # Android launch_background bitmap (100dp logical size).
    res = os.path.join(mobile_dir, "android", "app", "src", "main", "res")
    for bucket, px in [
        ("drawable-mdpi", 100),
        ("drawable-hdpi", 150),
        ("drawable-xhdpi", 200),
        ("drawable-xxhdpi", 300),
        ("drawable-xxxhdpi", 400),
    ]:
        save_scaled(px, os.path.join(res, bucket, "launch_icon.png"))

    print(f"Wrote icon_1024.png, icon_foreground.png, launch_icon.png to {out_dir}")
    print("Wrote iOS LaunchIcon imageset and Android launch_icon drawables")


if __name__ == "__main__":
    main()
