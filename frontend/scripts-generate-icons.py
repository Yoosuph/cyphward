#!/usr/bin/env python3
"""Generate PNG icons, apple-touch-icon, favicon.ico, and OG image from favicon.svg."""
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PUBLIC = Path(__file__).resolve().parent / "public"
ICONS = PUBLIC / "icons"
ICONS.mkdir(exist_ok=True)
SVG = PUBLIC / "favicon.svg"
BG = "#0A0907"
AMBER = "#E5532B"


def svg_to_png(size: int, out: Path, bg: str | None = None) -> None:
    cmd = [
        "rsvg-convert",
        "-w", str(size),
        "-h", str(size),
        "--background-color", bg or "transparent",
        str(SVG),
        "-o", str(out),
    ]
    subprocess.run(cmd, check=True)


def font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def make_og() -> None:
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    # subtle amber accent bar
    draw.rectangle([0, 0, w, 8], fill=AMBER)

    # shield centered-left
    shield = Image.new("RGBA", (360, 360), (0, 0, 0, 0))
    subprocess.run(
        ["rsvg-convert", "-w", "360", "-h", "360", "--background-color", "transparent",
         str(SVG), "-o", "/tmp/cyphward_shield.png"],
        check=True,
    )
    shield = Image.open("/tmp/cyphward_shield.png").convert("RGBA")
    img.paste(shield, (90, 135), shield)

    # wordmark
    f1 = font(92)
    f2 = font(30)
    f3 = font(24)
    draw.text((500, 200), "CYPH", font=f1, fill="#F5F2EB")
    # measure CYPH width
    cw = draw.textlength("CYPH", font=f1)
    draw.text((500 + cw, 200), "WARD", font=f1, fill=AMBER)

    draw.text((502, 320), "Security scoring, simplified.", font=f2, fill="#A8A095")
    draw.text(
        (502, 380),
        "0–100 score · Findings · Reports · NDPA 2023 ready",
        font=f3,
        fill="#8C8477",
    )

    # footer
    draw.text((90, 560), "cyphward.com", font=f3, fill=AMBER)

    img.save(PUBLIC / "og-image.png", "PNG", optimize=True)


def main() -> None:
    # transparent SVG-based icons
    for s in (16, 32, 48, 64, 128, 180, 192, 256, 512):
        svg_to_png(s, ICONS / f"icon-{s}x{s}.png")

    # root convenience copies
    svg_to_png(180, PUBLIC / "apple-touch-icon.png")
    svg_to_png(32, PUBLIC / "favicon-32x32.png")
    svg_to_png(16, PUBLIC / "favicon-16x16.png")

    # favicon.ico (multi-size from 32px render)
    Image.open(ICONS / "icon-32x32.png").save(
        PUBLIC / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32)]
    )

    make_og()
    print("icons + og-image generated")


if __name__ == "__main__":
    main()
